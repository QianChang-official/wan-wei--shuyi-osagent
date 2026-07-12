from pydantic import BaseModel, Field


class ModelProvider(BaseModel):
    provider: str
    api_base: str
    api_key_alias: str
    model: str
    enabled: bool = False
    status: str = "stub"
    notes: str = ""


class ModelGatewayConfigIn(BaseModel):
    provider: str = Field(
        min_length=1,
        pattern=r"^[A-Za-z0-9_-][A-Za-z0-9._-]*$",
    )
    api_base: str = Field(min_length=1)
    api_key: str = ""
    model: str = Field(min_length=1)
    enabled: bool = False
    notes: str = ""


class ModelGatewayConfigOut(BaseModel):
    provider: str
    api_base: str
    api_key: str = "***"
    model: str
    enabled: bool = False
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
    key_policy: str = "真实 key 仅以 Fernet 加密存储，不回显、不打印"
    latency_ms: int | None = None
    response_preview: str | None = None
