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
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections.abc import Callable
from urllib.parse import urlsplit

from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


logger = logging.getLogger(__name__)

MIN_PRODUCTION_API_KEY_LENGTH = 32
LAN_VERIFY_PATH = "/platform/system/lan/verify"
_LAN_SESSION_EXACT_PATHS = {
    ("GET", "/platform/agents/runs"),
    ("GET", "/platform/agents/context-size"),
    ("POST", "/platform/agents/chat"),
    ("POST", "/platform/memory/dreams/archive-now"),
    ("GET", "/platform/system/power"),
    ("PUT", "/platform/system/power"),
    ("GET", "/platform/mobile/events"),
    ("GET", "/platform/mobile/tool-calls"),
    ("GET", "/platform/mobile/list"),
    ("POST", "/platform/mobile/upload"),
}
# blake2b 要求 salt 恰为 16 字节；"wanwei-owner-v1!" 恰好 16 字节。
_ACTOR_ID_SALT = b"wanwei-owner-v1!"


def _api_key_hash(api_key: str) -> str:
    """API key 的不可逆哈希（用于 identity 表查询，不存储明文 key）。

    说明（CodeQL py/weak-sensitive-data-hashing）：SHA-256 在这里不是密码哈希，
    而是高熵 API key（secrets.token_hex(24)，96 bit 熵）的确定性索引。
    输入空间足够大，离线暴力破解不成立；输出仅用于 identity 表查询，
    不用于凭据校验（校验走 compare_digest 明文常量时间比较）。
    """
    return hashlib.sha256(api_key.strip().encode("utf-8")).hexdigest()


def _derive_legacy_owner_id(api_key: str) -> str:
    """旧版派生逻辑（blake2b），仅用于向后兼容和 identity 表未命中时的回退。

    说明（CodeQL py/weak-sensitive-data-hashing）：blake2b 在这里不是密码哈希，
    而是高熵 API key（secrets.token_hex(24)，96 bit 熵）的确定性派生。
    输入空间足够大，离线暴力破解不成立；输出仅用作稳定标识符，
    不用于凭据校验（校验走 compare_digest 明文常量时间比较）。
    保留此函数是为了向后兼容：identity 表未建时，既有 agent 行的 owner_id
    仍按此逻辑派生，不因升级而变更。
    """
    digest = hashlib.blake2b(  # noqa: S324  # nosec B324
        api_key.strip().encode("utf-8"),
        digest_size=12,
        salt=_ACTOR_ID_SALT,
    ).digest()
    return "api_" + digest.hex()


def _identity_table_ready() -> bool:
    """检查 identity 表是否已建（init_db 可能尚未运行）。

    只读查询复用线程本地连接，不创建或提交调用方事务。
    """
    from ..db import get_conn

    row = get_conn().execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='identity'"
    ).fetchone()
    return row is not None


