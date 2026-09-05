from __future__ import annotations

import asyncio
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import http.client
import json as jsonlib
import logging
import os
import socket
import sqlite3
import threading
import time
import uuid
from urllib.parse import quote, urlparse

import httpx

logger = logging.getLogger(__name__)

from .schemas import (
    ModelGatewayConfigOut,
    ModelGatewayTestIn,
    ModelGatewayTestOut,
    ModelProvider,
)
from ..db import get_conn, transaction
from ..security import encryption
from ..security.ssrf import (
    SSRFError,
    _hostname_is_blocked,
    resolve_external_url,
    validate_external_url,
)
from ..utils.datetime_utils import utc_now_iso

# 03-#14 配置单源化：WANWEI_OPENAI_COMPATIBLE_* 的 env 解析只在本模块这一处
# 实现。运行时路径（list_providers / run_provider_test / main._chat_complete）
# 一律经下面的访问函数读取，消除「导入期快照与请求期重读各自解析、可漂移」
# 的双源问题；allowlist 解析与超时常量同样收口于此。
# 模块级 LOCAL_LLAMA_* / PROVIDERS 仅作既有调用方的导入期快照兼容保留，
# 运行时代码不得再引用。
def local_llama_settings() -> tuple[str, str, bool]:
    """读取本地 OpenAI 兼容端点配置：(api_base, model, configured)。"""
    base = os.getenv("WANWEI_OPENAI_COMPATIBLE_BASE", "").strip()
    model = os.getenv("WANWEI_OPENAI_COMPATIBLE_MODEL", "").strip()
    return base, model, bool(base and model)


def local_llama_allowlist() -> list[str] | None:
    """SSRF 主机白名单（历史名称保留，语义已泛化）。

    单一事实源在 ``security.ssrf.extra_allowed_hosts()``（推荐名
    ``WANWEI_SSRF_EXTRA_ALLOWED_HOSTS`` + 历史名合并去重）；本函数仅保留
    兼容包装供既有调用方使用。无白名单时返回 None。
    """
    from ..security.ssrf import extra_allowed_hosts

    return extra_allowed_hosts() or None


def active_chat_provider(owner_id: str | None = None) -> dict | None:
    """解析指定主体显式启用的云端 provider（供 /soul/chat 消费）。

    ``owner_id`` 可省略以兼容内部调用，此时使用配置主体；HTTP 调用方应始终
    传入当前请求主体，避免跨主体选择凭据。
    """
    try:
        from ..platform_api.providers import get_active_provider
    except ImportError:  # pragma: no cover - 平台舱缺失的部署形态
        logger.warning("platform providers module unavailable; no active chat provider")
        return None
    return get_active_provider(owner_id=owner_id)


OPENAI_COMPATIBLE_TIMEOUT_S = 20
# Preserve the previous four-request admission ceiling while splitting it into
# two isolated network workers plus two queued jobs. This avoids increasing the
# number of request workers waiting for a result during rollout.
_SMOKE_WORKER_COUNT = 2
_SMOKE_QUEUE_CAPACITY = 2
_SMOKE_RESULT_TIMEOUT_S = OPENAI_COMPATIBLE_TIMEOUT_S + 5
_SMOKE_RUNTIME_LOCK = threading.RLock()
_SMOKE_QUEUE_SLOTS: threading.BoundedSemaphore | None = None
_SMOKE_EXECUTOR: ThreadPoolExecutor | None = None


class _SmokeQueueFull(RuntimeError):
    pass


class _SmokeDeadlineExceeded(TimeoutError):
    pass


def _start_smoke_executor_locked() -> ThreadPoolExecutor:
    global _SMOKE_EXECUTOR, _SMOKE_QUEUE_SLOTS

    if _SMOKE_EXECUTOR is None:
        _SMOKE_QUEUE_SLOTS = threading.BoundedSemaphore(
            _SMOKE_WORKER_COUNT + _SMOKE_QUEUE_CAPACITY
        )
        _SMOKE_EXECUTOR = ThreadPoolExecutor(
            max_workers=_SMOKE_WORKER_COUNT,
            thread_name_prefix="model-gateway-smoke",
        )
    return _SMOKE_EXECUTOR


def start_smoke_executor() -> ThreadPoolExecutor:
    """Start the isolated smoke runtime, or return the active instance."""
    with _SMOKE_RUNTIME_LOCK:
        return _start_smoke_executor_locked()


def shutdown_smoke_executor() -> None:
    """Cancel queued work and wait until every smoke worker has exited."""
    global _SMOKE_EXECUTOR, _SMOKE_QUEUE_SLOTS

    # Submit and shutdown share this lock. Holding it through shutdown prevents
    # a new application lifespan from reusing or replacing a draining runtime.
    with _SMOKE_RUNTIME_LOCK:
        executor = _SMOKE_EXECUTOR
        _SMOKE_EXECUTOR = None
        _SMOKE_QUEUE_SLOTS = None
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)


