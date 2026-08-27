"""Regression tests for the unified provider and bounded gateway paths."""

from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def test_runtime_provider_resolves_enabled_cockpit_config(monkeypatch):
    from app.model_gateway import service
    from app.platform_api import providers

    record = {
        "enabled": True,
        "base_url": "https://provider.example/v1",
        "model": "provider-model",
        "api_key_encrypted": "ciphertext",
    }
    monkeypatch.setattr(
        providers._store,
        "get",
        lambda key, default=None: record if key == "custom_endpoint" else default,
    )
    monkeypatch.setattr(providers, "_decrypt_key", lambda _record: "provider-secret")
    monkeypatch.setattr(service, "_get_config", lambda _provider: None)
    monkeypatch.setattr(service, "local_llama_settings", lambda: ("", "", False))

    target = service.resolve_runtime_provider()
    assert target == (
        "custom_endpoint",
        "https://provider.example/v1",
        "provider-secret",
        "provider-model",
    )


def test_agent_gateway_uses_bounded_provider_dispatch(monkeypatch):
    from app.platform_api import agents
    from app.model_gateway import service

    captured: dict[str, object] = {}

    async def fake_dispatch(provider, api_base, api_key, model, prompt, max_tokens):
        captured.update(
            provider=provider,
            api_base=api_base,
            api_key=api_key,
            model=model,
            prompt=prompt,
            max_tokens=max_tokens,
        )
        return "ok", 1, "bounded result"

    monkeypatch.setattr(
        agents,
        "_resolve_gateway_target",
        lambda _run: ("https://provider.example", "secret", "model", "anthropic"),
    )
    monkeypatch.setattr(service, "_run_smoke_in_dedicated_pool_async", fake_dispatch)

    result = asyncio.run(agents._try_gateway("hello", {"provider_pid": "anthropic"}))
    assert result == ("bounded result", "anthropic")
    assert captured["provider"] == "anthropic"
    assert captured["api_key"] == "secret"
    assert captured["max_tokens"] == 384


def test_provider_extra_metadata_is_redacted_before_echo(monkeypatch):
    from app.platform_api import providers

    payload = providers._masked_config(
        "custom_endpoint",
        {
            "extra": {
                "password": "plaintext-secret",
                "headers": {"Authorization": "Bearer live-token-value"},
                "label": "normal metadata",
            }
        },
    )
    extra = payload["extra"]
    assert extra["password"] == "***REDACTED***"
    assert extra["headers"]["Authorization"] == "***REDACTED***"
    assert extra["label"] == "normal metadata"
    assert "plaintext-secret" not in str(extra)
    assert "live-token-value" not in str(extra)


@pytest.fixture()
def gateway_client(tmp_path, monkeypatch):
    key_a = "gateway-owner-a"
    key_b = "gateway-owner-b"
    monkeypatch.setenv("WANWEI_API_KEY", key_a)
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.setenv("WANWEI_PLATFORM_DIR", str(tmp_path / "platform"))
    monkeypatch.delenv("WANWEI_PRODUCTION", raising=False)
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

    import app.security.auth as auth
    import backend.app.security.auth as backend_auth

    verify = lambda provided: provided in {key_a, key_b}
    monkeypatch.setattr(auth, "_verify_api_key", verify)
    monkeypatch.setattr(backend_auth, "_verify_api_key", verify)

    import backend.app.main as main_mod

    importlib.reload(main_mod)
    with TestClient(main_mod.app, raise_server_exceptions=False) as client:
        yield client, key_a, key_b


def test_legacy_gateway_routes_reject_foreign_principal(gateway_client):
    client, key_a, key_b = gateway_client
    body = {
        "provider": "legacy-owner-check",
        "api_base": "https://api.example.com/v1",
        "api_key": "owner-a-secret",
        "model": "model-a",
        "enabled": True,
    }
    created = client.post("/model-gateway/configs", json=body, headers={"x-api-key": key_a})
    assert created.status_code == 200, created.text

    foreign = {"x-api-key": key_b}
    assert client.get("/model-gateway/configs", headers=foreign).status_code == 404
    assert client.post("/model-gateway/configs", json=body, headers=foreign).status_code == 404
    assert client.delete("/model-gateway/configs/legacy-owner-check", headers=foreign).status_code == 404
    assert client.post(
        "/model-gateway/test",
        json={"provider": "legacy-owner-check", "dry_run": True},
        headers=foreign,
    ).status_code == 404


def test_legacy_memory_center_routes_reject_foreign_principal(gateway_client):
    client, _key_a, key_b = gateway_client
    foreign = {"x-api-key": key_b}
    assert client.get("/platform/memory/instructions", headers=foreign).status_code == 404
    assert client.get("/platform/memory/phrases", headers=foreign).status_code == 404
    assert client.get("/platform/memory/sessions", headers=foreign).status_code == 404
    assert client.post("/platform/memory/dreams/archive-now", headers=foreign).status_code == 404


def test_device_system_routes_reject_foreign_principal(gateway_client):
    """The single physical device state is not a cross-key shared resource."""
    client, _key_a, key_b = gateway_client
    foreign = {"x-api-key": key_b}
    for path in (
        "/platform/system/health",
        "/platform/system/voice",
        "/platform/system/browser/rules",
        "/platform/system/emulator/downloads",
        "/platform/system/lan/status",
    ):
        assert client.get(path, headers=foreign).status_code == 404
    assert client.put(
        "/platform/system/settings",
        json={"theme": "night"},
        headers=foreign,
    ).status_code == 404


def test_governance_routes_reject_foreign_principal(gateway_client):
    """Global incident/release state is an admin surface, not tenant data."""
    client, _key_a, key_b = gateway_client
    foreign = {"x-api-key": key_b}
    assert client.get(
        "/memory/governance/release-gate", headers=foreign,
    ).status_code == 404
    assert client.get(
        "/memory/governance/incidents", headers=foreign,
    ).status_code == 404
    assert client.post(
        "/memory/governance/incidents",
        json={"mhg_level": 5, "incident_type": "other"},
        headers=foreign,
    ).status_code == 404


def test_legacy_global_surfaces_reject_foreign_principal(gateway_client):
    """Single-node mobile/knowledge/workflow/audit/Kylin state stays local-admin only."""
    client, _key_a, key_b = gateway_client
    foreign = {"x-api-key": key_b}

    for path in (
        "/workflow/runs",
        "/workflow/stats",
        "/audit/logs",
        "/kylin/sdk/status",
        "/memoryos/bench/report",
        "/platform/knowledge/docs",
        "/platform/knowledge/stats",
        "/platform/mobile/list",
        "/platform/mobile/tool-calls",
    ):
        assert client.get(path, headers=foreign).status_code == 404, path

    workflow_body = {
        "scenario": "weekly_report_preference_learning",
        "user_goal": "security boundary check",
        "include_model_gateway": False,
        "include_forgetting": False,
        "dry_run": True,
    }
    assert client.post(
        "/workflow/runs", json=workflow_body, headers=foreign,
    ).status_code == 404
    assert client.post(
        "/workflow/cleanup?ttl_days=7", headers=foreign,
    ).status_code == 404
    assert client.post(
        "/kylin/sdk/reindex?limit=1", headers=foreign,
    ).status_code == 404
    assert client.post(
        "/platform/knowledge/import",
        json={"items": []},
        headers=foreign,
    ).status_code == 404
