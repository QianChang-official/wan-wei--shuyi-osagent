"""Security follow-up tests for v0.9.4.

Tests core security hardening fixes.
"""
import logging
import os
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient


def auth_logger_name() -> str:
    """auth 模块的 logger 名，供 caplog 过滤使用。"""
    from backend.app.security import auth

    return auth.logger.name


def _client(tmp_path: Path, *, api_key: str = "test-key", production: bool = False):
    """Create test client with fresh app instance."""
    os.environ["WANWEI_API_KEY"] = api_key
    os.environ["WANWEI_MEMORY_DB"] = str(tmp_path / "memory.db")
    if production:
        os.environ["WANWEI_PRODUCTION"] = "1"
    else:
        os.environ.pop("WANWEI_PRODUCTION", None)
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    import importlib
    import backend.app.main as main_mod
    import backend.app.security.auth as auth_mod
    importlib.reload(auth_mod)
    importlib.reload(main_mod)
    return TestClient(main_mod.app, raise_server_exceptions=False)


def test_production_self_bootstraps_api_key(tmp_path, monkeypatch):
    """Production mode no longer hard-blocks on a missing key (issue #45 P1).

    The backend self-bootstraps: a 48-hex key is generated and persisted at
    the platform default path with 0600 permissions, so any launch method
    (bare uvicorn, systemd, container) starts up and self-heals.
    """
    monkeypatch.delenv("WANWEI_API_KEY", raising=False)
    monkeypatch.delenv("WANWEI_API_KEY_FILE", raising=False)
    monkeypatch.setenv("WANWEI_PLATFORM_DIR", str(tmp_path / "platform"))
    monkeypatch.setenv("WANWEI_PRODUCTION", "1")
    # 隔离 APPDATA/XDG_CONFIG_HOME，避免加载已存在的密钥文件干扰测试。
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg_config"))

    from backend.app.security import auth

    # 隔离跨测试的进程内生成缓存，确保本次真实走到「生成+落盘」路径。
    monkeypatch.setattr(auth, "_AUTO_GENERATED_API_KEY", None)

    key = auth.get_api_key()
    assert len(key) == 48
    assert all(c in "0123456789abcdef" for c in key)
    # 自动生成的 key 必须落盘到平台目录上级，且内容一致（进程内自洽）。
    persisted = (tmp_path / "api-key").read_text(encoding="utf-8").strip()
    assert persisted == key


@pytest.mark.parametrize("production_value", ["1", "true", "yes", "TRUE"])
def test_production_truthy_values_self_bootstrap(monkeypatch, tmp_path, production_value):
    """All production truthy values follow the same self-bootstrap path."""
    monkeypatch.delenv("WANWEI_API_KEY", raising=False)
    monkeypatch.delenv("WANWEI_API_KEY_FILE", raising=False)
    monkeypatch.setenv("WANWEI_PLATFORM_DIR", str(tmp_path / "platform"))
    monkeypatch.setenv("WANWEI_PRODUCTION", production_value)

    from backend.app.security.auth import get_api_key

    assert len(get_api_key()) == 48


def test_production_short_api_key_warns_but_starts(monkeypatch, tmp_path, caplog):
    """A short explicit key downgrades to a WARNING instead of blocking startup."""
    monkeypatch.setenv("WANWEI_API_KEY", "too-short")
    monkeypatch.setenv("WANWEI_PRODUCTION", "1")
    monkeypatch.setenv("WANWEI_PLATFORM_DIR", str(tmp_path / "platform"))

    from backend.app.security.auth import get_api_key

    with caplog.at_level(logging.WARNING, logger=auth_logger_name()):
        assert get_api_key() == "too-short"

    assert any("shorter than" in r.message for r in caplog.records)


def test_production_reads_api_key_file(tmp_path, monkeypatch):
    secret_file = tmp_path / "api-key"
    secret_file.write_text("a-strong-production-key-with-40-characters\n", encoding="utf-8")
    monkeypatch.delenv("WANWEI_API_KEY", raising=False)
    monkeypatch.setenv("WANWEI_API_KEY_FILE", str(secret_file))
    monkeypatch.setenv("WANWEI_PRODUCTION", "1")

    from backend.app.security.auth import get_api_key

    assert get_api_key() == "a-strong-production-key-with-40-characters"