LOCAL_LLAMA_BASE, LOCAL_LLAMA_MODEL, LOCAL_LLAMA_CONFIGURED = local_llama_settings()


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPSConnection that connects to a pinned IP but keeps original SNI."""

    def __init__(self, connect_host: str, *, port: int, server_hostname: str, timeout: float):
        super().__init__(connect_host, port=port, timeout=timeout)
        self._wanwei_server_hostname = server_hostname

    def connect(self) -> None:  # pragma: no cover - stdlib-compatible socket glue
        self.sock = socket.create_connection((self.host, self.port), self.timeout, self.source_address)
        if self._tunnel_host:
            self._tunnel()
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self._wanwei_server_hostname)


def _host_header(parsed) -> str:
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    default_port = 443 if parsed.scheme == "https" else 80
    if parsed.port and parsed.port != default_port:
        return f"{host}:{parsed.port}"
    return host


def _request_target(parsed) -> str:
    target = parsed.path or "/"
    if parsed.query:
        target += f"?{parsed.query}"
    return target


def _pinned_json_post(url: str, pinned_ip: str, payload: dict, headers: dict[str, str], timeout_s: int) -> dict:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("invalid pinned request URL")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    request_headers = dict(headers)
    request_headers["Host"] = _host_header(parsed)
    body = jsonlib.dumps(payload).encode("utf-8")
    request_headers["Content-Length"] = str(len(body))
    if parsed.scheme == "https":
        conn = _PinnedHTTPSConnection(pinned_ip, port=port, server_hostname=parsed.hostname, timeout=timeout_s)
    else:
        conn = http.client.HTTPConnection(pinned_ip, port=port, timeout=timeout_s)
    try:
        conn.request("POST", _request_target(parsed), body=body, headers=request_headers)
        response = conn.getresponse()
        raw = response.read()
    finally:
        conn.close()
    if response.status >= 400:
        request = httpx.Request("POST", url)
        raise httpx.HTTPStatusError(
            f"HTTP {response.status} {response.reason}",
            request=request,
            response=httpx.Response(response.status, request=request, content=raw),
        )
    return jsonlib.loads(raw.decode("utf-8"))


def _build_providers() -> list[ModelProvider]:
    """按当前 env 配置构建 provider 目录（运行时单一事实源）。

    issue #45 (4.1)：local_mock 整条 provider 已删除——本地模型请接
    Ollama / llama.cpp 的 OpenAI 兼容端点，复用已验证的 openai_compatible
    通路；本地不存在「模拟成功」的 provider。
    """
    base, model, configured = local_llama_settings()
    return [
        ModelProvider(
            provider="openai_compatible",
            api_base=base,
            api_key_alias="NONE_LOCAL_LLAMA_CPP",
            model=model,
            enabled=configured,
            status="available_configured" if configured else "configuration_required",
            notes="Set WANWEI_OPENAI_COMPATIBLE_BASE and WANWEI_OPENAI_COMPATIBLE_MODEL to enable a real local smoke call. No API key is stored.",
        ),
        ModelProvider(
            provider="anthropic",
            api_base="https://api.anthropic.com",
            api_key_alias="ANTHROPIC_API_KEY",
            model="claude-sonnet-4",
            enabled=False,
            status="configuration_required",
            notes="Anthropic provider; real /v1/messages smoke once configured and enabled (issue #45 4.1).",
        ),
        ModelProvider(
            provider="gemini",
            api_base="https://generativelanguage.googleapis.com",
            api_key_alias="GEMINI_API_KEY",
            model="gemini-2.5-pro",
            enabled=False,
            status="configuration_required",
            notes="Gemini provider; real generateContent smoke once configured and enabled (issue #45 4.1).",
        ),
        ModelProvider(
            provider="deepseek",
            api_base="https://api.deepseek.com",
            api_key_alias="DEEPSEEK_API_KEY",
            model="deepseek-chat",
            enabled=False,
            status="configuration_required",
            notes=(
                "DeepSeek 官方 OpenAI 兼容接口，真实调用通路已接通。推荐在平台模型接入舱"
                "（/platform/providers/configs/deepseek）配置密钥并启用；启用后 /soul/chat "
                "对话即走 DeepSeek 真实调用，无需再设置 WANWEI_OPENAI_COMPATIBLE_*。"
            ),
        ),
        ModelProvider(
            provider="aws_bedrock",
            api_base="https://bedrock-runtime.us-east-1.amazonaws.com",
            api_key_alias="AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY",
            model="amazon.nova-pro-v1:0",
            enabled=False,
            status="configuration_required",
            notes=(
                "AWS Bedrock SigV4 真实调用通路（InvokeModel，手工签名无需 boto3）。"
                "api_key 字段固定格式为 'ACCESS_KEY_ID|SECRET_ACCESS_KEY'（恰好一段"
                "竖线分隔，两段均非空；密钥 Fernet 加密落盘，绝不回显）。region 从 "
                "api_base 主机名自动提取（https://bedrock-runtime.{region}.amazonaws.com）。"
                "当前适配 meta.llama* 与 amazon.nova* 两类模型体，其余家族如实报 "
                "unsupported_model_format。"
            ),
        ),
    ]


# Import-time compatibility snapshot; runtime paths use _build_providers().
# TODO(v0.12.0): remove after external callers have migrated to the builder.
PROVIDERS: list[ModelProvider] = _build_providers()


def _ensure_config_table() -> None:
    """Create/migrate the legacy model gateway table to owner-scoped rows."""
    conn = get_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS model_gateway_configs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL,
            owner_id TEXT,
            api_base TEXT NOT NULL,
            api_key_encrypted TEXT,
            model TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 0,
            notes TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info(model_gateway_configs)")}
    # ALTER TABLE is insufficient for the original provider UNIQUE constraint:
    # it would still prevent two owners from configuring the same provider.
    unique_provider = False
    for index in conn.execute("PRAGMA index_list(model_gateway_configs)").fetchall():
        # PRAGMA index_list: seq, name, unique, origin, partial.  The
        # ownerless partial index created below must not trigger migration on
        # every subsequent request.
        if not index[2] or (len(index) > 4 and index[4]):
            continue
        index_columns = [row[2] for row in conn.execute(f"PRAGMA index_info({index[1]!r})")]
        if index_columns == ["provider"]:
            unique_provider = True
            break
    if "owner_id" not in columns or unique_provider:
        conn.execute("ALTER TABLE model_gateway_configs RENAME TO model_gateway_configs_legacy")
        conn.execute(
            """
            CREATE TABLE model_gateway_configs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                owner_id TEXT,
                api_base TEXT NOT NULL,
                api_key_encrypted TEXT,
                model TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 0,
                notes TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        legacy_columns = {row[1] for row in conn.execute("PRAGMA table_info(model_gateway_configs_legacy)")}
        owner_expr = "owner_id" if "owner_id" in legacy_columns else "NULL"
        conn.execute(
            f"""
            INSERT INTO model_gateway_configs(
                id,provider,owner_id,api_base,api_key_encrypted,model,enabled,notes,created_at,updated_at
            )
            SELECT id,provider,{owner_expr},api_base,api_key_encrypted,model,enabled,notes,created_at,updated_at
            FROM model_gateway_configs_legacy
            """
        )
        conn.execute("DROP TABLE model_gateway_configs_legacy")
    # A normal composite UNIQUE index treats NULL as distinct.  Partial
    # indexes enforce uniqueness for both scoped rows and the single legacy
    # ownerless row, while allowing an ownerless row beside an owned row.
    conn.execute("DROP INDEX IF EXISTS uq_model_gateway_owner_provider")
    conn.execute(
        "DELETE FROM model_gateway_configs WHERE owner_id IS NULL AND id NOT IN "
        "(SELECT MIN(id) FROM model_gateway_configs WHERE owner_id IS NULL GROUP BY provider)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_model_gateway_owner_provider "
        "ON model_gateway_configs(owner_id, provider) WHERE owner_id IS NOT NULL"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_model_gateway_legacy_provider "
        "ON model_gateway_configs(provider) WHERE owner_id IS NULL"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_model_gateway_owner "
        "ON model_gateway_configs(owner_id, updated_at)"
    )
    conn.commit()


