# v0.8 Authoritative Technology Adoption Matrix

## 1. v0.8 定位

v0.8 是「权威技术吸收版 / Authoritative Technology Adoption Edition」。它不是继续泛泛扩页面，也不是把项目重新压回小型 demo，而是把 v0.1-v0.7 形成的 MemoryOps 平台与权威论文、顶会技术、前沿 Agent Memory 系统进行系统对齐。

本版本的目标：把 MemoryArena、MemOS、Reflexion、MemoryBank、HippoRAG、LoCoMo、MemGPT、Generative Agents、AgeMem 等技术中可 70%-90% 工程化吸收的部分，落到现有 20 舱平台的 API、数据结构、前端舱室、评测路线和文档矩阵中。

## 2. 权威来源分级

| 等级 | 含义 | 使用边界 |
| --- | --- | --- |
| A | 顶会/正式发表论文 | 可作为核心技术依据，但仍不能声称完整复现 |
| B | arXiv / 前沿预印本 / 大机构系统论文 | 可作为工程吸收参考，publication_status 必须诚实标注 |
| C | 行业治理 / 标准化资料 | 可作为治理和评估框架补充 |
| D | 工程背景 / 博客 / 转载 | 只能作为背景材料，不能作为核心创新依据 |

不确定来源状态时统一标 `needs_verification`，不得把预印本写成顶会已发表。

## 3. 技术吸收总表

| 技术/论文/系统 | 来源级别 | 发表状态 | 核心技术 | 对应舱室 | 可吸收比例 | 当前状态 | v0.8 落地动作 | v0.9 风险收敛动作 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| MemoryArena | B | needs_verification | 多会话 Memory-Agent-Environment loops，write/read/action 轨迹与断言评测 | 归藏评测舱、兰台鉴证 | 90% | partial | case editor 设计、session timeline、interdependent subtasks、memory trace、failure diagnosis、历史报告趋势 | 区分 benchmark 通过率与真实生产成功率；新增 misleading_memory_rate 和 production_task_success_rate 实测 |
| MemOS / MemCube-like | B | arXiv_preprint | Memory as manageable system resource，记忆资源治理与生命周期 | 枢忆核、建木同步、玉衡权限舱 | 85% | partial | MemoryCapsule 2.1 schema extension：memory_scope、memory_tier、scheduler_policy、access_policy、migration_state、sync_state、version_vector | 多设备同步与迁移需实测；access_policy 需安全 case 覆盖 |
| Reflexion | A | confirmed_published | Actor / Evaluator / Self-Reflection，语言反馈强化 | 兰台复盘、Reflection Engine | 85% | partial | reflection evaluator stub、failure taxonomy、reflection_quality_score、before/after comparison、自演化 case 增强路线 | 防止错误复盘自我强化；高影响反思写入必须绑定证据卡 |
| MemoryBank | B | arXiv_preprint | 长期记忆、记忆强化/遗忘、用户个性适应 | 玄珠偏好、忘机机制、司南调参舱 | 85% | partial | memory_strength、recall_count、last_recalled_at、forgetting_decay、retention_score visualization | 情感显著性不得覆盖治理；遗忘 purge 需验证 |
| HippoRAG | B | arXiv_preprint | 知识图谱 + Personalized PageRank 风格扩散召回 | 建木网络、琅嬛知识 | 80% | planned | MemoryCapsule nodes、relation_edges、query seed nodes、PageRank-like spreading recall stub、evidence path display | 与 FTS baseline 对比后再声明收益；防 hallucinated evidence path |
| LoCoMo | B | needs_verification | 长期会话记忆评测、event graph、long-range consistency | 归藏评测舱 Long-Session Mode、玄衡评分舱 | 75%-80% | planned | mini-LoCoMo case template、event graph、timeline QA、long-session scenario catalog | 长会话一致性与短 case pass rate 分离统计 |
| MemGPT | B | arXiv_preprint | virtual context management / memory tiers / OS-like memory | 枢忆核 Memory Tier Manager、通玄模型舱 | 80% | partial | working_context、active_capsules、archival_capsules、paging_policy、context budget panel | 上下文预算策略需实测；分页必须受 trust/source_layer 约束 |
| Generative Agents | A | confirmed_published | memory stream / reflection / planning | 太微观测舱、天工编排舱、兰台复盘 | 70%-80% | planned | observation stream、importance score、reflection trigger、plan timeline | 避免过度拟人化宣称；计划轨迹必须可审计 |
| AgeMem / Agentic Memory | B | needs_verification | memory operations as tool actions：store/retrieve/update/summarize/discard | 百工技能舱、Memory Tools API、玉衡权限舱 | 接口层 80%，训练/RL 层 planned | planned | memory.add/update/delete/retrieve/summarize/filter 接口预埋；tool registry 展示 | mutating tool 必须权限检查与确认；调用写入审计与证据卡 |

