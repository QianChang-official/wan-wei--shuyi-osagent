# Copyright (c) 2026 QianChang-official
#
# 宛委·枢忆 is licensed under Mulan PSL v2.
# You can use this software according to the terms of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
# http://license.coscl.org.cn/MulanPSL2
#
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

"""OriginHostGuardMiddleware 的 CSRF / DNS-rebinding 防护测试。

覆盖审计报告点名的两条入向攻击：
- simple-request CSRF（带恶意 Origin 的写请求必须 403）
- DNS rebinding（Host 头指向非回环域名必须 403）
- 非浏览器客户端（无 Origin）不受影响，保持向后兼容
"""
from __future__ import annotations

import importlib
import sys

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """隔离数据库与密钥，构造带 Origin/Host 防护的 TestClient。"""
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("WANWEI_AUDIT_DB", str(tmp_path / "t_audit.db"))
    monkeypatch.setenv("WANWEI_API_KEY", "test-key")
    monkeypatch.setenv("WANWEI_ALLOWED_HOSTS", "testserver")
    import backend.app.app_runtime as main_mod
    importlib.reload(main_mod)
    return TestClient(main_mod.app, raise_server_exceptions=False)


class TestHostGuard:
    """DNS rebinding：Host 头必须指向回环或显式白名单。"""

    def test_evil_host_rejected_on_get(self, client):
        r = client.get("/health", headers={"host": "evil.com"})
        assert r.status_code == 403
        assert "Host" in r.json()["detail"]

    def test_evil_host_rejected_on_post(self, client):
        r = client.post(
            "/platform/memory/remember",
            headers={"host": "attacker.example", "x-api-key": "test-key"},
            json={"text": "x"},
        )
        assert r.status_code == 403

    def test_loopback_host_allowed(self, client):
        r = client.get("/health", headers={"host": "127.0.0.1:8010"})
        assert r.status_code == 200

    def test_localhost_with_port_allowed(self, client):
        r = client.get("/health", headers={"host": "localhost:8010"})
        assert r.status_code == 200

    def test_testserver_host_allowed_via_env(self, client):
        # TestClient 默认 Host=testserver，经 WANWEI_ALLOWED_HOSTS 放行
        r = client.get("/health")
        assert r.status_code == 200


class TestOriginGuard:
    """CSRF：带 Origin 的写请求必须命中白名单。"""

    def test_evil_origin_post_rejected(self, client):
        r = client.post(
            "/platform/memory/remember",
            headers={
                "origin": "https://evil.com",
                "x-api-key": "test-key",
            },
            json={"text": "恶意写入"},
        )
        assert r.status_code == 403
        assert "Origin" in r.json()["detail"]

    def test_null_origin_post_rejected(self, client):
        # sandboxed iframe / file:// 的 Origin 是字面量 null，fail-closed
        r = client.post(
            "/platform/memory/remember",
            headers={"origin": "null", "x-api-key": "test-key"},
            json={"text": "x"},
        )
        assert r.status_code == 403

    def test_loopback_origin_post_allowed(self, client):
        r = client.post(
            "/platform/memory/remember",
            headers={
                "origin": "http://127.0.0.1:8010",
                "x-api-key": "test-key",
            },
            json={"text": "团队周会每周三下午"},
        )
        assert r.status_code == 200

    def test_localhost_origin_post_allowed(self, client):
        r = client.post(
            "/platform/memory/remember",
            headers={
                "origin": "http://localhost:8010",
                "x-api-key": "test-key",
            },
            json={"text": "团队周会每周三下午"},
        )
        assert r.status_code == 200

    def test_allowed_lan_origin_uses_cli_port(self, client, monkeypatch):
        """The Origin fallback must follow uvicorn's effective CLI port."""
        from backend.app.security import auth

        monkeypatch.delenv("WANWEI_PORT", raising=False)
        monkeypatch.setenv("WANWEI_ALLOWED_HOSTS", "testserver,lan.example.test")
        monkeypatch.setattr(
            sys,
            "argv",
            # This only supplies argv to the parser; no server or socket starts.
            ["uvicorn", "--host", "0.0.0.0", "--port", "8000", "app:app"],  # nosec B104
        )

        assert auth._origin_is_allowed("http://lan.example.test:8000") is True
        assert auth._origin_is_allowed("http://lan.example.test:8010") is False

    def test_get_with_evil_origin_not_blocked_by_origin_guard(self, client):
        # Origin 校验只针对写方法；GET 的读取面由 Host 校验与 API key 覆盖。
        # 带恶意 Origin 的 GET 应走到 API key 层（401），而非 Origin 403。
        r = client.get("/memory/v2/capsules", headers={"origin": "https://evil.com"})
        assert r.status_code == 401  # 缺 key，证明未被 Origin 守卫拦截

    def test_no_origin_non_browser_client_unaffected(self, client):
        # curl / Electron / python requests 不带 Origin，保持原有 API key 路径
        r = client.post(
            "/platform/memory/remember",
            headers={"x-api-key": "test-key"},
            json={"text": "无 Origin 的写入"},
        )
        assert r.status_code == 200