def _legacy_owner_allowed(owner_id: str) -> bool:
    try:
        from ..soul.ownership import configured_actor_id

        return owner_id == configured_actor_id()
    except Exception:
        return False


def _effective_owner(owner_id: str | None) -> str | None:
    if owner_id is not None:
        return owner_id
    try:
        from ..soul.ownership import configured_actor_id

        return configured_actor_id()
    except Exception:
        return None


def list_providers() -> dict:
    return {"items": [provider.model_dump() for provider in _build_providers()]}


def _encode_api_key(api_key: str) -> str:
    return encryption.encrypt(api_key)


def _decode_api_key(api_key_encrypted: str | None) -> str:
    if not api_key_encrypted:
        return ""
    try:
        return encryption.decrypt(api_key_encrypted)
    except encryption.LegacyCiphertextError:
        # 02-#4：旧 base64 明文不再原样返回。视同不可解密，走调用方既有的
        # 「Stored API key cannot be decrypted」显式错误路径（不 500、不泄露明文）；
        # 可按 encryption.migrate_legacy_ciphertext() 指引一次性迁移。
        logger.warning(
            "model_gateway config contains legacy base64 ciphertext; treating as "
            "undecryptable. Migrate via security.encryption.migrate_legacy_ciphertext()."
        )
        return ""


def _get_config(provider: str, owner_id: str | None = None) -> dict | None:
    owner = _effective_owner(owner_id)
    _ensure_config_table()
    with transaction(immediate=True) as tx:
        if owner is not None and _legacy_owner_allowed(owner):
            row = tx.execute(
                """
                SELECT provider,api_base,api_key_encrypted,model,enabled,notes,owner_id
                FROM model_gateway_configs
                WHERE provider=? AND (owner_id=? OR owner_id IS NULL)
                ORDER BY CASE WHEN owner_id=? THEN 0 ELSE 1 END
                LIMIT 1
                """,
                (provider, owner, owner),
            ).fetchone()
        else:
            row = tx.execute(
                """
                SELECT provider,api_base,api_key_encrypted,model,enabled,notes,owner_id
                FROM model_gateway_configs
                WHERE provider=? AND owner_id=?
                LIMIT 1
                """,
                (provider, owner),
            ).fetchone()
        if row is None:
            return None
        if row["owner_id"] is None and owner is not None and _legacy_owner_allowed(owner):
            # Atomically claim the legacy row only when this owner has no
            # scoped row.  A different owner may already have its own row.
            tx.execute(
                """
                UPDATE model_gateway_configs SET owner_id=?
                WHERE provider=? AND owner_id IS NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM model_gateway_configs
                      WHERE provider=? AND owner_id=?
                  )
                """,
                (owner, provider, provider, owner),
            )
            row = tx.execute(
                """
                SELECT provider,api_base,api_key_encrypted,model,enabled,notes,owner_id
                FROM model_gateway_configs WHERE provider=? AND owner_id=?
                LIMIT 1
                """,
                (provider, owner),
            ).fetchone()
        if row is None:
            return None
        return {
            "provider": row["provider"],
            "api_base": row["api_base"],
            "api_key": _decode_api_key(row["api_key_encrypted"]),
            "api_key_encrypted": row["api_key_encrypted"],
            "model": row["model"],
            "enabled": bool(row["enabled"]),
            "notes": row["notes"] or "",
        }


