# v0.9.1 Deep Expansion & Visual Verification

v0.9.1 是「深做追问与视觉同步验证版」。它不把 v0.9 的 lightweight reproduction 夸大成完整论文复现，而是在现有 Runtime、论文系统复现层和 Vue 控制台之上，补一层可追问、可验收、可说明边界的深做舱。

## 1. 目标

- 加厚 v0.1 到 v0.9 的项目解释力。
- 把 OSAgent 的链路、意图拆解、记忆优化、Token 成本、故障兜底和数据证据讲清楚。
- 新增后端 `backend/app/deepening/` 和 `/deepening/*` dry-run API。
- 新增前端 `/console/#/deepening` 页面。
- 建立视觉同步验证协议：优先浏览器验收，失败时用 dist token + src token + API smoke 兜底。

## 2. 残留审计说明

本轮先按 source_layer 原则审计真实仓库文件，而不是聊天复制噪声。

真实审计结果：

- `backend/app/deepening/` 已存在但只有 `__init__.py` 与 `schemas.py`，属于半写入残留。
- `frontend/console-vue/src/views/DeepeningView.vue` 不存在。
- `docs/V091_DEEP_EXPANSION_VISUAL_VERIFICATION.md` 不存在。
- `README.md`、`backend/app/main.py`、`frontend/console-vue/src/router/index.ts`、`frontend/console-vue/src/App.vue` 存在但没有 v0.9.1 deepening 接入。
- 未在真实仓库文件中命中 `Stream interrupted`、`partial-stream-stub`、`Ask me to retry`、`old_string and new_string are identical`。

source_layer 规则：

- `chat_render` / `copied_text` / `tool_display` 中的 HTML anchor、class、data-lexical-text、base64 不算仓库污染。
- 只有 `file_content` / `git_tracked` / `runtime_log` 层真实命中才算工程残留。

## 3. Hermes Session Core 借鉴

v0.9.1 借鉴 Hermes 的会话核心思想，但不读取 Hermes 私有数据。

落地为 `GET /deepening/session-core/design`：

- `session_id`
- `title`
- `source`
- `messages_summary`
- `tool_trace_summary`
- `memory_trace_summary`
- `compression_state`
- `background_task_state`
- `visual_validation_state`
- `searchable_index`
- `export_format`

`GET /deepening/session-core/demo-trace` 给出示例链路：

`user_intent -> tool_calls -> memory_events -> evidence_cards -> visual_validation -> audit_record`

## 4. OpenMythos Recurrent Depth 借鉴

v0.9.1 不训练模型，不声称复现 Claude Mythos，只吸收 recurrent-depth 的工程思想：不同任务不该使用同一推理深度。

`GET /deepening/reasoning-depth/design` 定义四档：

- `shallow`：快速状态检查和低风险 copy。
- `normal`：普通功能实现。
- `deep`：架构审查、比赛交付、跨层功能。
- `audit`：发布闸门、残留审计、安全敏感声明。

`POST /deepening/reasoning-depth/simulate` 返回：

- `selected_mode`
- `retrieval_top_k`
- `evidence_cards_required`
- `reflection_loops`
- `visual_checks`
- `token_cost_model`
- `risk_notes`

## 5. Red Queen Godel Machine 借鉴

v0.9.1 借鉴 Red Queen Godel Machine 的 controlled utility evolution，但只做 evaluator proposal，不做自修改代码。

`GET /deepening/redqueen/evaluator-design` 定义效用评估标准：

- utility alignment
- truth boundary
- evidence pressure
- regression guard
- visual sync

`POST /deepening/redqueen/evaluate-dry-run` 只返回评分、penalty 和 utility update proposal，不写文件、不改记忆、不改配置。

## 6. TriadJS Single Source of Truth 借鉴

v0.9.1 把 API、schema、frontend、smoke、docs 当作一组契约，而不是各写各的。

`GET /deepening/contracts/source-of-truth` 返回：

- API 契约：`backend/app/main.py` 挂载 `/deepening/*`。
- Schema 契约：`backend/app/deepening/schemas.py` 约束 POST dry-run payload。
- Frontend 契约：`DeepeningView.vue` 调真实 API。
- Smoke 契约：curl 每个 `/deepening/*`。
- Docs 契约：本文件写清 done/partial/planned/pending。

`GET /deepening/contracts/drift-check` 返回 drift 检查清单，用于验证前后端、dist、Arena 和文档是否一致。

## 7. From AGI to ASI 四路径映射

`GET /deepening/agi-asi/pathways` 给出四条路线映射。它是路线图，不是能力声明。

- memory governance to agent reliability
- tool use to supervised autonomy
- reflection to controlled self-improvement
- long-session memory to operating-system layer

## 8. OSAgent 全链路设计

当前链路：

