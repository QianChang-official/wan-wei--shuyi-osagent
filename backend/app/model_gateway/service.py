from __future__ import annotations

import uuid

from .schemas import ModelGatewayTestIn, ModelGatewayTestOut, ModelProvider


PROVIDERS: list[ModelProvider] = [
    ModelProvider(
        provider="openai_compatible",
        api_base="https://api.example.com/v1",
        api_key_alias="OPENAI_COMPATIBLE_API_KEY",
        model="gpt-4.1-compatible",
        enabled=False,
        status="planned_configurable",
        notes="OpenAI-compatible endpoint stub; stores env alias only, never stores raw key.",
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
        notes="Gemini provider stub; no outbound call is made in v0.7 dry-run.",
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
    return {"items": [provider.dict() for provider in PROVIDERS]}


def test_provider(req: ModelGatewayTestIn) -> ModelGatewayTestOut:
    provider = next((item for item in PROVIDERS if item.provider == req.provider), None)
    model = req.model or (provider.model if provider else "unknown")
    if provider is None:
        return ModelGatewayTestOut(
            provider=req.provider,
            model=model,
            dry_run=req.dry_run,
            status="not_found",
            request_id="mgw_" + uuid.uuid4().hex[:12],
            message="Provider is not registered in the v0.7 model gateway catalog.",
        )
    if not req.dry_run:
        return ModelGatewayTestOut(
            provider=provider.provider,
            model=model,
            dry_run=False,
            status="blocked_in_alpha",
            request_id="mgw_" + uuid.uuid4().hex[:12],
            message="v0.7 only exposes safe dry-run tests. Real outbound calls require v0.8 credential policy.",
        )
    return ModelGatewayTestOut(
        provider=provider.provider,
        model=model,
        dry_run=True,
        status="ok",
        request_id="mgw_" + uuid.uuid4().hex[:12],
        message=f"Dry-run accepted for {provider.provider}; prompt preview length={len(req.prompt_preview)}.",
    )