def list_configs(owner_id: str | None = None) -> dict:
    owner = _effective_owner(owner_id)
    _ensure_config_table()
    with transaction(immediate=True) as tx:
        # Bind each ownerless legacy row to the configured migration actor only
        # when that actor has no scoped row.  This is atomic and leaves an
        # ownerless row beside other owners' scoped rows when they already
        # coexist.
        if owner is not None and _legacy_owner_allowed(owner):
            tx.execute(
                """
                UPDATE model_gateway_configs SET owner_id=?
                WHERE owner_id IS NULL AND NOT EXISTS (
                    SELECT 1 FROM model_gateway_configs existing
                    WHERE existing.provider=model_gateway_configs.provider
                      AND existing.owner_id=?
                )
                """,
                (owner, owner),
            )
        rows = tx.execute(
            """
            SELECT provider,api_base,model,enabled,notes,owner_id
            FROM model_gateway_configs WHERE owner_id=?
            ORDER BY provider ASC
            """,
            (owner,),
        ).fetchall()
    return {
        "items": [
            ModelGatewayConfigOut(
                provider=row["provider"],
                api_base=row["api_base"],
                model=row["model"],
                enabled=bool(row["enabled"]),
                notes=row["notes"] or "",
            ).model_dump()
            for row in rows
        ]
    }


def upsert_config(
    provider: str,
    api_base: str,
    api_key: str,
    model: str,
    enabled: bool,
    notes: str,
    owner_id: str | None = None,
) -> dict:
    # Reject invalid/SSRF-prone endpoints before persisting configuration.
    # 写入时校验只做「语法 + 主机黑名单」的静态检查（validate_external_url
    # 同样经此路径但不做 DNS 解析），不调用 resolve_external_url——后者会
    # 解析 DNS，测试环境/离线环境下 .example 等保留域名会失败，且 DNS 结果
    # 在真实调用时还会重新解析（pin IP 在执行时进行才有时效性）。
    _parsed = urlparse(api_base or "")
    if _parsed.scheme not in ("http", "https"):
        raise SSRFError(f"Scheme '{_parsed.scheme}' is not allowed")
    _host = _parsed.hostname
    if not _host:
        raise SSRFError("URL has no host")
    if _parsed.username or _parsed.password or "@" in (_parsed.netloc or ""):
        raise SSRFError("URL must not contain credentials")
    if _hostname_is_blocked(_host):
        raise SSRFError(f"Host '{_host}' is in SSRF block list")
    _ensure_config_table()
    owner = _effective_owner(owner_id)
    now = utc_now_iso()
    existing = _get_config(provider, owner)
    encoded_key = _encode_api_key(api_key) if api_key else (
        existing["api_key_encrypted"] if existing else None
    )
    with transaction(immediate=True) as conn:
        updated = conn.execute(
            """
            UPDATE model_gateway_configs
            SET api_base=?, api_key_encrypted=?, model=?, enabled=?, notes=?, updated_at=?
            WHERE provider=? AND owner_id IS ?
            """,
            (api_base, encoded_key, model, int(enabled), notes, now, provider, owner),
        ).rowcount
        if not updated:
            conn.execute(
                """
                INSERT INTO model_gateway_configs(
                    provider,owner_id,api_base,api_key_encrypted,model,enabled,notes,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (provider, owner, api_base, encoded_key, model, int(enabled), notes, now, now),
            )
    return ModelGatewayConfigOut(
        provider=provider,
        api_base=api_base,
        model=model,
        enabled=enabled,
        notes=notes,
    ).model_dump()


def delete_config(provider: str, owner_id: str | None = None) -> bool:
    _ensure_config_table()
    owner = _effective_owner(owner_id)
    with transaction(immediate=True) as conn:
        deleted = conn.execute(
            "DELETE FROM model_gateway_configs WHERE provider=? AND owner_id=?",
            (provider, owner),
        ).rowcount
        if not deleted and owner is not None and _legacy_owner_allowed(owner):
            deleted = conn.execute(
                "DELETE FROM model_gateway_configs WHERE provider=? AND owner_id IS NULL "
                "AND NOT EXISTS(SELECT 1 FROM model_gateway_configs WHERE provider=? AND owner_id=?)",
                (provider, provider, owner),
            ).rowcount
    return bool(deleted)


def _provider_config(provider_name: str, owner_id: str | None = None) -> dict | None:
    configured = _get_config(provider_name, owner_id)
    if configured is not None:
        return configured
    provider = next((item for item in _build_providers() if item.provider == provider_name), None)
    if provider is None:
        return None
    return {
        "provider": provider.provider,
        "api_base": provider.api_base,
        "api_key": "",
        "model": provider.model,
        "enabled": provider.enabled,
        "notes": provider.notes,
    }


def _openai_compatible_smoke(
    api_base: str,
    api_key: str,
    model: str,
    prompt: str,
    max_tokens: int,
) -> tuple[str, int, str]:
    """同步阻塞式 smoke 调用；API 路径必须经专用池提交。"""
    started = time.perf_counter()
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是宛委枢忆项目的本地模型网关 smoke 测试助手。回答要短。"},
            {"role": "user", "content": prompt[:500]},
        ],
        "temperature": 0.2,
        "max_tokens": max(16, min(max_tokens, 256)),
        "stream": False,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    validated_base, pinned_ip = resolve_external_url(api_base, allowlist=local_llama_allowlist())
    data = _pinned_json_post(
        validated_base.rstrip("/") + "/chat/completions",
        pinned_ip,
        payload,
        headers,
        OPENAI_COMPATIBLE_TIMEOUT_S,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)
    choices = data.get("choices") or []
    message = choices[0].get("message", {}) if choices else {}
    text = message.get("content", "") or ""
    if not text.strip():
        # 推理类模型（deepseek-r*/v* 等）可能把全部输出写进 reasoning_content
        # 而 content 留空；此时如实回退推理文本，避免「成功但空回复」。
        text = message.get("reasoning_content", "") or ""
    return "ok", latency_ms, text[:600]


def _anthropic_smoke(
    api_base: str,
    api_key: str,
    model: str,
    prompt: str,
    max_tokens: int,
) -> tuple[str, int, str]:
    """Anthropic Messages API 真实 smoke（issue #45 4.1，复用 pinned-IP 模式）。"""
    started = time.perf_counter()
    payload = {
        "model": model,
        "max_tokens": max(16, min(max_tokens, 256)),
        "system": "你是宛委枢忆项目的本地模型网关 smoke 测试助手。回答要短。",
        "messages": [{"role": "user", "content": prompt[:500]}],
    }
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    validated_base, pinned_ip = resolve_external_url(api_base, allowlist=local_llama_allowlist())
    data = _pinned_json_post(
        validated_base.rstrip("/") + "/v1/messages",
        pinned_ip,
        payload,
        headers,
        OPENAI_COMPATIBLE_TIMEOUT_S,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)
    blocks = data.get("content") or []
    text = "".join(
        b.get("text", "") for b in blocks
        if isinstance(b, dict) and b.get("type") == "text"
    )
    if not text.strip():
        # 开启扩展思考的 Claude 可能只产出 thinking 块；content 为空时如实
        # 回退思考文本，避免「成功但空回复」。
        text = "".join(
            b.get("thinking", "") for b in blocks
            if isinstance(b, dict) and b.get("type") == "thinking"
        )
    return "ok", latency_ms, text[:600]


def _gemini_smoke(
    api_base: str,
    api_key: str,
    model: str,
    prompt: str,
    max_tokens: int,
) -> tuple[str, int, str]:
    """Gemini generateContent 真实 smoke（issue #45 4.1，复用 pinned-IP 模式）。"""
    started = time.perf_counter()
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": "你是宛委枢忆项目的本地模型网关 smoke 测试助手。回答要短。\n\n" + prompt[:500]},
                ],
            },
        ],
        "generationConfig": {"maxOutputTokens": max(16, min(max_tokens, 256))},
    }
    headers = {"Content-Type": "application/json"}
    validated_base, pinned_ip = resolve_external_url(api_base, allowlist=local_llama_allowlist())
    base = validated_base.rstrip("/")
    if base.endswith("/v1beta"):
        # 平台目录里 google_ai_studio 的默认端点已带 /v1beta，剥掉避免拼出双重前缀
        base = base[: -len("/v1beta")]
    data = _pinned_json_post(
        base + f"/v1beta/models/{model}:generateContent?key={api_key}",
        pinned_ip,
        payload,
        headers,
        OPENAI_COMPATIBLE_TIMEOUT_S,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)
    candidates = data.get("candidates") or []
    text = ""
    if candidates:
        parts = [p for p in ((candidates[0].get("content") or {}).get("parts") or [])
                 if isinstance(p, dict)]
        # 思考型 Gemini（2.5 系列）会把推理写进 thought:true 部件：优先取
        # 正式输出；为空时如实回退思考文本，避免「成功但空回复」。
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if not text.strip():
            text = "".join(p.get("text", "") for p in parts)
    return "ok", latency_ms, text[:600]


