# v0.7 MemoryOps Autopilot Platform

## 1. v0.7 为什么存在

v0.6 已经把宛委·枢忆推进到可运行 Runtime：FastAPI、SQLite + FTS5、MemoryCapsule 2.0、Policy Gate、Evidence Cards、Command Loop、Reflection/Evolution 与 MemoryArena-Lite。问题是 v0.6 仍偏“运行时证明”，平台规模、产品感、模块矩阵、前端操作面和赛题覆盖呈现还不够强。

v0.7 的存在目的，是把项目从 MemoryOps Runtime 扩张成 MemoryOps Autopilot Platform。当前阶段优先做大框架、前端、后端模块、README 门面和赛题覆盖能力；风险收敛、指标细化和工程硬化放在 v0.8/v0.9 系统治理。

## 2. 从 Runtime 到 Autopilot Platform

v0.6 Runtime 证明“记忆可以被生产、检索、证据化、复盘和评测”。v0.7 Platform 进一步把这些能力组织成平台控制面：

```text
多源接入
  -> 石渠校验
  -> 司契 Policy Gate
  -> 枢忆核 MemoryCapsule 2.0
  -> 琅嬛知识 / 玄珠偏好 / 建木网络
  -> 通玄模型舱 / 百工技能舱
  -> 指挥闭环
  -> 复盘演化
  -> 归藏评测舱
  -> 兰台鉴证 / 云笈导出舱
```

## 3. 平台总架构

平台由四层组成：

| 层级 | 组成 | 作用 |
| --- | --- | --- |
| 数据与记忆层 | MemoryCapsule 2.0、SQLite、FTS5、relation_edges | 承载长期记忆、状态、证据、关系和检索索引 |
| 治理与策略层 | 石渠校验、司契护栏、忘机机制、玉衡权限舱 | 控制入库质量、风险、确认、遗忘和工具权限 |
| 编排与调用层 | 通玄模型舱、百工技能舱、天工编排舱、司南调参舱 | 承载模型调用、MCP/Skills、任务链与参数调节 |
| 评测与交付层 | 兰台鉴证、归藏评测舱、玄衡评分舱、太微观测舱、云笈导出舱 | 承载指标、报告、观测、审计和参赛材料 |

## 4. 祖宗模块与新增舱室

祖宗主线：石渠校验、司契护栏、枢忆核、玄珠偏好、琅嬛知识、建木网络、灵犀情感、忘机机制、兰台鉴证、建木同步。

v0.7 新增：通玄模型舱、百工技能舱、归藏评测舱、司南调参舱、云笈导出舱、昭明数据舱、太微观测舱、玄衡评分舱、天工编排舱、玉衡权限舱。

每个舱室在 `/platform/modules` 中都有统一数据结构：

```json
{
  "id": "tongxuan_model_gateway",
  "name_cn": "通玄模型舱",
  "name_en": "Model Gateway",
  "pillar": "v0.7 新增",
  "status": "partial",
  "backend_refs": ["/model-gateway/providers", "/model-gateway/test"],
  "frontend_refs": ["/model-gateway"],
  "competition_refs": ["模型调用", "成本统计", "调用日志"],
  "description": "..."
}
```

## 5. 全自动闭环

平台目标闭环：

1. 多源数据进入石渠校验。
2. 司契护栏判断 allow / require_confirmation / quarantine / reject。
3. 枢忆核写入 MemoryCapsule 2.0，并建立 FTS5 索引。
4. 检索时同时返回结果与 Evidence Cards。
5. Command Loop 生成任务计划、风险分级和确认点。
6. Reflection/Evolution 把执行结果转化为偏好、知识、风险或流程记忆。
7. MemoryArena 运行 case，生成 reports。
8. 云笈导出舱把文档、报告、演示路径汇总成参赛材料包。

v0.7 中该闭环已有可运行核心，但自动化深度仍为 alpha：真实危险操作不自动执行，高风险步骤保留确认和状态标注。

## 6. 手动调参闭环

司南调参舱暴露默认参数：

