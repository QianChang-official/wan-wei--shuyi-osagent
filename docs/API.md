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

## MemoryCapsule 与检索

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/memory/v2/capsules` | 写入受治理的 MemoryCapsule |
| GET | `/memory/v2/capsules` | 列出 Capsule |
| GET | `/memory/v2/capsules/{capsule_id}` | 读取单个 Capsule |
| GET | `/memory/v2/search` | FTS5/中文 substring 召回与证据卡 |
| POST | `/memory/v2/command` | 风险分级与指挥闭环 |
| POST | `/memory/v2/reflection` | 任务复盘与演化动作 |
| POST | `/memory/forget/preview` | 精准遗忘预览 |
| POST | `/memory/forget/confirm` | 确认后执行遗忘 |

兼容入口 `/memory/events`、`/memory/search` 与 `/memory/capsules/{capsule_id}` 仍保留，但新集成应优先使用 v2 路径。

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
