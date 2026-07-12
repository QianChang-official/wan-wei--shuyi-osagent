# 更新日志

## Unreleased - 2026-07-12

### PR #21 已合并基线：麒麟 VM 证据与运行时硬化

> 对应上游 squash 提交：`3e38918`（`[codex] harden Kylin VM evidence and vector deletion`）。本节补记从上一次文档分支基线 `9f5c9e4` 到当前 `origin/main` 的全部改动类别，避免 PR #22 因历史分叉重复展示这些已合并内容。

#### 麒麟原生 SDK 与证据

- 完成 Kylin V11 2603 x86_64 VM 上的 embedding/vector Bridge 构建、状态探测、写入、语义检索、遗忘删除、历史重建索引和延迟采样，并将原始日志、JSON、截图和 SHA-256 清单收录到 `reports/kylin-native-sdk-evidence/`。
- 强化原生 Bridge 协议、SDK 可用性探测、collection/model/dimension 元数据和正常模式验证；SDK 可用时优先原生向量检索，不可用或失败时显式回退 SQLite FTS5。
- 把兼容性结论限定为已验证 VM、当前源快照和指定架构，不扩大为物理硬件、LoongArch/ARM、大规模或 SLA 认证。

#### 原子遗忘与向量生命周期

- 将 Capsule 本地遗忘、向量 `delete_pending`、审计和遗忘票据纳入事务状态机；原生删除失败继续保留可审计 outbox/tombstone，避免把未知结果伪装成成功。
- 增加向量 generation fencing、单调状态合并、删除 claim lease/token、过期接管与 CAS，阻止晚到 upsert、陈旧 replay 或失效 claim 覆盖新状态。
- 增加延迟删除复核和 bounded sweeper；当厂商返回 `deleted=false` 时，权威持久化状态允许遗忘票据从 `deleted` 回退到 `pending`，同时阻止普通陈旧快照降级已确认成功。
- 将重复删除 claim 的请求等待限制在独立短窗口，不再占用请求线程完整 61 秒租约；遗忘 replay 复用现有数据库连接，避免热路径重复 schema DDL 与隐式提交。

#### 检索、输入、安全与运维

- 对失败向量 Capsule 使用有界 SQL join 的 FTS fallback，修正 pending/failed 统计与 `retrieval_fallback_reason`，并保持证据卡、审计和历史重建索引的一致语义。
- 加固请求体流式大小限制、认证、可信代理限流、错误/审计脱敏、安全响应头、CSP 与遗留控制台开关；移除嵌入式开发 API Key，生产环境保持显式 secret 配置。
- 补齐 `memory_vector_delete_claims` 等启动 schema，移除请求路径冗余 `CREATE TABLE IF NOT EXISTS`，并扩展工作流持久化、SSRF、安全基线和并发竞态测试。
- 更新前端同源 API/CSP 兼容性并重建版本化 `dist` 资产；同步更新 API、部署、赛题覆盖、麒麟 SDK 与兼容性说明。

#### PR #21 验证

- 最终本地后端：`238 passed, 1 skipped`。
- 最终远程 15 项检查全部通过：Ubuntu/Windows Python 3.10/3.12、前端生产构建、HTTP integration smoke、Hardened container smoke、CodeQL、Trivy、容器漏洞扫描、依赖审计/审查和 Kilo Code Review。
- Kilo 最终结论：`No Issues Found`，建议合并。

### PR #22 当前改动：统一文档中心

#### 文档中心生成与保真规则

- 新增根目录 `文档中心_DOCUMENTATION_HUB.md`，从最新上游 `3e38918` 的 `docs/*.md` 生成 48 份全文文档、10 个固定分类、42 份现行文档和 6 份历史备份。
- 每份文档具有稳定显式锚点、来源路径、current/backup 状态、源提交、SHA-256、摘要、折叠全文、source-start/source-end 边界和返回目录链接。
- Markdown 标题只在代码围栏外降级；反引号/波浪线围栏、未闭合围栏尾部空行和无末尾换行状态均原样保留，避免 shell、Mermaid 或示例正文被误改。
- 文档中心基于 PR #21 最终 squash 树重新生成，已吸收兼容性报告后续 7 行边界修订，不使用旧 `e0d18b4` 快照覆盖 `main`。

#### 生成器与回归测试

