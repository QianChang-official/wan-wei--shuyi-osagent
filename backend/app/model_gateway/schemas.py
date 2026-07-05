from pydantic import BaseModel


class ModelProvider(BaseModel):
    provider: str
    api_base: str
    api_key_alias: str
    model: str
    enabled: bool = False
    status: str = "stub"
    notes: str = ""


class ModelGatewayTestIn(BaseModel):
    provider: str
    model: str | None = None
    dry_run: bool = True
    prompt_preview: str = "MemoryOps gateway dry-run"
    max_tokens: int = 96


class ModelGatewayTestOut(BaseModel):
    provider: str
    model: str
    dry_run: bool
    status: str
    request_id: str
    message: str
    key_policy: str = "真实 key 不入库、不回显、不打印"
    latency_ms: int | None = None
    response_preview: str | None = None