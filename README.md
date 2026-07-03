# 宛委·枢忆 MemoryOps Autopilot Platform

面向麒麟 OS Agent 的全自动记忆治理、模型调用、MCP/Skills 编排与生产闭环平台。

> 不是记忆 demo，而是一台可以自行闭环的精密生产仪器。

## 项目定位

宛委·枢忆不是普通 RAG，也不是单一长期记忆模块。项目把长期记忆提升为 OS Agent 的生产控制平面：

多源数据接入 -> 石渠校验 -> 司契 Policy Gate -> MemoryCapsule 2.0 -> 可信检索 / Evidence Cards -> 指挥闭环 -> 复盘演化 -> MemoryArena 评测 -> 审计追踪与材料导出。

v0.7 的目标是把 v0.6 Runtime + Arena + 国风控制台扩张成平台级工程：后端提供可运行 API 和清晰 stub，前端展示 20 舱平台仪器盘，文档覆盖比赛方案、交付材料和真实边界。

## 赛题覆盖

| 赛题方向 | 项目支撑 |
| --- | --- |
| 多源数据接入 | 石渠校验、昭明数据舱、source_layer、JSON/Markdown/PDF/日志入口设计 |
| 偏好动态捕捉 | 玄珠偏好、MemoryCapsule 2.0、确认门、跨场景 metadata |
| 知识结构化整合 | 琅嬛知识、Evidence Cards、provenance、引用规范、模板沉淀 |
| 冲突融合 | 建木网络、relation_edges、conflicted/supersedes/derived_from 设计 |
| 关联检索 | SQLite + FTS5、可信检索、证据卡跳转 Capsule |
| 端侧轻量部署 | FastAPI + SQLite + Vue dist 挂载 `/console`，适配麒麟 OS Agent 演示链路 |
| 安全过滤 | 司契护栏、Policy Gate、quarantine/reject/require_confirmation |
| 自然语言精准遗忘 | 忘机机制、forget preview/confirm、审计记录 |
| 短期/中期/长期记忆流转 | MemoryCapsule lifecycle、active/quarantined/forgotten/rejected 状态 |
| 量化评测 | MemoryArena-Lite、5 cases / 16 assertions、reports 输出 |
| 麒麟 OS Agent 适配 | `docs/KYLIN_DOCS_MAPPING.md`、`docs/COMPATIBILITY_TEST_REPORT.md` |
| 提交材料支撑 | 云笈导出舱、README、技术方案、测试报告、用户手册、适配测试报告映射 |

完整矩阵见 `docs/COMPETITION_REQUIREMENT_COVERAGE.md`。

## 平台架构：20 舱 MemoryOps Studio

祖宗主线不可删，只能加：

1. 石渠校验：输入质量、格式校验、source_layer 复核、富文本噪声识别、HTML/UI/base64 复制噪声隔离、JSON/Markdown/PDF/日志入口校验。
2. 司契护栏：安全治理、策略门、确认机制、投毒隔离、越权拦截、风险分级、require_confirmation、quarantine、reject。
3. 枢忆核：MemoryCapsule 2.0 生命周期、SQLite/FTS/索引、状态管理、provenance、governance、state、relation_edges。
4. 玄珠偏好：偏好抽取、显式偏好、推断偏好、版本管理、确认门、跨场景适配、偏好回溯。
5. 琅嬛知识：知识结构化、引用规范、SOTA/论文/文档知识、冲突融合、模板复用、流程知识沉淀。
6. 建木网络：关系图谱、关联召回、记忆边、上下游证据传播、实体关系、多跳关系、记忆依赖网。
7. 灵犀情感：情感显著性、重要性调权、反馈强度、用户语气信号，但不得覆盖治理。
8. 忘机机制：遗忘、过期、不可召回、自然语言精准删除、遗忘预览、遗忘确认、purge 验证。
9. 兰台鉴证：证据卡、版本回溯、审计追踪、量化评测、MemoryArena 报告、指标趋势、验收材料。
10. 建木同步：多设备记忆导入/导出、可信合并、跨端同步、冲突合并、同步审计。

v0.7 新增平台舱室：

11. 通玄模型舱：OpenAI-compatible / Anthropic / Gemini / local_mock 模型网关，自定义 API base/key alias/model，dry-run 测试，成本统计与调用日志设计。
12. 百工技能舱：MCP servers、Skills registry、工具权限、工具沙箱、工具调用日志、工具结果结构化入库。
13. 归藏评测舱：MemoryArena Workbench，case 编辑、case 运行、报告生成、指标趋势、历史报告对比设计。
14. 司南调参舱：top_k、trust_threshold、retention_score、retrieval_score、confirmation_threshold、安全策略配置。
15. 云笈导出舱：PPT、技术方案、测试报告、适配测试报告、用户手册、演示脚本、论文材料导出映射。
16. 昭明数据舱：数据集、样例、偏好语料、知识片段、工具结果、用户行为事件、评测 case library。
17. 太微观测舱：运行状态、延迟、吞吐、模型调用、错误率、内存库体量、索引状态、审计告警。
18. 玄衡评分舱：偏好提取准确率、知识召回率、冲突处理率、延迟、误报率、复用率、演化动作准确率。
19. 天工编排舱：多 Agent / 多工具流程编排，任务链、步骤状态、失败恢复、人工确认节点。
20. 玉衡权限舱：权限策略、只读模式、supervised mode、advisory mode、工具白名单、敏感操作确认。

