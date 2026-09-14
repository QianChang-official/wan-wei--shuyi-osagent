# 麒麟个人助手桥接组件（assistant-bridge）

宛委·枢忆 与银河麒麟桌面版 V11 内置个人助手（kylin-aiassistant）之间的桥接组件，使宛委的记忆能力可作为系统级智能助手的记忆后端，或经系统助手通道完成对话。

## 组件

| 文件 | 说明 |
|---|---|
| `sidecar.cpp` | C++ HTTP sidecar（127.0.0.1:8021），包装官方 `libkyai-assistant`（OsAssistant），负责 glib 主循环、流式回复收集、线程互斥、每轮上下文清理 |
| `wanwei_assistant_adapter.py` | Python 侧适配器：`chat(text) -> 纯文本回复`，内置流式 JSON 分片解析 |
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