- retrieval.top_k
- retrieval.trust_threshold
- retrieval.retrieval_score_weight
- retrieval.retention_score_weight
- retrieval.emotional_salience_weight
- policy.confirmation_threshold
- policy.quarantine_threshold
- policy.high_risk_requires_confirmation
- arena.assertion_pass_rate_target
- arena.unsafe_autonomy_rate_target

v0.7 先提供 API 与 UI 展示；后续版本再加入配置落盘、版本化、回滚和 AB 对比。

## 7. 模型网关设计

通玄模型舱支持 provider catalog：

- openai_compatible
- anthropic
- gemini
- local_mock

字段包括 provider、api_base、api_key_alias、model、enabled、status。v0.7 只提供 dry-run 测试，真实 key 不保存、不回显、不打印。真实外部调用、成本统计、调用日志和限额策略留到 v0.8/v0.9。

## 8. MCP/Skills 编排设计

百工技能舱登记 MCP servers、internal tools、external tools 与 Skills。每项记录包含：

- id
- name_cn
- kind / scope
- permission_mode
- sandbox
- status
- result_storage
- description

v0.7 的重点是建立工具权限、沙箱等级和结构化结果入库模型；真实多工具编排由天工编排舱在后续版本深化。

## 9. 多源数据接入设计

多源入口包括：

- 用户输入
- 文档片段
- Git 提交/审查结果
- 工具调用结果
- 运行日志
- 评测 case
- 偏好语料
- 知识模板

石渠校验必须区分 source_layer：chat_render、copied_text、tool_display、file_content、git_tracked、runtime_log。关键词命中不是注入证据，富文本噪声不是文件污染，聊天渲染不是仓库落盘。

## 10. MemoryArena Workbench 设计

当前 MemoryArena-Lite 已有 5 个 case：

- docs_reference_governance
- git_commit_review
- poisoning_preference_confirm
- self_evolution_loop
- prompt_injection_false_positive_echo

当前真实指标：5 cases / 16 assertions / assertion_pass_rate=1.0 / unsafe_autonomy_rate=0.0。v0.7 归藏评测舱展示现有报告与 case library，case 编辑器、历史趋势对比和新增生产任务指标属于后续深化。

## 11. 国风 Studio 设计

Studio 视觉方向：秘府典籍 / 宣纸水墨 / 朱砂印章 / 精密生产仪器盘。

v0.7 前端重点：

- 总览页展示平台舱室数量、真实 Arena 指标和生产线闭环。
- 主线架构页展示 20 舱，并可切换祖宗主线 / v0.7 新增。
- 平台舱室页展示每个舱室的 backend_refs、frontend_refs、competition_refs 和状态。
- 模型舱、技能舱、调参舱、导出舱提供可操作入口。

## 12. 与比赛方案要求的关系

详见 `docs/COMPETITION_REQUIREMENT_COVERAGE.md`。原则是每个赛题要求必须能落到：项目模块、当前实现、演示路径、证据文件、状态。

## 13. 已实现 / 部分实现 / 规划中

| 状态 | 内容 |
| --- | --- |
| done | FastAPI、SQLite + FTS5、MemoryCapsule 2.0、Policy Gate、Evidence Cards、Command Loop、Reflection/Evolution、MemoryArena-Lite、Vue 控制台基础页 |
| partial | 平台模块 API、模型网关 dry-run、工具/技能注册表、调参默认值、导出中心、20 舱前端展示、偏好/知识/关系/遗忘部分能力 |
| planned | 多设备同步深度实现、真实模型调用成本统计、观测指标采集、评分舱实测、天工编排、导出文件一键生成、生产级权限策略 |
| pending | misleading_memory_rate、production_task_success_rate、PPT/演示视频、部分比赛目标的实测数值 |

## 14. v0.8/v0.9 风险收敛计划

v0.8/v0.9 将重点处理：

- 风险边界系统治理。
- 模型网关真实凭据策略、调用日志脱敏、成本统计。
- MCP/Skills 工具白名单、权限落盘、敏感操作确认。
- MemoryArena case 扩容和指标趋势。
- 调参配置持久化和回滚。
- 精准遗忘 purge 验证。
- 端侧部署脚本、麒麟环境兼容性复测。
- README/前端/提交材料中所有 partial/planned 能力的二次核验与收敛。
