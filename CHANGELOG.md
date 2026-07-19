# 更新日志

本日志按时间倒序记录可追溯的项目变更。Unreleased 条目尚未形成发布版本或 Git tag，不代表已对外发布。

## 2026-07-18 - v0.11.0「万枢」桌面协作平台

- 新增 `backend/app/platform_api/` 万枢平台 API 聚合包，由 `app.main` 统一以 `/platform` 前缀挂载，子模块自动发现、单模块导入失败仅告警跳过，共八个后端模块：
  - `providers`：31 家模型厂商接入目录（catalog）与用户配置管理，密钥 Fernet 加密落盘、接口只写不读；配置就绪才真实调用，否则返回明确 stub 标识。
  - `agents`：多智能体编排运行（run），全平台共享思考深度六档（low/medium/high/xhigh/max/ultracode）与工作档位三档 gear 门禁（human_review/sandbox/device；device 与 sandbox 同为可执行档位，整机级危险操作由具体模块显式校验）。
  - `spaces`：项目任务空间 tree / main / perch 三态状态机；alpha 期为目录级物理隔离 + 状态机建模，真实 `git worktree` 绑定列入 M2。
  - `automation`：AI 可编辑工作流，规则式中文解析器把自然语言指令转为流程定义 diff（engine='mock'，诚实标注为模拟引擎）；运行模拟不真实执行 shell/http/agent/memory 步骤，仅返回 would_run 说明。
  - `knowledge`：知识库收录、分块与检索；基于 SQLite FTS5（CJK 逐字插空格分词，支持中文子串检索），0 命中时 LIKE 兜底；**无外部向量检索后端**，麒麟原生向量 SDK 的接入列入 M2。
  - `memory_center`：记忆指令（「记住……」快捷写入，单条不超过 200 行，remember / instructions / phrases 写入前统一过 Policy Gate 拦截密码/密钥/投毒）与手动触发的会话摘要归档（`/dreams/archive-now`）；无每夜自动调度（`/dreams/schedule` 如实返回 `enabled:false, mode:'manual'`），压缩冗余/合并近义/标记冲突/全程审计留痕列入 M2。
  - `system_svc`：系统服务出口（健康检查、防睡眠状态镜像、通用设置、语音输入存档、防追踪浏览器规则与启动计划、模拟器镜像下载、LAN 模式与手机配对 token 签发、沙盒命令执行、wanwei CLI 使用指南）；版本/模块清单/自启动状态查询当前未实现，列入 M2。
  - `mcp_hub`：MCP 服务器注册表与工具调用代理；stdio 传输仅在服务端显式开启 device 档且 command 命中 `WANWEI_MCP_STDIO_COMMANDS` 白名单时真实连接，子进程使用最小环境且不继承 `WANWEI_*` 服务秘密；sse/streamable_http 真实连接为 M2，调用结果以 stub/live/error 诚实标注。
- 新增 `frontend/console-vue/src/views/platform/` 十一个中文视图：万枢工作台（WorkbenchView）、模型接入（ProvidersView）、智能体（AgentsView）、空间（SpacesView）、自动化（AutomationView）、知识库（KnowledgeView）、记忆中枢（MemoryCenterView）、会话（SessionsView）、设置（SettingsView）、帮助（HelpView）、手机伴侣（MobileView）。
- 桌面端 `desktop/src` 新增防睡眠（`powerSaveBlocker` app/display 双模式）、局域网手机控制（后端 `127.0.0.1 ↔ 0.0.0.0` 热重启切换、私有网段 IPv4 优选、LAN token 配对）与浮动工作区小窗（420×640 无边框置顶，加载移动视图）。
- 修复自动化模块路由：统一收敛到 `/platform/automation` 前缀，固定路径（/flows/ai-edit、/flows/schedule/overview）先于参数路径（/flows/{fid}）注册，避免被参数路径吞掉。
- 新增 `docs/万枢平台-架构设计.md`：愿景定位、Orca 理念映射、麒麟标准符合性清单、系统架构、八模块 M1 契约、安全边界与 M1–M3 路线图。
- 许可证改用国产木兰宽松许可证第 2 版（Mulan PSL v2）。
- 事实边界保持诚实：本平台仍为可运行单节点 alpha；真实模型 API 调用（未配置时 stub）、git worktree 真实绑定等未接通能力一律以 stub / simulated 明确标注，不宣称已可用；device 档与 sandbox 同为可执行档位，整机级危险操作由具体模块显式校验。

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
- v0.10.0-delivery-hardening 仍为 in_progress；公开 Release 的许可证前置条件已满足——项目所有者已选定国产开源许可证木兰宽松许可证第2版（Mulan PSL v2），全文见根目录 LICENSE。

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