def actor_id_from_api_key(api_key: str) -> str:
    """Resolve the stable owner ID for an API key.

    **v0.12 身份层解耦**：owner_id 不再由 API key 直接派生，而是独立 UUID。
    首次使用时自动注册到 identity 表；后续 key 轮换通过 ``rotate_api_key``
    将新 key 映射到同一 identity_id，历史数据不丢失。

    向后兼容：identity 表未建（旧数据库）时回退到旧版 blake2b 派生，
    保证升级过程不中断服务。

    **注册门槛（issue #211）**：自动注册**仅限配置的 owner key**（环境
    变量 / 密钥文件来源，即 ``get_api_key()`` 返回的那把）。其余 key：

    - 已在 identity 表（经 ``rotate_api_key`` 显式注册）→ 返回其 identity；
    - 陌生 key → 返回派生 ID（``_derive_legacy_owner_id``）**但不落库**——
      任何碰过一次服务的 key 不再静默变成永久凭据。个人单 key 使用
      零变化：配置的那把 key 首次使用照常完成身份引导。
    """
    normalized = api_key.strip()
    if not normalized:
        raise ValueError("api_key must not be empty")

    if not _identity_table_ready():
        return _derive_legacy_owner_id(normalized)

    from ..db import _db_path, get_conn
    from ..utils.datetime_utils import utc_now_iso_compact
    import sqlite3
    import uuid

    key_hash = _api_key_hash(normalized)
    row = get_conn().execute(
        "SELECT identity_id FROM identity WHERE api_key_hash=?",
        (key_hash,),
    ).fetchone()
    if row is not None:
        return str(row["identity_id"])

    if not secrets.compare_digest(normalized.encode('utf-8'), get_api_key().encode('utf-8')):
        return _derive_legacy_owner_id(normalized)

    # Only owner bootstrap acquires a write lock; the caller's transaction is
    # never committed or rolled back by identity resolution.
    conn = sqlite3.connect(str(_db_path()), timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT identity_id FROM identity WHERE api_key_hash=?",
            (key_hash,),
        ).fetchone()
        if row is not None:
            conn.commit()
            return str(row["identity_id"])
        identity_id = "id_" + uuid.uuid4().hex[:16]
        conn.execute(
            "INSERT INTO identity(identity_id, api_key_hash, created_at) VALUES (?,?,?)",
            (identity_id, key_hash, utc_now_iso_compact()),
        )
        conn.commit()
        logger.info("identity bootstrap: owner key registered as %s", identity_id)
        return identity_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def rotate_api_key(old_key: str, new_key: str) -> str:
    """轮换 API key：将新 key 映射到旧 key 的 identity，旧 key 标记为已轮换。

    返回 identity_id。旧 key 的 ``is_active`` 置 0，新 key 继承同一身份，
    历史记忆、Soul、账本数据全部保留。

    回滚到曾用过的 key 时，先删除同身份下的 inactive 历史行，释放全局唯一
    key hash；相比 ``INSERT OR REPLACE``，该做法不影响其它列或未来约束语义。
    删除、失效和插入在同一事务中执行，失败时显式回滚，避免留下半完成轮换。
    """
    if not _identity_table_ready():
        raise RuntimeError("identity table not initialized; run init_db first")

    from ..db import _db_path
    from ..utils.datetime_utils import utc_now_iso_compact
    import sqlite3

    old_hash = _api_key_hash(old_key)
    new_hash = _api_key_hash(new_key)

    conn = sqlite3.connect(str(_db_path()), timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT identity_id FROM identity "
            "WHERE api_key_hash=? AND is_active=1",
            (old_hash,),
        ).fetchone()
        if row is None:
            raise KeyError("old key not registered")

        identity_id = str(row["identity_id"])
        owned_by_other = conn.execute(
            "SELECT 1 FROM identity "
            "WHERE api_key_hash=? AND identity_id<>? LIMIT 1",
            (new_hash, identity_id),
        ).fetchone()
        if owned_by_other is not None:
            # Deliberately generic: callers learn neither the other identity nor
            # whether that identity's key is active. Keep the existing database
            # collision exception type for direct callers.
            raise sqlite3.IntegrityError("new key is unavailable")
        if old_hash == new_hash:
            raise sqlite3.IntegrityError("new key is unavailable")

        existing = conn.execute(
            "SELECT is_active FROM identity "
            "WHERE api_key_hash=? AND identity_id=?",
            (new_hash, identity_id),
        ).fetchone()
        # Reusing this identity's own inactive historical key is supported.
        if existing is not None:
            conn.execute(
                "DELETE FROM identity WHERE identity_id=? AND api_key_hash=? "
                "AND is_active=0",
                (identity_id, new_hash),
            )
        conn.execute(
            "UPDATE identity SET is_active=0, rotated_from=? "
            "WHERE api_key_hash=? AND identity_id=?",
            (identity_id, old_hash, identity_id),
        )
        conn.execute(
            "INSERT INTO identity(identity_id, api_key_hash, created_at, rotated_from) "
            "VALUES (?,?,?,?)",
            (identity_id, new_hash, utc_now_iso_compact(), identity_id),
        )
        conn.commit()
        return identity_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def revoke_api_key(
    api_key: str,
    *,
    current_key: str | None = None,
    current_identity_id: str | None = None,
) -> dict:
    """撤销当前 identity 所属的 API key。

    撤销不是管理员接口；在现有身份模型中，只有当前请求主体自己的 key
    可以被吊销。跨 identity 的目标统一按不可用处理，避免泄露 key 注册状态。
    """
    if not _identity_table_ready():
        raise RuntimeError("identity table not initialized; run init_db first")

    normalized = api_key.strip()
    if not normalized:
        raise ValueError("api_key must not be empty")

    # 防自杀：不允许撤销当前请求的 key
    if current_key and normalized == current_key.strip():
        raise ValueError("cannot revoke the key used by the current request")

    from ..db import get_conn

    key_hash = _api_key_hash(normalized)
    conn = get_conn()
    row = conn.execute(
        "SELECT identity_id, is_active FROM identity WHERE api_key_hash=?",
        (key_hash,),
    ).fetchone()
    if not row:
        return {"revoked": False, "reason": "key_not_registered"}
    if not row["is_active"]:
        return {"revoked": False, "reason": "key_already_inactive"}
    if current_identity_id is not None and str(row["identity_id"]) != current_identity_id:
        return {"revoked": False, "reason": "key_not_owned"}

    conn.execute(
        "UPDATE identity SET is_active=0 WHERE api_key_hash=?",
        (key_hash,),
    )
    conn.commit()
    return {
        "revoked": True,
        "identity_id": str(row["identity_id"]),
        "api_key_prefix": normalized[:8] + "…" if len(normalized) > 8 else "***",
    }


