# 更新日志

本日志按时间倒序记录可追溯的项目变更。Unreleased 条目尚未形成发布版本或 Git tag，不代表已对外发布。

## Unreleased

### 2026-07-12 - 文档中心整合

- 根目录文档中心收录原 docs/*.md 的全文内容、稳定锚点、来源元数据和 SHA-256。
- README、交付导出、研究吸收、工具注册、工作流和深做契约的文档引用统一指向文档中心锚点。
- 文档中心保留为根目录唯一入口；已收录的源文档与一次性生成脚本不再单独保留。
- 发布预检改为验证文档中心及部署、运维、发布清单锚点，不再依赖已收录的 docs/*.md 源文件。
- README 重构为当前可运行能力、验证证据、启动/验证入口和真实边界，避免把 partial/planned 或环境特定结论写成通用生产能力。

### 2026-07-12 - PR #21：麒麟 VM 证据与向量删除硬化

- 合并提交：3e38918。
- 在 Kylin V11 2603 x86_64 QEMU/WHPX VM 的捕获源码快照中，记录官方 embedding/vector Bridge 的构建、状态探测、写入、语义检索、遗忘删除、历史重建和延迟原始证据。
- 将 Capsule 本地遗忘、delete_pending、审计和遗忘票据纳入事务状态机，并加入 generation fencing、删除 claim、tombstone 和有界 sweeper，防止晚到 upsert 或陈旧回放复活向量。
- SDK 不可用或原生操作失败时保持 SQLite FTS5 显式后备；失败 Capsule 的后备检索与统计保持有界和可审计。
- PR 远端检查全部成功。VM 结论仅适用于捕获源码快照和该 VM，不覆盖最终合并 SHA、物理硬件、LoongArch/ARM、OCR、大规模数据、长期稳定性或 SLA。

### 2026-07-11 - PR #20：原生 SDK 优先检索

- 合并提交：9f5c9e4。
- 新增官方 Kylin text-embedding/vector-engine SDK 的 C++17 stdin/stdout JSON Bridge，配置显式 bridge 路径并约束输入输出协议。
- 原生 SDK 可用时优先向量检索；不可用或失败时显式回退 FTS5；补充索引映射、治理写入/删除和有界历史 reindex。
- 当时主机不具备厂商 ABI/工具链，目标 VM 的真实 SDK 行为与性能证据在后续 PR #21 单独记录。

### 2026-07-11 - PR #19：Kylin VM 兼容性工具

- 合并提交：98c694f。
- 新增 QEMU/WHPX Kylin V11 启动脚本、仅监听 127.0.0.1:5959 的 QMP 键盘辅助脚本和 VM 测试计划。
- 此项提供安装、磁盘启动和图形登录的复现工具，不等同于 SDK 或目标硬件认证。

### 2026-07-11 - PR #18：人工依赖治理

- 合并提交：5513355。
- 移除自动版本升级和自动安全修复 PR，改为人工按生态、兼容边界和验证结果审阅依赖变更。
- 保留漏洞告警、Dependency Audit/Review、CodeQL、Trivy、Secret Scanning 和 Push Protection。

### 2026-07-10 - v0.10.0 交付硬化、赛题校准与审阅门槛

- 合并提交：2b38255；相关提交：0e0dc65、9a8a6b0。
- 增加非 root 多阶段 Docker 镜像、安全默认 Compose、Windows/Linux setup、smoke、verify、backup 和 secret 初始化脚本。
- 增加 health/readiness、受保护 metrics、请求 ID、SQLite 在线备份、完整性校验、停机恢复、生产密钥强度和可信代理限流边界。
- 增加跨平台 CI、HTTP/容器 smoke、CodeQL、依赖审查、Trivy、SBOM 和发布前检查；README 明确 alpha、赛题就绪度和未验收边界。
- v0.10.0-delivery-hardening 仍为 in_progress；公开 Release 仍等待所有者选择许可证。

## 2026-07-09 - v0.9.6.2 CI/CD 清理

- 相关提交：753057b、01a9d41、19e7cea、2e34327、69e63c4。
- 修复主分支与 PR pipeline 依赖路径和入口，统一 PR 目标为 main，移除失效的 master pipeline。
- 删除未使用的 guardrail 死代码和历史认证辅助函数，保留 APIKeyMiddleware 作为认证主路径。
- 新增中文更新日志。

## 2026-07-08 - v0.9.6.1 静态扫描修复

- 相关提交：7d0cb7e、4b4d890。
- 修复静态扫描发现的问题并完成合并。

## 2026-07-06 - v0.9.6 限流与测试硬化

- 相关提交：4555bfa、1a12160。
- 增加限流、核心路径测试、性能基线工具、批量查询优化、线程本地连接复用和 WAL。
- 移除 workflow 内存 fallback，运行记录统一经 SQLite 持久化。

## 2026-07-05 - v0.9.5 持久化与 v0.9.4 安全基线

- v0.9.5 相关提交：da7f741、3d191f9。新增 workflow run SQLite 持久化、TTL 清理、时区感知 UTC 和 FastAPI lifespan 迁移。
- v0.9.4 相关提交：b05663e、7b4c3c2、870b967。修复 SSRF、认证、敏感 GET、审计和 Policy Gate 安全边界。
- v0.9.3 相关提交：fbcd665。完成 workflow run dry-run、阶段编排、trace 和 artifacts API。

## 2026-07-04 - v0.9.1 深做层与 GitHub 迁移

- 相关提交：026e9e8、24862c6、c282d75、d59ea81、b3cf2ce。
- 新增深做追问、视觉验证、契约检查和安全 dry-run 接口。
- 初始化 GitHub 仓库和默认 pipeline 模板，完成 Gitee 到 GitHub 的迁移。

## 2026-07-03 - v0.9 至 v0.4 平台、运行时和治理基础

- v0.9：3618454，新增轻量研究系统复现层。
- v0.8：e18e271，新增权威技术吸收矩阵和研究吸收控制台。
- v0.7：d5dfc2c，扩展 MemoryOps Autopilot 平台和 20 舱 Studio。
- v0.6：13ea153、a9e5d8a、bf42238、a156094、744ac61，新增运行时、MemoryArena-Lite、复盘 case、误召回风险 case 和 source-layer 原则。
- 前端与工程：44e8fd7、502ecac、cc4c017，新增 Vue 控制台并移除受跟踪的 node_modules。
- v0.5：a4bf334、5dfbd58、fd0e187、fbe1ff8、4b4fae7，建立偏好/知识记忆架构、MemoryCapsule v2、监督闭环和生产评测规范。
- v0.4：63e2a55、264ddc1、685191e、31dc027、a2fd551，建立记忆治理、安全评测、ASI 风险映射和权威参考基础。

## 2026-07-01 - v0.3.1 初始项目

- 相关提交：f65214f。
- 初始化宛委·枢忆 OSAgent 项目，建立早期 Memory OS、情感感知记忆和安全边界文档基础。