- 新增 `scripts/build_documentation_hub.py`：冻结来源清单和分类映射，校验来源漂移、重复锚点、details/source 边界、代码围栏、源哈希、生成日期与确定性输出。
- 提供 `--generated-on YYYY-MM-DD` 可复现生成和 `--check` 只读检查；生成结果不一致、来源新增/遗漏或结构损坏时 fail closed。
- 新增 `scripts/tests/test_build_documentation_hub.py`，覆盖 48/48 来源清单、6 份历史备份、标题变换、两类代码围栏、EOF/尾行保真、唯一锚点、48 个全文块和外部锚点引用有效性。
- 保留全部 48 份 `docs/*.md` 源文档及生成器/测试；文档中心作为统一入口和全文镜像，不制造正文历史路径断链，也不留下无法重建的静态巨文件。

#### README 与运行时引用

- README 新增“文档入口”，说明统一文档中心、源文档保留策略和确定性检查命令；赛题矩阵、麒麟适配、v0.8/v0.9/v0.9.1、运维、部署与项目探索入口改为可点击的文档中心锚点。
- README 项目树同时列出 `docs/` 来源、根文档中心和生成脚本，明确维护责任边界。
- `deepening/contract_truth.py` 的文档契约迁移到 v0.9.1 文档中心锚点。
- `export_center/service.py` 的技术方案、兼容性报告和用户手册证据迁移到稳定锚点。
- `research_adoption/service.py` 中 MemOS、MemoryBank、HippoRAG、LoCoMo、MemGPT、Generative Agents、AgeMem 及 v0.1-v0.8 版本映射的文档证据全部迁移到稳定锚点。
- `tool_registry/service.py` 的记忆治理策略与参赛材料导出 entrypoint 迁移到稳定锚点。
- `workflow/service.py` 的赛题工作流与版本谱系 artifacts 迁移到稳定锚点。

#### 分支与差异治理

- 确认 GitHub 原先不存在 PR #22，原本地 `codex/documentation-hub@4e94294` 也从未推送；因此以最新 `origin/main@3e38918` 新建干净的 `codex/documentation-hub-pr22`。
- 原分支同时携带 PR #21 的未 squash 提交，导致三点比较虚增约 90 个文件并产生主线冲突；正式 PR #22 仅移植文档中心净改动，不重复推送已合并的 PR #21 代码和证据。
- 原始分支、同步前快照和审计过程保留在本地备份分支；正式远程分支不包含冲突实验、构建噪声、用户凭据或无效删除。

#### PR #22 验证口径

- 文档生成器单元测试、确定性 `--check`、外部锚点存在性、仓库 `docs/*.md` 引用扫描、后端全量测试、前端生产构建、MemoryArena 与 `git diff --check` 均作为推送前门禁。
- 此处记录的是待审查 PR #22 的实现和验证范围，不把尚未运行或尚未返回的远程 CI 写成已通过。

---

## Unreleased - 2026-07-10

### v0.10.0 交付硬化

- 增加非 root 多阶段 Docker 镜像、安全默认 Compose、Linux setup/smoke/verify/backup 与 secret 初始化脚本。
- 增加 GitHub Windows/Linux CI、HTTP/容器 smoke、CodeQL、Dependency Review、Trivy、Dependabot、Release、SBOM、校验和与 provenance attestation。
- 增加 `/health/live`、`/health/ready`、受保护 `/metrics`、`X-Request-ID` 与低基数 HTTP 指标。
- 增加 SQLite 在线备份、quick_check、SHA-256 manifest、防篡改验证、停机恢复和恢复前安全副本。
- 生产 API Key 增加 32 字符最低强度与 secret 文件加载；限流仅信任显式配置的代理 IP/CIDR，并从右向左剥离代理链以避免伪造转发头影响分桶。
- 升级到 FastAPI 0.139、Starlette 1.3、Pydantic 2.13、HTTPX 0.28、Uvicorn 0.51 和 pytest 9.1，并迁移 Pydantic v2 序列化接口。
- 拆分运行时/开发依赖；本地 `pip-audit` 与 `npm audit` 均未发现已知漏洞。
- 运行时镜像在安装应用依赖前固定升级 `pip` 至 26.1.2，消除基础镜像中扫描到的高危 pip CVE。
- 增加生产运维手册、灾备演练、发布检查表、API 契约概览和分阶段 v1.0 路线图。

### 仍需所有者决策

- 根目录许可证尚未选择，因此公开 Release 流水线会 fail closed；不会擅自替项目所有者选择法律条款。

### 赛题合规与文档校准

