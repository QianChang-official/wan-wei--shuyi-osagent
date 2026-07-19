"""W05 MCP 枢纽修复回归测试（07-#6 / #9 / #15 / #16 / #17 / #18）。

覆盖：
- 07-#6  Windows .cmd/.bat shim 去 shell=True：cmd 元字符逐 token 拒绝 +
  cmd.exe /d /s /c 参数化拉起（shell=False）
- 07-#9  initialize 握手与 tools/list、tools/call 分离计时 +
  服务器级 timeout_seconds 配置
- 07-#15 status 伪造连接态拒绝（合法迁移集 {* → unknown}）+
  command/args/transport 变更使工具缓存失效 + overview 只计成功缓存
- 07-#16 _record_call 读-改-写收进模块级单锁；请求模型 extra='forbid'；
  敏感键（password/token/secret/key/api_key）打码
- 07-#17 Windows 进程树回收（CREATE_NEW_PROCESS_GROUP + taskkill /T /F）
- 07-#18 模块 docstring 诚实标注「前端未接入、仅 API 面」
- 安全回归：真实 stdio 默认禁用，需服务端 device 授权 + 显式 command
  白名单；子进程不继承 WANWEI_* 等父进程秘密
"""

from __future__ import annotations

import importlib
import io
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[3]


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
    import backend.app.main as main_mod

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
# 真实 stdio 服务端授权、命令白名单与最小环境
# ---------------------------------------------------------------------------


def test_stdio_command_allowlist_rejects_interpreters_and_client_paths(mcp_store, monkeypatch):
    from backend.app.platform_api import mcp_hub

    monkeypatch.setenv('WANWEI_MCP_STDIO_COMMANDS', 'npx.cmd,uvx')
    for command in ('python', 'python.exe', 'powershell.exe', 'cmd.exe', r'C:\\tools\\npx.cmd', '/usr/bin/uvx'):
        with pytest.raises(ValueError):
            mcp_hub._validate_stdio_command(command)
    monkeypatch.setattr(mcp_hub.shutil, 'which', lambda value: f'C:\\trusted\\{value}')
    assert mcp_hub._validate_stdio_command('npx.cmd').lower().endswith('npx.cmd')

    trusted = str((PROJECT_ROOT / 'tools' / 'trusted-mcp').resolve())
    monkeypatch.setenv('WANWEI_MCP_STDIO_COMMANDS', trusted)
    assert os.path.normcase(mcp_hub._validate_stdio_command(trusted)) == os.path.normcase(trusted)


def test_stdio_subprocess_env_does_not_inherit_service_secrets(mcp_store, monkeypatch):
    from backend.app.platform_api import mcp_hub

    monkeypatch.setenv('PATH', r'C:\\Windows\\System32')
    monkeypatch.setenv('WANWEI_API_KEY', 'parent-api-secret')
    monkeypatch.setenv('WANWEI_ENCRYPTION_KEY', 'parent-encryption-secret')
    monkeypatch.setenv('OPENAI_API_KEY', 'parent-provider-secret')
    child = mcp_hub._minimal_subprocess_env({'MCP_ONLY_TOKEN': 'configured-secret'})
    assert child['PATH'] == r'C:\\Windows\\System32'
    assert child['MCP_ONLY_TOKEN'] == 'configured-secret'
    assert 'WANWEI_API_KEY' not in child
    assert 'WANWEI_ENCRYPTION_KEY' not in child
    assert 'OPENAI_API_KEY' not in child


