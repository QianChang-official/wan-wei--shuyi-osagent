"""API key authentication with fail-closed security.

- WANWEI_API_KEY env variable sets the API key.
- Resolution order is self-bootstrapping (issue #45, P1):
  1. ``WANWEI_API_KEY`` env var;
  2. ``WANWEI_API_KEY_FILE`` file;
  3. platform default path (``$WANWEI_PLATFORM_DIR/../api-key`` or
     ``XDG_CONFIG_HOME/wanwei-shuyi-desktop/api-key``, where the desktop
     shell persists its generated key);
  4. when all sources are missing, auto-generate ``secrets.token_hex(24)``
     and persist it at the platform default path with 0600 permissions.
- ``WANWEI_PRODUCTION`` no longer hard-blocks startup on a missing/short key:
  the auto-generated 48-hex key satisfies the previous strength requirement
  by construction; a short explicit key only downgrades to a WARNING log.
- Loopback exemption (P1-3/4): when ``WANWEI_HOST`` is a loopback address and
  the request peer is 127.0.0.1/::1 with no ``X-Forwarded-For`` header, the
  API key is not required, unless ``WANWEI_REQUIRE_KEY_ON_LOOPBACK=1``.
  Non-loopback binding stays fail-closed and logs a WARNING at startup.
- Uses constant-time comparison to prevent timing attacks.
- Protects sensitive GET endpoints (audit logs, memory search, workflow runs).
"""
from __future__ import annotations

import hashlib
import ipaddress
import logging
import os
import secrets
import sys
from functools import lru_cache
from pathlib import Path
from typing import Callable

from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


logger = logging.getLogger(__name__)

MIN_PRODUCTION_API_KEY_LENGTH = 32
# blake2b 要求 salt 恰为 16 字节；"wanwei-owner-v1!" 恰好 16 字节。
_ACTOR_ID_SALT = b"wanwei-owner-v1!"


@lru_cache(maxsize=1024)
def actor_id_from_api_key(api_key: str) -> str:
    """Derive the stable, non-reversible owner ID shared by protected APIs.

    Valid API keys are high-entropy values and repeat across requests. Caching
    avoids paying the KDF cost on every authenticated Soul, memory, and agent
    operation while retaining the existing identifier.

    PF-1 (issue #45): single-machine single-user deployments do not need an
    offline-brute-force-resistant KDF. Replacing scrypt (n=2^14, r=8,
    maxmem=64MB per miss) with blake2b cuts the per-miss cost from ~100ms to
    microseconds, and maxsize is raised to 1024 so a multi-key rotation no
    longer thrashes the cache.
    """
    normalized = api_key.strip()
    if not normalized:
        raise ValueError("api_key must not be empty")
    # 说明（CodeQL py/weak-sensitive-data-hashing）：这里不是密码哈希。
    # 输入是 secrets.token_hex(24)（96 bit 熵）级别的 API key，输出仅用作
    # 稳定、不可逆的 actor 标识符，不用于凭据校验（校验走 compare_digest
    # 明文常量时间比较）。高熵输入下离线暴力破解不成立，因此无需
    # scrypt/argon2 这类计算昂贵 KDF；相反 KDF 会给每次请求加 ~100ms。
    digest = hashlib.blake2b(  # noqa: S324  # nosec B324
        normalized.encode("utf-8"),
        digest_size=12,
        salt=_ACTOR_ID_SALT,
    ).digest()
    return "api_" + digest.hex()


def is_production_mode() -> bool:
    """Check if running in production mode."""
    return os.getenv("WANWEI_PRODUCTION", "").strip().lower() in {"1", "true", "yes"}


def _platform_api_key_paths() -> list[Path]:
    """Platform default API-key file candidates, in priority order.

    Mirrors the desktop shell's persistence location so any launch method
    (bare uvicorn, systemd, container) reuses the key the desktop generated.
    """
    candidates: list[Path] = []
    platform_dir = os.environ.get("WANWEI_PLATFORM_DIR", "").strip()
    if platform_dir:
        candidates.append(Path(platform_dir).resolve().parent / "api-key")
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "").strip()
        if appdata:
            candidates.append(Path(appdata) / "wanwei-shuyi-desktop" / "api-key")
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
        base = Path(xdg) if xdg else Path.home() / ".config"
        candidates.append(base / "wanwei-shuyi-desktop" / "api-key")
    return candidates


def _load_platform_api_key() -> str | None:
    for path in _platform_api_key_paths():
        try:
            if path.is_file():
                key = path.read_text(encoding="utf-8").strip()
                if key:
                    return key
        except OSError:
            continue
    return None


def _persist_platform_api_key(key: str) -> Path | None:
    """Persist an auto-generated key at the platform default path (0600).

    Persistence failure must never block startup: the key is still returned
    in-memory (self-healing per process) and the failure is logged.
    """
    for path in _platform_api_key_paths():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(key + "\n", encoding="utf-8")
            try:
                path.chmod(0o600)
            except OSError:
                # Windows 上 chmod 仅只读位有效；尽力而为，不构成权限保证。
                pass
            return path
        except OSError as exc:
            logger.warning(
                "unable to persist auto-generated API key to %s: %s",
                path,
                exc,
            )
            continue
    return None


