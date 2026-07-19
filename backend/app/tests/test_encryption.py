from __future__ import annotations

import base64
import hashlib

import pytest
from cryptography.fernet import Fernet

from backend.app.security import encryption


def test_encrypt_uses_explicit_fernet_key(monkeypatch):
    key = Fernet.generate_key()
    monkeypatch.setenv("WANWEI_ENCRYPTION_KEY", key.decode("ascii"))

    ciphertext = encryption.encrypt("provider-secret")

    assert ciphertext != "provider-secret"
    assert Fernet(key).decrypt(ciphertext.encode("ascii")) == b"provider-secret"
    assert encryption.decrypt(ciphertext) == "provider-secret"


def test_encrypt_derives_key_from_api_key(monkeypatch):
    api_key = "development-api-key"
    monkeypatch.delenv("WANWEI_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("WANWEI_API_KEY", api_key)
    derived_key = base64.urlsafe_b64encode(
        hashlib.sha256(api_key.encode("utf-8")).digest()
    )

    ciphertext = encryption.encrypt("derived-secret")

    assert Fernet(derived_key).decrypt(ciphertext.encode("ascii")) == b"derived-secret"
    assert encryption.decrypt(ciphertext) == "derived-secret"


def test_invalid_explicit_encryption_key_fails_closed(monkeypatch):
    monkeypatch.setenv("WANWEI_ENCRYPTION_KEY", "not-a-fernet-key")
    monkeypatch.setenv("WANWEI_API_KEY", "must-not-be-used")

    with pytest.raises(RuntimeError, match="WANWEI_ENCRYPTION_KEY"):
        encryption.encrypt("provider-secret")


def test_non_ascii_explicit_encryption_key_fails_closed(monkeypatch):
    monkeypatch.setenv("WANWEI_ENCRYPTION_KEY", "not-a-key-\u5bc6\u94a5")

    with pytest.raises(RuntimeError, match="WANWEI_ENCRYPTION_KEY"):
        encryption.encrypt("provider-secret")


def test_decrypt_legacy_base64_raises_and_migrates(monkeypatch):
    """02-#4：旧 base64 明文不再静默返回——显式报错，一次性迁移后可回环。"""
    monkeypatch.setenv("WANWEI_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    legacy_ciphertext = base64.b64encode(b"legacy-secret").decode("ascii")

    with pytest.raises(encryption.LegacyCiphertextError, match="migrate_legacy_ciphertext"):
        encryption.decrypt(legacy_ciphertext)

    migrated = encryption.migrate_legacy_ciphertext(legacy_ciphertext)
    assert encryption.decrypt(migrated) == "legacy-secret"


def test_decrypt_invalid_value_returns_empty_string(monkeypatch):
    monkeypatch.setenv("WANWEI_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))

    assert encryption.decrypt("not encrypted data") == ""


def test_startup_check_fails_closed_in_production_without_key(monkeypatch):
    monkeypatch.setenv("WANWEI_PRODUCTION", "1")
    monkeypatch.delenv("WANWEI_ENCRYPTION_KEY", raising=False)

    with pytest.raises(RuntimeError, match="WANWEI_ENCRYPTION_KEY"):
        encryption.startup_check()


def test_startup_check_passes_in_production_with_valid_key(monkeypatch):
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("WANWEI_PRODUCTION", "1")
    monkeypatch.setenv("WANWEI_ENCRYPTION_KEY", key)

    # 不应抛错
    encryption.startup_check()


def test_startup_check_noop_in_non_production_without_key(monkeypatch):
    monkeypatch.delenv("WANWEI_PRODUCTION", raising=False)
    monkeypatch.delenv("WANWEI_ENCRYPTION_KEY", raising=False)

    # 非生产环境允许派生密钥，不应抛错
    encryption.startup_check()
