# Codex 借鉴：沙箱策略矩阵 + 哈希链执行轨迹

> v0.16 · `backend/app/platform_api/sandbox_policy.py` · `backend/app/audit/rollout.py`
> · 测试 `backend/app/tests/test_codex_borrowed_sandbox_rollout.py`（18 例）

## 许可证与借鉴边界

**openai/codex = Apache License 2.0（Copyright 2025 OpenAI）**——宽松许可，
可引用可衍生（须保留归属声明）。本项目实现为 **Python 自研**，未复制其 Rust
源码；借鉴的是**机制设计与不变量**，并在模块 docstring 与本文标注归属。

与 AstrBot 的对比：AstrBot 是 **AGPL-3.0**，与本项目 Mulan PSL v2 不兼容，
只借鉴架构思想、零代码引用。两者待遇不同是许可证决定的，不是双标。

## 为什么借这两块

本项目已有审批/权限模型（`platform_api/agent_bridge.py` 的能力矩阵 +
封装的 Approval 票据：fingerprint / Fernet 密封 / 300s TTL / owner 绑定），
与 Codex 高度重合，**不重复造**。探索后确认真正的空白只有两处：

| 空白 | 现状 | 本次补齐 |
|---|---|---|
| OS 级沙箱 | `agent_bridge.py:355` 直接 `raise BridgeFailure('process_sandbox_unavailable')`（显式留白） | `sandbox_policy.py`：模式 × 策略二维裁决，接线点已标注 |
| 结构化执行轨迹 | `agent_runs` 是 JsonStore 文件，前端轨迹抽屉未接线 | `audit/rollout.py`：SQLite 哈希链 append-only |

## 一、沙箱策略矩阵（Codex 语义，自研实现）

Codex 官方文档（learn.chatgpt.com/docs/agent-approvals-security）的核心定义：

> "Sandbox mode" 决定技术上能做什么；"Approval policy" 决定越界前是否询问用户。

**必须守住的不变量**：`approval_policy = never` **只关闭审批提示，不扩大沙箱
权限**。把「不询问」读成「允许」是权限设计里最常见的致命误读，策略层用
测试钉死这条。

裁决顺序刻意与 Codex 一致：**先技术边界，后审批**。技术上做不到的事，
审批也不该把它变成「能做」——否则审批机制成了提权后门。

| sandbox mode | fs_read | fs_write | shell | git | device | network |
|---|---|---|---|---|---|---|
| `read_only` | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `workspace_write` | ✅ | ✅* | ✅ | ✅ | ✅ | 开关+审批 |
| `full_access` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

\* 受保护路径例外：`.git` / `.agents` / `.codex` **递归只读**
（Codex 同款），任何非 `full_access` 模式写入这些路径一律 `retryable`。

四态裁决输出（Codex 区分「审批拒绝」与「可重试沙箱拒绝」）：

| outcome | 含义 | 后续动作 |
|---|---|---|
| `allow` | 沙箱内且无需审批 | 直接执行 |
| `approval` | 技术允许但策略要求人工确认 | 出审批票据 |
| `retryable` | 被技术边界拒绝 | 换模式/申请提升后可重试（带 `escalate_to`） |
| `terminal` | 策略层明确禁止 | 重试无意义 |

## 二、哈希链执行轨迹（Codex rollout 思路，自研实现）

Codex 把每个 thread 的执行过程持久化为 rollout 记录以支持 resume。本项目
做成**哈希链 append-only**：`entry_sha256 = H(prev_sha256 ‖ thread_id ‖
turn_index ‖ item_type ‖ item ‖ created_at)`，篡改任一条即导致其后整条链
校验失败，`verify_chain` 精确指出第一处断裂位置。

与既有日志的分工：

- `audit_logs`：平铺事件，面板检索用（无完整性保证）
- `memory_ledger`：记忆生命周期账本（触发器强制 append-only）
- **`agent_rollouts`（新）**：Agent / 感知**执行动作**的结构化轨迹 + 哈希链

方法论与项目一脉相承：不给信任，给证据。

**接线**：感知管道（`perception/pipeline.py`）每个动作落一条轨迹
（`perception_completed` / `perception_fault`）。轨迹失败**不反噬**感知结果
（审计辅助设施不该让主流程失败），缺失会以链短一节的形式被 `verify` 发现。

## API

| 端点 | 说明 |
|---|---|
| `GET /memory/perception/policy` | 当前沙箱模式 × 审批策略（含语义差异声明） |
| `POST /memory/perception/policy/decide` | 对候选操作做准入裁决 |
| `GET /memory/audit/rollout/{thread_id}` | 执行轨迹条目 |
| `GET /memory/audit/rollout/{thread_id}/verify` | 哈希链完整性校验 |

环境变量：`WANWEI_SANDBOX_MODE`（默认 `workspace_write`）、
`WANWEI_APPROVAL_POLICY`（默认 `on_request`）——默认保持严格。

## 边界声明（诚实清单）

- **不是 OS 级隔离**。本模块是**准入裁决**层：回答「该不该允许、要不要问人」，
  不提供 seccomp/namespace 级别的强制隔离。Codex 靠 Landlock/seatbelt 实现
  强制，本项目在麒麟环境的等价物尚未落地——`agent_bridge` 的占位失败仍在，
  接线点已标注，等并行改动收敛后再合。
- `approval_policy = on_failure` 保留但**语义自定义**为「执行失败后才允许人工
  介入」；Codex 当前文档只定义 `never` / `on-request`，该值以
  `POLICY_SEMANTICS_NOTE` 显式声明差异，不假装与上游一致。
- 轨迹表与记忆表同库，**不做独立对象存储**；单节点形态不变。