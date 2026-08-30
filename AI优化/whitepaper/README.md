# Memory OS 白皮书

> 一本白皮书 + 附录库。各章为唯一权威正文(Canonical Owner),其他文档只能引用,不得复制维护。
> 结构来源:`AI优化/MemoryOS-白皮书结构.md`(2026-08-20 入库草案)
> 迁移执行:2026-08-30,按「概念所有权」而非 docx 边界组织

## 章节导航

| 章 | 标题 | 状态 | 来源 |
|---|---|---|---|
| [第 1 章](ch01-vision.md) | 问题定义与 Memory OS 愿景 | ✅ 已迁移 | 0.docx + 4.docx |
| [第 2 章](ch02-cognitive-foundations.md) | 认知科学根基 | ✅ 已迁移 | 1.docx |
| [第 3 章](ch03-tech-map-l0-l4.md) | 技术地图与 L0-L4 架构 | ✅ 已迁移 | 0.docx + 1.txt |
| [第 4 章](ch04-osagent-gap.md) | OSAgent 项目现状与 Gap | ✅ 已迁移 | 2.docx |
| [第 5 章](ch05-memory-benchmark.md) | Memory Experience Benchmark | ✅ 已迁移 | 3.docx → BenchmarkHarness.md |
| [第 6 章](ch06-harm-economics.md) | Memory Harm × Economics 标准 | ✅ 已合并 | 4.docx → Accounting + Health |
| [第 7 章](ch07-iq-mq.md) | IQ/MQ 双轴智能模型 | ✅ 已迁移 | 5.docx → IQMQ双轴框架.md |
| [第 8 章](ch08-governance-lifecycle.md) | Governance / Accounting / Lifecycle 规范 | ✅ 已合并 | 新增 + 4.docx → Governance账本 + Lifecycle状态机 + core参考实现 |

## Canonical 规则

- **权重与评分公式**:唯一定义于第 6 章;第 5 章只引用。
- **Lifecycle 状态机**:唯一定义于第 8 章;第 3 章只定义分层结构。
- **MQ 定义**:唯一定义于第 7 章;第 6 章不得重新定义。
- **Ledger/Provenance**:唯一定义于第 8 章;第 6 章只提出指标需求。

## 附录

- 附录 A:原典理论列表(随第 2 章 docx 提取补全)
- 附录 B:术语表(待统一)
- 附录 C:Benchmark case schema(见第 5 章 §2.1)
- 附录 D:实现代码草案(随各章规范内嵌)

原始 docx 与过程稿保留于 `AI优化/` 原目录,作为附录库,不再新增 docx。
