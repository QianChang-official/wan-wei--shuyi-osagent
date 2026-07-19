"""API key authentication with fail-closed security.

- WANWEI_API_KEY env variable sets the API key.
- In production (WANWEI_PRODUCTION=1/true/yes), API key is REQUIRED.
- In dev mode, defaults to 'wanwei-dev-key' if not set.
- Uses constant-time comparison to prevent timing attacks.
- Protects sensitive GET endpoints (audit logs, memory search, workflow runs).
"""
from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path
from typing import Callable

from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


MIN_PRODUCTION_API_KEY_LENGTH = 32


def is_production_mode() -> bool:
    """Check if running in production mode."""
    return os.getenv("WANWEI_PRODUCTION", "").strip().lower() in {"1", "true", "yes"}


def get_api_key() -> str:
    """Get API key with fail-closed security."""
    key = os.getenv("WANWEI_API_KEY")
    if key is not None:
        key = key.strip()
    key_file = os.getenv("WANWEI_API_KEY_FILE")
    if not key and key_file:
        try:
            key = Path(key_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError("Unable to read WANWEI_API_KEY_FILE.") from exc

    if is_production_mode():
        if not key:
            raise RuntimeError(
                "WANWEI_PRODUCTION=1 requires WANWEI_API_KEY to be set. "
                "Set a strong API key in production environment."
            )
        if len(key) < MIN_PRODUCTION_API_KEY_LENGTH:
            raise RuntimeError(
                f"WANWEI_API_KEY must contain at least {MIN_PRODUCTION_API_KEY_LENGTH} "
                "characters in production mode."
            )

    if not key:
        return "wanwei-dev-key"

    return key

_PUBLIC_PATHS = {
    "/health",
    "/health/live",
    "/health/ready",
    "/",
    "/console",
    # 开发文档端点：生产模式下这些路径本就不存在（返回 404），
    # 加入公开名单避免默认保护策略把它们变成 401，干扰「生产禁用文档」探测。
    "/docs",
    "/redoc",
    "/openapi.json",
}
_PUBLIC_PREFIXES = ("/console/",)
_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# 历史清单（v0.9.4 之前的敏感 GET 黑名单）。v0.11 起策略已反转为
# 「默认保护 + 显式公开白名单」，本清单仅作文档留存。
_PROTECTED_GET_PATHS = frozenset(
    {
        "/audit/logs",
        "/memory/v2/capsules",
        "/memory/v2/search",
        "/memory/events",
        "/memory/search",
        "/kylin/sdk/status",
        "/metrics",
        "/workflow/stats",
        "/model-gateway/configs",
    }
)
_PROTECTED_GET_PREFIXES = (
    "/memory/v2/capsules/",
    "/workflow/runs",
    "/console-legacy",
)


def _is_public_path(path: str) -> bool:
    if path in _PUBLIC_PATHS:
        return True
    return path.startswith(_PUBLIC_PREFIXES)


def is_public_path(path: str) -> bool:
    """公开白名单判定。

    「哪些路径无需鉴权」的单一事实来源：APIKeyMiddleware 与
    RateLimitMiddleware（保护性 GET 限流面）共用，避免两份手工清单漂移。
    """
    return _is_public_path(path)


def _is_protected_get(method: str, path: str) -> bool:
    """Fail-closed: 除显式公开路径外，所有 GET 均要求鉴权。"""
    if method != "GET":
        return False
    return not _is_public_path(path)


def _verify_api_key(provided_key: str | None) -> bool:
    """Constant-time API key comparison to prevent timing attacks."""
    if not provided_key:
        return False
    api_key = get_api_key()
    try:
        return secrets.compare_digest(provided_key, api_key)
    except TypeError:
        # compare_digest 只接受 ASCII 字符串；带非 ASCII 字符的 X-API-Key
        # 会抛 TypeError。按认证失败（401）处理，不让异常冒泡成 500。
        return False


class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):
        if _is_public_path(request.url.path):
            return await call_next(request)

        # Check if auth required: 写方法 或 任何非公开 GET
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