def _lan_session_table_ready() -> bool:
    if not _identity_table_ready():
        return False
    from ..db import _db_path

    try:
        conn = sqlite3.connect(str(_db_path()))
        try:
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='lan_sessions'"
            ).fetchone()
            return row is not None
        finally:
            conn.close()
    except Exception:
        return False


def issue_lan_session(identity_id: str, *, ttl_seconds: int) -> tuple[str, str]:
    """Issue a random LAN credential mapped to an existing identity."""
    if not _lan_session_table_ready():
        raise RuntimeError("LAN session table not initialized")
    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be positive")

    from ..db import _db_path
    from ..utils.datetime_utils import utc_now_iso_compact

    credential = "lan_" + secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    conn = sqlite3.connect(str(_db_path()), timeout=5)
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute(
            "INSERT INTO lan_sessions(credential_hash, identity_id, created_at, expires_at) "
            "VALUES (?,?,?,?)",
            (
                _api_key_hash(credential),
                identity_id,
                utc_now_iso_compact(),
                expires_at.isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return credential, expires_at.isoformat()


def revoke_lan_sessions() -> int:
    """Revoke every currently active LAN session credential."""
    if not _lan_session_table_ready():
        return 0
    from ..db import _db_path
    from ..utils.datetime_utils import utc_now_iso_compact

    conn = sqlite3.connect(str(_db_path()), timeout=5)
    try:
        cursor = conn.execute(
            "UPDATE lan_sessions SET revoked_at=? WHERE revoked_at IS NULL",
            (utc_now_iso_compact(),),
        )
        conn.commit()
        return max(cursor.rowcount, 0)
    finally:
        conn.close()


def _lan_session_identity(credential: str) -> str | None:
    """Return the mapped identity only for an active, unexpired LAN session."""
    if not credential.startswith("lan_") or not _lan_session_table_ready():
        return None
    from ..db import _db_path

    conn = sqlite3.connect(str(_db_path()), timeout=5)
    try:
        row = conn.execute(
            "SELECT identity_id, expires_at, revoked_at FROM lan_sessions "
            "WHERE credential_hash=?",
            (_api_key_hash(credential),),
        ).fetchone()
        if row is None or row[2] is not None:
            return None
        try:
            expires_at = datetime.fromisoformat(str(row[1]))
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
        if datetime.now(timezone.utc) >= expires_at:
            return None
        return str(row[0])
    finally:
        conn.close()


def authenticated_identity(api_key: str | None) -> tuple[str | None, bool]:
    """Validate a credential and return ``(identity_id, is_lan_session)``."""
    if not api_key:
        return None, False
    lan_identity = _lan_session_identity(api_key)
    if lan_identity is not None:
        return lan_identity, True
    if _verify_api_key(api_key):
        try:
            return actor_id_from_api_key(api_key), False
        except (TypeError, ValueError):
            return None, False
    return None, False


def _lan_session_path_allowed(method: str, path: str) -> bool:
    if (method, path) in _LAN_SESSION_EXACT_PATHS:
        return True
    if method == "POST" and path.startswith("/platform/agents/runs/"):
        suffix = path.removeprefix("/platform/agents/runs/")
        return suffix.endswith("/approve") and suffix.count("/") == 1
    if path.startswith("/platform/mobile/"):
        suffix = path.removeprefix("/platform/mobile/")
        if method == "GET" and suffix.endswith("/content"):
            return suffix.count("/") == 1
        if method == "DELETE" and suffix:
            return suffix.count("/") == 0
    return False


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


def _argv_option(name: str) -> str | None:
    """从进程参数里取 ``--name value`` / ``--name=value``（uvicorn CLI 路径）。

    issue #211 关联发现：``uvicorn --host 0.0.0.0`` 启动而 ``WANWEI_HOST``
    未设时,回环判定只看环境变量会误判为回环绑定。进程参数是绑定地址的
    事实来源（CLI 部署/sysd 服务都用它）,优先于环境变量声明。
    """
    argv = sys.argv
    for index, arg in enumerate(argv):
        if arg == f"--{name}" and index + 1 < len(argv):
            return argv[index + 1]
        if arg.startswith(f"--{name}="):
            return arg.split("=", 1)[1]
    return None


def _effective_bind_host() -> str:
    """实际绑定地址：进程参数 ``--host`` > ``WANWEI_HOST`` > 127.0.0.1。"""
    return (
        _argv_option("host")
        or os.getenv("WANWEI_HOST", "127.0.0.1").strip()
        or "127.0.0.1"
    )


def _effective_port() -> str:
    """实际监听端口：进程参数 ``--port`` > ``WANWEI_PORT`` > 8010。

    issue #211 关联发现：回环 Origin 白名单端口此前只看 ``WANWEI_PORT``
    (默认 8010),与 ``uvicorn --port 8000`` 的实际监听不符时,同源写请求
    会被 Origin 守卫 403。
    """
    return (
        _argv_option("port")
        or os.getenv("WANWEI_PORT", "8010").strip()
        or "8010"
    )


def _is_loopback_bound() -> bool:
    """Whether the service actually binds a loopback address.

    事实来源优先级：进程参数 ``--host``（uvicorn CLI 实际绑定）>
    ``WANWEI_HOST`` 环境声明 > 默认 127.0.0.1。此前只看环境变量,
    ``--host 0.0.0.0`` 启动而 env 未设时会误判回环 → 回环免密静默生效
    （issue #211）。
    """
    host = _effective_bind_host().lower()
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


def _loopback_exempt_write_allowed() -> bool:
    """回环免密是否覆盖**写方法**（POST/PUT/PATCH/DELETE）。

    与 ``_loopback_exempt_enabled`` 的区别：后者是「是否免密」的总开关，
    本函数是「免密是否包含写操作」的收紧层。

    默认行为：免密**只读**——GET/HEAD 放行（控制台浏览、健康检查即插即用），
    写操作必须带 key。理由：裸启动场景下，本地任意进程（含恶意软件、
    被 XSS 劫持的浏览器标签页）无需凭证即可篡改记忆库，这与「记忆是私产」
    的立项承诺直接冲突；而读操作的暴露面在回环绑定下本就受限于本机进程。

    显式豁免（兼容既有工作流）：
    - ``WANWEI_LOOPBACK_EXEMPT_WRITE=1``：恢复旧行为，写操作也免密。
      供 CI / 本地脚本等「确实需要无凭证写」的场景显式开启，并记 WARNING。
    """
    if os.getenv("WANWEI_LOOPBACK_EXEMPT_WRITE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        logger.warning(
            "WANWEI_LOOPBACK_EXEMPT_WRITE is enabled: loopback write requests "
            "are exempt from API-key auth. This is insecure for any deployment "
            "where untrusted local processes exist."
        )
        return True
    return False


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
    """Constant-time API key comparison to prevent timing attacks.

    v0.12 起：如果 identity 表已建，额外检查该 key 是否仍活跃（未被轮换）。
    轮换后的旧 key 在环境变量层面仍匹配，但在身份层已失效。

    多 key 支持：identity 表已建时，任何活跃 identity 的 key 均可通过鉴权
    （不限于环境变量里的那一个），key 的合法性由 identity 注册表背书。
    """
    if not provided_key:
        return False

    # identity 表已建时，优先查注册表（支持多 key / 轮换后新 key）
    if _identity_table_ready():
        from ..db import _db_path
        import sqlite3 as _sqlite3

        key_hash = _api_key_hash(provided_key)
        conn = _sqlite3.connect(str(_db_path()))
        try:
            row = conn.execute(
                "SELECT is_active FROM identity WHERE api_key_hash=?",
                (key_hash,),
            ).fetchone()
            if row is not None:
                return bool(row[0])  # 活跃则通过，轮换后旧 key 拒绝
        finally:
            conn.close()

    # identity 表未建（旧数据库）或 key 未注册：回退到环境变量比对
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

    收紧（v0.11.1）：免密**只读**。写方法（POST/PUT/PATCH/DELETE）即使命中
    回环免密条件，仍需通过 ``_loopback_exempt_write_allowed`` 显式放行，
    否则回到 fail-closed 鉴权路径。
    """
    if not _loopback_exempt_enabled():
        return False
    if not _is_loopback_bound():
        return False
    if request.headers.get("x-forwarded-for"):
        # 存在代理头时 client.host 不可信，不得免密。
        return False
    if not _is_loopback_host(request.client.host if request.client else None):
        return False
    # 写操作需额外显式放行（默认关闭，见 _loopback_exempt_write_allowed）。
    if request.method in _WRITE_METHODS and not _loopback_exempt_write_allowed():
        return False
    return True


class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):
        path = request.url.path
        if _is_public_path(path):
            return await call_next(request)

        # The one-time pairing token is the sole credential accepted here. Keep
        # this exception exact so no sibling LAN route becomes unauthenticated.
        token_only_verify = request.method == "POST" and path == LAN_VERIFY_PATH

        # Check if auth required: 写方法 或 任何非公开 GET/HEAD
        needs_auth = (
            request.method in _WRITE_METHODS or
            _is_protected_get(request.method, path)
        )
        header_key = request.headers.get("x-api-key")
        owner_id, is_lan_session = authenticated_identity(header_key)

        if (
            needs_auth
            and not token_only_verify
            and owner_id is None
            and (header_key is not None or not _request_is_loopback_exempt(request))
        ):
            return JSONResponse(
                {"detail": "Missing or invalid X-API-Key"},
                status_code=status.HTTP_401_UNAUTHORIZED
            )
        if is_lan_session and not _lan_session_path_allowed(request.method, path):
            return JSONResponse(
                {"detail": "LAN session is not authorized for this endpoint"},
                status_code=status.HTTP_403_FORBIDDEN,
            )

        # Route ownership helpers consume this principal instead of deriving a
        # fresh identity from a short-lived LAN credential.
        request.state.authenticated_identity = owner_id
        request.state.is_lan_session = is_lan_session

        # Bind the authenticated principal for deep audit writes. Public and
        # token-only pairing requests intentionally have no attributed context.
        from ..audit.service import audit_owner_context
        with audit_owner_context(owner_id):
            return await call_next(request)


# ---------------------------------------------------------------------------
# 浏览器攻击面收敛：Origin / Host 校验（反 CSRF + 反 DNS-rebinding）
# ---------------------------------------------------------------------------
#
# 威胁模型：本后端默认绑定 127.0.0.1 且回环免密（见 ``_loopback_exempt_enabled``）。
# 这带来两类经典入向攻击，仅靠 CORS 中间件无法覆盖：
#
# 1. **simple-request CSRF**：恶意网页用 ``<form>`` 或 ``fetch(..., {mode:'no-cors'})``
#    向 ``http://127.0.0.1:8010/...`` 发 POST。Content-Type 为表单或 text/plain 时
#    不触发 CORS 预检，请求直接生效；回环免密下甚至无需 X-API-Key。
# 2. **DNS rebinding**：恶意域名先解析到公网 IP 通过浏览器 SOP 检查，TTL 到期后
#    重新解析到 127.0.0.1，此后同源策略认为与目标同源，响应可被读取。
#
# 防御口径（fail-closed 但零误伤非浏览器客户端）：
#
# - **只对带 ``Origin`` 头的请求做 Origin 校验**。curl / python requests /
#   Electron 主进程 / Starlette TestClient 均不带 ``Origin``，直接放行，走原有
#   API key 逻辑；浏览器发出的导航、同源与跨域写请求**必然带 ``Origin``**。
# - **Host 校验对所有请求生效**，但白名单默认仅含回环与 localhost；TestClient
#   的默认 Host ``testserver`` 通过 ``WANWEI_ALLOWED_HOSTS`` 环境变量补充，
#   不硬编码进白名单，避免把测试值带进生产。
#
# 这不是对 CORS 的替代：CORS 管「浏览器是否被允许读响应」，本模块管
# 「这个请求是否被允许到达路由」。两者叠加才覆盖 simple-request 与 rebinding。


def _loopback_origin_allowlist() -> frozenset[str]:
    """回环部署下被接受的 Origin 白名单（协议 + 主机 + 端口）。

    端口取**实际监听端口**（进程参数 ``--port`` > ``WANWEI_PORT`` > 8010，
    issue #211 关联修复：此前只看 env 默认 8010，与 ``uvicorn --port 8000``
    实际监听不符时同源写请求被 403）；手机伴侣 H5 等跨源前端不在此列——
    它们应通过 ``WANWEI_CORS_ORIGINS`` 显式放行，且走 API key 鉴权，
    与回环免密互不叠加。
    """
    port = _effective_port()
    return frozenset({
        f"http://127.0.0.1:{port}",
        f"http://localhost:{port}",
        f"http://[::1]:{port}",
        f"https://127.0.0.1:{port}",
        f"https://localhost:{port}",
    })


def _allowed_hostnames() -> frozenset[str]:
    configured = {
        h.strip().lower()
        for h in os.getenv("WANWEI_ALLOWED_HOSTS", "").split(",")
        if h.strip()
    }
    return frozenset({"127.0.0.1", "localhost", "::1", *configured})


def _origin_is_allowed(origin: str | None) -> bool:
    """判断浏览器 ``Origin`` 是否可信。

    - ``None``：非浏览器客户端（curl / Electron / TestClient），放行；
      CSRF 与 rebinding 都只在浏览器上下文发生。
    - ``"null"``：sandboxed iframe / file:// 页面 / 重定向链脱敏后的占位。
      在回环免密部署下，``null`` origin 无法与「本地受信前端」区分，
      一律拒绝（fail-closed）；生产模式本就要求显式 key，不受影响。
    - 其他：必须命中回环白名单、显式 CORS 来源，或是当前端口上由
      ``WANWEI_ALLOWED_HOSTS`` 明确列出的本机 LAN 地址。
    """
    if origin is None:
        return True
    normalized = origin.strip().rstrip("/").lower()
    if normalized == "null" or not normalized:
        return False
    if normalized in _loopback_origin_allowlist():
        return True
    extra = {
        o.strip().rstrip("/").lower()
        for o in os.getenv("WANWEI_CORS_ORIGINS", "").split(",")
        if o.strip()
    }
    if normalized in extra:
        return True
    try:
        parsed = urlsplit(normalized)
        parsed_port = parsed.port
        expected_port = int(os.getenv("WANWEI_PORT", "8010").strip() or "8010")
    except (ValueError, TypeError):
        return False
    return (
        parsed.scheme in {"http", "https"}
        and parsed.hostname is not None
        and parsed.hostname.lower() in _allowed_hostnames()
        and parsed_port == expected_port
        and not parsed.username
        and not parsed.password
        and not parsed.path
        and not parsed.query
        and not parsed.fragment
    )


def _host_is_allowed(host_header: str | None) -> bool:
    """判断 ``Host`` 头是否指向本机回环，用于阻断 DNS rebinding。

    rebinding 成功的标志是浏览器把恶意域名当作源站发出请求，此时 ``Host``
    头是恶意域名而非回环地址——直接拒绝即可让响应不被发出。

    白名单来源（按优先级）：
    1. ``WANWEI_ALLOWED_HOSTS`` 环境变量（逗号分隔，含测试用 ``testserver``）；
    2. 回环字面量：``127.0.0.1`` / ``localhost`` / ``::1``（可带端口）。
    """
    if not host_header:
        # 无 Host 的直连（极少见）；没有 Host 就无法判断目标，交给后续鉴权处理。
        return True
    host = host_header.strip().lower()
    # 去掉端口部分（含 IPv6 的 [addr]:port 形式）
    if host.startswith("["):
        host = host[1:host.index("]")] if "]" in host else host
    elif ":" in host:
        host = host.split(":", 1)[0]
    extra = {
        h.strip().lower()
        for h in os.getenv("WANWEI_ALLOWED_HOSTS", "").split(",")
        if h.strip()
    }
    return host in {"127.0.0.1", "localhost", "::1"} or host in extra


class OriginHostGuardMiddleware(BaseHTTPMiddleware):
    """反 CSRF + 反 DNS-rebinding 中间件。

    注册顺序：在 ``APIKeyMiddleware`` **之后** ``add_middleware``（Starlette 后注册
    者更外层，先执行）。这样在鉴权之前就拒绝恶意来源，避免恶意请求消耗鉴权与
    业务逻辑资源，也让 403 语义区别于 401（来源非法，而非凭据缺失）。
    """

    async def dispatch(self, request: Request, call_next: Callable):
        # Host 校验对所有请求生效（rebinding 可读响应，GET 也要挡）。
        if not _host_is_allowed(request.headers.get("host")):
            return JSONResponse(
                {"detail": "Host header is not allowed for this deployment"},
                status_code=status.HTTP_403_FORBIDDEN,
            )
        # Origin 校验只对「带 Origin 的写方法」生效：同源/跨域 GET 读取已被
        # Host 校验与 API key 覆盖，无需重复；写操作是 CSRF 的唯一有效载荷。
        if request.method in _WRITE_METHODS and not _origin_is_allowed(
            request.headers.get("origin")
        ):
            return JSONResponse(
                {"detail": "Origin is not allowed for state-changing requests"},
                status_code=status.HTTP_403_FORBIDDEN,
            )
        return await call_next(request)
