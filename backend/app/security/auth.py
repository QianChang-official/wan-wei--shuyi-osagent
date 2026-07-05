"""API key authentication with fail-closed security.

- WANWEI_API_KEY env variable sets the API key.
- In production (WANWEI_PRODUCTION=1), API key is REQUIRED.
- In dev mode, defaults to 'wanwei-dev-key' if not set.
- Uses constant-time comparison to prevent timing attacks.
- Protects sensitive GET endpoints (audit logs, memory search, workflow runs).
"""
from __future__ import annotations

import logging
import os
import secrets
from typing import Callable

from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


def is_production_mode() -> bool:
    """Check if running in production mode."""
    return os.getenv("WANWEI_PRODUCTION", "").strip() == "1"


def get_api_key() -> str:
    """Get API key with fail-closed security."""
    key = os.getenv("WANWEI_API_KEY")

    if is_production_mode() and not key:
        raise RuntimeError(
            "WANWEI_PRODUCTION=1 requires WANWEI_API_KEY to be set. "
            "Set a strong API key in production environment."
        )

    if not key:
        return "wanwei-dev-key"

    return key

_PUBLIC_PATHS = {"/health", "/", "/console", "/console-legacy"}
_PUBLIC_PREFIXES = ("/console/", "/console-legacy/")
_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Sensitive GET endpoints that require authentication
_PROTECTED_GET_PATHS = {
    "/audit/logs",
    "/memory/v2/capsules",
    "/memory/v2/search",
    "/memory/events",
    "/memory/search",
}
_PROTECTED_GET_PREFIXES = (
    "/workflow/runs",
)


def _is_public_path(path: str) -> bool:
    if path in _PUBLIC_PATHS:
        return True
    return path.startswith(_PUBLIC_PREFIXES)


def _is_protected_get(method: str, path: str) -> bool:
    """Check if GET request to sensitive endpoint requires auth."""
    if method != "GET":
        return False
    if path in _PROTECTED_GET_PATHS:
        return True
    return path.startswith(_PROTECTED_GET_PREFIXES)


def _verify_api_key(provided_key: str | None) -> bool:
    """Constant-time API key comparison to prevent timing attacks."""
    if not provided_key:
        return False
    api_key = get_api_key()
    return secrets.compare_digest(provided_key, api_key)


class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):
        if _is_public_path(request.url.path):
            return await call_next(request)

        # Check if auth required
        needs_auth = (
            request.method in _WRITE_METHODS or
            _is_protected_get(request.method, request.url.path)
        )

        if needs_auth:
            header_key = request.headers.get("x-api-key")
            if not _verify_api_key(header_key):
                return JSONResponse(
                    {"detail": "Missing or invalid X-API-Key"},
                    status_code=status.HTTP_401_UNAUTHORIZED
                )

        return await call_next(request)


def require_api_key(request: Request):
    """Legacy function for manual key checks in endpoints."""
    api_key = get_api_key()
    header_key = request.headers.get("x-api-key")
    if header_key != api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid X-API-Key")
