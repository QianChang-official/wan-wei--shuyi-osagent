from __future__ import annotations

import os
import sqlite3
import time
import uuid

import httpx

from .schemas import (
    ModelGatewayConfigOut,
    ModelGatewayTestIn,
    ModelGatewayTestOut,
    ModelProvider,
)
from ..db import get_conn
from ..security import encryption
from ..security.ssrf import SSRFError, validate_external_url
from ..utils.datetime_utils import utc_now_iso

LOCAL_LLAMA_BASE = os.getenv("WANWEI_OPENAI_COMPATIBLE_BASE", "").strip()
LOCAL_LLAMA_MODEL = os.getenv("WANWEI_OPENAI_COMPATIBLE_MODEL", "").strip()
LOCAL_LLAMA_CONFIGURED = bool(LOCAL_LLAMA_BASE and LOCAL_LLAMA_MODEL)

PROVIDERS: list[ModelProvider] = [
    ModelProvider(
        provider="openai_compatible",
        api_base=LOCAL_LLAMA_BASE,
        api_key_alias="NONE_LOCAL_LLAMA_CPP",
        model=LOCAL_LLAMA_MODEL,
        enabled=LOCAL_LLAMA_CONFIGURED,
        status="available_configured" if LOCAL_LLAMA_CONFIGURED else "configuration_required",
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
    return {"items": [provider.model_dump() for provider in PROVIDERS]}


def _encode_api_key(api_key: str) -> str:
    return encryption.encrypt(api_key)


def _decode_api_key(api_key_encrypted: str | None) -> str:
    if not api_key_encrypted:
        return ""
    return encryption.decrypt(api_key_encrypted)


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
    conn = get_conn()
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
    conn.commit()
    return ModelGatewayConfigOut(
        provider=provider,
        api_base=api_base,
        model=model,
        enabled=enabled,
        notes=notes,
    ).model_dump()


def delete_config(provider: str) -> bool:
    _ensure_config_table()
    conn = get_conn()
    deleted = conn.execute(
        "DELETE FROM model_gateway_configs WHERE provider=?", (provider,)
    ).rowcount
    conn.commit()
    return bool(deleted)


def _provider_config(provider_name: str) -> dict | None:
    configured = _get_config(provider_name)
    if configured is not None:
        return configured
    provider = next((item for item in PROVIDERS if item.provider == provider_name), None)
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
    with httpx.Client(timeout=90, follow_redirects=False) as client:
        response = client.post(api_base.rstrip("/") + "/chat/completions", json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
    latency_ms = int((time.perf_counter() - started) * 1000)
    choices = data.get("choices") or []
    text = choices[0].get("message", {}).get("content", "") if choices else ""
    return "ok", latency_ms, text[:600]


def run_provider_test(req: ModelGatewayTestIn) -> ModelGatewayTestOut:
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
    api_base = provider["api_base"]
    try:
        allowlist_env = os.getenv("WANWEI_OPENAI_COMPATIBLE_HOST_ALLOWLIST")
        allowlist = [h.strip() for h in allowlist_env.split(",") if h.strip()] if allowlist_env else None
        validate_external_url(api_base, allowlist=allowlist)
        status, latency_ms, preview = _openai_compatible_smoke(
            api_base,
            provider["api_key"],
            model,
            req.prompt_preview,
            req.max_tokens,
        )
        return ModelGatewayTestOut(
            provider=provider["provider"],
            model=model,
            dry_run=False,
            status=status,
            request_id=request_id,
            message=f"OpenAI-compatible smoke completed via {api_base}.",
            latency_ms=latency_ms,
            response_preview=preview,
        )
    except SSRFError as exc:
        return ModelGatewayTestOut(
            provider=provider["provider"],
            model=model,
            dry_run=False,
            status="ssrf_blocked",
            request_id=request_id,
            message=f"SSRF block: {exc}",
        )
    except (httpx.RequestError, httpx.TimeoutException, httpx.HTTPStatusError, ValueError) as exc:
        return ModelGatewayTestOut(
            provider=provider["provider"],
            model=model,
            dry_run=False,
            status="error",
            request_id=request_id,
            message=f"Model gateway smoke failed: {exc}",
        )