## 4. 版本映射

| 版本 | 对应权威路线 | 说明 |
| --- | --- | --- |
| v0.1 | Agent Memory write/retrieve 基础 | 基础记忆写入、检索原型 |
| v0.2 | MemoryBank / MemGPT 结构化记忆 | MemoryCapsule 与偏好/知识双轨 |
| v0.3 | Generative Agents / Reflexion | Memory OS、情感显著性、反思规划雏形 |
| v0.3.1 | Affective boundary correction | 明确情感不得覆盖治理 |
| v0.4 | MemOS governance / privacy / lifecycle | 安全治理、ASI 风险映射、生命周期策略 |
| v0.5 | MemoryBank / Reflexion / MemOS | 偏好—知识优化、监督命令闭环、生产评测设计 |
| v0.6 | MemoryArena / LoCoMo / Reflexion | 可运行 Runtime、MemoryArena-Lite、自演化闭环 |
| v0.7 | MemoryOps Platform | 20 舱平台、模型/技能/调参/导出 stub、国风仪器盘 |
| v0.8 | Authoritative Technology Adoption | 权威技术吸收矩阵、后端 catalog/API、前端权威吸收舱 |
| v0.9 | Risk Convergence & Hardening | 风险收敛、工程硬化、指标实测、边界防夸大 |

## 5. 五大优先落地路线

### 5.1 MemoryArena Workbench

吸收 MemoryArena 的多会话评测思想，把当前 `./scripts/run_eval.sh` 和报告输出升级为 Workbench 路线：case editor、session timeline、write/read/action 轨迹、assertion failure diagnosis、历史报告趋势。

当前状态：partial。已有 5 cases / 16 assertions 的真实基线，但 case editor 与历史趋势仍为 planned。

### 5.2 Hippo-Lite 建木网络

吸收 HippoRAG 的图谱召回思想，但不声称完整复现。v0.8 仅定义轻量路线：MemoryCapsule nodes、relation_edges、query seed nodes、PageRank-like spreading recall stub、evidence path display。

当前状态：planned。v0.9 需要与 FTS5 baseline 对比后才能声明效果提升。

### 5.3 MemoryBank Retention

吸收 MemoryBank 的强化/遗忘机制：memory_strength、recall_count、last_recalled_at、forgetting_decay、retention_score visualization，推动忘机机制 2.0。

当前状态：partial。已有 lifecycle 和忘记 preview/confirm，但 decay 与 purge verification 未完成。

### 5.4 Reflexion Evaluator

吸收 Reflexion 的 Actor/Evaluator/Self-Reflection 结构：reflection evaluator stub、failure taxonomy、reflection_quality_score、before/after comparison，并增强 self_evolution_loop。

当前状态：partial。已有 Reflection/Evolution runtime 与 self_evolution_loop case，但 evaluator scoring 未实装。

### 5.5 Memory Tools API

吸收 AgeMem / Agentic Memory 的工具化方向：memory.add、memory.update、memory.delete、memory.retrieve、memory.summarize、memory.filter。训练/RL 层不实现，只预埋接口和权限策略。

当前状态：planned。v0.9 前 mutating memory tools 必须通过玉衡权限舱和审计流水。

## 6. API 与前端入口

后端新增：

- `GET /research-adoption/technologies`
- `GET /research-adoption/routes`
- `GET /research-adoption/version-map`

前端新增：

- `/console/#/research-adoption`
- 导航组：研究吸收 / 权威吸收
- 页面：技术卡片区、五大路线区、版本映射区、状态统计、done/partial/planned/pending 标签

## 7. 诚实边界

- 未实现项必须标 partial/planned/pending。
- 不把论文对标写成已完整复现。
- 不把 arXiv 写成顶会。
- 不把接口 stub 写成完整实现。
- 不伪造 DOI、指标、论文状态或评测结果。
- v0.8 只做技术吸收和工程路线落地，v0.9 再做系统风险收敛与工程硬化。
