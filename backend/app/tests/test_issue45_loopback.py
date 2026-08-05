"""Issue #45 (P1-3/P1-4): loopback API-key exemption tests.

Verifies the plug-and-play auth boundary:
- loopback peer + loopback bind + no X-Forwarded-For  -> no key needed (200);
- any of those conditions failing -> fail-closed 401;
- WANWEI_REQUIRE_KEY_ON_LOOPBACK=1 disables the exemption entirely.
"""
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


def _client(tmp_path: Path, *, peer: str = "testclient") -> TestClient:
    os.environ["WANWEI_API_KEY"] = "test-key"
    os.environ["WANWEI_MEMORY_DB"] = str(tmp_path / "memory.db")
    os.environ.pop("WANWEI_PRODUCTION", None)

    import importlib
    import backend.app.main as main_mod
    import backend.app.security.auth as auth_mod

    importlib.reload(auth_mod)
    importlib.reload(main_mod)
    return TestClient(
        main_mod.app,
        raise_server_exceptions=False,
        client=(peer, 50000),
    )


def test_loopback_peer_with_loopback_bind_is_exempt(tmp_path, monkeypatch):
    """桌面单机场景：回环绑定 + 回环对端无 key 可访问（即插即用核心）。"""
    monkeypatch.setenv("WANWEI_HOST", "127.0.0.1")
    client = _client(tmp_path, peer="127.0.0.1")
    # /model-gateway/configs 是受保护 GET，无 key 时回环应放行。
    assert client.get("/model-gateway/configs").status_code == 200


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
