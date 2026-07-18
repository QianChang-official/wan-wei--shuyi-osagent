"""B8 · MCP 协议枢纽。

职责：
- MCP 服务器注册 CRUD（持久化于 ``JsonStore('mcp_servers')``）；
- 工具发现：stdio 传输下以 JSON-RPC（``initialize`` → ``tools/list``）实时探测，
  10 秒总预算、subprocess 管道通信；
- 调用代理：真实连接可用（enabled + stdio + command）时转发 ``tools/call``，
  否则诚实返回 ``stub`` 调用计划；
- 总览：服务器数 / 启用数 / 已发现工具数 / 最近 20 条调用记录。

存储约定（单文件 ``platform_mcp_servers.json``）：
- 服务器记录以其 ``id`` 为键；
- 保留键以下划线开头：``_recent_calls``（最近调用，最新在前，≤20 条）、
  ``_seeded_at``（预置示例写入标记，防止用户清空后重复播种）。

协议说明（诚实边界）：
- 写帧采用平台契约要求的 LSP 风格 ``Content-Length`` 帧；
- 读帧宽容：同时兼容 Content-Length 帧与 MCP 官方 stdio 的换行分隔 JSON
  （NDJSON），以提高对真实 MCP 服务器的命中率；
- sse / streamable_http 传输暂未接入真实连接，相关发现/调用一律返回
  ``stub`` 标识与说明，不伪装已连接。
"""
import json
import os
import queue
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.platform_api.store import JsonStore

router = APIRouter(prefix='/mcp', tags=['mcp-hub'])

_store = JsonStore('mcp_servers')

Transport = Literal['stdio', 'sse', 'streamable_http']
Status = Literal['unknown', 'connected', 'error']

_CALLS_KEY = '_recent_calls'
_SEED_KEY = '_seeded_at'
_CALLS_CAP = 20
_RPC_BUDGET = 10.0  # 一次 stdio 会话（initialize + 一次请求）的总超时（秒）


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------

class ServerIn(BaseModel):
    """POST /mcp/servers 请求体。"""

    name: str = Field(min_length=1)
    transport: Transport
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    enabled: bool = True
    status: Status = 'unknown'
    note: str | None = None


class ServerPatch(BaseModel):
    """PUT /mcp/servers/{sid} 请求体（部分更新，仅合并显式传入字段）。"""

    name: str | None = Field(default=None, min_length=1)
    transport: Transport | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    url: str | None = None
    enabled: bool | None = None
    status: Status | None = None
    note: str | None = None


class CallIn(BaseModel):
    """POST /mcp/servers/{sid}/call 请求体。"""

    tool: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# 存储辅助
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec='seconds')


def _new_id() -> str:
    return f'srv_{uuid.uuid4().hex[:8]}'


_PRESETS: list[dict[str, Any]] = [
    {
        'id': 'srv_filesystem',
        'name': 'filesystem',
        'transport': 'stdio',
        'command': 'npx',
        'args': ['-y', '@modelcontextprotocol/server-filesystem', '.'],
        'env': {},
        'url': None,
        'enabled': False,
        'status': 'unknown',
        'note': '示例：官方文件系统 MCP 服务器（需 Node.js，启用前请确认允许访问的目录）',
    },
    {
        'id': 'srv_brave_search',
        'name': 'brave-search',
        'transport': 'stdio',
        'command': 'npx',
        'args': ['-y', '@modelcontextprotocol/server-brave-search'],
        'env': {'BRAVE_API_KEY': ''},
        'url': None,
        'enabled': False,
        'status': 'unknown',
        'note': '示例：Brave 搜索 MCP 服务器（需在 env 中填入 BRAVE_API_KEY 后方可启用）',
    },
    {
        'id': 'srv_sqlite',
        'name': 'sqlite',
        'transport': 'stdio',
        'command': 'uvx',
        'args': ['mcp-server-sqlite', '--db-path', 'data/platform.sqlite'],
        'env': {},
        'url': None,
        'enabled': False,
        'status': 'unknown',
        'note': '示例：SQLite MCP 服务器（需 uv/uvx，启用前请确认库文件路径）',
    },
]


def _ensure_seeded() -> None:
    """首次访问时写入 3 个预置示例服务器（enabled:false），幂等。"""
    if _store.get(_SEED_KEY):
        return
    now = _now()
    mapping: dict[str, Any] = {_SEED_KEY: now}
    for preset in _PRESETS:
        rec = dict(preset)
        rec['created_at'] = now
        rec['tools_cache'] = []
        rec['tools_count'] = 0
        mapping[rec['id']] = rec
    _store.update(mapping)


