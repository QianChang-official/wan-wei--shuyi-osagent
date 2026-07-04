# CHANGELOG

本文档记录“宛委·枢忆 OSAgent”文档、架构与研究包的主要版本演进。

## v0.3.1 - 情感感知记忆调权与安全边界校正版

日期：2026-07-01

### 新增

- 新增 `CHANGELOG.md`，开始记录版本演进。
- `ARCHITECTURE.md` 升级到 v0.3.1。
- MemoryCapsule 的 `affective_metadata` 增加：
  - `affective_evidence_ids`
  - `affective_update_policy`
- 新增“灵犀情感分支结构”：情感线索抽取、情感元数据、记忆调制、安全边界。
- `EVALUATION.md` 新增 A20 情感感知记忆评测。
- `AcceptanceTestSpecification.md` 新增 A20-01 到 A20-05 验收项。
- 情感记忆论文包新增并确认：
  - Dynamic Affective Memory Management for Personalized LLM Agents, arXiv:2510.27418。

### 修改

- `SOTA_ALIGNMENT.md` 将 Dynamic Affective Memory Management 从“待核验”移动到“已纳入”。
- `AFFECTIVE_MEMORY_BRANCH.md` 修正 Dynamic Affective 的核验状态。
- 明确安全边界：`emotional_salience` 只能影响记忆保留、排序、偏好演化，不得覆盖司契护栏。

### 设计决策

- 统一采用“情感感知记忆元数据增强记忆管理 / Emotion-aware Memory Modulation”表述。
- 不使用“模型自有情感机制”作为正式表述，避免暗示模型具有真实情感。

---

## v0.3 - Memory OS + 情感感知记忆 + 安全治理 + 自演化评测

日期：2026-07-01

### 新增

- `ARCHITECTURE.md` 从简版架构升级为完整 v0.3 分层架构。
- 新增 `INSPIRATION_POOL.md`，整理操作系统、人类记忆、免疫系统、档案馆、认知架构、预测处理、数据治理等灵感。
- 新增 `AFFECTIVE_MEMORY_BRANCH.md`，提出“灵犀情感分支”。
- 情感记忆论文包新增：
  - Emotional Memory / Affective Computing 经典文献链接。
  - MemEmo、EmoLLM、MemoryBank、Emotional Chatting Machine、EmpatheticDialogues 等 PDF/链接。

### 修改

- `SOTA_ALIGNMENT.md` 纳入 MemEmo、Affective Computing、Emotional Memory、Generative Agents、MemoryBank。
- `ARCHITECTURE.md` 增加 affective_metadata、情感调权、纵向安全与情感评测。

### 设计决策

- 情感不是事实本身，而是记忆管理的调制信号。
- 系统不做心理诊断、不保存高敏情绪隐私、不把临时情绪误判为长期人格偏好。

---

## v0.2 - SOTA 对标、记忆安全、自演化与评测增强

日期：2026-07-01 前后

### 新增

- `SOTA_ALIGNMENT.md` 初版。
- `SECURITY_MEMORY.md`：司契护栏 2.0、记忆投毒防御、纵向安全。
- `ROADMAP.md`：v0.2 到 v1.0 路线。
- `ARCHITECTURE.md` 引入 MemoryCapsule。
- `PLAN.md` 增加 Phase 0 到 Phase 6。

### 纳入方向

- LangGraph
- MemOS / Memory OS
- Honcho
- SE-GA / TTME
- SimpleMem
- Memory Poisoning Defense
- Longitudinal Safety
- Memory-R2
- Engram / MoE 未来扩展

---

## v0.1 - 基础方案文档包

日期：早期整理阶段

### 内容

- 项目定位：面向麒麟操作系统的多源融合偏好与知识记忆优化系统。
- 核心主线：偏好记忆 + 知识记忆 + 安全遗忘 + 端侧高效检索。
- 基础文档：
  - `PLAN.md`
  - `ARCHITECTURE.md`
  - `API.md`
  - `DEPLOYMENT.md`
  - `USER_MANUAL.md`
  - `EVALUATION.md`
  - `AcceptanceTestSpecification.md`
  - `KYLIN_DOCS_MAPPING.md`
  - `COMPATIBILITY_TEST_REPORT.md`

### 设计来源

- 麒麟 OS Agent 赛题要求。
- PIXIU 的多源输入、证据卡、UKUI 入口思路。
- safe-agent 的规则护栏、安全审计思路。

---

## 工作区整理

日期：2026-07-01

### 调整

- 根目录整理为：
  - `00_main_project/`
  - `01_docs_legacy/`
  - `02_research/`
  - `03_mindmaps/`
  - `99_archives/`
- 新增 `README_工作区说明.md`。
- 所有移动为归档整理，未删除原始资料。
