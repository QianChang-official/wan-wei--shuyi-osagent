# Version Lineage

本文件记录宛委·枢忆 MemoryOps Autopilot Platform 从 v0.1 到 v0.8 的版本谱系。它用于说明每一版解决了什么、留下了什么、被后续版本如何继承，以及背后的权威技术支撑。

## v0.1 基础记忆原型

定位：Agent Memory write/retrieve 基础原型。

已完成：

- 基础记忆写入。
- 初始检索概念。
- 多源偏好与知识记忆方向雏形。

未完成：

- 治理策略。
- Evidence Cards。
- MemoryArena 评测。

后续继承：

- v0.2 MemoryCapsule。
- v0.6 Runtime。

权威支撑：

- Agent memory write/retrieve 基础路线。

证据文件：

- `docs/PLAN.md`
- `docs/ARCHITECTURE.md`

## v0.2 MemoryCapsule 与偏好/知识双轨

定位：结构化记忆容器与 preference / knowledge 双轨。

已完成：

- MemoryCapsule 抽象。
- 偏好记忆与知识记忆分流。
- 初始 schema 设计。

未完成：

- 生命周期治理。
- 评测闭环。
- 安全策略门。

后续继承：

- v0.5 偏好—知识优化层。
- v0.8 MemOS / MemGPT 对齐。

权威支撑：

- MemoryBank。
- MemGPT。

证据文件：

- `docs/MEMORY_CAPSULE_V2_SCHEMA.md`

## v0.3 Memory OS 与情感感知记忆

定位：把记忆从数据结构推进到 Memory OS，并引入情感显著性。

已完成：

- 情感显著性概念。
- 反思/规划方向雏形。
- Memory OS 叙事骨架。

未完成：

- 情感边界。
- 情感调权与安全治理的优先级规则。

后续继承：

- v0.3.1 情感边界校正。
- v0.7 国风平台舱室。

权威支撑：

- Generative Agents。
- Reflexion。
- Affective memory references。

证据文件：

- `docs/AFFECTIVE_MEMORY_BRANCH.md`

## v0.3.1 情感边界校正

定位：明确灵犀情感不能覆盖司契护栏。

已完成：

- 情感只调 retention/retrieval 排序。
- 安全治理优先级高于情感显著性。

未完成：

- 情感显著性指标实测。
- 反馈强度长期趋势可视化。

后续继承：

- v0.5 偏好知识优化。
- v0.8 MemoryBank retention route。

权威支撑：

- Affective computing。
- MemoryBank personalization。

证据文件：

- `docs/AFFECTIVE_MEMORY_BRANCH.md`
- `docs/MEMORY_GOVERNANCE_POLICY.md`

## v0.4 安全记忆治理底座

定位：长期记忆安全治理、ASI 风险映射、生命周期策略。

已完成：

- `ASI_ORIENTED_MEMORY_ENVIRONMENT.md`
- `MEMORY_GOVERNANCE_POLICY.md`
- `MEMORY_SECURITY_EVAL.md`
- `ASI_RISK_MAPPING.md`

未完成：

- 可运行策略门集成。
- 自动化评测。

后续继承：

- v0.6 Policy Gate。
- v0.8 MemOS governance mapping。

权威支撑：

- MemOS governance framing。
- Privacy / lifecycle governance references。

证据文件：

- `docs/MEMORY_GOVERNANCE_POLICY.md`
- `docs/ASI_RISK_MAPPING.md`
- `docs/MEMORY_SECURITY_EVAL.md`

## v0.5 偏好—知识记忆优化层

定位：偏好知识记忆从静态存储推进到演化策略和监督闭环。

已完成：

- `PREFERENCE_KNOWLEDGE_MEMORY_ARCHITECTURE.md`
- `MEMORY_CAPSULE_V2_SCHEMA.md`
- `PREFERENCE_KNOWLEDGE_EVOLUTION_POLICY.md`
- `OVERSIGHT_COMMAND_LOOP.md`
- `PRODUCTION_MEMORY_EVAL.md`

未完成：

- Runtime API。
- MemoryArena 实测指标。