def _servers() -> dict[str, dict]:
    """全部服务器记录（过滤保留键与墓碑）。"""
    return {
        key: value
        for key, value in _store.all().items()
        if not key.startswith('_') and isinstance(value, dict)
    }


def _get_server_or_404(sid: str) -> dict:
    rec = _store.get(sid)
    if not isinstance(rec, dict):
        raise HTTPException(status_code=404, detail=f'MCP 服务器不存在：{sid}')
    return rec


def _delete_key(key: str) -> None:
    """JsonStore 无公开 delete，整读重写移除指定键（带锁，失败退化为墓碑）。"""
    data = _store.all()
    if key not in data:
        return
    data.pop(key)
    write = getattr(_store, '_write', None)
    lock = getattr(_store, '_lock', None)
    if callable(write) and lock is not None:
        with lock:
            write(data)
    else:  # 私有结构变化时的兜底：墓碑（读路径已过滤非 dict 值）
        _store.set(key, None)


def _record_call(rec: dict, payload: CallIn, *, ok: bool, mode: str, note: str) -> dict:
    """向 _recent_calls 追加一条调用记录（最新在前，封顶 20 条）。"""
    calls = _store.get(_CALLS_KEY, [])
    if not isinstance(calls, list):
        calls = []
    entry = {
        'id': f'call_{uuid.uuid4().hex[:8]}',
        'ts': _now(),
        'server_id': rec.get('id'),
        'server_name': rec.get('name'),
        'tool': payload.tool,
        'arguments': payload.arguments,
        'ok': ok,
        'mode': mode,
        'note': note,
    }
    calls.insert(0, entry)
    _store.set(_CALLS_KEY, calls[:_CALLS_CAP])
    return entry


# ---------------------------------------------------------------------------
# stdio JSON-RPC 客户端（Content-Length 帧写入，宽容读帧，10 秒总预算）
# ---------------------------------------------------------------------------

def _parse_length(header_line: bytes) -> int | None:
    try:
        return int(header_line.split(b':', 1)[1].strip())
    except (IndexError, ValueError):
        return None


def _read_exact(stream: Any, size: int) -> bytes | None:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b''.join(chunks)