_AUTO_GENERATED_API_KEY: str | None = None


def _auto_generate_api_key() -> str:
    """Generate a 48-hex key and cache it for the process lifetime.

    The in-process cache is what keeps verification self-consistent: without
    it every ``_verify_api_key`` call would derive a fresh key and all
    authentication would fail.
    """
    global _AUTO_GENERATED_API_KEY
    if _AUTO_GENERATED_API_KEY is None:
        key = secrets.token_hex(24)
        _persist_platform_api_key(key)
        _AUTO_GENERATED_API_KEY = key
    return _AUTO_GENERATED_API_KEY


def get_api_key() -> str:
    """Get API key with fail-closed security and self-bootstrapping.

    Resolution order: env var -> ``WANWEI_API_KEY_FILE`` -> platform default
    path -> auto-generate + persist (0600). Any launch method therefore
    self-heals instead of silently falling back to a public dev constant.
    """
    key = os.getenv("WANWEI_API_KEY")
    if key is not None:
        key = key.strip()

    if not key:
        key_file = os.getenv("WANWEI_API_KEY_FILE")
        if key_file:
            try:
                key = Path(key_file).read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise RuntimeError("Unable to read WANWEI_API_KEY_FILE.") from exc

    if not key:
        key = _load_platform_api_key()

    if not key:
        key = _auto_generate_api_key()

    if len(key) < MIN_PRODUCTION_API_KEY_LENGTH:
        logger.warning(
            "WANWEI_API_KEY is shorter than %d characters; use a stronger "
            "key for any non-loopback deployment.",
            MIN_PRODUCTION_API_KEY_LENGTH,
        )

    return key


def _is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host.lower() == "localhost"


def _is_loopback_bound() -> bool:
    """Whether ``WANWEI_HOST`` binds a loopback address (default 127.0.0.1)."""
    host = os.getenv("WANWEI_HOST", "127.0.0.1").strip().lower()
    return host in {"127.0.0.1", "localhost", "::1"}


def _loopback_exempt_enabled() -> bool:
    """回环免密是否启用。

    默认开启（单机自用即插即用），但以下任一情形视为"运维方明确要求鉴权"，
    免密必须让位给 fail-closed 路径：

    1. ``WANWEI_REQUIRE_KEY_ON_LOOPBACK`` 显式打开；
    2. ``WANWEI_PRODUCTION`` 生产模式；
    3. 显式提供了密钥来源（``WANWEI_API_KEY`` / ``WANWEI_API_KEY_FILE``）——
       用户特意配了密钥，就是想让它被校验，而非被绕过。

    自举生成的密钥不算"显式提供"，所以裸启动仍然免密可用。
    """
    if os.getenv("WANWEI_REQUIRE_KEY_ON_LOOPBACK", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        return False
    if is_production_mode():
        return False
    if os.getenv("WANWEI_API_KEY", "").strip() or os.getenv(
        "WANWEI_API_KEY_FILE", ""
    ).strip():
        return False
    return True


def warn_if_exposed_bind() -> None:
    """Log a WARNING when the backend binds beyond loopback (P1-4)."""
    if not _is_loopback_bound():
        logger.warning(
            "WANWEI_HOST=%s is not a loopback address: the API is exposed "
            "beyond this machine and API-key auth is enforced for all clients.",
            os.getenv("WANWEI_HOST", "127.0.0.1"),
        )


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
    """Fail-closed: 除显式公开路径外，所有 GET/HEAD 均要求鉴权。

    HEAD 是无响应体的 GET，Starlette 会为声明了 GET 的路由自动接受 HEAD。
    若不一并纳入保护判定，HEAD 请求会同时绕过鉴权与保护性 GET 限流。
    """
    if method not in {"GET", "HEAD"}:
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


def _request_is_loopback_exempt(request: Request) -> bool:
    """回环免密判定（P1-3）。

    仅当同时满足：明确绑定回环、对端为回环、无代理头、未显式关闭免密。
    任一条件不满足都回到 fail-closed 鉴权路径。
    """
    if not _loopback_exempt_enabled():
        return False
    if not _is_loopback_bound():
        return False
    if request.headers.get("x-forwarded-for"):
        # 存在代理头时 client.host 不可信，不得免密。
        return False
    return _is_loopback_host(request.client.host if request.client else None)


class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):
        if _is_public_path(request.url.path):
            return await call_next(request)

        # Check if auth required: 写方法 或 任何非公开 GET/HEAD
        needs_auth = (
            request.method in _WRITE_METHODS or
            _is_protected_get(request.method, request.url.path)
        )

        if needs_auth and not _request_is_loopback_exempt(request):
            header_key = request.headers.get("x-api-key")
            if not _verify_api_key(header_key):
                return JSONResponse(
                    {"detail": "Missing or invalid X-API-Key"},
                    status_code=status.HTTP_401_UNAUTHORIZED
                )

        return await call_next(request)