class TestGuardOrdering:
    """Origin/Host 守卫在鉴权之前执行：403 与 401 语义不混淆。"""

    def test_malicious_origin_without_key_gets_403_not_401(self, client):
        # 恶意来源即使缺 key 也应先吃到 403（来源非法），而非 401（凭据缺失）
        r = client.post(
            "/platform/memory/remember",
            headers={"origin": "https://evil.com"},
            json={"text": "x"},
        )
        assert r.status_code == 403

    def test_legitimate_origin_without_key_gets_401(self, client):
        r = client.post(
            "/platform/memory/remember",
            headers={"origin": "http://127.0.0.1:8010"},
            json={"text": "x"},
        )
        assert r.status_code == 401


class TestLoopbackOriginDevPort:
    """开发期前后端分端口（Vite 5173 / 后端 8010）不应被 Origin 守卫 403。

    这是 ``run_dev`` 的默认形态：浏览器 Origin 的端口必然不同于后端监听端口。
    此前口径让每一次写操作都 403，实测会把「自定义端点保存」等常规操作挡死。
    """

    def test_dev_front_port_allowed_non_production(self, monkeypatch):
        """非生产模式：回环来源的任意端口都放行。"""
        from backend.app.security import auth

        monkeypatch.delenv("WANWEI_PRODUCTION", raising=False)
        for origin in (
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:3000",
            "https://127.0.0.1:5173",
        ):
            assert auth._origin_is_allowed(origin) is True, origin

    def test_production_keeps_strict_port_matching(self, monkeypatch):
        """生产模式：回环来源仍必须命中监听端口，不得因本次修复而放宽。"""
        from backend.app.security import auth

        monkeypatch.setenv("WANWEI_PRODUCTION", "1")
        monkeypatch.delenv("WANWEI_CORS_ORIGINS", raising=False)
        assert auth._origin_is_allowed("http://127.0.0.1:5173") is False
        # 监听端口本身仍然放行
        assert auth._origin_is_allowed("http://127.0.0.1:8010") is True

    def test_remote_origin_still_rejected(self, monkeypatch):
        """远程来源在任何模式下都拒绝——这是反 CSRF 的核心，不受影响。"""
        from backend.app.security import auth

        monkeypatch.delenv("WANWEI_PRODUCTION", raising=False)
        monkeypatch.delenv("WANWEI_CORS_ORIGINS", raising=False)
        assert auth._origin_is_allowed("https://evil.example.com") is False
        assert auth._origin_is_allowed("http://evil.example.com:5173") is False

    def test_null_origin_still_rejected(self, monkeypatch):
        """``Origin: null``（sandboxed iframe / file://）维持 fail-closed。"""
        from backend.app.security import auth

        monkeypatch.delenv("WANWEI_PRODUCTION", raising=False)
        assert auth._origin_is_allowed("null") is False

    def test_loopback_origin_with_credentials_or_path_rejected(self, monkeypatch):
        """回环也不豁免结构校验：带凭据或路径的 Origin 必须被拒。"""
        from backend.app.security import auth

        monkeypatch.delenv("WANWEI_PRODUCTION", raising=False)
        assert auth._origin_is_allowed("http://user:pw@127.0.0.1:5173") is False
        assert auth._origin_is_allowed("http://127.0.0.1:5173/evil") is False
        assert auth._origin_is_allowed("ftp://127.0.0.1:5173") is False

    def test_lan_host_port_still_enforced(self, monkeypatch):
        """非回环主机仍须端口匹配——本次修复不得波及 LAN 部署。"""
        from backend.app.security import auth

        monkeypatch.delenv("WANWEI_PRODUCTION", raising=False)
        monkeypatch.delenv("WANWEI_PORT", raising=False)
        monkeypatch.setenv("WANWEI_ALLOWED_HOSTS", "lan.example.test")
        monkeypatch.setattr(
            sys, "argv", ["uvicorn", "--host", "0.0.0.0", "--port", "8000", "app:app"],
        )
        assert auth._origin_is_allowed("http://lan.example.test:8000") is True
        assert auth._origin_is_allowed("http://lan.example.test:8010") is False
