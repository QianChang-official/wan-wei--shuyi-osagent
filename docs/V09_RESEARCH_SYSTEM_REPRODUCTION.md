# v0.9 Research System Reproduction Edition

## 1. v0.9 目标

v0.9 的目标不是继续写 catalog，也不是风险收敛，而是开始造城：把 v0.8 权威技术吸收矩阵中的 9 条技术路线推进为项目内可运行的轻量复现子系统。

本版本新增 `backend/app/reproduction/`，并在 Vue Studio 中新增 `/console/#/reproduction` 论文复现页。核心 5 个系统提供 dry-run 或读取现有运行数据的可执行逻辑，次级 4 个系统提供 schema/template/API。

## 2. 为什么 v0.8 不够

v0.8 的价值是地图：说明项目站在哪些论文/系统谱系上，哪些技术要吸收，落在哪些舱室，当前状态是什么。

v0.9 的价值是造城：把这些 planned/partial 技术路线变成项目中的 API、数据结构、前端入口和可验证 dry-run。

## 3. Full Reproduction vs Lightweight Reproduction

| 类型 | 含义 | v0.9 状态 |
| --- | --- | --- |
| Full official reproduction | 严格复现论文完整算法、数据集、训练设置、指标和实验 | 未声明、未完成 |
| Lightweight reproduction layer | 在现有 MemoryOps 平台内复现核心机制、数据结构、API 和 dry-run 流程 | 已实现 |

v0.9 不伪造论文指标，不声称完整复现官方系统，不联网调用论文 API，不执行危险工具。

## 4. 九个论文系统复现范围

### 4.1 MemoryArena Workbench

来源：MemoryArena。

核心机制：多会话 Memory-Agent-Environment loop、session timeline、write/read/action trace、assertion failure diagnosis。

当前实现：`GET /reproduction/memoryarena/workbench` 读取 `backend/app/memory_arena/cases/*.json` 和 `reports/production_memory_eval_metrics.json`，生成 case cards、session timeline、metrics、failure_diagnosis。

前端入口：论文复现页的 MemoryArena Workbench 面板。

未完成：case editor、历史趋势数据库、失败断言交互式定位。

状态：partial。

### 4.2 Hippo-Lite Graph Recall

来源：HippoRAG。

核心机制：MemoryCapsule graph、seed retrieval、PageRank-like spreading、evidence path。

当前实现：

- `GET /reproduction/hippo-lite/graph`
- `POST /reproduction/hippo-lite/recall`

从 MemoryCapsule 构建 nodes，从 relation_edges 构建 edges；无边时返回 demo_similarity edges；recall 使用字符串 seed + 2 轮图传播。

前端入口：Hippo-Lite Graph Recall 面板，支持 query 输入和 recall dry-run。

未完成：真实 Personalized PageRank、知识图谱构建、与 FTS baseline 的指标对比。

状态：partial。

### 4.3 MemoryBank Retention Engine

来源：MemoryBank。

核心机制：memory_strength、recall_count、last_recalled_at、forgetting_decay、retention_score。

当前实现：

- `GET /reproduction/retention/state`
- `POST /reproduction/retention/simulate`

retention_score 简化为 `importance * memory_strength / (1 + age_days)`，simulate 支持 recall / reinforce / decay，且不修改真实 capsule。

前端入口：MemoryBank Retention 面板。

未完成：真实状态落库、retrieval 后自动更新、forgetting purge 验证。

状态：partial。

### 4.4 Reflexion Evaluator

来源：Reflexion。

核心机制：Actor / Evaluator / Self-Reflection，failure taxonomy，reflection_quality_score，before/after comparison。

当前实现：

- `GET /reproduction/reflexion/evaluator`
- `POST /reproduction/reflexion/evaluate`

failure taxonomy 包括 missing_memory、unsafe_plan、weak_evidence、conflict_ignored、false_positive_echo、no_failure。evaluate 为 dry-run，不写真实记忆。

前端入口：Reflexion Evaluator 面板。

未完成：与 `reflect_task` 深度合并、质量分数实测、二次任务前后对比指标。

状态：partial。

### 4.5 Memory Tools API

来源：AgeMem / Agentic Memory。

核心机制：memory.add、memory.update、memory.delete、memory.retrieve、memory.summarize、memory.filter。

当前实现：

- `GET /reproduction/memory-tools`
- `POST /reproduction/memory-tools/dry-run`

mutating tools 默认只 dry-run，返回 required_confirmation、audit_required、blocked_reason。

前端入口：Memory Tools API 面板。

未完成：真实 mutating tool 权限链、审计写入、测试隔离库。

状态：partial。

### 4.6 MemCube / MemoryCapsule 2.1

来源：MemOS。

核心机制：memory_scope、memory_tier、scheduler_policy、access_policy、migration_state、sync_state、version_vector。

当前实现：`GET /reproduction/memcube/schema` 返回 MemoryCapsule 2.1 扩展 schema，不执行迁移。

状态：planned。

### 4.7 MemGPT Memory Tier Manager

来源：MemGPT。

核心机制：working_context、active_capsules、archival_capsules、paging_policy、context_budget。

当前实现：`GET /reproduction/memory-tiers` 从现有 capsule 状态生成 tier simulation，不执行真实上下文分页。

状态：planned。

### 4.8 LoCoMo Long-Session Template

来源：LoCoMo。

核心机制：10-session long memory case、event graph、timeline QA、long-range consistency check。

当前实现：`GET /reproduction/locomo/template` 返回 10-session template 与 event graph/timeline QA schema。

状态：planned。

### 4.9 Generative Agents Memory Stream

来源：Generative Agents。

核心机制：observation stream、importance score、reflection trigger、plan timeline。

当前实现：`GET /reproduction/generative-stream/template` 返回 stream schema 和 plan timeline。

状态：planned。

## 5. API 清单

- `GET /reproduction/systems`
- `GET /reproduction/memoryarena/workbench`
- `GET /reproduction/hippo-lite/graph`
- `POST /reproduction/hippo-lite/recall`
- `GET /reproduction/retention/state`
- `POST /reproduction/retention/simulate`
- `GET /reproduction/reflexion/evaluator`
- `POST /reproduction/reflexion/evaluate`
- `GET /reproduction/memory-tools`
- `POST /reproduction/memory-tools/dry-run`
- `GET /reproduction/memcube/schema`
- `GET /reproduction/memory-tiers`
- `GET /reproduction/locomo/template`
- `GET /reproduction/generative-stream/template`

## 6. 验证命令

```bash
PYTHONPATH=backend python3 -m compileall -q backend/app
cd frontend/console-vue && npm run build
./scripts/run_eval.sh
PYTHONPATH=backend backend/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8011
```

API smoke 使用 curl 或 Python urllib 验证上述 reproduction 端点与 `/console/`。

## 7. v1.0 风险收敛计划

v1.0 再进行系统风险收敛：

- 不把 lightweight reproduction 宣传为 full official reproduction。
- 给 Hippo-Lite 与 FTS 做真实对比。
- 给 Retention Engine 增加隔离测试库和 purge verification。
- 给 Reflexion Evaluator 加自我误报回声防护。
- 给 Memory Tools API 增加权限、确认、审计和测试覆盖。
- 给 LoCoMo/Generative Agents 路线加入真实 case 后再声明指标。
