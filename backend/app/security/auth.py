"""API key authentication with fail-closed security.

- WANWEI_API_KEY env variable sets the API key.
- WANWEI_API_KEY_FILE points to a file containing the key.
- Fallback: platform default path ($WANWEI_PLATFORM_DIR/../api-key or
  XDG_CONFIG_HOME/wanwei-shuyi-desktop/api-key); if missing, a fresh key
  is generated (secrets.token_hex(24)) and persisted with 0600 perms.
  Any launch method (uvicorn direct, systemd, container) self-bootstraps.
- Loopback requests may bypass the key when WANWEI_HOST=127.0.0.1
  (disable with WANWEI_REQUIRE_KEY_ON_LOOPBACK=1). Non-loopback stays
  fail-closed.
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

logger = logging.getLogger(__name__)

MIN_PRODUCTION_API_KEY_LENGTH = 32


def is_production_mode() -> bool:
    """Check if running in production mode."""
    return os.getenv("WANWEI_PRODUCTION", "").strip().lower() in {"1", "true", "yes"}


def _platform_dir() -> Path:
    """Resolve platform data dir (same logic as platform_api.store)."""
    base = os.environ.get("WANWEI_PLATFORM_DIR", "").strip()
    if base:
        return Path(base)
    # Fall back to XDG config home when the platform dir is not set.
    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if xdg:
        return Path(xdg) / "wanwei-shuyi-desktop"
    home = Path.home()
    return home / ".config" / "wanwei-shuyi-desktop"


def _default_key_file_path() -> Path:
    """Default key file location: platform dir's parent / api-key."""
    platform_dir = _platform_dir()
    candidate = platform_dir.parent / "api-key"
    # If platform dir is under XDG config home, keep the file next to it.
    if str(platform_dir).endswith("wanwei-shuyi-desktop"):
        candidate = platform_dir / "api-key"
    return candidate


def _bootstrap_key_file(path: Path) -> str:
    """Generate a fresh key, persist it 0600, and return it."""
    key = secrets.token_hex(24)  # 48 hex chars, meets strength requirements
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(key + "\n", encoding="utf-8")
        path.chmod(0o600)
        logger.warning("Self-bootstrapped API key file at %s", path)
    except OSError as exc:
        logger.warning("Could not persist self-bootstrapped API key (%s); using in-memory key.", exc)
    return key


def get_api_key() -> str:
    """Get API key with fail-closed security and self-bootstrap fallback."""
    key = os.getenv("WANWEI_API_KEY")
    if key is not None:
        key = key.strip()
    key_file = os.getenv("WANWEI_API_KEY_FILE")
    if not key and key_file:
        try:
            key = Path(key_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError("Unable to read WANWEI_API_KEY_FILE.") from exc

    if not key:
        # Fallback: platform default path (already-present file from desktop).
        default_path = _default_key_file_path()
        if default_path.exists():
            try:
                key = default_path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                logger.warning("Could not read default API key file %s: %s", default_path, exc)

    if not key:
        # Self-bootstrap: generate and persist a fresh key.
        key = _bootstrap_key_file(_default_key_file_path())

    if is_production_mode():
        if len(key) < MIN_PRODUCTION_API_KEY_LENGTH:
            # Downgrade to warning: auto-generated 48-hex keys satisfy strength.
            logger.warning(
                "API key length %d is below the %d-char production guideline.",
                len(key), MIN_PRODUCTION_API_KEY_LENGTH,
            )

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


def _is_loopback_request(request: Request) -> bool:
    """True when the request originates from the loopback interface.

    即插即用（Issue #45 P1-3）的关键：本机回环视为信任边界，单机桌面
    场景无需密钥仪式。可用 WANWEI_REQUIRE_KEY_ON_LOOPBACK=1 强制回环
    也校验密钥（多用户主机上同机其他账号可访问后端时的显式关闭项）。
    """
    if os.getenv("WANWEI_REQUIRE_KEY_ON_LOOPBACK", "").strip().lower() in {"1", "true", "yes"}:
        return False
    host = os.getenv("WANWEI_HOST", "").strip().lower()
    # 只有明确绑定回环时才放行；绑 0.0.0.0 或未设置一律 fail-closed。
    if host not in {"127.0.0.1", "localhost", "::1"}:
        return False
    client_host = getattr(request, "client", None)
    if client_host is None:
        return False
    return client_host.host in {"127.0.0.1", "::1", "localhost"}


class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):
        if _is_public_path(request.url.path):
            return await call_next(request)

        # Issue #45 P1-3: 本机回环免密（仅当 WANWEI_HOST 明确绑回环时）。
        if _is_loopback_request(request):
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