def _sigv4_sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sigv4_hmac(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def _sigv4_signing_key(secret_key: str, date_stamp: str, region: str, service: str) -> bytes:
    """AWS4 派生链：kDate → kRegion → kService → kSigning。"""
    k_date = _sigv4_hmac(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region = _sigv4_hmac(k_date, region)
    k_service = _sigv4_hmac(k_region, service)
    return _sigv4_hmac(k_service, "aws4_request")


def _sigv4_authorization(
    *,
    method: str,
    canonical_uri: str,
    canonical_query: str,
    header_pairs: list[tuple[str, str]],
    payload_hash: str,
    amz_date: str,
    access_key: str,
    secret_key: str,
    region: str,
    service: str,
) -> str:
    """构造 SigV4 Authorization 头（手工签名，不引入 boto3）。

    header_pairs 必须已小写化、按名称排序且同名单值；canonical_uri 为
    URI 编码后的请求路径（'/' 保留）。离线正确性由 AWS 官方 SigV4
    测试向量（get-vanilla / post-vanilla）回归保证，见
    tests/test_bedrock_sigv4_and_oauth_device.py。
    """
    canonical_headers = "".join(f"{name}:{value}\n" for name, value in header_pairs)
    signed_headers = ";".join(name for name, _ in header_pairs)
    canonical_request = "\n".join(
        [method, canonical_uri, canonical_query, canonical_headers, signed_headers, payload_hash]
    )
    creq_hash = _sigv4_sha256_hex(canonical_request.encode("utf-8"))
    date_stamp = amz_date[:8]
    scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, creq_hash])
    signing_key = _sigv4_signing_key(secret_key, date_stamp, region, service)
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    return (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )


class _BedrockConfigError(ValueError):
    """AWS Bedrock 凭据/端点配置不满足真实调用前置条件（not_configured 语义）。

    绝不在异常消息中回显凭据内容——只描述格式期望。
    """