1. 多源输入进入石渠校验。
2. source_layer 过滤复制噪声和展示噪声。
3. 司契 Policy Gate 判定 allow / reject / quarantine / require_confirmation。
4. 枢忆核写入 MemoryCapsule，保留 lifecycle、trust_score、retention 信息。
5. 琅嬛知识和建木网络提供检索、证据卡和关系边。
6. 指挥闭环调用工具，所有高风险动作进入 supervised / dry-run。
7. 兰台鉴证记录 audit log、Arena 报告和版本文档。
8. 前端控制台展示真实 API 状态，dist 作为演示交付物。

## 9. 用户意图拆解

v0.9.1 将用户意图拆为：

- `goal`：用户到底要完成什么。
- `task_type`：架构审查、实现、验证、文档、发布。
- `risk`：低风险只读、中风险写代码、高风险发布/凭据/系统操作。
- `source_layer`：信息来自真实文件、运行日志，还是聊天展示噪声。
- `evidence_requirement`：需要多少证据卡和 runtime smoke。
- `visual_requirement`：是否需要浏览器截图或 fallback 视觉证据。

## 10. 记忆优化

记忆优化不是无限堆上下文，而是：

- 使用 MemoryCapsule lifecycle 管理 active / candidate / quarantined / forgotten。
- 用 trust_score 和 policy_result 约束召回。
- 用 relation_edges 表达冲突、派生和替代关系。
- 用 top-k 与 mode routing 控制检索量。
- 用 evidence card 保留来源，避免把摘要当原文。

## 11. Token 节省模型

v0.9.1 只给相对模型，不伪造具体节省金额。

节省来源：

- source_layer 过滤掉 copied_text / tool_display 噪声。
- shallow / normal / deep / audit 分档限制 top-k。
- session core 只保存摘要和 source handles。
- docs/VERSION_LINEAGE 复用历史解释，不每次重述全部背景。
- 浏览器失败时使用 dist token + src token + API smoke fallback，避免反复重试。

## 12. 线上故障兜底

线上故障处理顺序：

1. `GET /health`。
2. 关键 API smoke。
3. Vue dist 是否能由 `/console/` 返回。
4. 检查 dist 是否包含目标 route chunk。
5. 退回 legacy console 或只读接口。
6. 保留 reports 与 docs 作为离线演示材料。

## 13. 成本模型

当前成本模型为相对倍率：

- shallow: 1.0x
- normal: 1.35x
- deep: 1.9x
- audit: 2.6x

这些倍率用于解释不同验证强度的成本趋势，不代表真实 token 或人民币账单。真实金额必须等模型调用日志和价格表接入后再计算。

## 14. 数据证据与兜底

真实证据来源：

- `backend/app/*` 源码。
- `frontend/console-vue/src/*` 源码。
- `frontend/console-vue/dist/*` 构建产物。
- `reports/production_memory_eval_metrics.json`。
- `reports/production_memory_eval_report.md`。
- `docs/VERSION_LINEAGE.md`。
- `git status` / `git log` / `runtime_log`。

## 15. 视觉技能同步验证协议

优先路径：

1. 启动 FastAPI。
2. 打开 `/console/#/deepening`。
3. 检查页面标题、导航、Session Core、Reasoning Depth、Red Queen、Contract Truth、AGI-to-ASI、Interrogation、Visual Verification 面板。
4. 点击 dry-run 按钮并确认 API 数据回显。

Fallback 路径：

1. `curl /console/` 返回 built index。
2. dist 中存在 `DeepeningView` chunk 或关键 token。
3. src 中存在 `深做追问`、`Visual Verification`、`Session Core`、`Red Queen`、`Contract Truth`。
4. API smoke 覆盖全部 `/deepening/*` 端点。

## 16. 本轮实现边界

Implemented：

- `backend/app/deepening/` 服务模块。
- 13 个 `/deepening/*` API。
- `docs/OSAGENT_MODEL_GATEWAY_FLOW.md` 模型接入后 OSAgent 流程图。
- `frontend/console-vue/src/views/DeepeningView.vue`。
- `frontend/console-vue/src/api/client.ts` deepening client。
- `/console/#/deepening` route。
- App 导航「研究吸收 -> 深做追问」。
- v0.9.1 文档、README、版本谱系。

Partial：

- Red Queen evaluator 是启发式 dry-run，不是真自改系统。
- Reasoning Depth 是策略模拟，不是模型训练。
- Visual Verification 有浏览器优先和 fallback，但不保证每台机器都能跑浏览器。

Planned：

- 接入真实调用日志后计算实际 token / money cost。
- 扩展 long-session benchmark。
- 加入更多 MemoryArena cases。
- 把 drift-check 从 contract list 升级成自动文件存在和端点探测。

Pending：

- misleading_memory_rate 实测。
- production_task_success_rate 实测。
- 外部论文/项目状态逐条联网核验。
