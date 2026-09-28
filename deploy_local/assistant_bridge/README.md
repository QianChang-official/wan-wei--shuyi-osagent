# wanwei-assistant-sidecar
宛委 · 枢忆 <-> 麒麟个人助手桥接组件

## 组件
- `sidecar.cpp` → `wanwei-assistant-sidecar`: C++ HTTP 服务(127.0.0.1:8021),包装 kyai-assistant(OsAssistant),管理 glib 主循环/流式收集/互斥
- `wanwei_assistant_adapter.py`: 宛委 Python 侧调用封装,含流式 JSON 分片解析

## API
- GET  /health → {"ok":true}
- POST /chat {"text":"..."} → {"reply":"...", "length":N, "timed_out":bool}
  - reply 为流式分片原始 JSON 串的拼接（由 adapter 的 `_extract_text` 解析出纯文本），每轮自动清 context
  - 服务端硬超时 90s：超时返回已收集内容并置 `timed_out:true`（adapter 会附加截断警告）

## 启动
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
nohup /var/data/wanwei-assistant/wanwei-assistant-sidecar > /tmp/sidecar.log 2>&1 &

## 宛委侧调用
from wanwei_assistant_adapter import chat
reply = chat("用户消息")

实测链路: 宛委 python → sidecar(8021) → OsAssistant(assistant.sock) → 个人助手 → kytensor(通义千问端侧)
