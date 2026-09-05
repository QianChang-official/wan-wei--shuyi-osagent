"""Issue #45 (P1-3/P1-4): loopback API-key exemption tests.

Verifies the plug-and-play auth boundary:
- loopback peer + loopback bind + no X-Forwarded-For  -> no key needed (200);
- any of those conditions failing -> fail-closed 401;
- WANWEI_REQUIRE_KEY_ON_LOOPBACK=1 disables the exemption entirely.
"""
import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


def _client(
    tmp_path: Path, *, peer: str = "testclient", explicit_key: bool = True
) -> TestClient:
    """构造测试客户端。

    ``explicit_key=True`` 模拟运维方显式配置 ``WANWEI_API_KEY``（此时回环免密
    让位给 fail-closed 校验）；``False`` 模拟裸启动自举密钥的桌面即插即用场景。
    """
    if explicit_key:
        os.environ["WANWEI_API_KEY"] = "test-key"
    else:
        os.environ.pop("WANWEI_API_KEY", None)
        os.environ.pop("WANWEI_API_KEY_FILE", None)
    os.environ["WANWEI_MEMORY_DB"] = str(tmp_path / "memory.db")
    os.environ.pop("WANWEI_PRODUCTION", None)

    import importlib
    import backend.app.app_runtime as runtime_mod
    import backend.app.main as main_mod
    import backend.app.security.auth as auth_mod

    importlib.reload(auth_mod)
    importlib.reload(runtime_mod)
    importlib.reload(runtime_mod)
    importlib.reload(main_mod)
    return TestClient(
        main_mod.app,
        raise_server_exceptions=False,
        client=(peer, 50000),
    )


def test_loopback_peer_with_loopback_bind_is_exempt(tmp_path, monkeypatch):
    """桌面单机场景：回环绑定 + 回环对端 + 自举密钥，无 key 可访问（即插即用核心）。"""
    monkeypatch.setenv("WANWEI_HOST", "127.0.0.1")
    monkeypatch.delenv("WANWEI_API_KEY", raising=False)
    monkeypatch.delenv("WANWEI_API_KEY_FILE", raising=False)
    client = _client(tmp_path, peer="127.0.0.1", explicit_key=False)
    # /model-gateway/configs 是受保护 GET，无 key 时回环应放行。
    assert client.get("/model-gateway/configs").status_code == 200


def test_loopback_identity_does_not_register_unvalidated_header(tmp_path, monkeypatch):
    monkeypatch.setenv('WANWEI_HOST', '127.0.0.1')
    monkeypatch.setenv('WANWEI_ALLOWED_HOSTS', 'testserver')
    monkeypatch.setenv('WANWEI_PLATFORM_DIR', str(tmp_path / 'platform'))
    monkeypatch.delenv('WANWEI_REQUIRE_KEY_ON_LOOPBACK', raising=False)
    monkeypatch.delenv('WANWEI_LOOPBACK_EXEMPT_WRITE', raising=False)
    client = _client(tmp_path, peer='127.0.0.1', explicit_key=False)
    from backend.app import init_db
    from backend.app.db import get_conn
    from backend.app.security.auth import _api_key_hash, _verify_api_key
    from backend.app.soul.ownership import configured_actor_id

    init_db.main()
    key = 'unregistered-loopback-key'
    rejected = client.get('/memory/identity', headers={'X-API-Key': key})
    assert rejected.status_code == 401, rejected.text
    assert get_conn().execute(
        'SELECT 1 FROM identity WHERE api_key_hash=?', (_api_key_hash(key),)
    ).fetchone() is None
    assert not _verify_api_key(key)
    assert client.post('/memory/identity/rotate', headers={'X-API-Key': key}, json={}).status_code == 401
    anonymous = client.get('/memory/identity')
    assert anonymous.status_code == 200, anonymous.text
    assert anonymous.json()['owner_id'] == configured_actor_id()


def test_explicit_api_key_env_disables_exemption(tmp_path, monkeypatch):
    """回归 CI smoke：显式配置 WANWEI_API_KEY 即视为要求鉴权，回环也不免密。

    起因：CI 的 HTTP integration smoke 断言「缺 key 必 401」，但服务以
    WANWEI_API_KEY + WANWEI_PRODUCTION 启动、请求来自 127.0.0.1，旧逻辑
    照样免密放行，导致 smoke 失败。
    """
    monkeypatch.setenv("WANWEI_HOST", "127.0.0.1")
    client = _client(tmp_path, peer="127.0.0.1", explicit_key=True)
    assert client.get("/model-gateway/configs").status_code == 401
    assert (
        client.get(
            "/model-gateway/configs",
            headers={"X-API-Key": "test-key"},
        ).status_code
        == 200
    )


def test_production_mode_disables_exemption(tmp_path, monkeypatch):
    """生产模式下回环免密必须关闭（即使密钥是自举的）。"""
    monkeypatch.setenv("WANWEI_HOST", "127.0.0.1")
    monkeypatch.delenv("WANWEI_API_KEY", raising=False)
    monkeypatch.delenv("WANWEI_API_KEY_FILE", raising=False)
    client = _client(tmp_path, peer="127.0.0.1", explicit_key=False)
    monkeypatch.setenv("WANWEI_PRODUCTION", "1")
    assert client.get("/model-gateway/configs").status_code == 401


