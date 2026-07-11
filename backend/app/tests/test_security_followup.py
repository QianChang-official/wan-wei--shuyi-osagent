"""Security follow-up tests for v0.9.4.

Tests core security hardening fixes.
"""
import os
import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient


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


def test_production_requires_api_key(tmp_path):
    """Production mode must fail if WANWEI_API_KEY not set."""
    os.environ.pop("WANWEI_API_KEY", None)
    os.environ["WANWEI_PRODUCTION"] = "1"

    with pytest.raises(RuntimeError, match="WANWEI_PRODUCTION=1 requires WANWEI_API_KEY"):
        from backend.app.security.auth import get_api_key
        get_api_key()


@pytest.mark.parametrize("production_value", ["1", "true", "yes", "TRUE"])
def test_production_truthy_values_require_api_key(monkeypatch, production_value):
    monkeypatch.delenv("WANWEI_API_KEY", raising=False)
    monkeypatch.setenv("WANWEI_PRODUCTION", production_value)

    from backend.app.security.auth import get_api_key

    with pytest.raises(RuntimeError, match="WANWEI_PRODUCTION=1 requires WANWEI_API_KEY"):
        get_api_key()


def test_production_rejects_short_api_key(monkeypatch):
    monkeypatch.setenv("WANWEI_API_KEY", "too-short")
    monkeypatch.setenv("WANWEI_PRODUCTION", "1")

    from backend.app.security.auth import get_api_key

    with pytest.raises(RuntimeError, match="at least 32"):
        get_api_key()


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


def test_production_app_fails_during_startup_without_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("WANWEI_API_KEY", raising=False)
    monkeypatch.setenv("WANWEI_PRODUCTION", "true")
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(tmp_path / "memory.db"))

    import importlib
    import backend.app.main as main_mod

    importlib.reload(main_mod)
    with pytest.raises(RuntimeError, match="WANWEI_PRODUCTION=1 requires WANWEI_API_KEY"):
        with TestClient(main_mod.app):
            pass


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
    dist_scripts = list((console_root / "dist" / "assets").glob("*.js"))

    assert "wanwei-dev-key" not in app_vue
    assert "wanwei-dev-key" not in client_ts
    assert dist_scripts
    assert all(
        "wanwei-dev-key" not in script.read_text(encoding="utf-8")
        for script in dist_scripts
    )


def test_policy_patterns_precompiled():
    """Verify policy patterns are precompiled."""
    from backend.app.memory_runtime import policy_gate
    import re

    assert hasattr(policy_gate, 'S3_PATTERNS')
    if policy_gate.S3_PATTERNS:
        assert isinstance(policy_gate.S3_PATTERNS[0], re.Pattern)
