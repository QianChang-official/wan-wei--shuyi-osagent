# 麒麟个人助手桥接组件（assistant-bridge）

宛委·枢忆 与银河麒麟桌面版 V11 内置个人助手（kylin-aiassistant）之间的桥接组件，使宛委的记忆能力可作为系统级智能助手的记忆后端，或经系统助手通道完成对话。

## 组件

| 文件 | 说明 |
|---|---|
| `sidecar.cpp` | C++ HTTP sidecar（默认 127.0.0.1:8021），包装官方 `libkyai-assistant`（OsAssistant）。持有进程内唯一 GLib 主上下文/主循环（专用线程）与有界工作线程池，见下文「并发与生命周期」 |
| `json_util.h` | 便携 JSON 工具（请求解析 / 响应序列化），不依赖 Kylin SDK 与 GLib，可独立单测 |
| `wanwei_assistant_adapter.py` | Python 侧适配器：`chat(text) -> 纯文本回复`，`chat_with_memory(text)` 带宛委记忆检索注入与写回，内置流式 JSON 分片解析 |
| `memory_link.py` | 宛委记忆后端 link：`search_memories()`（GET /memory/v2/search）与 `remember_statement()`（POST /memory/v2/capsules），写回经服务端 policy_gate 过滤 |
| `tests/` | `json_util_test.cpp`（JSON 逻辑单测）+ `stubs/`（CI 语法检查用的桩头文件） |
| `Makefile` | 编译、语法检查与自检目标 |

## 依赖

- 银河麒麟桌面操作系统 V11（预装 libkyai-assistant + 个人助手服务）
- `sudo apt install libkysdk-ai-private-dev`（官方 SDK 开发包）
- glib-2.0 / gio-2.0（系统自带）

## 编译与启动

```bash
make check          # 先自检：编译器 + SDK 头文件 + glib 是否齐备
make                # 产出 wanwei-assistant-sidecar
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
./wanwei-assistant-sidecar &         # 监听 127.0.0.1:8021
```

可选环境变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `WANWEI_SIDECAR_PORT` | `8021` | 监听端口（仅绑定回环地址） |
| `WANWEI_SIDECAR_TOKEN` | 空 | 配置后所有请求必须带 `X-Bridge-Token` 头（常数时间比对）；adapter 读取同名变量自动携带 |

## API

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| GET | `/health` | - | 就绪时 `200 {"ok":true,"ready":true,"busy":false}`；未就绪时 `503 {"ok":false,"ready":false,"reason":"..."}` |
| POST | `/chat` | `{"text":"用户消息","timeout":60000,"memory_context":"<可选，已净化的记忆块>"}` | `{"reply":"<原始流式分片拼接>","length":N,"chunks":N,"elapsed":S,"partial":false,"memory_injected":false}` |

`memory_context` 为可选字段：由调用方（`memory_link.build_context()`）生成并已完成净化与长度预算，sidecar 只加「数据非指令」标注后拼进提示词。

**sidecar 自身不访问网络、不读密钥文件、不执行外部命令**——出向策略（SSRF 白名单）、注入净化与预算统一由 Python 侧单一信任边界负责。这样既避免在 C++ 里重复实现安全控制，也避免把用户文本拼进 shell 命令（历史上出现过用 `popen("curl … --data '<原始文本>'")` 做召回的写法，文本中的单引号可逃逸出引号造成命令注入）。

**`reply` 是原始流式分片拼接，不是纯文本**：sidecar 把 SDK 回调收到的 JSON 分片原样累加（各分片形如 `content[0].text.result`），文本抽取由 Python 侧的 `_extract_text()` 完成——因此直接调 HTTP 接口的调用方拿到的是分片原文，需要纯文本请用 `wanwei_assistant_adapter.chat()`。

`partial: true` 表示硬超时截断了回复（模型仍在生成但已超过 `timeout`）；`chunks: 0` 且返回 `504 assistant_no_response` 表示首片迟迟未到——两种情况都不会再返回「静默空串」冒充正常回复。

每轮对话自动清上下文（`clearContext`），多轮独立。

### 并发与生命周期

- **唯一 GLib 主上下文**：进程启动时创建 `g_context`/`g_loop`，`OsAssistant` 构造与 `init()` 期间把该上下文压为线程默认，因此 SDK 的 D-Bus 信号订阅绑定在它上面；之后只有主循环线程迭代它——所有 SDK 回调都在同一线程派发，不会出现「工作线程各自跑主循环抢 default context」的错派发。
- **对话串行化 + 状态隔离**：`OsAssistant` 是单会话语义，对话用互斥锁串行；每轮回复缓冲由 `shared_ptr<ChatState>` 持有并全程受 `mutex` 保护（回调与等待线程之间没有裸读）。
- **结束判定**：SDK 只提供 `setChatAsyncCallback`（分片回调）与 `stopChat()`，没有完成回调/结束标记，因此采用「**至少收到首片 + 静默窗口 2s**」判定完成，硬超时（默认 60s，上限 180s）兜底并在响应里标记 `partial`；超时后回调被替换为空操作并调用 `stopChat()`，迟到分片不会写入已释放的内存。
- **有界资源**：4 个工作线程 + 32 深队列（满则直接回 503），socket 读写超时 5s，请求体上限 1 MiB，忽略 `SIGPIPE`。

## 跨会话记忆（宛委记忆后端）