def test_loopback_exempt_disabled_by_env(tmp_path, monkeypatch):
    """WANWEI_REQUIRE_KEY_ON_LOOPBACK=1 关闭回环免密。"""
    monkeypatch.setenv("WANWEI_HOST", "127.0.0.1")
    monkeypatch.setenv("WANWEI_REQUIRE_KEY_ON_LOOPBACK", "1")
    client = _client(tmp_path, peer="127.0.0.1")
    assert client.get("/model-gateway/configs").status_code == 401
    assert (
        client.get(
            "/model-gateway/configs",
            headers={"X-API-Key": "test-key"},
        ).status_code
        == 200
    )


def test_non_loopback_peer_stays_fail_closed(tmp_path, monkeypatch):
    """回环绑定但对端非回环：必须 401。"""
    monkeypatch.setenv("WANWEI_HOST", "127.0.0.1")
    client = _client(tmp_path, peer="192.168.1.50")
    assert client.get("/model-gateway/configs").status_code == 401


def test_non_loopback_bind_never_exempts(tmp_path, monkeypatch):
    """绑定 0.0.0.0 时即使对端回环也不免密（暴露面 fail-closed）。"""
    monkeypatch.setenv("WANWEI_HOST", "0.0.0.0")
    client = _client(tmp_path, peer="127.0.0.1")
    assert client.get("/model-gateway/configs").status_code == 401


def test_forwarded_for_preserves_key_check(tmp_path, monkeypatch):
    """存在 X-Forwarded-For 时 client.host 不可信，不得免密。"""
    monkeypatch.setenv("WANWEI_HOST", "127.0.0.1")
    client = _client(tmp_path, peer="127.0.0.1")
    assert (
        client.get(
            "/model-gateway/configs",
            headers={"X-Forwarded-For": "203.0.113.7"},
        ).status_code
        == 401
    )


def test_loopback_bind_warning_logged(tmp_path, monkeypatch, caplog):
    """绑定非回环时启动打 WARNING 提示暴露面。"""
    monkeypatch.setenv("WANWEI_HOST", "0.0.0.0")
    import logging

    from backend.app.security import auth

    with caplog.at_level(logging.WARNING, logger=auth.logger.name):
        auth.warn_if_exposed_bind()

    assert any("not a loopback address" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# v0.11.1 收紧：回环免密默认只读，写操作必须带 key
# ---------------------------------------------------------------------------


def test_loopback_exempt_write_requires_key_by_default(tmp_path, monkeypatch):
    """裸启动回环免密下，写方法（POST）必须带 key（默认收紧）。"""
    monkeypatch.setenv("WANWEI_HOST", "127.0.0.1")
    monkeypatch.delenv("WANWEI_API_KEY", raising=False)
    monkeypatch.delenv("WANWEI_API_KEY_FILE", raising=False)
    monkeypatch.delenv("WANWEI_LOOPBACK_EXEMPT_WRITE", raising=False)
    client = _client(tmp_path, peer="127.0.0.1", explicit_key=False)
    # GET 仍免密放行（只读豁免）
    assert client.get("/model-gateway/configs").status_code == 200
    # POST 不再免密，必须 401
    assert (
        client.post("/platform/memory/remember", json={"text": "x"}).status_code
        == 401
    )


def test_loopback_exempt_write_allowed_via_env(tmp_path, monkeypatch, caplog):
    """WANWEI_LOOPBACK_EXEMPT_WRITE=1 显式恢复写免密（兼容 CI/脚本），并记 WARNING。"""
    import logging

    monkeypatch.setenv("WANWEI_HOST", "127.0.0.1")
    monkeypatch.delenv("WANWEI_API_KEY", raising=False)
    monkeypatch.delenv("WANWEI_API_KEY_FILE", raising=False)
    monkeypatch.setenv("WANWEI_LOOPBACK_EXEMPT_WRITE", "1")
    from backend.app.security import auth

    with caplog.at_level(logging.WARNING, logger=auth.logger.name):
        client = _client(tmp_path, peer="127.0.0.1", explicit_key=False)
        # 写操作恢复免密
        assert (
            client.post(
                "/platform/memory/remember", json={"text": "团队周会每周三下午"}
            ).status_code
            == 200
        )
    assert any("LOOPBACK_EXEMPT_WRITE" in r.message for r in caplog.records)


def test_loopback_exempt_read_still_open_by_default(tmp_path, monkeypatch):
    """默认收紧后，受保护 GET 在裸启动回环下仍免密（控制台即插即用）。"""
    monkeypatch.setenv("WANWEI_HOST", "127.0.0.1")
    monkeypatch.delenv("WANWEI_API_KEY", raising=False)
    monkeypatch.delenv("WANWEI_API_KEY_FILE", raising=False)
    monkeypatch.delenv("WANWEI_LOOPBACK_EXEMPT_WRITE", raising=False)
    client = _client(tmp_path, peer="127.0.0.1", explicit_key=False)
    assert client.get("/model-gateway/configs").status_code == 200
    assert client.get("/memory/v2/capsules").status_code == 200