def _parse_bedrock_credentials(api_key: str) -> tuple[str, str]:
    """解析 'ACCESS_KEY_ID|SECRET_ACCESS_KEY' 凭据约定（竖线分隔）。

    格式不符抛 _BedrockConfigError（not_configured 语义），绝不半签：
    只要拿不到完整两段凭据就不发起任何网络请求。
    """
    raw = (api_key or "").strip()
    parts = raw.split("|")
    if len(parts) != 2:
        raise _BedrockConfigError(
            "AWS Bedrock 凭据格式错误：api_key 必须为 'ACCESS_KEY_ID|SECRET_ACCESS_KEY'"
            "（恰好一段竖线分隔的两段非空文本）"
        )
    access_key = parts[0].strip()
    secret_key = parts[1].strip()
    if not access_key or not secret_key:
        raise _BedrockConfigError(
            "AWS Bedrock 凭据格式错误：ACCESS_KEY_ID 与 SECRET_ACCESS_KEY 均不能为空"
        )
    return access_key, secret_key


def _bedrock_region_from_base(api_base: str) -> str:
    """从 bedrock-runtime.{region}.amazonaws.com(.cn) 主机名提取 region。"""
    host = (urlparse(api_base or "").hostname or "").lower()
    labels = host.split(".")
    if len(labels) >= 3 and labels[0].startswith("bedrock-runtime") and labels[1]:
        return labels[1]
    raise _BedrockConfigError(
        "AWS Bedrock region 无法从 api_base 提取：期望形如 "
        "https://bedrock-runtime.{region}.amazonaws.com 的端点"
    )


_BEDROCK_TIMEOUT_S = OPENAI_COMPATIBLE_TIMEOUT_S
_BEDROCK_SERVICE = "bedrock"


def _bedrock_invoke_payload(model: str, prompt: str, max_tokens: int) -> dict:
    """按模型家族构造 InvokeModel 请求体（最小适配）。

    - meta.llama*  ：原生 prompt 字段（max_gen_len/temperature）；
    - amazon.nova* ：messages-v1 schema（messages + inferenceConfig）；
    - 其他家族     ：如实报 unsupported_model_format，不猜协议。
    """
    bounded_tokens = max(16, min(max_tokens, 256))
    bounded_prompt = prompt[:500]
    if model.startswith("meta.llama"):
        return {
            "prompt": bounded_prompt,
            "temperature": 0.2,
            "max_gen_len": bounded_tokens,
        }
    if model.startswith("amazon.nova"):
        return {
            "schemaVersion": "messages-v1",
            "messages": [
                {"role": "user", "content": [{"text": bounded_prompt}]},
            ],
            "inferenceConfig": {"max_new_tokens": bounded_tokens},
        }
    raise ValueError(
        "unsupported_model_format: AWS Bedrock invoke 仅适配 meta.llama*（prompt 字段）"
        f"与 amazon.nova*（messages 字段）；模型 '{model}' 属未适配家族，已拒绝猜测协议"
    )


def _bedrock_extract_text(data: dict) -> str:
    """从 InvokeModel 响应提取文本：llama 的 generation 或 nova 的 output.message。"""
    generation = data.get("generation")
    if isinstance(generation, str):
        return generation
    output = data.get("output")
    if isinstance(output, dict):
        message = output.get("message")
        blocks = message.get("content") if isinstance(message, dict) else None
        if isinstance(blocks, list):
            return "".join(
                block.get("text", "") for block in blocks if isinstance(block, dict)
            )
    return ""


def _bedrock_smoke(
    api_base: str,
    api_key: str,
    model: str,
    prompt: str,
    max_tokens: int,
) -> tuple[str, int, str]:
    """AWS Bedrock InvokeModel 真实 smoke（SigV4 手工签名，无需 boto3）。

    凭据约定见 _build_providers 中 aws_bedrock 条目的 notes；region 从
    api_base 主机名提取。签名走既有 pinned-IP 通道
    （resolve_external_url + _pinned_json_post）；SECRET 只参与签名派生，
    绝不出现在 URL、payload 或任何响应中。
    """
    started = time.perf_counter()
    access_key, secret_key = _parse_bedrock_credentials(api_key)
    region = _bedrock_region_from_base(api_base)
    validated_base, pinned_ip = resolve_external_url(api_base, allowlist=local_llama_allowlist())
    payload = _bedrock_invoke_payload(model, prompt, max_tokens)
    body_bytes = jsonlib.dumps(payload).encode("utf-8")
    encoded_model = quote(model, safe="")
    url = f"{validated_base.rstrip('/')}/model/{encoded_model}/invoke"
    parsed_url = urlparse(url)
    amz_date = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    payload_hash = _sigv4_sha256_hex(body_bytes)
    header_pairs = sorted([
        ("content-type", "application/json"),
        ("host", _host_header(parsed_url)),
        ("x-amz-content-sha256", payload_hash),
        ("x-amz-date", amz_date),
    ])
    authorization = _sigv4_authorization(
        method="POST",
        canonical_uri=parsed_url.path or "/",
        canonical_query="",
        header_pairs=header_pairs,
        payload_hash=payload_hash,
        amz_date=amz_date,
        access_key=access_key,
        secret_key=secret_key,
        region=region,
        service=_BEDROCK_SERVICE,
    )
    headers = {
        "Content-Type": "application/json",
        "X-Amz-Date": amz_date,
        "x-amz-content-sha256": payload_hash,
        "Authorization": authorization,
    }
    data = _pinned_json_post(url, pinned_ip, payload, headers, _BEDROCK_TIMEOUT_S)
    latency_ms = int((time.perf_counter() - started) * 1000)
    text = _bedrock_extract_text(data)
    return "ok", latency_ms, text[:600]


