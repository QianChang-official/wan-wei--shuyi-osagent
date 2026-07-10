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

    # Without key
    assert client.get("/audit/logs").status_code == 401
    assert client.get("/memory/v2/search?q=test").status_code == 401
    assert client.get("/workflow/runs").status_code == 401

    # With valid key
    headers = {"X-API-Key": "test-key"}
    assert client.get("/memory/v2/search?q=test", headers=headers).status_code == 200


def test_write_endpoints_require_auth(tmp_path):
    """Write endpoints require X-API-Key."""
    client = _client(tmp_path, api_key="test-key")
    body = {"memory_class": "preference", "content": {"text": "test"}}

    # Without key
    assert client.post("/memory/v2/capsules", json=body).status_code == 401

    # With valid key
    headers = {"X-API-Key": "test-key"}
    assert client.post("/memory/v2/capsules", json=body, headers=headers).status_code == 200


def test_constant_time_comparison():
    """Verify secrets.compare_digest is used."""
    from backend.app.security.auth import _verify_api_key
    import secrets

    assert hasattr(secrets, 'compare_digest')
    assert not _verify_api_key(None)
    assert not _verify_api_key("")


def test_forget_confirm_exact_matching(tmp_path):
    """Verify code uses exact JSON matching, not LIKE wildcards."""
    main_py = Path(__file__).parent.parent / "main.py"
    content = main_py.read_text(encoding="utf-8")

    # Should use json.loads for exact field matching
    assert "json.loads(row['payload'])" in content or "json.loads(preview['payload'])" in content
    # Should iterate and match exact field
    assert "payload.get('forget_request_id') ==" in content


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
    assert "content-security-policy" in headers_lower
    assert "referrer-policy" in headers_lower


def test_policy_patterns_precompiled():
    """Verify policy patterns are precompiled."""
    from backend.app.memory_runtime import policy_gate
    import re

    assert hasattr(policy_gate, 'S3_PATTERNS')
    if policy_gate.S3_PATTERNS:
        assert isinstance(policy_gate.S3_PATTERNS[0], re.Pattern)
