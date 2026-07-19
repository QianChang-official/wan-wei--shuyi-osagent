"""Field-level encryption for stored secrets (Fernet: AES-128-CBC + HMAC).

Key resolution order:
1. ``WANWEI_ENCRYPTION_KEY`` — dedicated 32-byte base64url Fernet key. This is
   the ONLY accepted source in production (``WANWEI_PRODUCTION=1``): deriving
   the field-encryption key from the API key is refused there, because the dev
   default API key (``wanwei-dev-key``) is a public constant, which would make
   every stored ciphertext trivially decryptable.
2. Non-production fallback — PBKDF2-HMAC-SHA256 over the API key with a
   domain-separated salt (keeps dev/test zero-config). A warning is logged
   once per process, since this fallback is only acceptable for local
   development. Production must use the dedicated key above.

Ciphertext contract (v0.11+):
- ``decrypt()`` accepts genuine Fernet tokens only (HMAC integrity checked).
- Legacy pre-Fernet values (raw base64 of the plaintext, no encryption, no
  integrity) are NEVER returned as plaintext anymore: ``decrypt()`` raises
  :class:`LegacyCiphertextError` with migration guidance. Run a one-time
  migration with :func:`migrate_legacy_ciphertext`, which re-encrypts to the
  current Fernet format (callers that version their storage keep it behind
  the ``enc:v1:`` prefix).
- Wrong-key / corrupted values return ``""`` so existing explicit failure
  paths keep working (e.g. model-gateway "Stored API key cannot be
  decrypted"); they are never silently mistaken for plaintext either.
"""
from __future__ import annotations

import base64
import logging
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from .auth import get_api_key, is_production_mode

logger = logging.getLogger(__name__)


class DecryptionError(ValueError):
    """A ciphertext value must not be treated as plaintext."""


class LegacyCiphertextError(DecryptionError):
    """The stored value is pre-Fernet legacy base64 plaintext."""


_derived_key_warning_emitted = False


# Keep the development fallback deterministic across restarts while using a
# password KDF and an application-specific derivation context. Production
# deployments must provide a dedicated random Fernet key instead.
_DEV_DERIVATION_SALT = b"wanwei.field-encryption.v1"
_DEV_DERIVATION_ITERATIONS = 600_000


def _derive_development_key(api_key: str) -> bytes:
    """Derive a Fernet key from a development API key with a password KDF."""
    derived = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_DEV_DERIVATION_SALT,
        iterations=_DEV_DERIVATION_ITERATIONS,
    ).derive(api_key.encode("utf-8"))
    return base64.urlsafe_b64encode(derived)


def _get_fernet() -> Fernet:
    configured_key = os.getenv("WANWEI_ENCRYPTION_KEY", "").strip()
    if not configured_key:
        if is_production_mode():
            raise RuntimeError(
                "WANWEI_ENCRYPTION_KEY must be set when WANWEI_PRODUCTION=1. "
                "Deriving the field-encryption key from the API key is refused "
                "in production (the dev default API key is a public constant)."
            )
        global _derived_key_warning_emitted
        if not _derived_key_warning_emitted:
            _derived_key_warning_emitted = True
            logger.warning(
                "WANWEI_ENCRYPTION_KEY is not set; deriving the field-encryption "
                "key from the API key. Acceptable only for local dev/test — set "
                "WANWEI_ENCRYPTION_KEY for any real deployment."
            )
        return Fernet(_derive_development_key(get_api_key()))

    try:
        return Fernet(configured_key.encode("ascii"))
    except (UnicodeEncodeError, TypeError, ValueError) as exc:
        raise RuntimeError(
            "WANWEI_ENCRYPTION_KEY must be a 32-byte base64url-encoded Fernet key."
        ) from exc


def startup_check() -> None:
    """启动期硬校验：生产模式下必须已配置合法的 WANWEI_ENCRYPTION_KEY。

    在首次使用加密前主动触发，确保生产环境启动即失败（fail-closed），
    而不是等到第一次写入/读取密文时才暴露密钥缺失。
    """
    if is_production_mode():
        # 强制初始化一次；缺失或非法密钥会在这里直接抛出
        _get_fernet()


def encrypt(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def _decode_legacy_plaintext(ciphertext: str) -> str | None:
    """Return the plaintext of a pre-Fernet legacy value, or None.

    Legacy values were stored as plain base64(utf-8 plaintext). Anything that
    is not cleanly base64+UTF-8 (corrupted Fernet tokens, arbitrary garbage)
    is not a legacy value and returns None.
    """
    candidate = ciphertext.strip()
    if not candidate:
        return None
    try:
        decoded = base64.b64decode(candidate.encode("ascii"), validate=True)
        return decoded.decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError, ValueError):
        return None


def decrypt(ciphertext: str) -> str:
    """Decrypt a Fernet token. Never returns unprotected plaintext.

    Raises:
        LegacyCiphertextError: the value is legacy base64-encoded plaintext
            (pre-Fernet storage without integrity protection). Migrate it once
            via :func:`migrate_legacy_ciphertext` and persist the result, or
            re-enter the secret; it is no longer returned as-is.

    Returns ``""`` for values that are neither valid Fernet tokens nor legacy
    plaintext (wrong key / corruption), so callers keep their existing
    explicit failure paths instead of an unauthenticated plaintext oracle.
    """
    try:
        return _get_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        pass

    if _decode_legacy_plaintext(ciphertext) is not None:
        raise LegacyCiphertextError(
            "Stored value is legacy base64-encoded plaintext without integrity "
            "protection and is no longer returned as-is. Re-encrypt it once via "
            "security.encryption.migrate_legacy_ciphertext() and persist the "
            "result (behind the 'enc:v1:' prefix where the caller uses one), "
            "or re-enter the secret."
        )
    return ""


def migrate_legacy_ciphertext(value: str) -> str:
    """One-time migration helper: legacy base64 plaintext -> Fernet token.

    Idempotent: values that already are valid Fernet tokens under the current
    key are returned unchanged. Raises :class:`DecryptionError` for values
    that are neither (nothing trustworthy to migrate; re-enter the secret).
    """
    try:
        _get_fernet().decrypt(value.encode("utf-8"))
        return value
    except InvalidToken:
        pass
    legacy_plaintext = _decode_legacy_plaintext(value)
    if legacy_plaintext is None:
        raise DecryptionError(
            "Value is neither a valid Fernet token nor legacy base64 plaintext; "
            "it cannot be migrated and the secret must be re-entered."
        )
    return encrypt(legacy_plaintext)