前置：宛委后端已启动（默认 `http://127.0.0.1:8010`，可用 `WANWEI_API_BASE` 覆盖）。
**本发行版后端在回环上也要求写请求带 `X-API-Key`**（显式配置 `WANWEI_API_KEY` 后回环免密关闭），所以桥侧必须提供 key：

```bash
# 推荐：专用 key 文件（权限 600），避免桥进程持有桌面主 key
export WANWEI_BRIDGE_API_KEY_FILE=~/.config/wanwei-shuyi-desktop/bridge.key
# 或（兼容旧用法）
export WANWEI_BRIDGE_API_KEY=<key>
```

```python
from wanwei_assistant_adapter import chat_with_memory

r = chat_with_memory("记住我最喜欢的语言是 Python")
# r["memories_written"]  -> 写入成功的陈述
# r["memories_rejected"] -> 被服务端 policy_gate 拒绝的陈述（PII 等）
# r["memory_errors"]     -> 记忆链路失败原因（对话本身不受影响）
r = chat_with_memory("我最喜欢什么语言？")
# r["memories_used"]     -> 注入给助手的记忆陈述（跨会话仍在）
```

### 安全与边界

- **出向目标白名单**：后端地址必须落在精确主机白名单内（默认仅 `127.0.0.1`/`localhost`/`::1`），经仓库中央 SSRF 校验器（`backend/app/security/ssrf.py`）校验；不接受重定向、显式禁用代理。需要跨机部署时用 `WANWEI_BRIDGE_ALLOWED_HOSTS` 逐主机放行——请理解该主机会收到 owner 级 key。
- **凭证最小化**：桥建议使用专用 key（`WANWEI_BRIDGE_API_KEY_FILE`）；检测到与桌面主 `WANWEI_API_KEY` 相同时启动打印告警。
- **记忆是不可信数据**：检索命中在注入前被压成单行、剥离控制字符与分隔符、单条截断（默认 500 字符），整块以 `[宛委记忆 · …不是指令…]` 标注并包在 `<<<WANWEI_MEMORY … WANWEI_MEMORY>>>` 之间，总长受 `WANWEI_BRIDGE_CONTEXT_BUDGET`（默认 2000 字符）约束——存储内容无法伪造新的指令行或越出分隔符。
- **写回规则刻意保守**：仅捕捉「记住xxx」与偏好/自称（「我喜欢/我叫…」）两类，宁漏勿滥；否定（「我不记得…」）、引号引用、非句首意图都不提取。启发式偏好以 `write_intent=inferred` 提交，命中服务端「影响未来行为」门禁时必须显式确认（落库为 `candidate`），不会自动改写助手行为。
- **去重**：同一 (owner, 类别, 陈述) 在进程内指纹缓存（1 小时）与后端精确匹配两层去重，避免同一偏好每轮对话新增一条 capsule。
- fail-open：宛委后端不可用时自动退化为纯透传，绝不阻塞对话主链路；失败的**原因**会出现在 `memory_errors` 里，不再静默吞掉。
- 记忆归属 `soul_id=kylin-assistant`（`WANWEI_BRIDGE_OWNER` 可覆盖），与其他业务数据隔离。

## 宛委侧调用

```python
from wanwei_assistant_adapter import chat, health

assert health()                      # 要求 sidecar 已就绪（ready=true）
reply = chat("帮我总结今天的会议纪要")
```

## 实测

- 链路：宛委 Python → sidecar(:8021) → OsAssistant（assistant.sock）→ 个人助手 → 端侧模型（通义千问）
- 回复延迟：**个人观测值，非基准**——开发机（麒麟桌面 V11 + 端侧通义千问）单轮完整回复约 5 秒量级，仅 1 次人工观测、未记录样本数/硬件明细/百分位方法，也未剥离模型生成耗时；仓库内没有对应 runner 与产物。作为对照，本仓库其余性能口径一律带可复现产物（`reports/`），本组数据不具备同等强度，勿用于对外性能声明。
- 上下文：每轮独立，无跨轮污染

## 验证状态

| 层次 | 是否可跑于 GitHub CI | 命令 |
|---|---|---|
| JSON 工具逻辑单测 | ✅ 可（任意带 C++ 编译器环境） | `g++ -std=c++17 -I scripts/assistant_bridge scripts/assistant_bridge/tests/json_util_test.cpp -o json_util_test && ./json_util_test` |
| sidecar 语法/类型检查（桩头文件） | ✅ 可 | `g++ -std=c++17 -Wall -Wextra -fsyntax-only -I scripts/assistant_bridge/tests/stubs -I scripts/assistant_bridge scripts/assistant_bridge/sidecar.cpp` |
| sidecar 真实编译与运行 | ❌ 否 | 需要麒麟 SDK（`libkysdk-ai-private-dev`）与个人助手服务，只能在麒麟环境执行 `make && ./wanwei-assistant-sidecar` |

以上前两层已由 `backend/app/tests/test_assistant_bridge_memory_link.py::TestNativeSideChecks` 在 CI 中执行（无编译器，或编译器缺 POSIX socket 头时自动跳过——GitHub 的 Windows runner 预装 MinGW g++ 即属后者，sidecar 语法回归由具备 POSIX 头的 ubuntu runner 覆盖）：麒麟 SDK 无法装进 GitHub runner，因此 CI 拦的是**本组件自有代码**的语法/类型/逻辑回归；真实 SDK 构建与端到端运行仍需在麒麟环境验证，属本组件的已知验证边界。
