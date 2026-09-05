"""自动化工作流「真实执行」回归测试（按 gear 门禁启用）。

覆盖条目：
1. human_review（默认档）保持 dry-run 模拟行为不变，run.mode='dry_run'。
2. shell 真实执行：白名单命中真实运行；非白名单/元字符/越界路径一律
   failed 且 detail 写明原因（复用 _system_svc_runtime 沙盒常量）。
3. http 真实请求：对本地起的真实 HTTP 子服务发 GET/POST 往返；
   非 2xx failed 带状态码；未 monkeypatch 时 SSRF 校验拦截回环地址。
4. memory 真实读写：写入前过 Policy Gate，敏感内容拦截即失败且不落库；
   正常内容真实写入后可按 capsule_id 读回。
5. condition 合法表达式安全求值；调用/名称/语法错误如实 failed。
6. agent 步骤复用网关回退链：网关不可用 → failed 不回退假文本；
   可用 → 真实文本 + provider 标注。
7. device 档未显式授权时 fail-closed。
8. gear 字段默认值与旧记录兼容（flow/run 双向回填）。
9. 显式模拟入口 /simulate 对 sandbox 流程强制 dry-run。
10. on_error=stop 跳过语义在真实执行下成立，绝不留 running 假死。
11. 真实执行起止各落一条审计事件（flow_run_started/flow_run_finished）。
"""
from __future__ import annotations

import http.server
import json
import os
import shutil
import sqlite3
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


from backend.app.platform_api import automation  # noqa: E402
from backend.app.platform_api import agents as agents_mod  # noqa: E402


# ---------------------------------------------------------------------------
# 夹具与工具
# ---------------------------------------------------------------------------

@pytest.fixture
def store_dir(tmp_path, monkeypatch):
    """隔离的 platform 存储目录（JsonStore 惰性解析路径，换 env 即隔离）。"""
    monkeypatch.setenv('WANWEI_PLATFORM_DIR', str(tmp_path / 'platform'))
    return tmp_path / 'platform'


@pytest.fixture
def client(store_dir):
    """只挂 automation 路由的轻量 TestClient（不走主 app 的鉴权中间件）。"""
    app = FastAPI()
    app.include_router(automation.router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def mem_db(tmp_path, monkeypatch):
    """隔离记忆库：capsule_store/policy_gate/audit 真实读写用。"""
    db_path = tmp_path / 'automation-memory.db'
    monkeypatch.setenv('WANWEI_MEMORY_DB', str(db_path))
    from backend.app.db import close_all
    close_all()
    from backend.app.init_db import main as init_db
    init_db()
    yield str(db_path)
    close_all()


class _EchoHandler(http.server.BaseHTTPRequestHandler):
    """本地真实 HTTP 子服务：/ok 返回 200 JSON；其余 404；POST 回显长度。"""

    def do_GET(self):  # noqa: N802 —— BaseHTTPRequestHandler 约定
        if self.path == '/ok':
            body = json.dumps({'ok': True}).encode('utf-8')
            self.send_response(200)
        else:
            body = json.dumps({'error': 'not found'}).encode('utf-8')
            self.send_response(404)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get('Content-Length') or 0)
        self.rfile.read(length)
        body = json.dumps({'received': length}).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # 静默访问日志
        pass


@pytest.fixture
def local_http_server():
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), _EchoHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_address[1]}'
    finally:
        server.shutdown()
        server.server_close()