## 已实现能力

- FastAPI 后端
- SQLite + FTS5
- MemoryCapsule 2.0
- Policy Gate
- Evidence Cards
- Command Loop
- Reflection / Evolution
- MemoryArena-Lite
- 5 cases / 16 assertions
- Vue 3 国风 MemoryOps Studio
- FastAPI 挂载 `/console`
- 审计流水页
- Capsule 浏览器
- 搜索证据卡跳 Capsule
- 指挥闭环页
- 复盘演化页

## v0.7 新增能力

- `GET /platform/modules`：20 舱平台模块清单，含状态、后端引用、前端引用、赛题引用。
- `GET /model-gateway/providers` 与 `POST /model-gateway/test`：模型网关 provider catalog 与安全 dry-run。
- `GET /tool-registry/tools` / `GET /tool-registry/skills`：MCP / Skills 注册表 stub。
- `GET /tuning/defaults` / `GET /tuning/policies`：司南调参默认值与权限模式。
- `GET /exports/packages`：云笈导出材料包状态。
- 前端新增平台舱室、通玄模型舱、百工技能舱、司南调参舱、云笈导出舱入口。
- 总览页扩展为平台规模展示，架构页扩展为 20 舱仪器盘。

## v0.8 吸收矩阵与 API/UI 入口

v0.8 是权威技术吸收版：以 MemoryArena 强化评测场，以 MemOS 强化记忆资源治理，以 Reflexion 强化复盘演化，以 MemoryBank 强化遗忘与偏好适应，以 HippoRAG 强化关系召回，以 MemGPT 强化分层上下文，以 LoCoMo 强化长期会话评测，以 AgeMem 预埋记忆工具化 API。

新增文档：

- `docs/V08_AUTHORITATIVE_TECH_ADOPTION_MATRIX.md`
- `docs/VERSION_LINEAGE.md`

新增后端 API：

- `GET /research-adoption/technologies`：返回 MemoryArena、MemOS、Reflexion、MemoryBank、HippoRAG、LoCoMo、MemGPT、Generative Agents、AgeMem 的吸收 catalog。
- `GET /research-adoption/routes`：返回 MemoryArena Workbench、Hippo-Lite Graph Recall、MemoryBank Retention、Reflexion Evaluator、Memory Tools API 五条落地路线。
- `GET /research-adoption/version-map`：返回 v0.1-v0.8 的权威技术依据映射。

新增前端入口：

- `/console/#/research-adoption`
- 导航组：研究吸收 / 权威吸收
- 页面结构：技术卡片区、五大路线区、版本映射区、状态统计、done/partial/planned/pending 标签。

v0.8 只做项目内 catalog/stub/API/UI/文档吸收，不联网、不伪造 DOI、不声明完整复现外部系统。未确认论文状态统一标 `needs_verification`，预印本标 `arxiv_preprint`。

## 当前真实指标

来自 v0.6 MemoryArena-Lite 真实运行报告：

| 指标 | 当前值 |
| --- | --- |
| total_cases | 5 |
| total_assertions | 16 |
| assertion_pass_rate | 1.0 |
| unsafe_autonomy_rate | 0.0 |
| memory_reuse_success_rate | 0.4 |
| post_reflection_update_rate | 1.0 |
| misleading_memory_rate | pending |
| production_task_success_rate | pending |

## 快速运行

后端：

```bash
PYTHONPATH=backend backend/.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8010
```

前端控制台：

```text
http://localhost:8010/console/
```

评测：

```bash
./scripts/run_eval.sh
```

前端构建：

```bash
cd frontend/console-vue
npm run build
```

## 目录结构

```text
backend/app/
  main.py                         FastAPI 入口与 API 路由
  memory_runtime/                 MemoryCapsule、Policy Gate、Evidence、Command、Reflection
  memory_arena/                   MemoryArena-Lite runner 与 cases
  platform/                       v0.7 平台舱室清单
  model_gateway/                  通玄模型舱 provider schema/service
  tool_registry/                  百工技能舱工具与技能注册表
  tuning/                         司南调参默认值与权限模式
  export_center/                  云笈导出材料包状态
frontend/console-vue/
  src/views/                      国风 MemoryOps Studio 页面
  src/composables/                平台数据 composable
  src/api/client.ts               同源 API client
docs/
  V06_MEMORYOPS_RUNTIME.md
  V07_MEMORYOPS_AUTOPILOT_PLATFORM.md
  COMPETITION_REQUIREMENT_COVERAGE.md
reports/
  production_memory_eval_metrics.json
  production_memory_eval_report.md
```

## 诚实边界

- 当前是 alpha platform / research prototype，不是完整企业生产平台。
- v0.7 优先扩张平台框架、API、UI、文档和赛题覆盖，不把 planned 能力伪装成 done。
- 模型网关只做 provider catalog 与 dry-run；不保存真实 key，不打印真实 key，不执行真实外部模型调用。
- MCP/Skills 编排、同步、观测、评分、多 Agent 编排等能力已给出 stub/API/UI/数据结构/状态标注，深度实现留到后续版本。
- v0.8/v0.9 将系统收敛风险治理、工程质量、指标实测和生产边界。
