# API 契约概览

本文档对应 `v0.10.0-delivery-hardening`。当前 API 尚未引入 `/api/v1` 前缀；兼容性敏感的客户端应固定项目版本，并在升级前检查 `/openapi.json` 差异。

## 鉴权与请求追踪

- 写请求和敏感读请求必须携带 `X-API-Key`。
- 开发模式默认密钥为 `wanwei-dev-key`；生产模式必须显式提供至少 32 个字符的密钥。
- 可通过 `WANWEI_API_KEY_FILE` 从只读 secret 文件加载密钥。
- 客户端可发送最长 128 字符的 `X-Request-ID`；服务端会原样返回合法值，否则生成 `req_<uuid>`。
- 限流响应为 HTTP `429`，并携带 `Retry-After: 1`。

## 运维端点

| 方法 | 路径 | 鉴权 | 用途 |
| --- | --- | --- | --- |
| GET | `/health` | 否 | 向后兼容的版本健康信息 |
| GET | `/health/live` | 否 | 进程存活探针，不检查外部状态 |
| GET | `/health/ready` | 否 | 检查 SQLite 查询与控制台静态资源 |
| GET | `/metrics` | 是 | Prometheus 文本格式进程/HTTP 指标 |
| GET | `/kylin/sdk/status` | 是 | 原生 SDK Bridge 可用性、能力、索引覆盖和 `delete_pending` 数量，不返回请求内容或凭据 |
| POST | `/kylin/sdk/reindex?limit=10&retry_failed=false` | 是 | 异步、有界迁移既有合规 Capsule 到原生向量索引；默认 10、最大 25，返回 `202` 后通过 status 观察进度 |

## MemoryCapsule 与检索

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/memory/v2/capsules` | 写入受治理的 MemoryCapsule |
| GET | `/memory/v2/capsules` | 列出 Capsule |
| GET | `/memory/v2/capsules/{capsule_id}` | 读取单个 Capsule |
| GET | `/memory/v2/search` | Kylin native 向量检索优先；SDK 不可用时 FTS5/中文 substring 后备，并返回 retrieval 状态 |
| POST | `/memory/v2/command` | 风险分级与指挥闭环 |
| POST | `/memory/v2/reflection` | 任务复盘与演化动作 |
| POST | `/memory/forget/preview` | 对 v2 Capsule 执行受治理语义检索，返回可选择的精准遗忘候选 |
| POST | `/memory/forget/confirm` | 仅删除请求中 `capsule_ids` / `event_ids` 且已出现在对应预览里的条目；本地 Capsule、两套 FTS、票据、审计和向量删除意图在一个 SQLite 事务中提交，厂商删除在提交后幂等执行并可由后台恢复；`hard_delete` 会物理删除 v2 Capsule |

原生 upsert 使用持久 attempt generation 和每代独立 vector ID。过期 worker
只能清理自己的旧 ID，不能覆盖或删除接管 worker 已发布的新向量。对并发遗忘、
厂商暂态失败或进程崩溃仍不确定的 ID，会保存在 `delete_pending`/tombstone
outbox 中，由启动即运行的有界 sweeper 重试；只有厂商明确确认后才报告完成。

兼容入口 `/memory/events` 与 `/memory/search` 仍保留；Capsule 详情仅提供 `/memory/v2/capsules/{capsule_id}`，新集成应统一使用 v2 路径。

## Workflow 与审计

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/workflow/runs` | 创建并持久化 dry-run 工作流 |
| GET | `/workflow/runs` | 分页列出运行记录 |
| GET | `/workflow/runs/{run_id}` | 获取完整运行记录 |
| GET | `/workflow/runs/{run_id}/trace` | 获取阶段 trace |
| GET | `/workflow/runs/{run_id}/artifacts` | 获取交付物映射 |
| POST | `/workflow/cleanup` | 按 TTL 清理旧运行记录 |
| GET | `/workflow/stats` | 获取持久化统计 |
| GET | `/audit/logs` | 读取审计日志，可按 `trace_id` 过滤 |

## 平台与研究入口

- `/platform/*`：20 舱模块清单与状态。
- `/model-gateway/*`：provider catalog、dry-run 和显式配置后的本地真实 smoke。
- `/tool-registry/*`、`/tuning/*`、`/exports/*`：技能、调参与交付映射。
- `/research-adoption/*`：研究来源与吸收矩阵。
- `/reproduction/*`：轻量复现 schema/template/dry-run。
- `/deepening/*`：深做追问与视觉验证 dry-run。

这些入口中包含 `partial`、`planned` 与 `stub` 能力；HTTP 200 仅表示接口可用，不表示外部研究系统已完整复现。

## 错误与边界

- 鉴权失败：HTTP `401`，`{"detail":"Missing or invalid X-API-Key"}`。
- Pydantic 请求校验失败：HTTP `422`，采用当前 FastAPI 标准错误结构。
- 未找到资源：部分历史接口返回业务 JSON，尚未统一为单一错误 envelope；统一错误模型列入 v0.11。
- 开发模式提供 `/docs` 与 `/openapi.json`；生产模式禁用二者。