- 收敛 README 项目定位，从完整生产平台表述调整为可运行 alpha 原型与参赛研发底座。
- 增加 XA-202612 赛题就绪度说明，区分已跑通、部分满足和待补齐能力。
- 明确提交前 P0 缺口：银河麒麟 embedding SDK、麒麟适配实测、三项硬指标评测、PPT/演示视频与最终材料包。
- 补充性能基线边界：本机 SQLite 检索满足 500ms 演示口径，但不等同于麒麟 SDK 和大规模数据集验收。
- 在诚实边界中标注偏好提取准确率、知识检索召回率、冲突处理正确率仍需正式实测报告。

### 跨平台搭建

- 增加 Windows `setup`、`run_dev`、`run_eval` 与 HTTP smoke 脚本。
- 统一开发与部署端口为 `8010`，补齐 Vite API 代理。
- 修复 SQLite 工作线程连接回收、Windows 测试隔离与 UTF-8 读取问题。
- 修复 FTS5 连字符查询解析与 MemoryArena 在 GBK 终端输出失败的问题。
- 控制台支持内存态 API Key，修复受保护 API 无法从 UI 调用的问题。
- 本地 OpenAI-compatible provider 改为显式配置，不再默认引用开发者私有地址和模型路径。
- 补充项目探索报告、外部研究来源链接和发表状态核验。

---

## v0.9.6.2 - 2026-07-09

> 状态：待发布，尚未打 tag。

### CI/CD

- 修复 Master / PR Pipeline 中错误的后端依赖路径与入口命令。
- 移除已失效的 `master-pipeline` 流水线配置。
- 将 PR Pipeline 的触发目标从 `master` 调整为 `main`。
- 将当前有效 CI 结构收敛为：
  - `branch-pipeline.yml`：覆盖 push 到 `main`
  - `pr-pipeline.yml`：覆盖 PR 到 `main`
- 避免 `main` 分支 push 时出现重复流水线执行与重复 release 制品发布风险。

### 安全与清理

- 删除未使用的 `guardrail/service.py` 死代码。
- 删除零调用且使用非常量时间比较的历史遗留 `require_api_key()` 辅助函数。
- 移除随之失效的 `HTTPException` import。
- 保留当前认证主路径 `APIKeyMiddleware`。
- 保留 `policy_gate.py` 与 `redaction.py` 的独立职责：
  - `policy_gate.py` 负责策略判定与拒绝逻辑。
  - `redaction.py` 负责审计与响应脱敏。

### 验证

- `compileall` 通过。
- CI 安全子集测试通过：`14 passed`。
- 清理阶段已验证后端全量测试：`125 passed`。
- 本地 `main` 与 `origin/main` 已同步到 `2e34327`。
- 远端 Gitee CI 结果仍需在 Gitee 页面人工确认。

### 相关提交

- `2e34327` chore: remove dead master pipeline
- `19e7cea` fix: target PR pipeline at main
- `01a9d41` fix: remove unused guardrail and legacy auth helper
- `753057b` fix: repair master and pr CI pipelines

---

## v0.9.6.1

### 安全

- 修复 v0.9.6.1 发布线中的静态扫描发现问题。
- 完成 v0.9.6.1 static scan fixes 合并。

### 相关提交

- `4b4d890` merge: v0.9.6.1 static scan fixes
- `7d0cb7e` fix: resolve v0.9.6.1 static scan findings

---

## v0.9.6

### 安全

- 引入 rate-limit 与测试加固改进。
- 强化安全相关测试覆盖。

### 测试

- 改进测试基线。
- 增强异常场景与防御型场景验证能力。

### 相关提交

- `1a12160` merge: v0.9.6 rate-limit and test hardening
- `4555bfa` feat: v0.9.6 rate-limit and test hardening

---

## v0.9.5

### Workflow

- 增加 workflow persistence and cleanup。
- 改进工作流生命周期管理。

### 文档

- 增加 v0.9.5 任务完成总结。

### 相关提交

- `3d191f9` docs: add v0.9.5 task completion summary
- `da7f741` feat: v0.9.5 workflow persistence and cleanup

---

## v0.9.4

### 安全

- 建立 v0.9.4 安全基线。
- 加强后续安全加固措施。
- 完成 v0.9.4 security follow-up 合并。

### 相关提交

- `870b967` merge: v0.9.4 security follow-up
- `7b4c3c2` fix: harden v0.9.4 security follow-up
- `b05663e` fix: establish v0.9.4 security baseline

