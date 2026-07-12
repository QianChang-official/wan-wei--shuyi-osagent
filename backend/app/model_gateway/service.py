from __future__ import annotations

import os
import time
import uuid

import httpx

from .schemas import ModelGatewayTestIn, ModelGatewayTestOut, ModelProvider
from ..security.ssrf import SSRFError, validate_external_url

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


def list_providers() -> dict:
    return {"items": [provider.model_dump() for provider in PROVIDERS]}


def _openai_compatible_smoke(api_base: str, model: str, prompt: str, max_tokens: int) -> tuple[str, int, str]:
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
    with httpx.Client(timeout=90, follow_redirects=False) as client:
        response = client.post(api_base.rstrip("/") + "/chat/completions", json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
    latency_ms = int((time.perf_counter() - started) * 1000)
    choices = data.get("choices") or []
    text = choices[0].get("message", {}).get("content", "") if choices else ""
    return "ok", latency_ms, text[:600]


def run_provider_test(req: ModelGatewayTestIn) -> ModelGatewayTestOut:
    provider = next((item for item in PROVIDERS if item.provider == req.provider), None)
    model = req.model or (provider.model if provider else "unknown")
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
            provider=provider.provider,
            model=model,
            dry_run=True,
            status="ok",
            request_id=request_id,
            message=f"Dry-run accepted for {provider.provider}; prompt preview length={len(req.prompt_preview)}.",
        )
    if not provider.enabled:
        return ModelGatewayTestOut(
            provider=provider.provider,
            model=model,
            dry_run=False,
            status="not_configured",
            request_id=request_id,
            message="Provider is not configured. Set the documented environment variables and restart the service.",
        )
    if provider.provider != "openai_compatible":
        return ModelGatewayTestOut(
            provider=provider.provider,
            model=model,
            dry_run=False,
            status="blocked_in_alpha",
            request_id=request_id,
            message="Only the local OpenAI-compatible llama.cpp endpoint is enabled for real smoke in this prototype.",
        )
    api_base = provider.api_base
    try:
        allowlist_env = os.getenv("WANWEI_OPENAI_COMPATIBLE_HOST_ALLOWLIST")
        allowlist = [h.strip() for h in allowlist_env.split(",") if h.strip()] if allowlist_env else None
        validate_external_url(api_base, allowlist=allowlist)
        status, latency_ms, preview = _openai_compatible_smoke(api_base, model, req.prompt_preview, req.max_tokens)
        return ModelGatewayTestOut(
            provider=provider.provider,
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
            provider=provider.provider,
            model=model,
            dry_run=False,
            status="ssrf_blocked",
            request_id=request_id,
            message=f"SSRF block: {exc}",
        )
    except (httpx.RequestError, httpx.TimeoutException, httpx.HTTPStatusError, ValueError) as exc:
        return ModelGatewayTestOut(
            provider=provider.provider,
            model=model,
            dry_run=False,
            status="error",
            request_id=request_id,
            message=f"Model gateway smoke failed: {exc}",
        )
