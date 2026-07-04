# OSAgent Model Gateway Flow

本图说明本地 llama.cpp 模型通过 OpenAI-compatible API 接入后，宛委·枢忆 OSAgent 的完整运行链路。当前接入点是 `openai_compatible` provider，WSL 通过 Windows WSL vEthernet 地址访问 Windows 上的 `llama-server`。

## Current Runtime State

- Frontend: `frontend/console-vue` built dist mounted at `/console/`.
- Backend: FastAPI `app.main:app`.
- Model gateway API: `GET /model-gateway/providers`, `POST /model-gateway/test`.
- Local model endpoint: `http://172.29.128.1:8084/v1`.
- Windows llama.cpp server: `llama-server` OpenAI-compatible `/v1/chat/completions`.
- Model file: `C:\LLMShare\Huihui-Qwen3.6-35B-A3B-Claude-4.7-Opus-abliterated-ggml-model-Q4_K.gguf`.
- Key policy: no API key is stored, echoed, or printed for the local endpoint.

## End-to-End Flow

```mermaid
flowchart LR
    U[User / Judge / Operator] --> UI[Vue MemoryOps Studio\n/console]
    UI --> MGW[通玄模型舱\nModelGatewayView]
    MGW --> API[FastAPI Backend\n/model-gateway/test]

    API --> CATALOG[Provider Catalog\nopenai_compatible]
    CATALOG --> BASE[api_base\nhttp://172.29.128.1:8084/v1]
    BASE --> LCPP[Windows llama-server\nOpenAI-compatible API]
    LCPP --> GGUF[Huihui Qwen3.6 35B A3B GGUF\nQ4_K]
    GGUF --> RESP[chat.completions response]

    RESP --> API
    API --> LOG[Smoke Result\nstatus / latency_ms / response_preview]
    LOG --> MGW
    MGW --> UI

    API --> POLICY[司契 Policy Gate\npermission / dry-run boundary]
    POLICY --> MEM[枢忆核 MemoryCapsule\nSQLite + FTS5]
    POLICY --> EVID[兰台 Evidence Cards\nsource_layer + audit]
    POLICY --> LOOP[指挥闭环 Command Loop\ntool plan + model output]
    LOOP --> REFLECT[复盘演化 Reflection]
    REFLECT --> ARENA[MemoryArena-Lite\nreports metrics]
    ARENA --> UI
```

## OSAgent Control Loop After Model Access

```mermaid
sequenceDiagram
    participant User as User
    participant Console as Vue Console
    participant Backend as FastAPI OSAgent Runtime
    participant Policy as Policy Gate
    participant Memory as MemoryCapsule / FTS5
    participant Gateway as Model Gateway
    participant Llama as llama-server 8084
    participant Audit as Evidence / Audit / Arena

    User->>Console: Submit task or run model smoke
    Console->>Backend: POST /model-gateway/test or runtime API
    Backend->>Policy: classify risk and execution mode
    Policy->>Memory: retrieve relevant capsules and evidence handles
    Backend->>Gateway: select openai_compatible provider
    Gateway->>Llama: POST /v1/chat/completions
    Llama-->>Gateway: assistant message
    Gateway-->>Backend: status, latency_ms, response_preview
    Backend->>Audit: record evidence boundary and result summary
    Backend-->>Console: structured response
    Console-->>User: visual panel + dry-run/real-smoke result
```

## Source Layer Boundary

```mermaid
flowchart TD
    INPUT[Incoming signal] --> LAYER{source_layer?}
    LAYER -->|file_content / git_tracked / runtime_log| ACCEPT[Accept as engineering evidence]
    LAYER -->|chat_render / copied_text / tool_display| IGNORE[Ignore as residue evidence]
    ACCEPT --> CONTRACT[Contract Truth\nAPI + schema + frontend + smoke + docs]
    CONTRACT --> VERIFY[compile / npm build / API smoke / visual fallback]
    IGNORE --> NOTE[Do not report as repository pollution]
```

## What Is Implemented

- `backend/app/model_gateway/service.py` now registers `openai_compatible` as an enabled local llama.cpp provider.
- `POST /model-gateway/test` supports real smoke for the local OpenAI-compatible endpoint when `dry_run=false`.
- `frontend/console-vue/src/views/ModelGatewayView.vue` exposes both `Dry-run` and `真实 smoke` buttons.
- The model response is returned only as a short `response_preview`; no raw key is stored or displayed.

## What Remains Partial

- The model is currently connected for gateway smoke and demonstration, not yet wired into every OSAgent runtime decision path.
- The command loop still needs a formal provider-selection policy before model output can drive broader task execution.
- Cost tracking is still relative / planned; real token accounting from llama.cpp is not yet persisted.
- Long-session model evaluation and visual QA over generated responses are planned follow-ups.

## Verification Commands

```bash
curl http://127.0.0.1:8011/model-gateway/providers
curl -X POST http://127.0.0.1:8011/model-gateway/test \
  -H 'Content-Type: application/json' \
  -d '{"provider":"openai_compatible","dry_run":false,"prompt_preview":"请用一句中文确认模型接入。","max_tokens":96}'
```
