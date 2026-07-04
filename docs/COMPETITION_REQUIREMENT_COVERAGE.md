# Competition Requirement Coverage

本文件把比赛方案要求映射到宛委·枢忆 MemoryOps Autopilot Platform 的模块、实现、演示路径、证据文件和状态。状态含义：

- done：已有可运行实现或真实报告支撑。
- partial：已有 API / UI / 数据结构 / 文档映射，但仍需深化。
- planned：已有设计和入口，后续版本实现。
- pending：不能声明完成，等待实测或材料补齐。

| 赛题要求 | 项目模块 | 当前实现 | 演示路径 | 证据文件 | 状态 |
| --- | --- | --- | --- | --- | --- |
| 多源数据接入 | 石渠校验、昭明数据舱 | MemoryEventIn、CapsuleWriteIn、data/samples、data/eval；source_layer 设计已进入平台模块 | `/console/#/platform` | `backend/app/schemas.py`, `data/samples/demo_events.json`, `docs/V07_MEMORYOPS_AUTOPILOT_PLATFORM.md` | partial |
| 偏好动态捕捉 | 玄珠偏好、灵犀情感 | `memory_class=preference`、`affects_future_behavior`、确认门策略；情感显著性为 metadata 设计 | `/console/#/capsules`, `/console/#/tuning` | `backend/app/memory_runtime/policy_gate.py`, `docs/PREFERENCE_KNOWLEDGE_MEMORY_ARCHITECTURE.md` | partial |
| 偏好版本管理 | 玄珠偏好、枢忆核 | Capsule state/provenance 支持版本语义；完整 preference version chain 未深度实现 | `/console/#/platform` | `docs/PREFERENCE_KNOWLEDGE_EVOLUTION_POLICY.md`, `docs/MEMORY_CAPSULE_V2_SCHEMA.md` | planned |
| 偏好跨场景适配 | 玄珠偏好、司南调参舱 | scene/task_type/production_context 字段已存在；跨场景策略仍为设计 | `/console/#/tuning` | `backend/app/schemas.py`, `backend/app/tuning/service.py` | partial |
| 知识结构化整合 | 琅嬛知识、兰台鉴证 | knowledge Capsule、provenance、Evidence Cards、引用治理 case | `/console/#/search` | `backend/app/memory_runtime/evidence.py`, `backend/app/memory_arena/cases/docs_reference_governance.json` | done |
| 冲突融合 | 琅嬛知识、建木网络 | relation_edges 与 conflicted/supersedes 设计；冲突融合算法尚未完整落地 | `/console/#/platform` | `docs/MEMORY_CAPSULE_V2_SCHEMA.md`, `backend/app/platform/service.py` | partial |
| 关联检索 | 建木网络、枢忆核 | SQLite + FTS5 检索已可运行；多跳图谱召回仍待深化 | `/console/#/search` | `backend/app/memory_runtime/retrieval.py`, `backend/app/db.py` | partial |
| 流程/案例/模板复用 | 琅嬛知识、归藏评测舱 | MemoryArena cases、reports、知识模板文档；模板库 UI 待深化 | `/console/#/`, `/console/#/platform` | `backend/app/memory_arena/cases/*.json`, `reports/production_memory_eval_report.md` | partial |
| 端侧轻量部署 | 枢忆核、FastAPI Runtime | FastAPI + SQLite + Vue dist 挂载 `/console`，无外部数据库依赖 | `http://localhost:8010/console/` | `backend/app/main.py`, `frontend/console-vue/dist/`, `docs/DEPLOYMENT.md` | done |
| 检索延迟目标 | 太微观测舱、司南调参舱 | latency_target_ms 已标注 pending_measurement；尚未做实测 benchmark | `/console/#/tuning` | `backend/app/tuning/service.py` | pending |
| 敏感信息过滤 | 司契护栏、玉衡权限舱 | Policy Gate 输出 allow/require_confirmation/quarantine/reject；安全 case 已运行 | `/console/#/command`, `/console/#/audit` | `backend/app/memory_runtime/policy_gate.py`, `backend/app/memory_arena/cases/poisoning_preference_confirm.json` | done |
| 自然语言精准遗忘 | 忘机机制 | forget preview/confirm legacy endpoint 与审计记录存在；purge 验证待深化 | `/memory/forget/preview`, `/memory/forget/confirm` | `backend/app/main.py`, `docs/MEMORY_GOVERNANCE_POLICY.md` | partial |
| 短期/中期/长期记忆流转 | 枢忆核 | MemoryCapsule lifecycle、active/quarantined/forgotten/rejected；中期缓存策略待细分 | `/console/#/capsules` | `backend/app/memory_runtime/capsule_store.py`, `docs/MEMORY_CAPSULE_V2_SCHEMA.md` | partial |
| 偏好提取准确率目标 | 玄衡评分舱、玄珠偏好 | 指标舱室已规划；暂无实测准确率 | `/console/#/platform` | `backend/app/platform/service.py` | pending |
| 知识召回率目标 | 玄衡评分舱、琅嬛知识 | MemoryArena 记录 memory_reuse_success_rate=0.4；知识召回率专项未单独实测 | `/console/#/` | `reports/production_memory_eval_metrics.json` | pending |
| 冲突处理率目标 | 玄衡评分舱、建木网络 | 冲突处理率指标已规划；暂无真实统计 | `/console/#/platform` | `docs/V07_MEMORYOPS_AUTOPILOT_PLATFORM.md` | pending |
| OpenAI / Anthropic / Gemini 模型网关 | 通玄模型舱 | provider catalog 与 dry-run API；不保存真实 key，不执行真实外部调用 | `/console/#/model-gateway`, `/model-gateway/providers` | `backend/app/model_gateway/service.py`, `frontend/console-vue/src/views/ModelGatewayView.vue` | partial |
| MCP servers / Skills registry | 百工技能舱 | 工具/技能注册表 API 与 UI，含权限、沙箱、结果入库策略 | `/console/#/skills` | `backend/app/tool_registry/service.py`, `frontend/console-vue/src/views/SkillsRegistryView.vue` | partial |
| 可手动修改参数 | 司南调参舱 | 参数默认值 API 与 UI；配置持久化待实现 | `/console/#/tuning` | `backend/app/tuning/service.py`, `frontend/console-vue/src/views/TuningView.vue` | partial |
| 平台模块矩阵 | 20 舱平台控制面 | `/platform/modules` 同源驱动 README、前端和文档映射 | `/console/#/platform`, `/platform/modules` | `backend/app/platform/service.py`, `frontend/console-vue/src/views/PlatformView.vue` | done |
| PPT | 云笈导出舱 | 导出包状态已有 pending 标注，未生成 PPT | `/console/#/exports` | `backend/app/export_center/service.py` | pending |
| 技术方案 | 云笈导出舱 | README + v0.7 平台文档 + 架构文档支撑 | `/console/#/exports` | `README.md`, `docs/V07_MEMORYOPS_AUTOPILOT_PLATFORM.md`, `docs/ARCHITECTURE.md` | partial |
| 测试报告 | 兰台鉴证、归藏评测舱 | MemoryArena-Lite 报告已生成 | `/console/#/` | `reports/production_memory_eval_metrics.json`, `reports/production_memory_eval_report.md` | done |
| 源码 | 全项目 | FastAPI、Vue、MemoryRuntime、Arena 与 v0.7 stub/API 已在源码中 | 本仓库 | `backend/`, `frontend/`, `scripts/` | done |
| 用户手册 | 云笈导出舱 | 已有用户手册，需后续同步 v0.7 新页面 | `/console/#/exports` | `docs/USER_MANUAL.md` | partial |
| 适配测试报告 | 云笈导出舱、麒麟适配 | 已有兼容性报告与麒麟文档映射，需随 v0.7 API 更新复测 | `/console/#/exports` | `docs/COMPATIBILITY_TEST_REPORT.md`, `docs/KYLIN_DOCS_MAPPING.md` | partial |
| 演示视频 | 云笈导出舱 | 未生成视频，仅有演示路径和控制台入口 | `/console/#/exports` | 无 | pending |

## 当前真实评测基线

| 指标 | 值 |
| --- | --- |
| total_cases | 5 |
| total_assertions | 16 |
| assertion_pass_rate | 1.0 |
| unsafe_autonomy_rate | 0.0 |
| memory_reuse_success_rate | 0.4 |
| post_reflection_update_rate | 1.0 |
| misleading_memory_rate | pending |
| production_task_success_rate | pending |

## 证据原则

1. 没有实测的指标保持 pending。
2. 只有 API/UI/stub 的能力标 partial 或 planned。
3. 真实可运行 Runtime、Arena 报告和源码能力才标 done。
4. 不把 v0.7 扩张阶段的规划项包装成完整企业生产能力。
