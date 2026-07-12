from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken

from .auth import get_api_key


def _get_fernet() -> Fernet:
    configured_key = os.getenv("WANWEI_ENCRYPTION_KEY", "").strip()
    if not configured_key:
        derived_key = base64.urlsafe_b64encode(
            hashlib.sha256(get_api_key().encode("utf-8")).digest()
        )
        return Fernet(derived_key)

    try:
        return Fernet(configured_key.encode("ascii"))
    except (UnicodeEncodeError, TypeError, ValueError) as exc:
        raise RuntimeError(
            "WANWEI_ENCRYPTION_KEY must be a 32-byte base64url-encoded Fernet key."
        ) from exc


def encrypt(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(ciphertext: str) -> str:
    try:
        return _get_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        pass

    try:
        return base64.b64decode(
            ciphertext.encode("ascii"), validate=True
        ).decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError, ValueError):
        return ""