后续继承：

- v0.6 MemoryOps Runtime。
- v0.8 MemoryBank retention 和 Reflexion evaluator。

权威支撑：

- MemoryBank。
- Reflexion。
- MemOS。

证据文件：

- `docs/PREFERENCE_KNOWLEDGE_EVOLUTION_POLICY.md`
- `docs/PRODUCTION_MEMORY_EVAL.md`

## v0.6 MemoryOps Runtime + Production MemoryArena-Lite

定位：可运行 Runtime 与生产评测雏形。

已完成：

- FastAPI。
- SQLite + FTS5。
- MemoryCapsule 2.0。
- Policy Gate。
- Evidence Cards。
- Command Loop。
- Reflection / Evolution。
- MemoryArena-Lite。
- 5 cases / 16 assertions。

未完成：

- Long-session evaluation。
- misleading_memory_rate 实测。
- production_task_success_rate 实测。

后续继承：

- v0.7 平台仪器盘。
- v0.8 MemoryArena Workbench。

权威支撑：

- MemoryArena。
- LoCoMo。
- Reflexion。

证据文件：

- `docs/V06_MEMORYOPS_RUNTIME.md`
- `backend/app/memory_arena/runner.py`
- `reports/production_memory_eval_report.md`

## v0.7 MemoryOps Autopilot Platform

定位：从 Runtime 扩张为平台级研究原型和国风 MemoryOps Studio。

已完成：

- 20 舱平台模块。
- README 平台门面。
- v0.7 平台文档。
- 赛题覆盖矩阵。
- Model Gateway stub。
- Tool Registry / MCP Skills stub。
- Tuning defaults stub。
- Export Center stub。
- Vue 3 国风仪器盘。

未完成：

- 多设备同步深度实现。
- 观测指标采集。
- 评分舱实测。
- 多 Agent 编排。
- 一键材料生成。

后续继承：

- v0.8 权威技术吸收舱。
- v0.9 工程硬化。

权威支撑：

- MemoryOps platform synthesis。
- MCP/Skills orchestration framing。

证据文件：

- `README.md`
- `docs/V07_MEMORYOPS_AUTOPILOT_PLATFORM.md`
- `docs/COMPETITION_REQUIREMENT_COVERAGE.md`
- `backend/app/platform/service.py`

## v0.8 Authoritative Technology Adoption Edition

定位：权威技术吸收版，把前沿 Agent Memory 技术工程化映射到 20 舱平台。

已完成：

- `docs/V08_AUTHORITATIVE_TECH_ADOPTION_MATRIX.md`
- `docs/VERSION_LINEAGE.md`
- `backend/app/research_adoption/`
- `GET /research-adoption/technologies`
- `GET /research-adoption/routes`
- `GET /research-adoption/version-map`
- 前端 `ResearchAdoptionView.vue`
- 导航新增「研究吸收 / 权威吸收」。

未完成：

- MemoryArena Workbench 深度实现。
- Hippo-Lite graph recall 算法实测。
- MemoryBank retention 字段迁移。
- Reflexion evaluator scoring。
- Memory Tools API mutating operations。
- 外部论文状态逐条联网核验。

后续继承：

- v0.9 风险收敛与工程硬化。
- 指标实测、权限策略、工具写入审计和端侧适配复测。

权威支撑：

- MemoryArena。
- MemOS。
- Reflexion。
- MemoryBank。
- HippoRAG。
- LoCoMo。
- MemGPT。
- Generative Agents。
- AgeMem / Agentic Memory。

证据文件：

- `docs/V08_AUTHORITATIVE_TECH_ADOPTION_MATRIX.md`
- `backend/app/research_adoption/service.py`
- `frontend/console-vue/src/views/ResearchAdoptionView.vue`

## v0.9 继承目标

定位：风险收敛与工程硬化。

计划处理：

- 不确定论文状态联网核验。
- partial/planned/pending 能力二次收敛。
- API stub 到真实配置落盘。
- MemoryArena case 扩容。
- 权限、审计、工具写入确认。
- 麒麟环境适配复测。
- 指标与宣传口径防夸大。
