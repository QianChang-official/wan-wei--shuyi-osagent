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
import sqlite3

from cryptography.fernet import Fernet

from backend.app.model_gateway import service as gateway_service
from backend.app.model_gateway.schemas import ModelGatewayTestIn


def _reload_service():
    gateway_service.shutdown_smoke_executor()
    return importlib.reload(gateway_service)


def test_providers_compatibility_snapshot_remains_importable():
    assert isinstance(gateway_service.PROVIDERS, list)
    assert {provider.provider for provider in gateway_service.PROVIDERS}


def test_env_override_takes_precedence(monkeypatch):
    monkeypatch.setenv("WANWEI_OPENAI_COMPATIBLE_BASE", "https://llm.example.internal/v1")
    monkeypatch.setenv("WANWEI_OPENAI_COMPATIBLE_MODEL", "test-model")
    try:
        mod = _reload_service()
        assert mod.LOCAL_LLAMA_BASE == "https://llm.example.internal/v1"
        catalog = {p.provider: p for p in mod._build_providers()}
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
        catalog = {p.provider: p for p in mod._build_providers()}
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


def test_real_smoke_still_ssrf_guarded(monkeypatch, isolated_db):
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


def test_db_config_is_masked_and_overrides_environment(tmp_path, monkeypatch):
    db_path = tmp_path / "gateway-config.db"
    encryption_key = Fernet.generate_key()
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(db_path))
    monkeypatch.setenv("WANWEI_ENCRYPTION_KEY", encryption_key.decode("ascii"))
    monkeypatch.setenv("WANWEI_OPENAI_COMPATIBLE_BASE", "https://env.example/v1")
    monkeypatch.setenv("WANWEI_OPENAI_COMPATIBLE_MODEL", "env-model")
    try:
        from backend.app.init_db import main as init_db

        init_db()
        gateway_service.upsert_config(
            provider="openai_compatible",
            api_base="https://db.example/v1",
            api_key="db-secret-key",
            model="db-model",
            enabled=True,
            notes="database configuration",
        )

        configs = gateway_service.list_configs()["items"]
        assert configs == [
            {
                "provider": "openai_compatible",
                "api_base": "https://db.example/v1",
                "api_key": "***",
                "model": "db-model",
                "enabled": True,
                "notes": "database configuration",
            }
        ]

        stored_key = sqlite3.connect(db_path).execute(
            "SELECT api_key_encrypted FROM model_gateway_configs WHERE provider=?",
            ("openai_compatible",),
        ).fetchone()[0]
        assert stored_key != "db-secret-key"
        assert Fernet(encryption_key).decrypt(stored_key.encode("ascii")) == b"db-secret-key"

        out = gateway_service.run_provider_test(
            ModelGatewayTestIn(provider="openai_compatible", dry_run=True)
        )
        assert out.model == "db-model"
    finally:
        monkeypatch.delenv("WANWEI_MEMORY_DB", raising=False)
        monkeypatch.delenv("WANWEI_ENCRYPTION_KEY", raising=False)
        monkeypatch.delenv("WANWEI_OPENAI_COMPATIBLE_BASE", raising=False)
        monkeypatch.delenv("WANWEI_OPENAI_COMPATIBLE_MODEL", raising=False)
        _reload_service()


def test_real_smoke_uses_database_api_base_and_key(tmp_path, monkeypatch):
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(tmp_path / "gateway-config.db"))
    try:
        from backend.app.init_db import main as init_db

        init_db()
        gateway_service.upsert_config(
            provider="custom",
            api_base="https://db.example/v1",
            api_key="db-secret-key",
            model="db-model",
            enabled=True,
            notes="",
        )
        captured: dict[str, str] = {}

        def fake_smoke(api_base, api_key, model, prompt, max_tokens):
            captured.update(api_base=api_base, api_key=api_key, model=model)
            return "ok", 12, "configured"

        monkeypatch.setattr(gateway_service, "_openai_compatible_smoke", fake_smoke)
        monkeypatch.setattr(gateway_service, "validate_external_url", lambda value, **_: value)

        out = gateway_service.run_provider_test(
            ModelGatewayTestIn(provider="custom", dry_run=False)
        )

        assert out.status == "ok"
        assert captured == {
            "api_base": "https://db.example/v1",
            "api_key": "db-secret-key",
            "model": "db-model",
        }
    finally:
        monkeypatch.delenv("WANWEI_MEMORY_DB", raising=False)


