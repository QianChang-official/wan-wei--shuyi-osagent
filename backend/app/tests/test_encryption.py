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


def test_decrypt_reads_legacy_base64(monkeypatch):
    monkeypatch.setenv("WANWEI_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    legacy_ciphertext = base64.b64encode(b"legacy-secret").decode("ascii")

    assert encryption.decrypt(legacy_ciphertext) == "legacy-secret"


def test_decrypt_invalid_value_returns_empty_string(monkeypatch):
    monkeypatch.setenv("WANWEI_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))

    assert encryption.decrypt("not encrypted data") == ""
