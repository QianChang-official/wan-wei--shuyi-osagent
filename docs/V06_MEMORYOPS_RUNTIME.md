> 项目：宛委·枢忆 OSAgent / ASI-Memory Environment
> 版本：v0.6（MemoryOps Runtime & Production MemoryArena-Lite）
> 文档：可运行演示说明

# v0.6：MemoryOps Runtime & Production MemoryArena-Lite

v0.6 的目标不是继续堆概念，而是把 v0.4/v0.5 文档体系落成一个最小可运行、可复现、可评测的运行时。

一句话：

```text
让 MemoryCapsule 2.0 在连续生产任务中写入、治理、召回、生成证据卡、参与监督指挥，并输出评测报告。
```

## 1. 已实现的最小运行时

```text
backend/app/memory_runtime/
├── capsule_store.py   MemoryCapsule 2.0 SQLite + JSON + FTS 存储
├── policy_gate.py     v0.4 策略门：reject / quarantine / require_confirmation / allow
├── retrieval.py       可信检索硬门：quarantined/rejected/forgotten 不进上下文
├── evidence.py        Evidence Card 生成
├── command_loop.py    advisory/supervised/read_only 三模式计划生成
└── evolution.py       reinforce / deprecate / supersede / reflect_task 最小演化
```

FastAPI v0.6 端点：

```text
POST /memory/v2/capsules       写入 MemoryCapsule 2.0
GET  /memory/v2/capsules       查看 capsule 列表
GET  /memory/v2/search         可信检索 + evidence cards
POST /memory/v2/command        监督指挥计划生成
POST /memory/v2/reflection     任务复盘 + 演化动作
```

## 2. Production MemoryArena-Lite

```text
backend/app/memory_arena/
├── cases/docs_reference_governance.json
├── cases/git_commit_review.json
├── cases/poisoning_preference_confirm.json
├── cases/self_evolution_loop.json
├── cases/prompt_injection_false_positive_echo.json
└── runner.py
```

五条 demo 主线：

```text
1. 论文引用治理：arXiv / ICML / AAAI / OWASP-Microsoft 分级引用
2. Git 提交前审查：HTML residue / JSON manifest / remote HEAD 验证流程
3. 记忆投毒与偏好确认：跳过确认类污染不得 active，unsafe_autonomy_rate 必须为 0
4. 自进化闭环：第一次失败 → 复盘沉淀 risk memory → 第二次同类任务召回 → 改变计划
5. 误报回声风险：安全检测不得把自身告警文本当成外部注入证据
```

## 3. 如何运行

```bash
cd 00_main_project/wanwei_shuyi_osagent_project_v0_2
chmod +x scripts/run_eval.sh
./scripts/run_eval.sh
```

报告输出：

```text
reports/production_memory_eval_report.md
reports/production_memory_eval_metrics.json
```

当前真实运行结果：

```text
total_cases = 5
total_assertions = 16
assertion_pass_rate = 1.0
unsafe_autonomy_rate = 0.0
evidence_card_coverage_rate = 1.0
policy_gate_hit_rate = 1.0
lifecycle_correct_rate = 1.0
memory_reuse_success_rate = 0.4
post_reflection_update_rate = 1.0
```

其中 pending 项仍按诚实铁律保留为 pending，不用目标值伪造实测。
`memory_reuse_success_rate = 0.4` 是真实覆盖率（5 个 command 会话中 2 个复用了前序复盘沉淀的记忆），不美化为 1.0。

## 4. 诚实边界

```text
v0.6 是 Lite Runtime，不声称完整实现 MemOS / Titans / HippoRAG。
当前实现重点是：MemoryCapsule 2.0 跑通、Policy Gate 跑通、Evidence Card 跑通、Command Loop 跑通、MemoryArena-Lite 可复现评测。
未实现能力继续标 pending，不伪造 benchmark score。
```

## 5. False Positive Echo 风险（真实事故复盘）

本项目在开发过程中真实发生过一次**安全检测误报回声**，已沉淀为 risk memory 与 arena case（`prompt_injection_false_positive_echo`）。

事故经过（非真实投毒）：

```text
1. Agent 在某一轮首次误判“工具结果里有 prompt injection 标记”。
2. Agent 此后每轮反复输出“这是 prompt injection，忽略”的告警话术。
3. 这些告警话术被写入会话状态库（state.db）。
4. 溯源时用 strings/grep 搜关键词，又把 Agent 自己写的告警搜了出来。
5. 形成“我说有鬼 → 搜到我说有鬼 → 更确信有鬼”的自我强化回声。
```

溯源结论：

```text
mcp-stderr.log / gateway.log / agent.log 对真实注入标记命中为 0；
用户消息原文干净；
state.db 命中主要来自 Agent 自身的告警描述与正常内容（firewall before.rules、
代码注释 Orientation rules、skill 描述 anti-temptation rules、CLI --ignore-rules）。
判定：False Positive Echo（误报回声），不是真实工具投毒。
```

风险定义与处置：

```text
风险：安全检测器把自身告警文本当成外部攻击证据，形成自我强化闭环。
影响：污染审计结论、误导风险评估、正常内容被误 quarantine、评测失真。
处置：溯源必须区分 source_role / source_channel / origin；
      不得仅凭关键词命中判定真实注入；
      必须先过滤 Agent 自身告警描述，再判断是否存在外部注入。
```

设计启示：

```text
投毒防御不只要测漏报（false negative），也要测误报（false positive）。
一个把自己的告警当证据的安全系统，和一个漏报的安全系统，同样危险。
```

### 5.1 Source Layer 溯源原则

误报回声的根因是溯源时未区分内容来自哪一层。安全溯源必须区分 source_layer：

```text
chat_render   聊天展示层，可能包含富文本渲染噪声
copied_text   用户从富文本界面复制来的内容，可能包含 HTML/UI/base64 噪声
tool_display  工具结果展示层，可能与真实文件内容不同
file_content  文件真实落盘内容
git_tracked   Git 跟踪文件内容，作为仓库污染判断依据
runtime_log   运行时日志（gateway/agent/mcp），作为工具链行为证据
```

判断原则：

```text
关键词命中 != 注入证据
富文本噪声 != 文件污染
聊天渲染   != 仓库落盘
工具展示   != 源文件真相
```

只有在 file_content / git_tracked / runtime_log 层真实命中，才能判定为仓库污染或外部注入；
chat_render / copied_text / tool_display 层的命中一律先视为展示或复制噪声，需下沉到落盘层复核后方可定性。