def test_real_smoke_blocks_unreadable_database_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(tmp_path / "gateway-config.db"))
    monkeypatch.setenv("WANWEI_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    try:
        from backend.app.init_db import main as init_db

        init_db()
        gateway_service.upsert_config(
            provider="custom",
            api_base="https://db.example/v1",
            api_key="db-secret-key",
            model="db-model",
            enabled=True,
            notes="",
        )
        monkeypatch.setenv("WANWEI_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
        monkeypatch.setattr(
            gateway_service,
            "_openai_compatible_smoke",
            lambda *args: ("ok", 12, "configured"),
        )
        monkeypatch.setattr(gateway_service, "validate_external_url", lambda value, **_: value)

        out = gateway_service.run_provider_test(
            ModelGatewayTestIn(provider="custom", dry_run=False)
        )

        assert out.status == "not_configured"
        assert "cannot be decrypted" in out.message
    finally:
        monkeypatch.delenv("WANWEI_MEMORY_DB", raising=False)
        monkeypatch.delenv("WANWEI_ENCRYPTION_KEY", raising=False)


def test_upsert_blank_api_key_preserves_existing_key(tmp_path, monkeypatch):
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(tmp_path / "gateway-config.db"))
    try:
        from backend.app.init_db import main as init_db

        init_db()
        gateway_service.upsert_config(
            provider="custom",
            api_base="https://one.example/v1",
            api_key="first-key",
            model="first-model",
            enabled=True,
            notes="first",
        )
        gateway_service.upsert_config(
            provider="custom",
            api_base="https://two.example/v1",
            api_key="",
            model="second-model",
            enabled=False,
            notes="second",
        )

        assert gateway_service._get_config("custom")["api_key"] == "first-key"
        assert gateway_service.list_configs()["items"][0]["api_key"] == "***"
    finally:
        monkeypatch.delenv("WANWEI_MEMORY_DB", raising=False)


def test_upsert_blank_api_key_preserves_unreadable_ciphertext(tmp_path, monkeypatch):
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(tmp_path / "gateway-config.db"))
    first_key = Fernet.generate_key()
    monkeypatch.setenv("WANWEI_ENCRYPTION_KEY", first_key.decode("ascii"))
    try:
        from backend.app.init_db import main as init_db

        init_db()
        gateway_service.upsert_config(
            provider="custom",
            api_base="https://one.example/v1",
            api_key="first-key",
            model="first-model",
            enabled=True,
            notes="first",
        )
        db_path = tmp_path / "gateway-config.db"
        original_ciphertext = sqlite3.connect(db_path).execute(
            "SELECT api_key_encrypted FROM model_gateway_configs WHERE provider=?",
            ("custom",),
        ).fetchone()[0]

        monkeypatch.setenv("WANWEI_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
        gateway_service.upsert_config(
            provider="custom",
            api_base="https://two.example/v1",
            api_key="",
            model="second-model",
            enabled=False,
            notes="second",
        )
        updated_ciphertext = sqlite3.connect(db_path).execute(
            "SELECT api_key_encrypted FROM model_gateway_configs WHERE provider=?",
            ("custom",),
        ).fetchone()[0]

        assert updated_ciphertext == original_ciphertext
    finally:
        monkeypatch.delenv("WANWEI_MEMORY_DB", raising=False)
        monkeypatch.delenv("WANWEI_ENCRYPTION_KEY", raising=False)


def test_owner_scoped_configs_coexist_and_delete_isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(tmp_path / "gateway-config.db"))
    try:
        from backend.app.init_db import main as init_db

        init_db()
        gateway_service.upsert_config(
            provider="custom", api_base="https://a.example/v1", api_key="a-key",
            model="a-model", enabled=True, notes="a", owner_id="owner-a",
        )
        gateway_service.upsert_config(
            provider="custom", api_base="https://b.example/v1", api_key="b-key",
            model="b-model", enabled=True, notes="b", owner_id="owner-b",
        )
        assert gateway_service.list_configs("owner-a")["items"][0]["model"] == "a-model"
        assert gateway_service.list_configs("owner-b")["items"][0]["model"] == "b-model"
        assert gateway_service.delete_config("custom", owner_id="owner-a") is True
        assert gateway_service.delete_config("custom", owner_id="owner-a") is False
        assert gateway_service.list_configs("owner-b")["items"][0]["model"] == "b-model"
    finally:
        monkeypatch.delenv("WANWEI_MEMORY_DB", raising=False)


def test_ownerless_legacy_config_can_coexist_with_owned_config(tmp_path, monkeypatch):
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(tmp_path / "gateway-config.db"))
    monkeypatch.setenv("WANWEI_API_KEY", "legacy-owner")
    try:
        from backend.app.init_db import main as init_db

        init_db()
        gateway_service._ensure_config_table()
        conn = sqlite3.connect(str(tmp_path / "gateway-config.db"))
        conn.execute(
            "INSERT INTO model_gateway_configs(provider,owner_id,api_base,api_key_encrypted,model,enabled,notes,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            ("custom", None, "https://legacy.example/v1", None, "legacy-model", 1, "", "now", "now"),
        )
        conn.commit()
        gateway_service.upsert_config(
            provider="custom", api_base="https://owned.example/v1", api_key="owned-key",
            model="owned-model", enabled=True, notes="", owner_id="owner-b",
        )
        assert gateway_service._get_config("custom")["model"] == "legacy-model"
        assert gateway_service._get_config("custom", "owner-b")["model"] == "owned-model"
        rows = conn.execute(
            "SELECT owner_id FROM model_gateway_configs WHERE provider='custom' ORDER BY id"
        ).fetchall()
        assert len(rows) == 2
    finally:
        monkeypatch.delenv("WANWEI_MEMORY_DB", raising=False)
        monkeypatch.delenv("WANWEI_API_KEY", raising=False)


def test_delete_config_removes_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(tmp_path / "gateway-config.db"))
    try:
        from backend.app.init_db import main as init_db

        init_db()
        gateway_service.upsert_config(
            provider="custom",
            api_base="https://example.com/v1",
            api_key="secret",
            model="custom-model",
            enabled=True,
            notes="",
        )

        assert gateway_service.delete_config("custom") is True
        assert gateway_service.list_configs() == {"items": []}
        assert gateway_service.delete_config("custom") is False
    finally:
        monkeypatch.delenv("WANWEI_MEMORY_DB", raising=False)
