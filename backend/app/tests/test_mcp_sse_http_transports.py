"""MCP sse / streamable_http 真实传输回归测试。

覆盖：
- streamable_http：POST JSON-RPC（Accept: application/json, text/event-stream）
  的真实发现（tools/list）与调用（tools/call）；整段 JSON 与 SSE data: 帧
  两种响应形态；Mcp-Session-Id 会话头回传。
- sse：GET 建立 text/event-stream 流读取 endpoint 事件 → 向上报端点 POST
  JSON-RPC → 从流上等待匹配响应的真实发现与调用。
- 协议语义：JSON-RPC id 会话内单调递增、协议版本 2024-11-05、initialize
  握手先于业务请求。
- 失败降级：服务端 500 / 垃圾响应体（协议错误）/ SSE 断连 / 无响应超时，
  分别如实落 error / error / error / timeout，不外泄异常细节，不再返回
  mode:'stub'。
- SSRF：写入时拦截 169.254 链路本地地址；绕过写入校验直接注入的记录在
  真实连接前仍被 resolve_external_url pinned-IP 复核拦截；精确主机白名单
  （WANWEI_MCP_HTTP_HOST_ALLOWLIST）只放行声明过的主机。

测试内用 Starlette/FastAPI 子应用 + uvicorn 后台线程在 127.0.0.1 随机端口
模拟真实 MCP server；平台侧经 TestClient 走完整 HTTP 面。
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[3]

MCP_PROTOCOL_VERSION = '2024-11-05'
_MOCK_TOOLS = [
    {
        'name': 'echo',
        'description': '回显参数',
        'inputSchema': {'type': 'object', 'properties': {'text': {'type': 'string'}}},
    },
    {
        'name': 'ping',
        'description': '存活检查',
        'inputSchema': {'type': 'object'},
    },
]


def _client(tmp_path, *, api_key: str = "test-key"):
    os.environ["WANWEI_API_KEY"] = api_key
    os.environ["WANWEI_MEMORY_DB"] = str(tmp_path / "memory.db")
    os.environ["WANWEI_PLATFORM_DIR"] = str(tmp_path / "platform")
    os.environ.pop("WANWEI_PRODUCTION", None)
    os.environ.pop("WANWEI_DEVICE_GEAR_ENABLED", None)

    backend_dir = str(PROJECT_ROOT / "backend")
    for path in (backend_dir, str(PROJECT_ROOT)):
        if path in sys.path:
            sys.path.remove(path)
        sys.path.insert(0, path)
    import backend.app.init_db
    import backend.app.app_runtime as runtime_mod
    import backend.app.main as main_mod

    importlib.reload(runtime_mod)
    importlib.reload(main_mod)
    backend.app.init_db.main()
    return TestClient(main_mod.app, raise_server_exceptions=False)


@pytest.fixture
def mcp_store(tmp_path, monkeypatch):
    """把 mcp_hub 的模块级 JsonStore 重定向到当前测试的隔离目录。"""
    monkeypatch.setenv("WANWEI_PLATFORM_DIR", str(tmp_path / "platform"))
    from backend.app.platform_api import mcp_hub
    from backend.app.platform_api.store import JsonStore

    store = JsonStore("mcp_servers")
    monkeypatch.setattr(mcp_hub, "_store", store)
    return store


# ---------------------------------------------------------------------------
# 本地 mock MCP server（Starlette 子应用 + uvicorn 后台线程，随机端口）
# ---------------------------------------------------------------------------


def _build_mock_app(
    *,
    flavor: str,
    fail_methods: set[str] | None = None,
    hang_methods: set[str] | None = None,
    garbage_methods: set[str] | None = None,
    sse_frame_methods: set[str] | None = None,
    disconnect_after_endpoint: bool = False,
):
    """构造一个最小但忠实的 MCP server 模拟端。

    flavor='streamable'：单端点 POST /mcp，直接返回 JSON-RPC 结果；
    flavor='sse'：GET /sse 先发 endpoint 事件，POST /messages 受理请求并把
    响应推回事件流（标准 MCP HTTP+SSE 形态）。
    """
    app = FastAPI()
    fail_methods = fail_methods or set()
    hang_methods = hang_methods or set()
    garbage_methods = garbage_methods or set()
    sse_frame_methods = sse_frame_methods or set()
    # 每个带 id 的请求记录一条：id / method / 会话标记 / 协议版本（仅 initialize）。
    # 会话标记：streamable 用 Mcp-Session-Id 头（首请求无头记 'fresh'），
    # sse 用上报端点的 session_id 查询参数。
    state = {'requests': []}

    def _record(rid, method: str, conn: str) -> None:
        state['requests'].append({'id': rid, 'method': method, 'conn': conn})

    def _dispatch(method: str, params: dict, conn: str) -> dict:
        if method == 'initialize':
            state.setdefault('protocol_versions', []).append(params.get('protocolVersion'))
            return {
                'protocolVersion': MCP_PROTOCOL_VERSION,
                'capabilities': {'tools': {}},
                'serverInfo': {'name': 'mock-mcp', 'version': '0.0.1'},
            }
        if method == 'tools/list':
            return {'tools': [dict(tool) for tool in _MOCK_TOOLS]}
        if method == 'tools/call':
            arguments = params.get('arguments') if isinstance(params, dict) else {}
            text = json.dumps(arguments, ensure_ascii=False) if arguments else 'pong'
            return {'content': [{'type': 'text', 'text': text}], 'isError': False}
        return {}

    def _reject_or_dispatch(method: str):
        if method in fail_methods:
            return JSONResponse(status_code=500, content={'mock': 'internal-boom'})
        return None

    if flavor == 'streamable':
        @app.post('/mcp')
        async def mcp_post(request: Request):  # noqa: ANN202
            body = await request.json()
            rid = body.get('id')
            method = str(body.get('method'))
            params = body.get('params') or {}
            if rid is None:
                return Response(status_code=202)
            header = request.headers.get('mcp-session-id')
            if method == 'initialize':
                state['session_counter'] = state.get('session_counter', 0) + 1
                seq = state['session_counter']
            else:
                seq = state.get('header_to_session', {}).get(header or '', 0)
            _record(rid, method, f'session-{seq}')
            rejected = _reject_or_dispatch(method)
            if rejected is not None:
                return rejected
            result = _dispatch(method, params, f'session-{seq}')
            payload = {'jsonrpc': '2.0', 'id': rid, 'result': result}
            if method in garbage_methods:
                return Response(
                    content='{ this is not json', status_code=200,
                    media_type='application/json',
                )
            data = json.dumps(payload, ensure_ascii=False)
            if method in sse_frame_methods:
                return Response(
                    content=f'event: message\r\ndata: {data}\r\n\r\n',
                    media_type='text/event-stream',
                )
            if method in hang_methods:
                await asyncio.sleep(6)  # 客户端预算（秒级）内必然超时
            response = JSONResponse(payload)
            if method == 'initialize':
                response.headers['Mcp-Session-Id'] = 'sess-streamable-1'
                state.setdefault('header_to_session', {})['sess-streamable-1'] = seq
            return response
    elif flavor == 'sse':
        queues: dict[str, asyncio.Queue] = {}

        @app.get('/sse')
        async def sse_get():  # noqa: ANN202
            sid = uuid.uuid4().hex[:8]
            queue: asyncio.Queue = asyncio.Queue()
            queues[sid] = queue

            async def event_stream():
                yield (
                    'event: endpoint\r\n'
                    f'data: /messages?session_id={sid}\r\n\r\n'
                )
                if disconnect_after_endpoint:
                    return
                while True:
                    try:
                        message = await asyncio.wait_for(queue.get(), timeout=15)
                    except asyncio.TimeoutError:
                        yield ': keep-alive\r\n\r\n'
                        continue
                    data = json.dumps(message, ensure_ascii=False)
                    yield f'event: message\r\ndata: {data}\r\n\r\n'

            return StreamingResponse(event_stream(), media_type='text/event-stream')

        @app.post('/messages')
        async def messages_post(request: Request):  # noqa: ANN202
            body = await request.json()
            sid = request.query_params.get('session_id', '')
            queue = queues.get(sid)
            if queue is None:
                return JSONResponse(status_code=404, content={'error': 'no session'})
            rid = body.get('id')
            method = str(body.get('method'))
            if rid is None:
                return Response(status_code=202)
            _record(rid, method, f'sse:{sid}')
            rejected = _reject_or_dispatch(method)
            if rejected is not None:
                return rejected
            if method in hang_methods:
                return Response(status_code=202)  # 受理但不推送响应 → 客户端超时
            result = _dispatch(method, body.get('params') or {}, f'sse:{sid}')
            await queue.put({'jsonrpc': '2.0', 'id': rid, 'result': result})
            return Response(status_code=202)
    else:
        raise ValueError(f'未知 flavor：{flavor}')

    app.state.mcp_state = state
    return app


class _MockMcpServer:
    """uvicorn 后台线程承载子应用；port=0 让内核分配随机端口。"""

    def __init__(self, app):
        config = uvicorn.Config(
            app, host='127.0.0.1', port=0, log_level='error',
            timeout_graceful_shutdown=2,
        )
        self.app = app
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self.port: int | None = None

    def __enter__(self) -> _MockMcpServer:
        self._thread.start()
        deadline = time.monotonic() + 20
        while not self._server.started:
            if time.monotonic() > deadline:
                raise RuntimeError('mock MCP server 启动失败')
            time.sleep(0.05)
        self.port = self._server.servers[0].sockets[0].getsockname()[1]
        return self

    def __exit__(self, *exc_info) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=10)

    @property
    def state(self) -> dict:
        return self.app.state.mcp_state


@pytest.fixture
def loopback_allowlist(monkeypatch):
    """放行回环主机供测试连接本地 mock；其余内网/链路本地地址仍被拒。"""
    monkeypatch.setenv('WANWEI_MCP_HTTP_HOST_ALLOWLIST', '127.0.0.1')


def _register_remote_server(client, *, transport: str, url: str, timeout_seconds: float | None = None,
                            headers: dict | None = None) -> dict:
    response = client.post(
        '/platform/mcp/servers',
        headers=headers,
        json={
            'name': f'remote-{transport}',
            'transport': transport,
            'url': url,
            'enabled': True,
            **({'timeout_seconds': timeout_seconds} if timeout_seconds else {}),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _assert_protocol(state) -> list[list[dict]]:
    """按会话分组断言协议语义：握手先行、版本 2024-11-05、id 会话内单调。"""
    groups: dict[str, list[dict]] = {}
    for entry in state['requests']:
        groups.setdefault(entry['conn'], []).append(entry)
    session_groups = list(groups.values())
    assert session_groups, 'mock server 应收到带 id 的请求'
    for group in session_groups:
        methods = [entry['method'] for entry in group]
        assert methods[0] == 'initialize', f'每个会话应先握手再发业务请求：{methods}'
        ids = [entry['id'] for entry in group]
        assert ids == sorted(ids), f'id 应在会话内单调递增：{ids}'
    assert set(state['protocol_versions']) == {MCP_PROTOCOL_VERSION}
    return session_groups


# ---------------------------------------------------------------------------
# streamable_http：真实发现与调用
# ---------------------------------------------------------------------------


def test_streamable_http_roundtrip_discover_and_call(tmp_path, mcp_store, loopback_allowlist):
    client = _client(tmp_path)
    h = {'x-api-key': 'test-key'}
    with _MockMcpServer(_build_mock_app(flavor='streamable')) as server:
        rec = _register_remote_server(
            client, transport='streamable_http',
            url=f'http://127.0.0.1:{server.port}/mcp',
            timeout_seconds=20, headers=h,
        )
        sid = rec['id']

        discovered = client.get(f'/platform/mcp/servers/{sid}/tools', headers=h)
        assert discovered.status_code == 200, discovered.text
        body = discovered.json()
        assert body['status'] == 'connected'
        assert body['source'] == 'live'
        names = {tool['name'] for tool in body['tools']}
        assert {'echo', 'ping'} <= names, body

        stored = mcp_store.get(sid)
        assert stored['status'] == 'connected'
        assert stored['tools_count'] == len(body['tools'])
        overview = client.get('/platform/mcp/overview', headers=h).json()
        assert overview['tools_discovered'] >= len(body['tools'])

        called = client.post(
            f'/platform/mcp/servers/{sid}/call',
            headers=h,
            json={'tool': 'echo', 'arguments': {'text': '万枢'}},
        )
        assert called.status_code == 200, called.text
        call_body = called.json()
        assert call_body['ok'] is True
        assert call_body['mode'] == 'live'
        assert '万枢' in call_body['result']['content'][0]['text']

        # 协议语义：每个会话握手先行、版本 2024-11-05、id 单调；
        # initialize 之后携带服务器下发的 Mcp-Session-Id。
        _assert_protocol(server.state)

        recent = client.get('/platform/mcp/overview', headers=h).json()['recent_calls']
        assert recent and recent[0]['mode'] == 'live'


def test_streamable_http_parses_sse_framed_response(tmp_path, mcp_store, loopback_allowlist):
    """Accept 协商后服务器以 text/event-stream 返回结果也应正确解析。"""
    client = _client(tmp_path)
    h = {'x-api-key': 'test-key'}
    with _MockMcpServer(_build_mock_app(
        flavor='streamable', sse_frame_methods={'tools/list'},
    )) as server:
        rec = _register_remote_server(
            client, transport='streamable_http',
            url=f'http://127.0.0.1:{server.port}/mcp',
            timeout_seconds=20, headers=h,
        )
        body = client.get(f"/platform/mcp/servers/{rec['id']}/tools", headers=h).json()
        assert body['status'] == 'connected', body
        assert {tool['name'] for tool in body['tools']} >= {'echo', 'ping'}


def test_streamable_http_server_500_degrades_to_error(tmp_path, mcp_store, loopback_allowlist):
    client = _client(tmp_path)
    h = {'x-api-key': 'test-key'}
    with _MockMcpServer(_build_mock_app(flavor='streamable', fail_methods={'tools/list'})) as server:
        rec = _register_remote_server(
            client, transport='streamable_http',
            url=f'http://127.0.0.1:{server.port}/mcp',
            timeout_seconds=10, headers=h,
        )
        sid = rec['id']
        response = client.get(f'/platform/mcp/servers/{sid}/tools', headers=h)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body['status'] == 'error'
        assert body['note'] == '工具发现失败，请检查服务器配置或运行状态'
        # 异常细节（mock 错误标记）不外泄
        assert 'boom' not in response.text
        assert mcp_store.get(sid)['status'] == 'error'


def test_streamable_http_garbage_response_is_protocol_error(tmp_path, mcp_store, loopback_allowlist):
    """200 但响应体不是合法 JSON-RPC → 如实 error，绝不渲染成成功。"""
    client = _client(tmp_path)
    h = {'x-api-key': 'test-key'}
    with _MockMcpServer(_build_mock_app(flavor='streamable', garbage_methods={'tools/call'})) as server:
        rec = _register_remote_server(
            client, transport='streamable_http',
            url=f'http://127.0.0.1:{server.port}/mcp',
            timeout_seconds=10, headers=h,
        )
        sid = rec['id']
        response = client.post(
            f'/platform/mcp/servers/{sid}/call',
            headers=h, json={'tool': 'echo', 'arguments': {}},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body['mode'] == 'error'
        assert body['ok'] is False
        assert 'not json' not in response.text


def test_streamable_http_call_timeout_degrades_to_timeout(tmp_path, mcp_store, loopback_allowlist):
    client = _client(tmp_path)
    h = {'x-api-key': 'test-key'}
    with _MockMcpServer(_build_mock_app(flavor='streamable', hang_methods={'tools/call'})) as server:
        rec = _register_remote_server(
            client, transport='streamable_http',
            url=f'http://127.0.0.1:{server.port}/mcp',
            timeout_seconds=2, headers=h,
        )
        sid = rec['id']
        response = client.post(
            f'/platform/mcp/servers/{sid}/call',
            headers=h, json={'tool': 'slow', 'arguments': {}},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body['mode'] == 'timeout'
        assert body['ok'] is False
        assert mcp_store.get(sid)['status'] == 'timeout'


# ---------------------------------------------------------------------------
# sse：endpoint 事件流 + 上报端点真实发现与调用
# ---------------------------------------------------------------------------


def test_sse_roundtrip_discover_and_call(tmp_path, mcp_store, loopback_allowlist):
    client = _client(tmp_path)
    h = {'x-api-key': 'test-key'}
    with _MockMcpServer(_build_mock_app(flavor='sse')) as server:
        rec = _register_remote_server(
            client, transport='sse',
            url=f'http://127.0.0.1:{server.port}/sse',
            timeout_seconds=20, headers=h,
        )
        sid = rec['id']

        discovered = client.get(f'/platform/mcp/servers/{sid}/tools', headers=h)
        assert discovered.status_code == 200, discovered.text
        body = discovered.json()
        assert body['status'] == 'connected'
        assert body['source'] == 'live'
        assert {tool['name'] for tool in body['tools']} >= {'echo', 'ping'}

        stored = mcp_store.get(sid)
        assert stored['status'] == 'connected'

        called = client.post(
            f'/platform/mcp/servers/{sid}/call',
            headers=h,
            json={'tool': 'ping', 'arguments': {}},
        )
        assert called.status_code == 200, called.text
        call_body = called.json()
        assert call_body['mode'] == 'live'
        assert call_body['result']['content'][0]['text'] == 'pong'

        _assert_protocol(server.state)

        recent = client.get('/platform/mcp/overview', headers=h).json()['recent_calls']
        assert recent and recent[0]['mode'] == 'live'


@pytest.mark.parametrize(
    ('endpoint_data', 'expected_origin'),
    [
        ('messages', 'https://sse.example.test/base/messages'),
        ('https://messages.example.test/rpc', 'https://messages.example.test/rpc'),
    ],
)
def test_sse_endpoint_is_resolved_and_pinned_separately(
    monkeypatch, endpoint_data, expected_origin,
):
    """endpoint 事件无论相对/绝对地址，都必须独立 SSRF resolve 并携带 Host/SNI。"""
    from backend.app.platform_api import mcp_hub

    resolved = []

    def fake_resolve(url, *, allowlist):
        resolved.append((url, allowlist))
        if url == 'https://sse.example.test/base/sse':
            return url, '203.0.113.10'
        assert url == expected_origin
        return url, '198.51.100.7'

    monkeypatch.setattr(mcp_hub, 'resolve_external_url', fake_resolve)

    class FakeResponse:
        status_code = 200
        headers = {'content-type': 'text/event-stream'}
        content = b''

        async def aiter_lines(self):
            yield 'event: endpoint'
            yield f'data: {endpoint_data}'
            yield ''
            yield 'event: message'
            yield 'data: {"jsonrpc":"2.0","id":1,"result":{}}'
            yield ''

    class FakeStream:
        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, *exc_info):
            return None

    class FakeClient:
        def __init__(self):
            self.posts = []

        def stream(self, method, url, *, headers, extensions):
            assert method == 'GET'
            assert url == 'https://203.0.113.10/base/sse'
            assert headers == {
                'Host': 'sse.example.test', 'Accept': 'text/event-stream',
            }
            assert extensions == {'sni_hostname': 'sse.example.test'}
            return FakeStream()

        async def post(self, url, *, json, headers, extensions):
            self.posts.append((url, json, headers, extensions))
            return type('PostResponse', (), {'status_code': 202, 'content': b''})()

    async def exercise():
        client = FakeClient()
        rpc = mcp_hub._SseRpc(
            client,
            'https://sse.example.test/base/sse',
            'https://203.0.113.10/base/sse',
            {'Host': 'sse.example.test'},
            {'sni_hostname': 'sse.example.test'},
            5,
        )
        await rpc.connect()
        await rpc.request('tools/list')
        await rpc.notify('notifications/initialized')
        return client

    client = asyncio.run(exercise())
    assert [item[0] for item in resolved] == [
        'https://sse.example.test/base/sse', expected_origin,
    ]
    assert client.posts[0][0] == 'https://198.51.100.7' + (
        '/base/messages' if endpoint_data == 'messages' else '/rpc'
    )
    assert client.posts[0][2]['Host'] == (
        'sse.example.test' if endpoint_data == 'messages' else 'messages.example.test'
    )
    assert client.posts[0][3] == {
        'sni_hostname': client.posts[0][2]['Host'],
    }
    assert client.posts[1][0] == client.posts[0][0]
    assert client.posts[1][2] == client.posts[0][2]
    assert client.posts[1][3] == client.posts[0][3]


def test_sse_endpoint_ssrf_rejection_uses_public_error(monkeypatch):
    """endpoint 二次 SSRF 失败时不发 POST，且错误不泄露事件地址。"""
    from backend.app.platform_api import mcp_hub

    def reject(url, *, allowlist):
        if url == 'https://sse.example.test/base/sse':
            return url, '203.0.113.10'
        raise ValueError('internal endpoint: http://169.254.169.254/')

    monkeypatch.setattr(mcp_hub, 'resolve_external_url', reject)

    class FakeResponse:
        status_code = 200
        headers = {'content-type': 'text/event-stream'}

        async def aiter_lines(self):
            yield 'event: endpoint'
            yield 'data: http://169.254.169.254/latest/meta-data'
            yield ''

    class FakeStream:
        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, *exc_info):
            return None

    class FakeClient:
        def stream(self, *args, **kwargs):
            return FakeStream()

    async def exercise():
        rpc = mcp_hub._SseRpc(
            FakeClient(),
            'https://sse.example.test/base/sse',
            'https://203.0.113.10/base/sse',
            {'Host': 'sse.example.test'},
            {'sni_hostname': 'sse.example.test'},
            5,
        )
        await rpc.connect()

    with pytest.raises(mcp_hub._McpSsrfBlocked) as blocked:
        asyncio.run(exercise())
    assert str(blocked.value) == mcp_hub._SSRF_BLOCKED_NOTE
    assert '169.254.169.254' not in str(blocked.value)


def test_sse_disconnect_before_response_is_error(tmp_path, mcp_store, loopback_allowlist):
    """endpoint 事件之后流被断开 → 如实 error，不伪装成功也不悬挂。"""
    client = _client(tmp_path)
    h = {'x-api-key': 'test-key'}
    with _MockMcpServer(_build_mock_app(
        flavor='sse', disconnect_after_endpoint=True,
    )) as server:
        rec = _register_remote_server(
            client, transport='sse',
            url=f'http://127.0.0.1:{server.port}/sse',
            timeout_seconds=5, headers=h,
        )
        response = client.get(f"/platform/mcp/servers/{rec['id']}/tools", headers=h)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body['status'] == 'error'
        assert body['note'] == '工具发现失败，请检查服务器配置或运行状态'
        assert mcp_store.get(rec['id'])['status'] == 'error'


def test_sse_discovery_timeout_when_server_silent(tmp_path, mcp_store, loopback_allowlist):
    """受理请求却永不推送响应 → 在服务器级预算内落 timeout。"""
    client = _client(tmp_path)
    h = {'x-api-key': 'test-key'}
    with _MockMcpServer(_build_mock_app(flavor='sse', hang_methods={'tools/list'})) as server:
        rec = _register_remote_server(
            client, transport='sse',
            url=f'http://127.0.0.1:{server.port}/sse',
            timeout_seconds=2, headers=h,
        )
        started = time.monotonic()
        response = client.get(f"/platform/mcp/servers/{rec['id']}/tools", headers=h)
        elapsed = time.monotonic() - started
        assert response.status_code == 200, response.text
        body = response.json()
        assert body['status'] == 'timeout'
        assert body['note'] == '工具发现超时，请稍后重试'
        assert elapsed < 8, f'应在预算附近返回而不是无限等待（实际 {elapsed:.1f}s）'


# ---------------------------------------------------------------------------
# SSRF：写入拦截 + 连接前复核拦截
# ---------------------------------------------------------------------------


@pytest.mark.parametrize('transport', ['sse', 'streamable_http'])
def test_ssrf_link_local_url_rejected_at_write_time(transport):
    """169.254 元数据地址在注册/更新时即被拒绝（422），不进入连接阶段。"""
    from fastapi import HTTPException

    from backend.app.platform_api import mcp_hub

    with pytest.raises(HTTPException) as blocked:
        mcp_hub._normalize_server_config({
            'transport': transport,
            'url': 'http://169.254.169.254/latest/meta-data',
            'command': None, 'args': [],
        })
    assert blocked.value.status_code == 422


@pytest.mark.parametrize('transport', ['sse', 'streamable_http'])
def test_ssrf_blocked_again_at_connect_time_for_injected_record(
    tmp_path, mcp_store, loopback_allowlist, transport,
):
    """绕过写入校验注入的记录，真实连接前仍被 pinned-IP 复核拦截。"""
    client = _client(tmp_path)
    h = {'x-api-key': 'test-key'}

    injected = {
        'id': f'srv_ssrf_{transport}',
        'name': 'ssrf-connect',
        'transport': transport,
        'url': 'http://169.254.169.254/latest/meta-data',
        'command': None,
        'args': [],
        'env': {},
        'enabled': True,
        'status': 'unknown',
        'created_at': '2026-01-01T00:00:00+08:00',
        'tools_cache': [],
        'tools_count': 0,
        '_config_revision': 1,
    }
    mcp_store.set(injected['id'], injected)

    response = client.get(f"/platform/mcp/servers/{injected['id']}/tools", headers=h)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['status'] == 'error'
    assert 'SSRF' in body['note']
    assert mcp_store.get(injected['id'])['status'] == 'error'

    called = client.post(
        f"/platform/mcp/servers/{injected['id']}/call",
        headers=h, json={'tool': 'steal', 'arguments': {}},
    )
    assert called.status_code == 200, called.text
    assert called.json()['mode'] == 'error'


# ---------------------------------------------------------------------------
# 缺失配置：已知传输如实 error，不再返回 stub
# ---------------------------------------------------------------------------


def test_missing_remote_config_reports_error_not_stub(tmp_path, mcp_store):
    """sse 未配置 url：发现返回 error；调用保持 503 契约且记录 mode:'error'。"""
    client = _client(tmp_path)
    h = {'x-api-key': 'test-key'}
    created = client.post(
        '/platform/mcp/servers',
        headers=h,
        json={'name': 'no-url', 'transport': 'sse', 'enabled': True},
    )
    assert created.status_code == 201, created.text
    sid = created.json()['id']

    discovered = client.get(f'/platform/mcp/servers/{sid}/tools', headers=h)
    assert discovered.status_code == 200, discovered.text
    body = discovered.json()
    assert body['status'] == 'error'
    assert '未配置 url' in body['note']
    assert body['status'] != 'stub'

    called = client.post(
        f'/platform/mcp/servers/{sid}/call',
        headers=h, json={'tool': 'x', 'arguments': {}},
    )
    assert called.status_code == 503, called.text
    detail = called.json()['detail']
    assert detail['reason'] == 'server_not_connected'
    entry = client.get('/platform/mcp/overview', headers=h).json()['recent_calls'][0]
    assert entry['mode'] == 'error'
    assert '未配置 url' in entry['note']
