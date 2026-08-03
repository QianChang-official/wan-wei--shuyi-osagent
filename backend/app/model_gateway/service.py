from __future__ import annotations

import asyncio
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
import http.client
import json as jsonlib
import logging
import os
import socket
import sqlite3
import threading
import time
import uuid
from urllib.parse import urlparse

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
from ..security.ssrf import SSRFError, resolve_external_url, validate_external_url
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
    """解析 WANWEI_OPENAI_COMPATIBLE_HOST_ALLOWLIST 为主机白名单列表。"""
    raw = os.getenv("WANWEI_OPENAI_COMPATIBLE_HOST_ALLOWLIST")
    return [h.strip() for h in raw.split(",") if h.strip()] if raw else None


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
    """按当前 env 配置构建 provider 目录（运行时单一事实源）。"""
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
            status="planned_configurable",
            notes="Anthropic provider stub with dry-run connectivity semantics.",
        ),
        ModelProvider(
            provider="gemini",
            api_base="https://generativelanguage.googleapis.com",
            api_key_alias="GEMINI_API_KEY",
            model="gemini-2.5-pro",
            enabled=False,
            status="planned_configurable",
            notes="Gemini provider stub; no outbound call is made in v0.9.4 dry-run.",
        ),
        ModelProvider(
            provider="local_mock",
            api_base="local://memoryops/mock-model",
            api_key_alias="NONE",
            model="memoryops-local-mock",
            enabled=True,
            status="available_stub",
            notes="Deterministic local dry-run provider for demos and CI.",
        ),
    ]


# Import-time compatibility snapshot; runtime paths use _build_providers().
# TODO(v0.12.0): remove after external callers have migrated to the builder.
PROVIDERS: list[ModelProvider] = _build_providers()


def _ensure_config_table() -> None:
    conn = get_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS model_gateway_configs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL UNIQUE,
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
    conn.commit()


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


def _get_config(provider: str) -> dict | None:
    try:
        row = get_conn().execute(
            """
            SELECT provider,api_base,api_key_encrypted,model,enabled,notes
            FROM model_gateway_configs
            WHERE provider=?
            """,
            (provider,),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc):
            raise
        return None
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


def list_configs() -> dict:
    try:
        rows = get_conn().execute(
            """
            SELECT provider,api_base,model,enabled,notes
            FROM model_gateway_configs
            ORDER BY provider ASC
            """
        ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc):
            raise
        _ensure_config_table()
        rows = get_conn().execute(
            """
            SELECT provider,api_base,model,enabled,notes
            FROM model_gateway_configs
            ORDER BY provider ASC
            """
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
) -> dict:
    _ensure_config_table()
    now = utc_now_iso()
    existing = _get_config(provider)
    encoded_key = _encode_api_key(api_key) if api_key else (
        existing["api_key_encrypted"] if existing else None
    )
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO model_gateway_configs(
                provider,api_base,api_key_encrypted,model,enabled,notes,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(provider) DO UPDATE SET
                api_base=excluded.api_base,
                api_key_encrypted=excluded.api_key_encrypted,
                model=excluded.model,
                enabled=excluded.enabled,
                notes=excluded.notes,
                updated_at=excluded.updated_at
            """,
            (provider, api_base, encoded_key, model, int(enabled), notes, now, now),
        )
    return ModelGatewayConfigOut(
        provider=provider,
        api_base=api_base,
        model=model,
        enabled=enabled,
        notes=notes,
    ).model_dump()


def delete_config(provider: str) -> bool:
    _ensure_config_table()
    with transaction() as conn:
        deleted = conn.execute(
            "DELETE FROM model_gateway_configs WHERE provider=?", (provider,)
        ).rowcount
    return bool(deleted)


def _provider_config(provider_name: str) -> dict | None:
    configured = _get_config(provider_name)
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
    text = choices[0].get("message", {}).get("content", "") if choices else ""
    return "ok", latency_ms, text[:600]


def _submit_smoke(
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
                _openai_compatible_smoke,
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
    future = _submit_smoke(api_base, api_key, model, prompt, max_tokens)
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
    api_base: str,
    api_key: str,
    model: str,
    prompt: str,
    max_tokens: int,
) -> tuple[str, int, str]:
    """Await a dedicated worker without occupying Starlette's AnyIO pool."""
    future = _submit_smoke(api_base, api_key, model, prompt, max_tokens)
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
) -> ModelGatewayTestOut | _ProviderTestContext:
    db_config = _get_config(req.provider)
    provider = db_config or _provider_config(req.provider)
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
    if db_config is None and provider["provider"] != "openai_compatible":
        return ModelGatewayTestOut(
            provider=provider["provider"],
            model=model,
            dry_run=False,
            status="blocked_in_alpha",
            request_id=request_id,
            message="Only the local OpenAI-compatible llama.cpp endpoint is enabled for real smoke in this prototype.",
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


def run_provider_test(req: ModelGatewayTestIn) -> ModelGatewayTestOut:
    """Run a provider test synchronously for existing direct callers."""
    prepared = _prepare_provider_test(req)
    if isinstance(prepared, ModelGatewayTestOut):
        return prepared
    provider = prepared.provider
    try:
        result = _run_smoke_in_dedicated_pool(
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


async def run_provider_test_async(req: ModelGatewayTestIn) -> ModelGatewayTestOut:
    """Run a provider test without blocking FastAPI's default worker pool."""
    prepared = _prepare_provider_test(req)
    if isinstance(prepared, ModelGatewayTestOut):
        return prepared
    provider = prepared.provider
    try:
        result = await _run_smoke_in_dedicated_pool_async(
            provider["api_base"],
            provider["api_key"],
            prepared.model,
            req.prompt_preview,
            req.max_tokens,
        )
        return _smoke_success_output(prepared, result)
    except _HANDLED_SMOKE_FAILURES as exc:
        return _smoke_failure_output(prepared, exc)