class _StdioRpc:
    """一次性 stdio JSON-RPC 会话：启动子进程 → initialize → 一次请求 → 关闭。

    所有等待共享 ``deadline``（单调时钟），超时/进程退出/协议错误均抛异常，
    由调用方落为 error/stub 响应。
    """

    def __init__(self, command: str, args: list[str], env: dict[str, str], deadline: float):
        self._deadline = deadline
        self._id = 0
        self._rx: queue.Queue = queue.Queue()

        resolved = shutil.which(command) or command
        argv = [resolved, *(args or [])]
        full_env = dict(os.environ)
        full_env.update({k: v for k, v in (env or {}).items() if isinstance(v, str) and v})

        popen_kwargs: dict[str, Any] = {
            'stdin': subprocess.PIPE,
            'stdout': subprocess.PIPE,
            'stderr': subprocess.DEVNULL,
            'env': full_env,
        }
        if os.name == 'nt':
            # 桌面端后台进程不弹控制台窗口
            popen_kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        if os.name == 'nt' and resolved.lower().endswith(('.cmd', '.bat')):
            # Windows 的 npx/uvx 是 .cmd  shim，CreateProcess 无法直接执行
            self._proc = subprocess.Popen(  # noqa: S602 —— 仅 shim 场景，命令源自用户配置
                subprocess.list2cmdline(argv), shell=True, **popen_kwargs
            )
        else:
            self._proc = subprocess.Popen(argv, shell=False, **popen_kwargs)

        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()

    # -- 底层帧 -------------------------------------------------------------

    def _pump(self) -> None:
        """读帧线程：Content-Length 帧或 NDJSON 行，解析后放入队列；EOF 放哨兵。"""
        stream = self._proc.stdout
        try:
            while True:
                line = stream.readline()
                if not line:
                    break
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.lower().startswith(b'content-length:'):
                    length = _parse_length(stripped)
                    # 吞掉其余头部，直到空行
                    while True:
                        header = stream.readline()
                        if not header or not header.strip():
                            break
                        if header.strip().lower().startswith(b'content-length:'):
                            length = _parse_length(header.strip())
                    if not length:
                        continue
                    body = _read_exact(stream, length)
                    if body is None:
                        break
                    self._offer(body)
                elif stripped.startswith(b'{'):
                    self._offer(stripped)
                # 其余行视为服务器日志输出，忽略
        except Exception:  # noqa: BLE001 —— 读帧线程静默收口，由队列哨兵通知主线程
            pass
        finally:
            self._rx.put(None)

    def _offer(self, body: bytes) -> None:
        try:
            msg = json.loads(body.decode('utf-8', errors='replace'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if isinstance(msg, dict):
            self._rx.put(msg)

    def _send(self, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        frame = f'Content-Length: {len(body)}\r\n\r\n'.encode('ascii') + body
        assert self._proc.stdin is not None
        self._proc.stdin.write(frame)
        self._proc.stdin.flush()

    def _remaining(self) -> float:
        left = self._deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError(f'MCP stdio 会话超过 {_RPC_BUDGET:.0f} 秒总预算')
        return left

    # -- 会话动作 -----------------------------------------------------------

    def request(self, method: str, params: dict | None = None) -> Any:
        self._id += 1
        rid = self._id
        self._send({'jsonrpc': '2.0', 'id': rid, 'method': method, 'params': params or {}})
        while True:
            try:
                msg = self._rx.get(timeout=self._remaining())
            except queue.Empty as exc:
                raise TimeoutError(f'{method} 等待响应超时（{_RPC_BUDGET:.0f}s 预算内）') from exc
            if msg is None:
                raise ConnectionError('MCP 服务器进程已退出或标准输出关闭')
            if msg.get('id') != rid:  # 跳过通知与无关响应
                continue
            if 'error' in msg:
                raise RuntimeError(f'{method} 被服务器拒绝：{msg["error"]}')
            return msg.get('result', {})

    def notify(self, method: str, params: dict | None = None) -> None:
        self._send({'jsonrpc': '2.0', 'method': method, 'params': params or {}})

    def close(self) -> None:
        try:
            if self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=1.5)
                except Exception:  # noqa: BLE001
                    self._proc.kill()
        except Exception:  # noqa: BLE001 —— 清理阶段不再抛错
            pass


def _open_session(rec: dict) -> _StdioRpc:
    """启动子进程并完成 initialize 握手；任何失败抛异常。"""
    deadline = time.monotonic() + _RPC_BUDGET
    rpc = _StdioRpc(rec['command'], rec.get('args') or [], rec.get('env') or {}, deadline)
    try:
        rpc.request('initialize', {
            'protocolVersion': '2024-11-05',
            'capabilities': {},
            'clientInfo': {'name': 'wanwei-mcp-hub', 'version': '0.1.0'},
        })
        rpc.notify('notifications/initialized')
    except Exception:
        rpc.close()
        raise
    return rpc


def _mark_error(sid: str, rec: dict, message: str) -> None:
    rec['status'] = 'error'
    rec['last_error'] = message
    _store.set(sid, rec)


# ---------------------------------------------------------------------------
# 服务器注册 CRUD
# ---------------------------------------------------------------------------

@router.get('/servers')
def list_servers() -> dict:
    """服务器列表（含预置示例）。"""
    _ensure_seeded()
    servers = sorted(
        _servers().values(),
        key=lambda s: (s.get('created_at') or '', s.get('id') or ''),
    )
    return {'servers': servers, 'total': len(servers)}


@router.post('/servers', status_code=201)
def create_server(payload: ServerIn) -> dict:
    """注册新 MCP 服务器。"""
    _ensure_seeded()
    sid = _new_id()
    rec = {
        'id': sid,
        **payload.model_dump(),
        'created_at': _now(),
        'tools_cache': [],
        'tools_count': 0,
    }
    _store.set(sid, rec)
    return rec


@router.get('/servers/{sid}')
def get_server(sid: str) -> dict:
    """单个服务器详情。"""
    _ensure_seeded()
    return _get_server_or_404(sid)


@router.put('/servers/{sid}')
def update_server(sid: str, payload: ServerPatch) -> dict:
    """部分更新服务器配置（仅合并显式传入字段）。"""
    _ensure_seeded()
    rec = _get_server_or_404(sid)
    rec.update(payload.model_dump(exclude_unset=True))
    _store.set(sid, rec)
    return rec


@router.delete('/servers/{sid}')
def delete_server(sid: str) -> dict:
    """注销服务器（历史调用记录保留在总览中）。"""
    _ensure_seeded()
    _get_server_or_404(sid)
    _delete_key(sid)
    return {'ok': True, 'id': sid}


# ---------------------------------------------------------------------------
# 工具发现
# ---------------------------------------------------------------------------

@router.get('/servers/{sid}/tools')
def discover_tools(sid: str) -> dict:
    """实时探测服务器工具清单。

    stdio + command 时发起真实 JSON-RPC 探测（10 秒预算）；其余情形返回
    stub/error 标识与说明，绝不伪装已连接。
    """
    _ensure_seeded()
    rec = _get_server_or_404(sid)
    transport = rec.get('transport')

    if transport != 'stdio':
        cache = rec.get('tools_cache') or []
        return {
            'server': sid,
            'transport': transport,
            'tools': cache,
            'status': 'stub',
            'note': f'传输方式 {transport} 的真实发现暂未接入（当前仅支持 stdio），返回已缓存清单',
        }
    if not rec.get('command'):
        return {
            'server': sid,
            'transport': transport,
            'tools': [],
            'status': 'stub',
            'note': '未配置 command，无法发起 stdio 探测',
        }

    try:
        rpc = _open_session(rec)
        try:
            result = rpc.request('tools/list')
        finally:
            rpc.close()
    except Exception as exc:  # noqa: BLE001 —— 子进程/协议/超时统一落为 error
        note = f'工具发现失败：{exc}'
        _mark_error(sid, rec, note)
        return {'server': sid, 'transport': transport, 'tools': [], 'status': 'error', 'note': note}

    tools = result.get('tools') if isinstance(result, dict) else None
    tools = tools if isinstance(tools, list) else []
    rec['status'] = 'connected'
    rec['last_error'] = None
    rec['tools_cache'] = tools
    rec['tools_count'] = len(tools)
    rec['last_discovery_at'] = _now()
    _store.set(sid, rec)
    return {
        'server': sid,
        'transport': transport,
        'tools': tools,
        'status': 'connected',
        'source': 'live',
        'note': f'实时探测成功，发现 {len(tools)} 个工具',
    }


# ---------------------------------------------------------------------------
# 调用代理
# ---------------------------------------------------------------------------

@router.post('/servers/{sid}/call')
def call_tool(sid: str, payload: CallIn) -> dict:
    """转发一次 tools/call。

    真实连接可用（enabled + stdio + command）时执行并返回 mode:'live'；
    连接不可用时返回 mode:'stub' 与调用计划；真实调用失败返回 mode:'error'。
    三种结局都会写入最近调用记录。
    """
    _ensure_seeded()
    rec = _get_server_or_404(sid)
    plan = {
        'server': sid,
        'server_name': rec.get('name'),
        'tool': payload.tool,
        'arguments': payload.arguments,
    }
    live_ready = bool(rec.get('enabled')) and rec.get('transport') == 'stdio' and bool(rec.get('command'))

    if not live_ready:
        note = 'MCP 服务器未连接，调用计划已记录'
        _record_call(rec, payload, ok=False, mode='stub', note=note)
        return {'ok': False, 'mode': 'stub', 'note': note, 'plan': plan}

    try:
        rpc = _open_session(rec)
        try:
            result = rpc.request('tools/call', {'name': payload.tool, 'arguments': payload.arguments})
        finally:
            rpc.close()
    except Exception as exc:  # noqa: BLE001
        note = f'真实调用失败：{exc}'
        _mark_error(sid, rec, note)
        _record_call(rec, payload, ok=False, mode='error', note=note)
        return {'ok': False, 'mode': 'error', 'note': note, 'plan': plan}

    rec['status'] = 'connected'
    rec['last_error'] = None
    _store.set(sid, rec)
    note = '真实转发成功'
    _record_call(rec, payload, ok=True, mode='live', note=note)
    return {'ok': True, 'mode': 'live', 'server': sid, 'tool': payload.tool, 'result': result, 'note': note}


# ---------------------------------------------------------------------------
# 总览
# ---------------------------------------------------------------------------

@router.get('/overview')
def overview() -> dict:
    """MCP 枢纽总览：规模统计 + 最近 20 条调用记录。"""
    _ensure_seeded()
    servers = _servers()
    calls = _store.get(_CALLS_KEY, [])
    if not isinstance(calls, list):
        calls = []
    return {
        'servers': len(servers),
        'enabled': sum(1 for s in servers.values() if s.get('enabled')),
        'tools_discovered': sum(int(s.get('tools_count') or 0) for s in servers.values()),
        'recent_calls': calls[:_CALLS_CAP],
    }