def _provider_dispatch(
    provider: str,
    api_base: str,
    api_key: str,
    model: str,
    prompt: str,
    max_tokens: int,
) -> tuple[str, int, str]:
    """按 provider 分发到真实 smoke 实现（issue #45 4.1 收口）。

    其余 provider 一律走 OpenAI 兼容通路——DeepSeek 官方接口即为该协议；
    google_ai_studio 是 Gemini 原生协议的平台目录别名；aws_bedrock 走
    SigV4 手工签名的 InvokeModel 通路。
    """
    if provider == "anthropic":
        return _anthropic_smoke(api_base, api_key, model, prompt, max_tokens)
    if provider in {"gemini", "google_ai_studio"}:
        return _gemini_smoke(api_base, api_key, model, prompt, max_tokens)
    if provider == "aws_bedrock":
        return _bedrock_smoke(api_base, api_key, model, prompt, max_tokens)
    return _openai_compatible_smoke(api_base, api_key, model, prompt, max_tokens)


def _submit_smoke(
    provider: str,
    api_base: str,
    api_key: str,
    model: str,
    prompt: str,
    max_tokens: int,
) -> Future[tuple[str, int, str]]:
    """Admit and submit one smoke call under the runtime lifecycle lock."""
    with _SMOKE_RUNTIME_LOCK:
        executor = _start_smoke_executor_locked()
        slot_gate = _SMOKE_QUEUE_SLOTS
        if slot_gate is None:  # pragma: no cover - protected by the runtime lock
            raise RuntimeError("smoke runtime initialized without an admission gate")
        if not slot_gate.acquire(blocking=False):
            raise _SmokeQueueFull
        try:
            future = executor.submit(
                _provider_dispatch,
                provider,
                api_base,
                api_key,
                model,
                prompt,
                max_tokens,
            )
        except Exception:
            slot_gate.release()
            raise

        # This callback is the sole owner of the slot after submit succeeds.
        # It covers normal completion, worker failure and queued cancellation.
        future.add_done_callback(lambda _future: slot_gate.release())
        return future


def _run_smoke_in_dedicated_pool(
    provider: str,
    api_base: str,
    api_key: str,
    model: str,
    prompt: str,
    max_tokens: int,
) -> tuple[str, int, str]:
    """同步兼容入口；真实 API 路由使用对应的 async 等待路径。

    容量槽覆盖正在运行和排队的任务。调用方等待超时后不能提前释放槽，
    因为底层 socket/DNS 工作可能仍在继续；完成回调才是唯一释放点。
    """
    future = _submit_smoke(provider, api_base, api_key, model, prompt, max_tokens)
    try:
        return future.result(timeout=_SMOKE_RESULT_TIMEOUT_S)
    except FutureTimeoutError as exc:
        # concurrent.futures.TimeoutError aliases built-in TimeoutError. A socket
        # timeout raised *by* the worker must keep its network-error semantics.
        if future.done():
            return future.result()
        future.cancel()
        raise _SmokeDeadlineExceeded from exc


def _consume_async_future_exception(future: asyncio.Future) -> None:
    """Retrieve late worker exceptions after timeout/cancellation."""
    if not future.cancelled():
        future.exception()


async def _run_smoke_in_dedicated_pool_async(
    provider: str,
    api_base: str,
    api_key: str,
    model: str,
    prompt: str,
    max_tokens: int,
) -> tuple[str, int, str]:
    """Await a dedicated worker without occupying Starlette's AnyIO pool."""
    future = _submit_smoke(provider, api_base, api_key, model, prompt, max_tokens)
    async_future = asyncio.wrap_future(future)
    async_future.add_done_callback(_consume_async_future_exception)
    try:
        return await asyncio.wait_for(
            asyncio.shield(async_future),
            timeout=_SMOKE_RESULT_TIMEOUT_S,
        )
    except (asyncio.TimeoutError, TimeoutError) as exc:
        # Python 3.10 exposes asyncio.TimeoutError separately; newer versions
        # alias it to built-in TimeoutError. Completion state identifies a
        # worker exception from a pool deadline in either runtime.
        if future.done():
            return future.result()
        future.cancel()
        raise _SmokeDeadlineExceeded from exc
    except asyncio.CancelledError:
        future.cancel()
        raise


@dataclass(frozen=True)
class _ProviderTestContext:
    provider: dict
    model: str
    request_id: str


def _prepare_provider_test(
    req: ModelGatewayTestIn,
    owner_id: str | None = None,
) -> ModelGatewayTestOut | _ProviderTestContext:
    db_config = (
        _get_config(req.provider, owner_id)
        if owner_id is not None
        else _get_config(req.provider)
    )
    provider = (
        db_config
        or (_provider_config(req.provider, owner_id) if owner_id is not None
            else _provider_config(req.provider))
    )
    model = req.model or (provider["model"] if provider else "unknown")
    request_id = "mgw_" + uuid.uuid4().hex[:12]
    if provider is None:
        return ModelGatewayTestOut(
            provider=req.provider,
            model=model,
            dry_run=req.dry_run,
            status="not_found",
            request_id=request_id,
            message="Provider is not registered in the model gateway catalog.",
        )
    if req.dry_run:
        return ModelGatewayTestOut(
            provider=provider["provider"],
            model=model,
            dry_run=True,
            status="ok",
            request_id=request_id,
            message=f"Dry-run accepted for {provider['provider']}; prompt preview length={len(req.prompt_preview)}.",
        )
    if not provider["enabled"]:
        return ModelGatewayTestOut(
            provider=provider["provider"],
            model=model,
            dry_run=False,
            status="not_configured",
            request_id=request_id,
            message="Provider is not configured. Update its configuration and enable it before a real smoke test.",
        )
    if provider.get("api_key_encrypted") and not provider["api_key"]:
        return ModelGatewayTestOut(
            provider=provider["provider"],
            model=model,
            dry_run=False,
            status="not_configured",
            request_id=request_id,
            message="Stored API key cannot be decrypted. Restore WANWEI_ENCRYPTION_KEY or submit a new API key.",
        )
    if db_config is None and provider["provider"] not in {"openai_compatible", "anthropic", "gemini", "deepseek"}:
        return ModelGatewayTestOut(
            provider=provider["provider"],
            model=model,
            dry_run=False,
            status="not_implemented",
            request_id=request_id,
            message="Provider has no real connectivity implementation; refusing to return ok (issue #45 4.1).",
        )
    return _ProviderTestContext(provider=provider, model=model, request_id=request_id)


