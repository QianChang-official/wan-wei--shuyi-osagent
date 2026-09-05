"""Cross-API-key isolation tests for provider cockpit configuration.

The second key is explicitly provisioned in the test identity registry;
requests exercise the production authentication middleware.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


KEY_A = "provider-owner-a"
KEY_B = "provider-owner-b"
HEADERS_A = {"x-api-key": KEY_A}
HEADERS_B = {"x-api-key": KEY_B}


@pytest.fixture()
def client(tmp_path, monkeypatch, seed_identity):
    monkeypatch.setenv("WANWEI_API_KEY", KEY_A)
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.setenv("WANWEI_PLATFORM_DIR", str(tmp_path / "platform"))
    monkeypatch.delenv("WANWEI_PRODUCTION", raising=False)
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

    import backend.app.init_db
    import backend.app.app_runtime as runtime_mod
    import backend.app.main as main_mod

    importlib.reload(runtime_mod)
    importlib.reload(main_mod)
    backend.app.init_db.main()
    seed_identity(KEY_B)
    with TestClient(main_mod.app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_provider_config_and_aux_are_isolated_between_keys(client):
    configured = client.put(
        "/platform/providers/configs/openai",
        json={"api_key": "sk-owner-a-secret", "enabled": True},
        headers=HEADERS_A,
    )
    assert configured.status_code == 200, configured.text
    assert "owner_id" not in configured.json()
    assert configured.json()["api_key_tail"] == "cret"

    aux = client.put(
        "/platform/providers/aux",
        json={"pid": "openai", "model": "gpt-owner-a", "enabled": True},
        headers=HEADERS_A,
    )
    assert aux.status_code == 200, aux.text
    assert "owner_id" not in aux.json()

    listed_b = client.get("/platform/providers/configs", headers=HEADERS_B)
    assert listed_b.status_code == 200, listed_b.text
    openai_b = next(item for item in listed_b.json() if item["pid"] == "openai")
    assert openai_b["configured"] is False
    assert openai_b["has_api_key"] is False
    assert openai_b["api_key_tail"] == ""

    aux_b = client.get("/platform/providers/aux", headers=HEADERS_B)
    assert aux_b.status_code == 200, aux_b.text
    assert aux_b.json()["enabled"] is False
    assert aux_b.json()["model"] == ""

    # A foreign principal cannot overwrite, delete, probe, or enter OAuth
    # flows for a credential it does not own.
    assert client.put(
        "/platform/providers/configs/openai",
        json={"enabled": False},
        headers=HEADERS_B,
    ).status_code == 404
    assert client.delete("/platform/providers/configs/openai", headers=HEADERS_B).status_code == 404
    assert client.post(
        "/platform/providers/test",
        json={"pid": "openai"},
        headers=HEADERS_B,
    ).status_code == 404
    assert client.put(
        "/platform/providers/aux",
        json={"enabled": False},
        headers=HEADERS_B,
    ).status_code == 404
    assert client.post(
        "/platform/providers/auth/openai/begin",
        headers=HEADERS_B,
    ).status_code == 404

    listed_a = client.get("/platform/providers/configs", headers=HEADERS_A)
    openai_a = next(item for item in listed_a.json() if item["pid"] == "openai")
    assert openai_a["configured"] is True
    assert openai_a["api_key_tail"] == "cret"
    assert client.get("/platform/providers/aux", headers=HEADERS_A).json()["model"] == "gpt-owner-a"


def test_ownerless_legacy_provider_rows_bind_to_compatible_actor(client):
    from backend.app.platform_api import providers as providers_mod

    providers_mod._store.set(  # noqa: SLF001
        "openai",
        {"enabled": True, "model": "legacy-model", "api_key_encrypted": ""},
    )
    providers_mod._store.set(  # noqa: SLF001
        providers_mod._AUX_KEY,
        {"enabled": True, "model": "legacy-aux"},
    )

    owned = client.get("/platform/providers/configs", headers=HEADERS_A)
    assert owned.status_code == 200
    openai_a = next(item for item in owned.json() if item["pid"] == "openai")
    assert openai_a["configured"] is True
    assert openai_a["model"] == "legacy-model"
    assert client.get("/platform/providers/aux", headers=HEADERS_A).json()["model"] == "legacy-aux"

    foreign = client.get("/platform/providers/configs", headers=HEADERS_B)
    assert foreign.status_code == 200
    openai_b = next(item for item in foreign.json() if item["pid"] == "openai")
    assert openai_b["configured"] is False
    assert client.get("/platform/providers/aux", headers=HEADERS_B).json()["model"] == ""


def test_same_provider_can_have_legacy_and_scoped_records(client):
    from backend.app.platform_api import providers as providers_mod

    providers_mod._store.set(
        "openai",
        {"enabled": True, "model": "legacy", "api_key_encrypted": ""},
    )
    configured = client.put(
        "/platform/providers/configs/openai",
        json={"model": "owner-b", "enabled": True},
        headers=HEADERS_B,
    )
    assert configured.status_code == 200
    assert configured.json()["model"] == "owner-b"

    listed_a = client.get("/platform/providers/configs", headers=HEADERS_A)
    listed_b = client.get("/platform/providers/configs", headers=HEADERS_B)
    assert next(item for item in listed_a.json() if item["pid"] == "openai")["model"] == "legacy"
    assert next(item for item in listed_b.json() if item["pid"] == "openai")["model"] == "owner-b"
    raw = providers_mod._store.all()
    assert raw["openai"]["model"] == "legacy"
    assert any(
        isinstance(value, dict)
        and value.get("openai", {}).get("model") == "owner-b"
        for key, value in raw.items()
        if key.startswith(providers_mod._OWNER_KEY_PREFIX)
    )
