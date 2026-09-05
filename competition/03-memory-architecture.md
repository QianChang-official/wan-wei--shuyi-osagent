# 记忆架构

MemoryOS 与既有 memory_runtime 协作，形成“写入闸门→生命周期→检索→治理验证→账本审计”的闭环。生命周期包含 candidate、active、reinforced、stale、conflicted、deprecated、quarantined、rejected、forgotten、deleted 十态；非法转移返回 422，forgotten/deleted 不可回到可检索状态。

治理层在 SQLite 中维护 `memory_ledger`、`memory_accounts`、`memory_incidents`、`memory_health_snapshots`。写入、更新、召回、删除均追加账目；删除验证覆盖主表、FTS、图边、向量引用和 legacy 表，证书由审计编号锚定。

平台架构为 FastAPI 后端、Vue3 控制台与 Electron 麒麟桌面端。详细模块边界和 M1-M3 路线见 [docs/MemoryOS-记忆治理层.md](../docs/MemoryOS-记忆治理层.md) 与 [docs/万枢平台-架构设计.md](../docs/万枢平台-架构设计.md)。

## 双演化体系（EGPM + TKE）

在治理闭环之上，记忆按类分两条演化线，均复用 capsule 与 relation_edges（零新表、零新状态）：

- **EGPM（偏好记忆）**：情感→偏好→演化。Beta 后验置信度 + 情感证据权重 + Outcome Validation + 漂移检测；Preference Graph 提供 preference_score 四因子评分、replaces 演化链、建议式冲突裁决与级联遗忘（`backend/app/memory_runtime/preference_graph.py`）。
- **TKE（知识记忆）**：时间→真值→演化。四类知识冲突检测（fact/status/config/temporal）+ 版本演化链 + 双时态（valid_time/transaction_time）+ as-of 历史回放 + Knowledge Timeline + freshness 老化（`backend/app/memory_runtime/knowledge_evolution.py`、`temporal_knowledge.py`）。

两条线的冲突裁决均为建议式（auto_execute 恒 False），生效路径统一走 `lifecycle.resolve_conflict(actor='human')`——算法给建议，治理做决定。