---

## 历史版本

> 以下版本当前没有对应 git tag，基于已核验的提交历史与提交信息整理。

### v0.9.3

#### Workflow

- 关闭 v0.9.3 workflow run dry-run loop。

#### 相关提交

- `fbcd665` feat: close v0.9.3 workflow run dry-run loop

---

### v0.9.2

#### CI/CD

- 新增默认 pipeline template YAML。

#### 相关提交

- `24862c6` add default pipeline template yaml

---

### v0.9.1

#### Agent Intelligence

- 新增深度追问机制。
- 新增视觉验证层。
- 改进复杂任务澄清能力。

#### 相关提交

- `026e9e8` feat(v0.9.1): add deepening interrogation and visual verification layer

---

### v0.9

#### Research Layer

- 新增 lightweight research system reproduction layer。
- 建立研究能力扩展基础。

#### 相关提交

- `3618454` feat(v0.9): add lightweight research system reproduction layer

---

### v0.8

#### Knowledge System

- 新增 authoritative technology adoption matrix。
- 新增 research adoption cockpit。
- 扩展研究与知识治理层。

#### 相关提交

- `e18e271` feat(v0.8): add authoritative technology adoption matrix and research adoption cockpit

---

### v0.7

#### MemoryOps Platform

- 扩展 MemoryOps Autopilot 平台。
- 改进记忆编排与自动化能力。

#### 相关提交

- `d5dfc2c` feat: expand memoryops autopilot platform v0.7

---

### Frontend / Engineering Updates

#### UI 与仓库工程化

- 新增 Vue 3 国风 SPA 控制台，包含 6 个视图、真实 API wiring 与构建产物。
- 新增国风秘府控制台，包含 SVG inline hero art、九宫格 layout 与 live v0.6 metrics。
- 从 git tracking 中移除 `node_modules`，并新增 `.gitignore`。

#### 相关提交

- `502ecac` feat(ui): add Vue 3 国风 SPA console with 6 views, real API wiring, built dist
- `44e8fd7` feat(ui): add 国风秘府控制台 with SVG inline hero art, 九宫格 layout, live v0.6 metrics
- `cc4c017` fix: remove node_modules from git tracking, add .gitignore

---

### v0.6

#### Runtime

- 新增 MemoryOps Runtime。
- 新增 Production MemoryArena-Lite。

#### Memory Governance

- 新增 self-evolution loop arena case。
- 新增 false-positive echo risk case。
- 新增 source-layer trace principle。

#### Refactor

- 降低 Memory Arena Runner cognitive complexity。

#### 相关提交

- `13ea153` feat(v0.6): MemoryOps Runtime + Production MemoryArena-Lite
- `a9e5d8a` feat(v0.6): add self-evolution loop arena case
- `bf42238` feat(v0.6): add false-positive echo risk case
- `a156094` docs(v0.6): add source_layer trace principle
- `744ac61` refactor(v0.6): reduce memory arena runner cognitive complexity

---

### v0.5

#### Memory Architecture

- 新增 Production Memory Evaluation Specification。
- 新增 Oversight Command Loop。
- 新增 Preference-Knowledge Evolution Policy。
- 新增 MemoryCapsule V2 Schema。
- 新增 Preference-Knowledge Memory Architecture。

#### 相关提交

- `4b4fae7` feat(v0.5): add production memory evaluation specification
- `fbe1ff8` feat(v0.5): add oversight command loop
- `fd0e187` feat(v0.5): add preference-knowledge evolution policy
- `5dfbd58` feat(v0.5): add MemoryCapsule v2 schema
- `a4bf334` feat(v0.5): add preference-knowledge memory architecture

---

### v0.4

#### Governance

- 新增 ASI risk mapping。
- 新增 memory security evaluation。
- 新增 memory governance policy。
- 新增 advanced memory technology and ASI environment。
- 新增 authoritative references。

#### 相关提交

- `a2fd551` feat(v0.4): add ASI risk mapping
- `31dc027` feat(v0.4): add memory security evaluation
- `685191e` feat(v0.4): add memory governance policy
- `264ddc1` feat(v0.4): add advanced memory technology and ASI environment
- `63e2a55` docs(v0.4): add authoritative references

---

### v0.3.1

#### Initial Release

- 初始化宛委枢忆 OSAgent 项目。
- 建立初始项目结构。

#### 相关提交

- `f65214f` init: 宛委枢忆 OSAgent project v0.3.1