def test_live_stdio_requires_server_side_authorization(tmp_path, mcp_store, monkeypatch):
    client = _client(tmp_path)
    h = {'x-api-key': 'test-key'}
    r = client.post(
        '/platform/mcp/servers',
        json={'name': 'blocked-live', 'transport': 'stdio', 'command': 'npx.cmd', 'enabled': True},
        headers=h,
    )
    assert r.status_code == 201, r.text
    sid = r.json()['id']

    monkeypatch.setenv('WANWEI_MCP_STDIO_COMMANDS', 'npx.cmd')
    monkeypatch.delenv('WANWEI_DEVICE_GEAR_ENABLED', raising=False)
    r = client.get(f'/platform/mcp/servers/{sid}/tools', headers=h)
    assert r.status_code == 403
    assert 'DEVICE_GEAR_ENABLED' in r.text

    monkeypatch.setenv('WANWEI_DEVICE_GEAR_ENABLED', '1')
    monkeypatch.setenv('WANWEI_MCP_STDIO_COMMANDS', 'uvx')
    r = client.post(f'/platform/mcp/servers/{sid}/call', json={'tool': 'x'}, headers=h)
    assert r.status_code == 403
    assert '允许列表' in r.text


# ---------------------------------------------------------------------------
# 07-#6 Windows shim 命令注入
# ---------------------------------------------------------------------------


def test_cmd_shim_argv_rejects_metacharacters(mcp_store):
    from backend.app.platform_api import mcp_hub

    for token in (
        'x&whoami', 'x|calc', 'a>b', 'a<b', 'a^b', '%PATH%', 'a!b',
        'es"cape', 'a\rb', 'a\nb',
    ):
        with pytest.raises(ValueError):
            mcp_hub._check_cmd_shim_argv(['npx.cmd', token])
    # 正常参数（含空格、中文、@scope 包名）放行
    mcp_hub._check_cmd_shim_argv([
        'C:\\tools\\npx.cmd', '-y', '@modelcontextprotocol/server-filesystem', 'D:\\工作 目录',
    ])


@pytest.mark.skipif(os.name != 'nt', reason='Windows shim 分支仅在 Windows 生效')
def test_cmd_shim_popen_shell_false_and_parameterized(mcp_store, monkeypatch):
    """shim 分支不再 shell=True，而是 cmd.exe /d /s /c 一次成型命令行。"""
    from backend.app.platform_api import mcp_hub

    captured = {}

    class _FakeProc:
        def __init__(self):
            self.stdin = None
            self.stdout = io.BytesIO(b'')  # 立即 EOF，读帧线程直接收口

        def poll(self):
            return 0

    def fake_popen(cmd, **kwargs):
        captured['cmd'] = cmd
        captured['kwargs'] = kwargs
        return _FakeProc()

    monkeypatch.setattr(mcp_hub.subprocess, 'Popen', fake_popen)
    rpc = mcp_hub._StdioRpc('fake shim.cmd', ['-y', 'pkg'], {}, 5.0)
    rpc.close()

    assert captured['kwargs'].get('shell') is False
    assert 'S602' not in Path(mcp_hub.__file__).read_text(encoding='utf-8')
    cmdline = captured['cmd']
    assert isinstance(cmdline, str)
    assert cmdline.startswith('cmd.exe /d /s /c "')
    assert '"fake shim.cmd"' in cmdline
    assert '-y pkg' in cmdline
    assert 'cmd.exe' in str(captured['kwargs'].get('executable')).lower()
    # 独立进程组，配合 taskkill /T 整树回收（07-#17）
    flags = captured['kwargs'].get('creationflags', 0)
    assert flags & subprocess.CREATE_NEW_PROCESS_GROUP


@pytest.mark.skipif(os.name != 'nt', reason='Windows shim 分支仅在 Windows 生效')
def test_cmd_shim_injection_blocked_before_spawn(mcp_store, monkeypatch):
    """含 cmd 元字符的 args 在拉起进程前即被拒绝。"""
    from backend.app.platform_api import mcp_hub

    spawned = []
    monkeypatch.setattr(
        mcp_hub.subprocess, 'Popen',
        lambda *a, **k: spawned.append((a, k)) or None,
    )
    with pytest.raises(ValueError):
        mcp_hub._StdioRpc('npx.cmd', ['x & whoami &'], {}, 5.0)
    assert spawned == [], '注入载荷不应触达 Popen'