def _smoke_success_output(
    context: _ProviderTestContext,
    result: tuple[str, int, str],
) -> ModelGatewayTestOut:
    status, latency_ms, preview = result
    api_base = context.provider["api_base"]
    return ModelGatewayTestOut(
        provider=context.provider["provider"],
        model=context.model,
        dry_run=False,
        status=status,
        request_id=context.request_id,
        message=f"OpenAI-compatible smoke completed via {api_base}.",
        latency_ms=latency_ms,
        response_preview=preview,
    )


def _smoke_failure_output(
    context: _ProviderTestContext,
    exc: Exception,
) -> ModelGatewayTestOut:
    common = {
        "provider": context.provider["provider"],
        "model": context.model,
        "dry_run": False,
        "request_id": context.request_id,
    }
    if isinstance(exc, _SmokeQueueFull):
        return ModelGatewayTestOut(
            **common,
            status="busy",
            message="Model gateway smoke queue is full; retry later.",
        )
    if isinstance(exc, _SmokeDeadlineExceeded):
        return ModelGatewayTestOut(
            **common,
            status="error",
            message="Model gateway smoke exceeded the isolated worker deadline.",
        )
    if isinstance(exc, SSRFError):
        return ModelGatewayTestOut(
            **common,
            status="ssrf_blocked",
            message=f"SSRF block: {exc}",
        )
    if isinstance(exc, _BedrockConfigError):
        # 凭据/端点格式问题属配置缺失而非运行故障：not_configured 语义，
        # 异常消息本身不含任何凭据内容。
        return ModelGatewayTestOut(
            **common,
            status="not_configured",
            message=str(exc),
        )
    return ModelGatewayTestOut(
        **common,
        status="error",
        message=f"Model gateway smoke failed: {exc}",
    )


_HANDLED_SMOKE_FAILURES = (
    _SmokeQueueFull,
    _SmokeDeadlineExceeded,
    SSRFError,
    OSError,
    http.client.HTTPException,
    httpx.HTTPError,
    ValueError,
)


def probe_openai_compatible(
    api_base: str,
    api_key: str,
    model: str,
    prompt: str = "MemoryOps connectivity probe",
    max_tokens: int = 16,
) -> tuple[str, int, str]:
    """公开的 OpenAI-compatible 连通性探测入口（同步，专用线程池内执行）。

    Issue #45 (4.5)：providers 舱的云端连通性测试复用本实现，与
    /model-gateway/test 走同一套 pinned-IP SSRF 防护与超时，不再各写一份。
    返回值 (status, latency_ms, preview)；失败时抛 _HANDLED_SMOKE_FAILURES
    中的异常，由调用方转为结构化错误。
    """
    return _run_smoke_in_dedicated_pool(
        "openai_compatible", api_base, api_key, model, prompt, max_tokens,
    )


def run_provider_test(
    req: ModelGatewayTestIn, owner_id: str | None = None,
) -> ModelGatewayTestOut:
    """Run a provider test synchronously for existing direct callers."""
    prepared = _prepare_provider_test(req, owner_id)
    if isinstance(prepared, ModelGatewayTestOut):
        return prepared
    provider = prepared.provider
    try:
        result = _run_smoke_in_dedicated_pool(
            provider["provider"],
            provider["api_base"],
            provider["api_key"],
            prepared.model,
            req.prompt_preview,
            req.max_tokens,
        )
        return _smoke_success_output(prepared, result)
    # _pinned_json_post 走原生 http.client/socket/ssl：网络层故障抛 OSError
    # （连接拒绝/超时/TLS 证书错误）与 http.client.HTTPException（坏状态行/
    # 对端提前断连），必须在此兜底，否则端点宕机会从优雅降级退化为 500。
    except _HANDLED_SMOKE_FAILURES as exc:
        return _smoke_failure_output(prepared, exc)


async def run_provider_test_async(
    req: ModelGatewayTestIn, owner_id: str | None = None,
) -> ModelGatewayTestOut:
    """Run a provider test without blocking FastAPI's default worker pool."""
    prepared = _prepare_provider_test(req, owner_id)
    if isinstance(prepared, ModelGatewayTestOut):
        return prepared
    provider = prepared.provider
    try:
        result = await _run_smoke_in_dedicated_pool_async(
            provider["provider"],
            provider["api_base"],
            provider["api_key"],
            prepared.model,
            req.prompt_preview,
            req.max_tokens,
        )
        return _smoke_success_output(prepared, result)
    except _HANDLED_SMOKE_FAILURES as exc:
        return _smoke_failure_output(prepared, exc)
