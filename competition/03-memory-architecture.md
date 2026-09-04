# 记忆架构

MemoryOS 与既有 memory_runtime 协作，形成“写入闸门→生命周期→检索→治理验证→账本审计”的闭环。生命周期包含 candidate、active、reinforced、stale、conflicted、deprecated、quarantined、rejected、forgotten、deleted 十态；非法转移返回 422，forgotten/deleted 不可回到可检索状态。

治理层在 SQLite 中维护 `memory_ledger`、`memory_accounts`、`memory_incidents`、`memory_health_snapshots`。写入、更新、召回、删除均追加账目；删除验证覆盖主表、FTS、图边、向量引用和 legacy 表，证书由审计编号锚定。

平台架构为 FastAPI 后端、Vue3 控制台与 Electron 麒麟桌面端。详细模块边界和 M1-M3 路线见 [docs/MemoryOS-记忆治理层.md](../docs/MemoryOS-记忆治理层.md) 与 [docs/万枢平台-架构设计.md](../docs/万枢平台-架构设计.md)。