# ---------------------------------------------------------------------------
# 07-#9 握手/调用预算分离 + 服务器级 timeout
# ---------------------------------------------------------------------------


def test_request_budget_defaults_and_override(mcp_store):
    from backend.app.platform_api import mcp_hub

    assert mcp_hub._request_budget({}) == mcp_hub._DEFAULT_CALL_BUDGET
    assert mcp_hub._request_budget({'timeout_seconds': None}) == mcp_hub._DEFAULT_CALL_BUDGET
    assert mcp_hub._request_budget({'timeout_seconds': 'junk'}) == mcp_hub._DEFAULT_CALL_BUDGET
    assert mcp_hub._request_budget({'timeout_seconds': -3}) == mcp_hub._DEFAULT_CALL_BUDGET
    assert mcp_hub._request_budget({'timeout_seconds': 55}) == 55.0
    assert mcp_hub._request_budget({'timeout_seconds': 99999}) == mcp_hub._MAX_CALL_BUDGET


def test_open_session_separates_handshake_and_call_budgets(mcp_store, monkeypatch):
    """initialize 用独立握手预算，会话预算取服务器级 timeout_seconds。"""
    from backend.app.platform_api import mcp_hub

    captured = {}

    class _FakeRpc:
        def __init__(self, command, args, env, request_timeout):
            captured['request_timeout'] = request_timeout

        def request(self, method, params=None, *, timeout=None):
            captured.setdefault('requests', []).append({'method': method, 'timeout': timeout})
            return {}

        def notify(self, method, params=None):
            pass

        def close(self):
            captured['closed'] = True

    monkeypatch.setattr(mcp_hub, '_StdioRpc', _FakeRpc)
    mcp_hub._open_session({'command': 'x', 'args': [], 'env': {}, 'timeout_seconds': 55.0})

    assert captured['request_timeout'] == 55.0
    init_calls = [r for r in captured['requests'] if r['method'] == 'initialize']
    assert init_calls, '应先完成 initialize 握手'
    assert init_calls[0]['timeout'] == mcp_hub._HANDSHAKE_BUDGET
    assert 'closed' not in captured, '握手成功不应关闭会话'


def test_open_session_closes_on_handshake_failure(mcp_store, monkeypatch):
    from backend.app.platform_api import mcp_hub

    captured = {}

    class _FakeRpc:
        def __init__(self, command, args, env, request_timeout):
            pass

        def request(self, method, params=None, *, timeout=None):
            raise TimeoutError('handshake timeout')

        def notify(self, method, params=None):
            pass

        def close(self):
            captured['closed'] = True

    monkeypatch.setattr(mcp_hub, '_StdioRpc', _FakeRpc)
    with pytest.raises(TimeoutError):
        mcp_hub._open_session({'command': 'x', 'args': [], 'env': {}})
    assert captured.get('closed') is True


def test_remaining_raises_after_deadline(mcp_store):
    from backend.app.platform_api import mcp_hub

    assert mcp_hub._StdioRpc._remaining(time.monotonic() + 60, 30.0) > 0
    with pytest.raises(TimeoutError):
        mcp_hub._StdioRpc._remaining(time.monotonic() - 1, 30.0)