def _wait_done(run_id: str, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = automation._runs.get(run_id)
        if isinstance(run, dict) and run.get('status') != 'running':
            return run
        time.sleep(0.05)
    raise AssertionError(f'运行 {run_id} 超时未终结')


def _create_flow(client: TestClient, **payload) -> dict:
    body = {'name': '真实执行测试流程', 'trigger': 'manual'}
    body.update(payload)
    r = client.post('/automation/flows', json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _run_and_wait(client: TestClient, flow: dict, *, path: str = 'run') -> tuple[dict, dict]:
    r = client.post(f"/automation/flows/{flow['id']}/{path}")
    assert r.status_code == 202, r.text
    run = r.json()
    return run, _wait_done(run['id'])


def _shell_py_command() -> str | None:
    """白名单里跨平台必然存在的命令只有 python/python3 --version。"""
    if shutil.which('python'):
        return 'python'
    if shutil.which('python3'):
        return 'python3'
    return None


# ---------------------------------------------------------------------------
# 1. human_review 默认档保持 dry-run
# ---------------------------------------------------------------------------

def test_human_review_default_stays_dry_run(store_dir, client):
    flow = _create_flow(client, steps=[{
        'id': 'st1', 'type': 'shell', 'name': '列目录',
        'config': {'command': 'echo hello'}, 'on_error': 'stop',
    }])
    assert flow['gear'] == 'human_review'  # 默认档位
    run, final = _run_and_wait(client, flow)
    assert run['mode'] == 'dry_run'
    assert final['mode'] == 'dry_run'
    assert final['status'] == 'done' and final['done'] is True
    st = final['step_results'][0]
    assert st['status'] == 'done'
    assert st['would_run'] == 'echo hello'
    assert '模拟执行' in st['detail']
    assert 'stdout' not in st  # 没有真实执行的产物字段


# ---------------------------------------------------------------------------
# 2. shell 真实执行：白名单命中 / 拒绝
# ---------------------------------------------------------------------------

def test_shell_whitelist_hit_runs_for_real(store_dir, client):
    py = _shell_py_command()
    if py is None:
        pytest.skip('沙盒白名单内 python/python3 在当前平台不可用')
    flow = _create_flow(client, gear='sandbox', steps=[{
        'id': 'st1', 'type': 'shell', 'name': '版本号',
        'config': {'command': f'{py} --version'}, 'on_error': 'stop',
    }])
    run, final = _run_and_wait(client, flow)
    assert run['mode'] == 'real'
    assert final['status'] == 'done'
    st = final['step_results'][0]
    assert st['status'] == 'done', st
    assert st['exit_code'] == 0
    assert st['stdout'].strip().startswith('Python'), st
    assert '真实执行完成' in st['detail']


@pytest.mark.skipif(os.name != 'posix', reason='cat/pwd 仅 POSIX 提供')
def test_shell_cwd_confined_to_sandbox_posix(store_dir, client):
    sandbox = store_dir / 'sandbox'
    sandbox.mkdir(parents=True, exist_ok=True)
    (sandbox / 'note.txt').write_text('hello-cwd-proof', encoding='utf-8')
    flow = _create_flow(client, gear='sandbox', steps=[
        {'id': 'st1', 'type': 'shell', 'name': 'pwd',
         'config': {'command': 'pwd'}, 'on_error': 'continue'},
        {'id': 'st2', 'type': 'shell', 'name': '读监禁目录文件',
         'config': {'command': 'cat note.txt'}, 'on_error': 'continue'},
    ])
    _run, final = _run_and_wait(client, flow)
    pwd_st, cat_st = final['step_results']
    assert Path(pwd_st['stdout'].strip()) == sandbox.resolve()
    assert 'hello-cwd-proof' in cat_st['stdout']


def test_shell_rejects_nonwhitelist_meta_chars_and_path_escape(store_dir, client):
    flow = _create_flow(client, gear='sandbox', steps=[
        {'id': 'st1', 'type': 'shell', 'name': '非白名单命令',
         'config': {'command': 'curl https://example.com'}, 'on_error': 'continue'},
        {'id': 'st2', 'type': 'shell', 'name': '参数不符',
         'config': {'command': 'python -c "print(1)"'}, 'on_error': 'continue'},
        {'id': 'st3', 'type': 'shell', 'name': '绝对路径越界',
         'config': {'command': 'cat /etc/passwd'}, 'on_error': 'continue'},
        {'id': 'st4', 'type': 'shell', 'name': '相对路径越界',
         'config': {'command': 'cat ../../secrets.txt'}, 'on_error': 'continue'},
        {'id': 'st5', 'type': 'shell', 'name': '元字符',
         'config': {'command': 'echo a && echo b'}, 'on_error': 'continue'},
    ])
    _run, final = _run_and_wait(client, flow)
    sts = {st['step_id']: st for st in final['step_results']}
    assert all(sts[f'st{i}']['status'] == 'failed' for i in range(1, 6))
    assert '不在沙盒白名单内' in sts['st1']['detail']
    assert '仅允许参数' in sts['st2']['detail']
    assert '越出沙盒监禁目录' in sts['st3']['detail']
    assert '越出沙盒监禁目录' in sts['st4']['detail']
    assert '元字符' in sts['st5']['detail']


# ---------------------------------------------------------------------------
# 3. http 真实请求
# ---------------------------------------------------------------------------

def test_http_real_get_post_and_404_against_local_server(
    store_dir, client, local_http_server, monkeypatch,
):
    # SSRF 校验器默认拒绝回环地址；本用例显式放行以打真实本地子服务，
    # pinned-IP 直连与响应处理逻辑仍走生产代码路径。
    monkeypatch.setattr(
        automation, 'resolve_external_url',
        lambda url, **kwargs: (url, '127.0.0.1'),
    )
    flow = _create_flow(client, gear='sandbox', steps=[
        {'id': 'st1', 'type': 'http', 'name': 'GET 200',
         'config': {'method': 'GET', 'url': f'{local_http_server}/ok'},
         'on_error': 'continue'},
        {'id': 'st2', 'type': 'http', 'name': 'POST 往返',
         'config': {'method': 'POST', 'url': f'{local_http_server}/echo'},
         'on_error': 'continue'},
        {'id': 'st3', 'type': 'http', 'name': 'GET 404',
         'config': {'method': 'GET', 'url': f'{local_http_server}/missing'},
         'on_error': 'continue'},
    ])
    _run, final = _run_and_wait(client, flow)
    get_st, post_st, miss_st = final['step_results']

    assert get_st['status'] == 'done', get_st
    assert get_st['status_code'] == 200
    assert '"ok"' in get_st['response_body']
    assert '状态码 200' in get_st['detail']

    assert post_st['status'] == 'done', post_st
    assert post_st['status_code'] == 200
    assert '"received"' in post_st['response_body']

    assert miss_st['status'] == 'failed'
    assert '404' in miss_st['detail']


def test_http_ssrf_blocks_loopback_by_default(store_dir, client):
    # 不做任何 monkeypatch：SSRF 校验必须把回环地址拦下，且未发起真实请求
    flow = _create_flow(client, gear='sandbox', steps=[
        {'id': 'st1', 'type': 'http', 'name': '回环目标',
         'config': {'method': 'GET', 'url': 'http://127.0.0.1:9/deny-me'},
         'on_error': 'stop'},
    ])
    _run, final = _run_and_wait(client, flow)
    st = final['step_results'][0]
    assert st['status'] == 'failed'
    assert 'SSRF 校验拦截' in st['detail']


def test_http_rejects_unsupported_method_for_real_exec(store_dir, client):
    flow = _create_flow(client, gear='sandbox', steps=[
        {'id': 'st1', 'type': 'http', 'name': 'DELETE 不支持',
         'config': {'method': 'DELETE', 'url': 'https://example.com/x'},
         'on_error': 'stop'},
    ])
    _run, final = _run_and_wait(client, flow)
    st = final['step_results'][0]
    assert st['status'] == 'failed'
    assert '仅支持 GET/POST' in st['detail']


# ---------------------------------------------------------------------------
# 4. memory 真实读写
# ---------------------------------------------------------------------------

def test_memory_write_blocked_by_policy_gate(store_dir, client, mem_db):
    from backend.app.memory_runtime import capsule_store
    secret_text = '生产环境我的密码是 hunter2-secret-value'
    flow = _create_flow(client, gear='sandbox', steps=[
        {'id': 'st1', 'type': 'memory', 'name': '写敏感内容',
         'config': {'op': 'write', 'key': '', 'desc': secret_text},
         'on_error': 'stop'},
    ])
    _run, final = _run_and_wait(client, flow)
    assert final['status'] == 'failed'
    st = final['step_results'][0]
    assert st['status'] == 'failed'
    assert 'Policy Gate 拦截' in st['detail']
    # 内容确实未落库
    capsule_store.init_runtime_schema()
    assert capsule_store.list_capsules(limit=50) == []
    # 拦截动作落了审计
    with sqlite3.connect(mem_db) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM audit_logs WHERE event_type='policy_blocked'"
        ).fetchone()
    assert row[0] >= 1


def test_memory_write_then_read_roundtrip(store_dir, client, mem_db):
    from backend.app.memory_runtime import capsule_store
    plain_text = '万枢自动化工作流真实写入的记忆内容'
    write_flow = _create_flow(client, gear='sandbox', steps=[
        {'id': 'st1', 'type': 'memory', 'name': '写入记忆',
         'config': {'op': 'write', 'key': 'auto-test', 'desc': plain_text},
         'on_error': 'stop'},
    ])
    _run, final = _run_and_wait(client, write_flow)
    assert final['status'] == 'done', final
    st = final['step_results'][0]
    assert st['status'] == 'done', st
    capsule_id = st['output']
    assert capsule_id.startswith('cap_')
    assert '真实写入记忆胶囊' in st['detail']
    # 库里确实有这条胶囊
    assert capsule_store.get_capsule(capsule_id) is not None

    read_flow = _create_flow(client, gear='sandbox', steps=[
        {'id': 'st1', 'type': 'memory', 'name': '读回记忆',
         'config': {'op': 'read', 'key': capsule_id, 'desc': ''},
         'on_error': 'stop'},
    ])
    _run2, final2 = _run_and_wait(client, read_flow)
    assert final2['status'] == 'done'
    read_st = final2['step_results'][0]
    assert read_st['status'] == 'done'
    assert plain_text in read_st['output']


def test_memory_steps_are_scoped_to_run_owner(store_dir, client, mem_db, monkeypatch):
    from backend.app.memory_runtime import capsule_store

    owner_a = 'api_owner_a'
    owner_b = 'api_owner_b'
    monkeypatch.setattr(automation, '_actor_id', lambda request=None: owner_a)
    write_flow = _create_flow(client, gear='sandbox', steps=[{
        'id': 'st1', 'type': 'memory', 'name': 'A 写入记忆',
        'config': {'op': 'write', 'key': 'owner-a', 'desc': 'only owner A can read this'},
        'on_error': 'stop',
    }])
    _run, written = _run_and_wait(client, write_flow)
    capsule_id = written['step_results'][0]['capsule_id']
    assert capsule_store.get_capsule(capsule_id, owner_id=owner_a) is not None
    assert capsule_store.get_capsule(capsule_id, owner_id=owner_b) is None

    monkeypatch.setattr(automation, '_actor_id', lambda request=None: owner_b)
    read_flow = _create_flow(client, gear='sandbox', steps=[{
        'id': 'st1', 'type': 'memory', 'name': 'B 读取 A 的记忆',
        'config': {'op': 'read', 'key': capsule_id}, 'on_error': 'stop',
    }])
    _run, read = _run_and_wait(client, read_flow)
    assert read['step_results'][0]['status'] == 'failed'
    assert '不存在或当前作用域不可读' in read['step_results'][0]['detail']


def test_memory_read_missing_capsule_fails_honestly(store_dir, client, mem_db):
    flow = _create_flow(client, gear='sandbox', steps=[
        {'id': 'st1', 'type': 'memory', 'name': '读不存在',
         'config': {'op': 'read', 'key': 'cap_does_not_exist00', 'desc': ''},
         'on_error': 'stop'},
    ])
    _run, final = _run_and_wait(client, flow)
    st = final['step_results'][0]
    assert st['status'] == 'failed'
    assert '不存在或当前作用域不可读' in st['detail']


# ---------------------------------------------------------------------------
# 5. condition 安全求值
# ---------------------------------------------------------------------------

def test_condition_valid_expressions_evaluate(store_dir, client):
    flow = _create_flow(client, gear='sandbox', steps=[
        {'id': 'st1', 'type': 'condition', 'name': '数值比较',
         'config': {'expr': '1 < 2'}, 'on_error': 'continue'},
        {'id': 'st2', 'type': 'condition', 'name': '字符串相等',
         'config': {'expr': "'a' == 'a'"}, 'on_error': 'continue'},
        {'id': 'st3', 'type': 'condition', 'name': '布尔组合与链式',
         'config': {'expr': '(1 < 2) and (3 >= 3)'}, 'on_error': 'continue'},
    ])
    _run, final = _run_and_wait(client, flow)
    sts = final['step_results']
    assert all(st['status'] == 'done' for st in sts)
    assert [st['condition_result'] for st in sts] == [True, True, True]


def test_condition_invalid_or_unsupported_fails_honestly(store_dir, client):
    flow = _create_flow(client, gear='sandbox', steps=[
        {'id': 'st1', 'type': 'condition', 'name': '函数调用',
         'config': {'expr': "len('ab') > 1"}, 'on_error': 'continue'},
        {'id': 'st2', 'type': 'condition', 'name': '动态导入',
         'config': {'expr': "__import__('os').getcwd()"}, 'on_error': 'continue'},
        {'id': 'st3', 'type': 'condition', 'name': '引用未知名称',
         'config': {'expr': 'some_var > 1'}, 'on_error': 'continue'},
        {'id': 'st4', 'type': 'condition', 'name': '语法错误',
         'config': {'expr': '1 <'}, 'on_error': 'continue'},
        {'id': 'st5', 'type': 'condition', 'name': '空表达式',
         'config': {'expr': ''}, 'on_error': 'continue'},
    ])
    _run, final = _run_and_wait(client, flow)
    sts = {st['step_id']: st for st in final['step_results']}
    for i in range(1, 6):
        assert sts[f'st{i}']['status'] == 'failed', sts[f'st{i}']
        assert '不支持安全求值' in sts[f'st{i}']['detail'] or '未配置表达式' in sts[f'st{i}']['detail']


# ---------------------------------------------------------------------------
# 6. agent 步骤走模型网关
# ---------------------------------------------------------------------------

def test_agent_step_fails_honest_when_gateway_unavailable(store_dir, client, monkeypatch):
    # 无可用 provider（回退链解析为 None）→ 必须如实 failed，不得回退模拟文本
    monkeypatch.setattr(
        agents_mod,
        '_resolve_gateway_target',
        lambda run=None, owner_id=None: None,
    )
    flow = _create_flow(client, gear='sandbox', steps=[
        {'id': 'st1', 'type': 'agent', 'name': '总结任务',
         'config': {'task': '总结一下今天的工作'}, 'on_error': 'stop'},
    ])
    _run, final = _run_and_wait(client, flow)
    st = final['step_results'][0]
    assert st['status'] == 'failed'
    assert '模型网关不可用' in st['detail']


def test_agent_step_uses_gateway_text_when_available(store_dir, client, monkeypatch):
    async def _fake_gateway(prompt, run=None, owner_id=None):
        return '网关返回的真实补全文本', 'fake-provider'

    monkeypatch.setattr(agents_mod, '_try_gateway', _fake_gateway)
    flow = _create_flow(client, gear='sandbox', steps=[
        {'id': 'st1', 'type': 'agent', 'name': '总结任务',
         'config': {'task': '总结一下今天的工作'}, 'on_error': 'stop'},
    ])
    _run, final = _run_and_wait(client, flow)
    st = final['step_results'][0]
    assert st['status'] == 'done'
    assert st['output'] == '网关返回的真实补全文本'
    assert st['provider'] == 'fake-provider'
    assert 'provider=fake-provider' in st['detail']


def test_agent_step_passes_run_owner_to_gateway(store_dir, client, monkeypatch):
    expected_owner = 'api_flow_owner'
    seen: list[str | None] = []

    async def _fake_gateway(prompt, run=None, owner_id=None):
        seen.append(owner_id)
        return 'owner scoped gateway reply', 'fake-provider'

    monkeypatch.setattr(automation, '_actor_id', lambda request=None: expected_owner)
    monkeypatch.setattr(agents_mod, '_try_gateway', _fake_gateway)
    flow = _create_flow(client, gear='sandbox', steps=[{
        'id': 'st1', 'type': 'agent', 'name': 'owner gateway',
        'config': {'task': 'use the request owner'}, 'on_error': 'stop',
    }])
    _run, final = _run_and_wait(client, flow)
    assert final['step_results'][0]['status'] == 'done'
    assert seen == [expected_owner]


# ---------------------------------------------------------------------------
# 7. device 档 fail-closed
# ---------------------------------------------------------------------------

def test_device_gear_fail_closed_without_env_authorization(store_dir, client, monkeypatch):
    monkeypatch.delenv('WANWEI_DEVICE_GEAR_ENABLED', raising=False)
    py = _shell_py_command()
    command = f'{py} --version' if py else 'date'
    flow = _create_flow(client, gear='device', steps=[
        {'id': 'st1', 'type': 'shell', 'name': '设备档命令',
         'config': {'command': command}, 'on_error': 'stop'},
    ])
    run, final = _run_and_wait(client, flow)
    assert run['mode'] == 'real'
    st = final['step_results'][0]
    assert st['status'] == 'failed'
    assert '门禁拒绝' in st['detail']
    # 兜底契约：绝不留 running 假死
    assert final['done'] is True and final['finished_at'] is not None


# ---------------------------------------------------------------------------
# 8. gear 字段默认值与旧记录兼容
# ---------------------------------------------------------------------------

def test_legacy_flow_and_run_records_default_compat(store_dir, client):
    # 旧流程记录无 gear 字段：读取视图回填 human_review，运行仍为 dry-run
    automation._flows.set('flow_legacy', {
        'id': 'flow_legacy', 'name': '旧流程', 'trigger': 'manual',
        'steps': [], 'enabled': True,
    })
    r = client.get('/automation/flows/flow_legacy')
    assert r.status_code == 200
    assert r.json()['gear'] == 'human_review'

    r = client.post('/automation/flows/flow_legacy/run')
    assert r.status_code == 202
    assert r.json()['mode'] == 'dry_run'

    # 旧运行记录无 mode 字段：视图回填 dry_run
    automation._runs.set('run_legacy_mode', {
        'id': 'run_legacy_mode', 'flow_id': 'f', 'status': 'done',
        'done': True, 'started_at': '2026-01-01T00:00:00+08:00',
        'finished_at': None, 'simulated': False,
    })
    r = client.get('/automation/runs/run_legacy_mode')
    assert r.json()['mode'] == 'dry_run'


def test_gear_field_validation_and_update(store_dir, client):
    # 非法 gear 422（FlowIn 与 FlowPatch 双入口）
    r = client.post('/automation/flows', json={'name': 'x', 'gear': 'root'})
    assert r.status_code == 422
    flow = _create_flow(client)
    r = client.put(f"/automation/flows/{flow['id']}", json={'gear': 'kernel'})
    assert r.status_code == 422
    # 合法 gear 可设置并可更新
    flow2 = _create_flow(client, name='沙盒流程', gear='sandbox')
    assert flow2['gear'] == 'sandbox'
    r = client.put(f"/automation/flows/{flow2['id']}", json={'gear': 'device'})
    assert r.status_code == 200
    assert r.json()['gear'] == 'device'


def test_ai_apply_preserves_proposed_gear(store_dir, client):
    proposed = {
        'name': '提案流程', 'trigger': 'manual', 'gear': 'sandbox',
        'steps': [{'id': 'st1', 'type': 'condition',
                   'config': {'expr': '1 < 2'}, 'on_error': 'stop'}],
    }
    r = client.post('/automation/flows/flow_absent/ai-apply?create=true',
                    json={'proposed_flow': proposed})
    assert r.status_code == 201, r.text
    assert r.json()['gear'] == 'sandbox'
    # ai-edit 规则解析的提案不带 gear 指令 → 新建归一为默认 human_review
    r = client.post('/automation/flows/ai-edit', json={'instruction': '每天7点抓取新闻'})
    assert r.json()['proposed_flow']['gear'] == 'human_review'
    # ai-edit 保留原流程 gear：规则解析绝不擅自改动执行门禁档位
    base_flow = _create_flow(client, name='沙盒原流程', gear='sandbox')
    r = client.post('/automation/flows/ai-edit', json={
        'flow_id': base_flow['id'],
        'instruction': f"每天8点运行「{base_flow['name']}」",
    })
    assert r.status_code == 200, r.text
    assert r.json()['proposed_flow']['gear'] == 'sandbox'


# ---------------------------------------------------------------------------
# 9. 显式模拟入口
# ---------------------------------------------------------------------------

def test_simulate_endpoint_forces_dry_run_for_sandbox_flow(store_dir, client):
    py = _shell_py_command()
    command = f'{py} --version' if py else 'date'
    flow = _create_flow(client, gear='sandbox', steps=[
        {'id': 'st1', 'type': 'shell', 'name': '预演命令',
         'config': {'command': command}, 'on_error': 'stop'},
    ])
    run, final = _run_and_wait(client, flow, path='simulate')
    assert run['mode'] == 'dry_run'
    assert final['status'] == 'done'
    st = final['step_results'][0]
    assert '模拟执行' in st['detail']
    assert 'stdout' not in st  # 未真实执行


# ---------------------------------------------------------------------------
# 10. on_error=stop 与不留假死
# ---------------------------------------------------------------------------

def test_on_error_stop_skips_rest_in_real_run(store_dir, client):
    flow = _create_flow(client, gear='sandbox', steps=[
        {'id': 'st1', 'type': 'shell', 'name': '必失败（非白名单）',
         'config': {'command': 'curl https://example.com'}, 'on_error': 'stop'},
        {'id': 'st2', 'type': 'condition', 'name': '不会执行到',
         'config': {'expr': '1 < 2'}, 'on_error': 'stop'},
    ])
    _run, final = _run_and_wait(client, flow)
    assert final['status'] == 'failed'
    assert final['done'] is True and final['finished_at'] is not None
    st1, st2 = final['step_results']
    assert st1['status'] == 'failed'
    assert st2['status'] == 'skipped'
    assert 'on_error=stop' in st2['detail']


# ---------------------------------------------------------------------------
# 11. 真实执行起止审计
# ---------------------------------------------------------------------------

def test_real_run_audit_start_and_finish_events(store_dir, client, mem_db):
    py = _shell_py_command()
    command = f'{py} --version' if py else 'date'
    flow = _create_flow(client, gear='sandbox', steps=[
        {'id': 'st1', 'type': 'shell', 'name': '版本号',
         'config': {'command': command}, 'on_error': 'stop'},
    ])
    run, _final = _run_and_wait(client, flow)
    with sqlite3.connect(mem_db) as conn:
        started = conn.execute(
            "SELECT payload FROM audit_logs WHERE event_type='flow_run_started' "
            "AND payload LIKE ?",
            (f'%{run["id"]}%',),
        ).fetchall()
        finished = conn.execute(
            "SELECT payload FROM audit_logs WHERE event_type='flow_run_finished' "
            "AND payload LIKE ?",
            (f'%{run["id"]}%',),
        ).fetchall()
    assert len(started) == 1 and '"mode": "real"' in started[0][0]
    assert len(finished) == 1
    finish_payload = json.loads(finished[0][0])
    assert finish_payload['mode'] == 'real'
    assert finish_payload['status'] == 'done'
