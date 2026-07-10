# 工程路线图

路线图以“真实可验收能力优先”为原则。页面、catalog 或 schema 不等同于能力完成；每个里程碑必须同时具备实现、测试、运行证据和边界说明。

## v0.10：交付硬化（当前）

- 非 root、多阶段 Docker 镜像和安全默认 Compose。
- Windows/Linux setup、verify、smoke、backup 工具。
- GitHub CI 矩阵、CodeQL、依赖审查、镜像扫描、SBOM 与构建溯源。
- 存活/就绪探针、请求关联 ID、受保护 Prometheus 指标。
- SQLite 在线备份、完整性校验、停机恢复与恢复前安全副本。
- FastAPI/Starlette/Pydantic 2 安全升级；运行时与开发依赖分离。

完成定义：全量测试、前端可复现构建、依赖审计、HTTP smoke、锁定容器 smoke 和备份恢复演练全部通过。

## v0.11：API 与数据接入收敛

- 引入 `/api/v1` 路由、统一错误 envelope、分页模型和 OpenAPI 契约快照测试。
- 建立 Adapter 接口与真实 JSON/Markdown/PDF/OCR 输入流水线，记录 provenance 与失败隔离。
- 为 SQLite schema 引入显式迁移版本和升级/回滚检查。
- 增加结构化日志配置、审计导出和数据保留策略。

## v0.12：赛题硬指标评测

- 扩展偏好、知识、冲突、遗忘、投毒、性能和办公场景数据集。
- 实测偏好提取准确率、Recall@K、冲突处理正确率、遗忘成功率和误删率。
- 区分 synthetic assertions、离线 benchmark 与真实任务结果。
- 提供数据集版本、随机种子、运行环境、原始结果和报告生成脚本。

## v0.13：银河麒麟真实适配

- 定义通用 EmbeddingAdapter，并接入银河麒麟 SDK 的实际版本。
- 在目标麒麟硬件/桌面环境完成安装、权限、性能、休眠恢复和升级测试。
- 将 `COMPATIBILITY_TEST_REPORT.md` 升级为带环境证据的实测报告。
- 验证 x86_64/arm64 镜像或离线安装包，不以非目标环境结果替代。

## v0.14：研究基线深化

- 优先完成 FTS5/BM25 与 HippoRAG-like recall 的可复现实验，不继续增加空壳页面。
- 选择官方 LoCoMo 或 MemoryArena 子集建立对照、消融与失败案例分析。
- 将图召回、retention 和 reflection 从 dry-run 提升为有数据、有指标的实现。

## v1.0：可提交版本

- 由项目所有者确定许可证，创建正式 tag、Release、源码包、镜像、SBOM 与校验和。
- 完成技术方案、测试报告、用户手册、适配报告、PPT、演示脚本和演示视频。
- 关闭 P0 缺口，冻结 API/数据格式，完成灾备恢复演练与发布回滚演练。

## 暂不承诺

- 当前 SQLite/单进程限流不构成多副本高可用方案。
- 未经实测不承诺银河麒麟性能、三项赛题准确率或生产稳定性。
- 不通过伪造数据、跳过失败测试或把 planned 状态改名来完成里程碑。
