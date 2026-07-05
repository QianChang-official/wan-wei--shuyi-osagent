"""Minimal API key authentication gate.

- WANWEI_API_KEY env variable sets the production key.
- Health, static /console, and top-level / are always public.
- All write/delete/model-gateway/workflow endpoints require X-API-Key.
- If WANWEI_API_KEY is unset, authentication is bypassed (dev mode) but a warning is logged.
"""
from __future__ import annotations

import logging
import os
from typing import Callable

from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


_API_KEY = os.getenv("WANWEI_API_KEY")
if _API_KEY is None:
    logging.warning("WANWEI_API_KEY is not set; API authentication is disabled (dev mode).")

_PUBLIC_PATHS = {"/health", "/", "/console", "/console-legacy"}
_PUBLIC_PREFIXES = ("/console/", "/console-legacy/")
_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _is_public_path(path: str) -> bool:
    if path in _PUBLIC_PATHS:
        return True
    return path.startswith(_PUBLIC_PREFIXES)


class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):
        if _API_KEY is None:
            return await call_next(request)
        if _is_public_path(request.url.path):
            return await call_next(request)
        if request.method in _WRITE_METHODS:
            header_key = request.headers.get("x-api-key")
            if header_key != _API_KEY:
                return JSONResponse({"detail": "Missing or invalid X-API-Key"}, status_code=status.HTTP_401_UNAUTHORIZED)
        return await call_next(request)


def require_api_key(request: Request):
    if _API_KEY is None:
        return
    header_key = request.headers.get("x-api-key")
    if header_key != _API_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid X-API-Key")  # endpoints can raise
