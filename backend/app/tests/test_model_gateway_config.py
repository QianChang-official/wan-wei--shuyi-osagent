"""Model gateway configuration tests (v0.9.6.1 static-scan follow-up).

Validates explicit local-provider configuration in
backend/app/model_gateway/service.py:
- environment configuration is reflected in the provider catalog;
- the provider is disabled when required configuration is absent;
- clients cannot inject api_base through ModelGatewayTestIn (only the catalog
  value is used);
- the SSRF denylist still guards real (non-dry-run) smoke calls.
"""
from __future__ import annotations

import importlib

from backend.app.model_gateway import service as gateway_service
from backend.app.model_gateway.schemas import ModelGatewayTestIn


def _reload_service():
    return importlib.reload(gateway_service)


def test_env_override_takes_precedence(monkeypatch):
    monkeypatch.setenv("WANWEI_OPENAI_COMPATIBLE_BASE", "https://llm.example.internal/v1")
    monkeypatch.setenv("WANWEI_OPENAI_COMPATIBLE_MODEL", "test-model")
    try:
        mod = _reload_service()
        assert mod.LOCAL_LLAMA_BASE == "https://llm.example.internal/v1"
        catalog = {p.provider: p for p in mod.PROVIDERS}
        assert catalog["openai_compatible"].api_base == "https://llm.example.internal/v1"
        assert catalog["openai_compatible"].enabled is True
    finally:
        monkeypatch.delenv("WANWEI_OPENAI_COMPATIBLE_BASE", raising=False)
        monkeypatch.delenv("WANWEI_OPENAI_COMPATIBLE_MODEL", raising=False)
        _reload_service()


def test_provider_disabled_without_env(monkeypatch):
    monkeypatch.delenv("WANWEI_OPENAI_COMPATIBLE_BASE", raising=False)
    monkeypatch.delenv("WANWEI_OPENAI_COMPATIBLE_MODEL", raising=False)
    try:
        mod = _reload_service()
        assert mod.LOCAL_LLAMA_BASE == ""
        catalog = {p.provider: p for p in mod.PROVIDERS}
        assert catalog["openai_compatible"].enabled is False
        assert catalog["openai_compatible"].status == "configuration_required"
    finally:
        _reload_service()


def test_client_cannot_inject_api_base():
    # ModelGatewayTestIn must not expose an api_base field; a client-supplied
    # value is ignored and only the provider catalog value is used.
    fields = getattr(ModelGatewayTestIn, "model_fields", None) or ModelGatewayTestIn.__fields__
    assert "api_base" not in fields
    req = ModelGatewayTestIn(
        provider="openai_compatible",
        dry_run=True,
        api_base="http://attacker.example/v1",  # extra field, silently ignored
    )
    assert not hasattr(req, "api_base")
    out = gateway_service.run_provider_test(req)
    assert out.status == "ok"  # dry-run path, no network call


def test_real_smoke_still_ssrf_guarded(monkeypatch):
    # Without an explicit host allowlist, a private endpoint must be
    # rejected by the SSRF denylist before any network call is attempted.
    monkeypatch.setenv("WANWEI_OPENAI_COMPATIBLE_BASE", "http://172.29.128.1:8084/v1")
    monkeypatch.setenv("WANWEI_OPENAI_COMPATIBLE_MODEL", "test-model")
    monkeypatch.delenv("WANWEI_OPENAI_COMPATIBLE_HOST_ALLOWLIST", raising=False)
    try:
        mod = _reload_service()
        out = mod.run_provider_test(
            ModelGatewayTestIn(provider="openai_compatible", dry_run=False)
        )
        assert out.status == "ssrf_blocked"
    finally:
        monkeypatch.delenv("WANWEI_OPENAI_COMPATIBLE_BASE", raising=False)
        monkeypatch.delenv("WANWEI_OPENAI_COMPATIBLE_MODEL", raising=False)
        _reload_service()