def test_timeout_seconds_field_roundtrip(tmp_path, mcp_store):
    """服务器级 timeout_seconds 写入/更新/回读（向后兼容的可选字段）。"""
    client = _client(tmp_path)
    h = {"x-api-key": "test-key"}

    r = client.post(
        "/platform/mcp/servers",
        json={"name": "t-timeout", "transport": "stdio", "enabled": False,
              "timeout_seconds": 45},
        headers=h,
    )
    assert r.status_code == 201, r.text
    assert r.json()["timeout_seconds"] == 45.0
    sid = r.json()["id"]

    r = client.put(f"/platform/mcp/servers/{sid}", json={"timeout_seconds": 120}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["timeout_seconds"] == 120.0

    # 非法值（0 / 超上限）被模型拒绝
    assert client.put(
        f"/platform/mcp/servers/{sid}", json={"timeout_seconds": 0}, headers=h,
    ).status_code == 422
    assert client.put(
        f"/platform/mcp/servers/{sid}", json={"timeout_seconds": 9999}, headers=h,
    ).status_code == 422


# ---------------------------------------------------------------------------
# 07-#15 status 伪造 + 缓存一致性
# ---------------------------------------------------------------------------


def test_status_forgery_rejected(tmp_path, mcp_store):
    """客户端不得直写 connected/error 伪造连接态；仅允许重置为 unknown。"""
    client = _client(tmp_path)
    h = {"x-api-key": "test-key"}

    r = client.post(
        "/platform/mcp/servers",
        json={"name": "t-forge", "transport": "stdio", "status": "connected"},
        headers=h,
    )
    assert r.status_code == 422, f'POST 直写 connected 应 422：{r.status_code}'

    r = client.post(
        "/platform/mcp/servers",
        json={"name": "t-forge", "transport": "stdio", "status": "unknown",
              "enabled": False},
        headers=h,
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert r.json()["status"] == "unknown"

    assert client.put(
        f"/platform/mcp/servers/{sid}", json={"status": "connected"}, headers=h,
    ).status_code == 422
    assert client.put(
        f"/platform/mcp/servers/{sid}", json={"status": "error"}, headers=h,
    ).status_code == 422

    # 合法迁移：显式重置为 unknown
    r = client.put(f"/platform/mcp/servers/{sid}", json={"status": "unknown"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "unknown"


def test_config_change_invalidates_cache(tmp_path, mcp_store):
    """command/args/transport 变更后，旧连接态与工具缓存必须失效。"""
    client = _client(tmp_path)
    h = {"x-api-key": "test-key"}

    r = client.post(
        "/platform/mcp/servers",
        json={"name": "t-cache", "transport": "stdio", "enabled": False},
        headers=h,
    )
    sid = r.json()["id"]

    from backend.app.platform_api import mcp_hub

    rec = mcp_hub._store.get(sid)
    rec.update({
        "status": "connected",
        "tools_cache": [{"name": "a"}],
        "tools_count": 1,
        "last_discovery_at": "2024-01-01T00:00:00+08:00",
    })
    mcp_hub._store.set(sid, rec)

    r = client.put(f"/platform/mcp/servers/{sid}", json={"command": "echo"}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "unknown"
    assert body["tools_cache"] == []
    assert body["tools_count"] == 0
    assert "last_discovery_at" not in body

    # 与连接无关的字段变更不清缓存
    rec = mcp_hub._store.get(sid)
    rec.update({"status": "connected", "tools_cache": [{"name": "a"}], "tools_count": 1})
    mcp_hub._store.set(sid, rec)
    r = client.put(f"/platform/mcp/servers/{sid}", json={"note": "仅备注"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["tools_count"] == 1


def test_overview_counts_only_successful_discovery(tmp_path, mcp_store):
    """overview.tools_discovered 只统计探测成功（connected）的缓存。"""
    client = _client(tmp_path)
    h = {"x-api-key": "test-key"}

    r = client.post(
        "/platform/mcp/servers",
        json={"name": "t-ov", "transport": "stdio", "enabled": False},
        headers=h,
    )
    sid = r.json()["id"]

    from backend.app.platform_api import mcp_hub

    rec = mcp_hub._store.get(sid)
    rec.update({"status": "error", "tools_count": 5, "tools_cache": [{}] * 5})
    mcp_hub._store.set(sid, rec)
    r = client.get("/platform/mcp/overview", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["tools_discovered"] == 0, 'error 状态下的陈旧缓存不应计入'

    rec = mcp_hub._store.get(sid)
    rec["status"] = "connected"
    mcp_hub._store.set(sid, rec)
    r = client.get("/platform/mcp/overview", headers=h)
    assert r.json()["tools_discovered"] == 5


# ---------------------------------------------------------------------------
# 07-#16 extra='forbid' + _record_call 原子性 + 敏感键打码
# ---------------------------------------------------------------------------


def test_request_models_forbid_extra_fields(tmp_path, mcp_store):
    client = _client(tmp_path)
    h = {"x-api-key": "test-key"}

    r = client.post(
        "/platform/mcp/servers",
        json={"name": "t-extra", "transport": "stdio", "bogus": 1},
        headers=h,
    )
    assert r.status_code == 422, f'POST 未知字段应 422：{r.status_code}'

    r = client.post(
        "/platform/mcp/servers",
        json={"name": "t-extra", "transport": "stdio", "enabled": False},
        headers=h,
    )
    sid = r.json()["id"]
    assert client.put(
        f"/platform/mcp/servers/{sid}", json={"bogus": 1}, headers=h,
    ).status_code == 422
    assert client.post(
        f"/platform/mcp/servers/{sid}/call",
        json={"tool": "x", "bogus": 1},
        headers=h,
    ).status_code == 422


def test_record_call_serialized_under_lock(tmp_path, mcp_store):
    """30 线程并发 _record_call：读-改-写原子，封顶 20 条且 id 不重复。"""
    from backend.app.platform_api import mcp_hub

    rec = {"id": "srv_race", "name": "race"}
    payload = mcp_hub.CallIn(tool="t", arguments={})

    def worker():
        mcp_hub._record_call(rec, payload, ok=False, mode="stub", note="n")

    threads = [threading.Thread(target=worker) for _ in range(30)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    calls = mcp_hub._store.get("_recent_calls")
    assert len(calls) == mcp_hub._CALLS_CAP, f'应完整保留封顶 20 条，实际 {len(calls)}'
    ids = [c["id"] for c in calls]
    assert len(set(ids)) == len(ids), '调用记录 id 不应重复'


def test_record_call_masks_sensitive_keys(tmp_path, mcp_store):
    """password/token/secret/key/api_key 等敏感键入库前打码。"""
    from backend.app.platform_api import mcp_hub

    rec = {"id": "srv_mask", "name": "mask"}
    payload = mcp_hub.CallIn(tool="t", arguments={
        "query": "保留", "normal": "v",
        "password": "hunter2", "api_key": "sk-x", "token": "t1", "secret": "s1",
    })
    entry = mcp_hub._record_call(rec, payload, ok=False, mode="stub", note="n")
    args = entry["arguments"]
    for key in ("password", "api_key", "token", "secret"):
        assert args[key] == "******", f'{key} 应被打码'
    assert args["query"] == "保留"
    assert args["normal"] == "v"


# ---------------------------------------------------------------------------
# 07-#17 Windows 进程树回收
# ---------------------------------------------------------------------------


@pytest.mark.skipif(os.name != 'nt', reason='进程树回收为 Windows 专项')
def test_close_kills_windows_process_tree(tmp_path, mcp_store):
    """.cmd shim 拉起孙进程后 close()：taskkill /T /F 应回收整棵进程树。"""
    from backend.app.platform_api import mcp_hub

    pid_file = tmp_path / 'grandchild.pid'
    shim = tmp_path / 'sleeper.cmd'
    shim.write_text(
        '@echo off\r\n'
        '"{}" -c "import os,sys,time;open(sys.argv[1],\'w\').write(str(os.getpid()));'
        'time.sleep(60)" "{}"\r\n'.format(sys.executable, pid_file),
        encoding='ascii',
    )
    rpc = mcp_hub._StdioRpc(str(shim), [], {}, 5.0)

    gpid = None
    for _ in range(50):
        if pid_file.exists():
            text = pid_file.read_text(encoding='ascii').strip()
            if text.isdigit():
                gpid = int(text)
                break
        time.sleep(0.2)
    assert gpid, '应存在 cmd 壳拉起的 python 孙进程'

    def _alive(pid):
        out = subprocess.run(
            ['tasklist', '/FI', f'PID eq {pid}'],
            capture_output=True, text=True, timeout=30,
        )
        return str(pid) in out.stdout

    assert _alive(gpid), '孙进程在 close 前应存活'
    rpc.close()
    assert rpc._proc.poll() is not None, 'cmd 壳应被回收'
    assert not _alive(gpid), f'孙进程 {gpid} 应随进程树一并回收'


def test_kill_process_tree_invokes_taskkill(mcp_store, monkeypatch):
    """_kill_process_tree 以 taskkill /PID x /T /F 回收，失败回退 terminate。"""
    from backend.app.platform_api import mcp_hub

    calls = {}

    class _FakeProc:
        pid = 4321

        def terminate(self):
            calls['terminate'] = True

        def wait(self, timeout=None):
            calls['wait'] = timeout
            return 0

        def kill(self):
            calls['kill'] = True

    def fake_run(cmd, **kwargs):
        calls['run'] = cmd
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(mcp_hub.subprocess, 'run', fake_run)
    mcp_hub._kill_process_tree(_FakeProc())
    assert calls['run'] == ['taskkill', '/PID', '4321', '/T', '/F']
    assert calls.get('wait') is not None, '回收后应 wait 收割'
    assert 'terminate' not in calls, 'taskkill 成功时不应回退 terminate'


# ---------------------------------------------------------------------------
# 超时与失败状态语义区分
# ---------------------------------------------------------------------------


def test_discover_tools_timeout_returns_timeout_status(tmp_path, mcp_store, monkeypatch):
    """tools/list 超时返回 status='timeout'，与普通 error 区分。"""
    client = _client(tmp_path)
    h = {"x-api-key": "test-key"}

    r = client.post(
        "/platform/mcp/servers",
        json={"name": "t-timeout", "transport": "stdio", "command": "echo", "enabled": True},
        headers=h,
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]

    from backend.app.platform_api import mcp_hub
    monkeypatch.setenv('WANWEI_DEVICE_GEAR_ENABLED', '1')
    monkeypatch.setenv('WANWEI_MCP_STDIO_COMMANDS', 'echo')

    def _boom(*args, **kwargs):
        raise TimeoutError('budget exhausted')

    monkeypatch.setattr(mcp_hub, '_open_session', _boom)
    r = client.get(f"/platform/mcp/servers/{sid}/tools", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "timeout", body
    assert "超时" in body["note"]


def test_call_tool_timeout_returns_timeout_mode(tmp_path, mcp_store, monkeypatch):
    """tools/call 超时返回 mode='timeout'，调用记录同样标注 timeout。"""
    client = _client(tmp_path)
    h = {"x-api-key": "test-key"}

    r = client.post(
        "/platform/mcp/servers",
        json={"name": "t-call-timeout", "transport": "stdio", "command": "echo", "enabled": True},
        headers=h,
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]

    from backend.app.platform_api import mcp_hub
    monkeypatch.setenv('WANWEI_DEVICE_GEAR_ENABLED', '1')
    monkeypatch.setenv('WANWEI_MCP_STDIO_COMMANDS', 'echo')

    def _boom(*args, **kwargs):
        raise TimeoutError('call budget exhausted')

    monkeypatch.setattr(mcp_hub, '_open_session', _boom)
    r = client.post(f"/platform/mcp/servers/{sid}/call", json={"tool": "x", "arguments": {}}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "timeout", body
    assert body["ok"] is False

    rec = mcp_hub._store.get(sid)
    assert rec["status"] == "timeout"


# ---------------------------------------------------------------------------
# 07-#18 前端消费者诚实标注
# ---------------------------------------------------------------------------


def test_module_docstring_marks_no_frontend_consumer():
    from backend.app.platform_api import mcp_hub

    doc = mcp_hub.__doc__ or ''
    assert '前端' in doc and '未接入' in doc, (
        'docstring 应如实标注「当前仅 API 面，前端未接入」'
    )
