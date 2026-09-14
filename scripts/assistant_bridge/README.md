# 麒麟个人助手桥接组件（assistant-bridge）

宛委·枢忆 与银河麒麟桌面版 V11 内置个人助手（kylin-aiassistant）之间的桥接组件，使宛委的记忆能力可作为系统级智能助手的记忆后端，或经系统助手通道完成对话。

## 组件

| 文件 | 说明 |
|---|---|
| `sidecar.cpp` | C++ HTTP sidecar（127.0.0.1:8021），包装官方 `libkyai-assistant`（OsAssistant），负责 glib 主循环、流式回复收集、线程互斥、每轮上下文清理 |
| `wanwei_assistant_adapter.py` | Python 侧适配器：`chat(text) -> 纯文本回复`，`chat_with_memory(text)` 带宛委记忆检索注入与写回，内置流式 JSON 分片解析 |
| `memory_link.py` | 宛委记忆后端 link：`search_memories()`（GET /memory/v2/search）与 `remember_statement()`（POST /memory/v2/capsules），写回经服务端 policy_gate 过滤 |
| `Makefile` | 一键编译 |

## 依赖

- 银河麒麟桌面操作系统 V11（预装 libkyai-assistant + 个人助手服务）
- `sudo apt install libkysdk-ai-private-dev`（官方 SDK 开发包）
- glib-2.0 / gio-2.0（系统自带）

## 编译与启动

```bash
make
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
./wanwei-assistant-sidecar &         # 监听 127.0.0.1:8021
```

## API

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| GET | `/health` | - | `{"ok": true}` |
| POST | `/chat` | `{"text": "用户消息"}` | `{"reply": "纯文本回复", "length": N}` |

每轮对话自动清上下文（`clearContext`），多轮独立。

## 跨会话记忆（宛委记忆后端）

前置：宛委后端已启动（默认 `http://127.0.0.1:8000`，可用 `WANWEI_API_BASE` 覆盖；
回环绑定免 API key）。

```python
from wanwei_assistant_adapter import chat_with_memory

r = chat_with_memory("记住我最喜欢的语言是 Python")
# r["memories_written"] -> 写入的陈述（经服务端 policy_gate，PII 自动拒绝）
r = chat_with_memory("我最喜欢什么语言？")
# r["memories_used"]    -> 注入给助手的记忆陈述（跨会话仍在）
```

- 写回规则刻意保守：仅捕捉「记住xxx」与偏好/自称（「我喜欢/我叫…」）两类，
  宁漏勿滥；内容过滤以服务端 policy_gate 裁决为准。
- fail-open：宛委后端不可用时自动退化为纯透传，绝不阻塞对话主链路。
- 记忆归属 `soul_id=kylin-assistant`（`WANWEI_BRIDGE_OWNER` 可覆盖），
  与其他业务数据隔离。

## 宛委侧调用

```python
from wanwei_assistant_adapter import chat, health

assert health()
reply = chat("帮我总结今天的会议纪要")
```

## 实测

- 链路：宛委 Python → sidecar(:8021) → OsAssistant（assistant.sock）→ 个人助手 → 端侧模型（通义千问）
- 回复延迟：约 5 秒内完成完整回复（流式分片收集后拼接）
- 上下文：每轮独立，无跨轮污染
