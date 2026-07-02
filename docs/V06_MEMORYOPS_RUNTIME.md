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
└── runner.py
```

三条 demo 主线：

```text
1. 论文引用治理：arXiv / ICML / AAAI / OWASP-Microsoft 分级引用
2. Git 提交前审查：HTML residue / JSON manifest / remote HEAD 验证流程
3. 记忆投毒与偏好确认：跳过确认类污染不得 active，unsafe_autonomy_rate 必须为 0
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
total_cases = 3
total_assertions = 9
assertion_pass_rate = 1.0
unsafe_autonomy_rate = 0.0
evidence_card_coverage_rate = 1.0
policy_gate_hit_rate = 1.0
lifecycle_correct_rate = 1.0
```

其中 pending 项仍按诚实铁律保留为 pending，不用目标值伪造实测。

## 4. 诚实边界

```text
v0.6 是 Lite Runtime，不声称完整实现 MemOS / Titans / HippoRAG。
当前实现重点是：MemoryCapsule 2.0 跑通、Policy Gate 跑通、Evidence Card 跑通、Command Loop 跑通、MemoryArena-Lite 可复现评测。
未实现能力继续标 pending，不伪造 benchmark score。
```
