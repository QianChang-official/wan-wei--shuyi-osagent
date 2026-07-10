# 更新日志

## Unreleased - 2026-07-10

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