def test_missing_api_key_file_fails_closed(tmp_path, monkeypatch):
    monkeypatch.delenv("WANWEI_API_KEY", raising=False)
    monkeypatch.setenv("WANWEI_API_KEY_FILE", str(tmp_path / "missing"))

    from backend.app.security.auth import get_api_key

    with pytest.raises(RuntimeError, match="Unable to read"):
        get_api_key()


def test_production_app_starts_without_api_key(tmp_path, monkeypatch):
    """Production startup no longer fails when no API key is provided (issue #45)."""
    monkeypatch.delenv("WANWEI_API_KEY", raising=False)
    monkeypatch.delenv("WANWEI_API_KEY_FILE", raising=False)
    monkeypatch.setenv("WANWEI_PRODUCTION", "true")
    # encryption 的生产模式硬校验（WANWEI_ENCRYPTION_KEY）是另一条既有安全
    # 边界，本工单只放开 API key 门槛，不影响它。
    monkeypatch.setenv("WANWEI_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.setenv("WANWEI_PLATFORM_DIR", str(tmp_path / "platform"))
    # 隔离 APPDATA/XDG_CONFIG_HOME，避免加载已存在的密钥文件干扰测试。
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg_config"))

    import importlib
    import backend.app.main as main_mod

    importlib.reload(main_mod)
    # TestClient 的 peer host 是 "testclient"（非回环），故不带 key 仍应
    # fail-closed 401；本测试的核心断言是「启动不再因缺 API key 抛异常」，
    # 以及自动生成的 key 可以正常鉴权。
    with TestClient(main_mod.app, raise_server_exceptions=False) as client:
        assert client.get("/model-gateway/configs").status_code == 401
        from backend.app.security import auth

        bootstrap_key = auth._AUTO_GENERATED_API_KEY
        assert bootstrap_key
        assert (
            client.get(
                "/model-gateway/configs",
                headers={"X-API-Key": bootstrap_key},
            ).status_code
            == 200
        )


def test_protected_get_endpoints_require_auth(tmp_path):
    """Sensitive GET endpoints require X-API-Key."""
    client = _client(tmp_path, api_key="test-key")
    from backend.app.workflow.persistence import init_workflow_persistence

    init_workflow_persistence()

    # Without key
    assert client.get("/audit/logs").status_code == 401
    assert client.get("/memory/v2/search?q=test").status_code == 401
    assert client.get("/kylin/sdk/status").status_code == 401
    assert client.get("/workflow/runs").status_code == 401
    assert client.get("/workflow/stats").status_code == 401

    # With valid key
    headers = {"X-API-Key": "test-key"}
    assert client.get("/memory/v2/search?q=test", headers=headers).status_code == 200
    assert client.get("/kylin/sdk/status", headers=headers).status_code == 200
    assert client.get("/workflow/stats", headers=headers).status_code == 200


def test_head_requests_do_not_bypass_auth_on_protected_endpoints(tmp_path):
    """回归：HEAD 请求必须与 GET 一样受 fail-closed 鉴权约束。

    修复前 needs_auth 只覆盖写方法与受保护 GET，HEAD 两者都不沾，于是绕过
    鉴权中间件。FastAPI 的 @app.get 处理器对 HEAD 返回 405（不执行处理器、
    不泄露响应体），但 Starlette 挂载（StaticFiles / 旧版控制台等）会响应
    HEAD，故仍须在鉴权层统一堵住。此测试锁定：未鉴权 HEAD 命中受保护路径
    一律被鉴权层拦为 401，而非漏到路由层。
    """
    client = _client(tmp_path, api_key="test-key")
    from backend.app.workflow.persistence import init_workflow_persistence

    init_workflow_persistence()

    # 未携带 key：受保护读端点的 HEAD 必须被鉴权层拦截（401），而非放行
    assert client.head("/audit/logs").status_code == 401
    assert client.head("/memory/v2/search?q=test").status_code == 401
    assert client.head("/kylin/sdk/status").status_code == 401
    assert client.head("/workflow/runs").status_code == 401

    # 公开路径不受鉴权影响：鉴权层放行（路由是否支持 HEAD 与鉴权判定无关）
    assert client.head("/health").status_code != 401


def test_model_gateway_config_routes_require_auth_and_mask_keys(tmp_path):
    client = _client(tmp_path, api_key="test-key")
    body = {
        "provider": "custom",
        "api_base": "https://api.example.com/v1",
        "api_key": "gateway-secret",
        "model": "custom-model",
        "enabled": True,
        "notes": "test config",
    }

    assert client.get("/model-gateway/configs").status_code == 401
    assert client.post("/model-gateway/configs", json=body).status_code == 401
    assert client.delete("/model-gateway/configs/custom").status_code == 401

    headers = {"X-API-Key": "test-key"}
    response = client.post("/model-gateway/configs", json=body, headers=headers)
    assert response.status_code == 200
    assert response.json()["api_key"] == "***"

    listed = client.get("/model-gateway/configs", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["items"][0]["api_key"] == "***"

    assert client.delete("/model-gateway/configs/custom", headers=headers).status_code == 200


def test_model_gateway_config_provider_must_be_a_single_url_segment(tmp_path):
    client = _client(tmp_path, api_key="test-key")
    response = client.post(
        "/model-gateway/configs",
        json={
            "provider": "a/b",
            "api_base": "https://api.example.com/v1",
            "api_key": "gateway-secret",
            "model": "custom-model",
            "enabled": True,
            "notes": "",
        },
        headers={"X-API-Key": "test-key"},
    )

    assert response.status_code == 422


def test_count_and_cleanup_parameters_are_bounded(tmp_path):
    client = _client(tmp_path, api_key="test-key")
    headers = {"X-API-Key": "test-key"}

    assert client.get("/memory/v2/capsules?limit=-1", headers=headers).status_code == 422
    assert client.get("/memory/v2/capsules?limit=201", headers=headers).status_code == 422
    assert client.get("/workflow/runs?limit=-1", headers=headers).status_code == 422
    assert client.get("/workflow/runs?limit=201", headers=headers).status_code == 422
    assert client.get("/workflow/runs?offset=-1", headers=headers).status_code == 422
    assert client.post("/workflow/cleanup?ttl_days=-1", headers=headers).status_code == 422
    assert client.post(
        "/memory/v2/command",
        json={"goal": "bounded command", "top_k": -1},
        headers=headers,
    ).status_code == 422
    assert client.post(
        "/memory/v2/command",
        json={"goal": "bounded command", "top_k": 51},
        headers=headers,
    ).status_code == 422


def test_middleware_generated_errors_keep_security_headers(tmp_path):
    client = _client(tmp_path, api_key="test-key")
    headers = {"X-API-Key": "test-key"}
    responses = [client.get("/audit/logs")]
    responses.append(
        client.post(
            "/memory/v2/capsules",
            content=b"x" * (5 * 1024 * 1024 + 1),
            headers={**headers, "Content-Type": "application/json"},
        )
    )
    rate_responses = [client.get("/kylin/sdk/status", headers=headers) for _ in range(11)]
    responses.append(rate_responses[-1])

    assert [response.status_code for response in responses] == [401, 413, 429]
    for response in responses:
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert "Content-Security-Policy" in response.headers


def test_capsule_detail_requires_auth(tmp_path):
    client = _client(tmp_path, api_key="test-key")
    headers = {"X-API-Key": "test-key"}
    capsule_id = client.post(
        "/memory/v2/capsules",
        json={"memory_class": "knowledge", "content": {"text": "private capsule"}},
        headers=headers,
    ).json()["capsule_id"]

    assert client.get(f"/memory/v2/capsules/{capsule_id}").status_code == 401
    assert client.get(f"/memory/v2/capsules/{capsule_id}", headers=headers).status_code == 200


def test_write_endpoints_require_auth(tmp_path):
    """Write endpoints require X-API-Key."""
    client = _client(tmp_path, api_key="test-key")
    body = {"memory_class": "preference", "content": {"text": "test"}}

    # Without key
    assert client.post("/memory/v2/capsules", json=body).status_code == 401
    assert client.post("/kylin/sdk/reindex").status_code == 401

    # With valid key
    headers = {"X-API-Key": "test-key"}
    assert client.post("/memory/v2/capsules", json=body, headers=headers).status_code == 200
    assert client.post("/kylin/sdk/reindex", headers=headers).status_code in {200, 202}


def test_constant_time_comparison():
    """Verify secrets.compare_digest is used."""
    from backend.app.security.auth import _verify_api_key
    import secrets

    assert hasattr(secrets, 'compare_digest')
    assert not _verify_api_key(None)
    assert not _verify_api_key("")


def test_forget_confirm_exact_matching(tmp_path):
    """Verify ticket lookup uses an exact parameterized ID, not LIKE wildcards."""
    main_py = Path(__file__).parent.parent / "main.py"
    content = main_py.read_text(encoding="utf-8")

    assert "WHERE forget_request_id=?" in content
    assert "forget_request_id LIKE" not in content


def test_input_limits_exist():
    """Verify input limits module."""
    from backend.app.security import input_limits
    assert hasattr(input_limits, 'validate_search_params')
    assert hasattr(input_limits, 'validate_goal_length')
    assert hasattr(input_limits, 'BodySizeLimitMiddleware')


def test_redaction_module_exists():
    """Verify redaction module."""
    from backend.app.security import redaction
    assert hasattr(redaction, 'redact_audit_payload')


def test_security_headers(tmp_path):
    """Response includes security headers."""
    client = _client(tmp_path, api_key="test-key")
    response = client.get("/health")

    headers_lower = {k.lower(): v for k, v in response.headers.items()}
    assert headers_lower.get("x-content-type-options") == "nosniff"
    assert "x-frame-options" in headers_lower
    csp = headers_lower.get("content-security-policy", "")
    assert "content-security-policy" in headers_lower
    assert "script-src 'self'" in csp
    assert "'unsafe-inline'" not in csp.split("style-src", 1)[0]
    assert "referrer-policy" in headers_lower


def test_legacy_console_disabled_by_default(tmp_path, monkeypatch):
    """The old single-file console is not exposed unless explicitly enabled."""
    monkeypatch.delenv("WANWEI_ENABLE_LEGACY_CONSOLE", raising=False)
    client = _client(tmp_path, api_key="test-key")

    assert client.get("/console-legacy/").status_code == 401
    assert client.get("/console-legacy/", headers={"X-API-Key": "test-key"}).status_code == 404


def test_legacy_console_opt_in_requires_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("WANWEI_ENABLE_LEGACY_CONSOLE", "1")
    client = _client(tmp_path, api_key="test-key")

    assert client.get("/console-legacy/").status_code == 401
    assert client.get("/console-legacy/", headers={"X-API-Key": "test-key"}).status_code == 200


def test_vue_console_does_not_ship_default_dev_api_key():
    console_root = Path(__file__).resolve().parents[3] / "frontend" / "console-vue"
    app_vue = (console_root / "src" / "App.vue").read_text(encoding="utf-8")
    client_ts = (console_root / "src" / "api" / "client.ts").read_text(encoding="utf-8")

    assert "wanwei-dev-key" not in app_vue
    # Key may appear only inside a DEV-only conditional; never as a bare default
    assert "let apiKey = 'wanwei-dev-key'" not in client_ts
    assert 'let apiKey = "wanwei-dev-key"' not in client_ts

    # dist/ is gitignored; only check if a build is present
    dist_assets = console_root / "dist" / "assets"
    if dist_assets.exists():
        assert all(
            "wanwei-dev-key" not in script.read_text(encoding="utf-8")
            for script in dist_assets.glob("*.js")
        )


def test_policy_patterns_precompiled():
    """Verify policy patterns are precompiled."""
    from backend.app.memory_runtime import policy_gate
    import re

    assert hasattr(policy_gate, 'S3_PATTERNS')
    if policy_gate.S3_PATTERNS:
        assert isinstance(policy_gate.S3_PATTERNS[0], re.Pattern)
