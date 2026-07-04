> 项目：宛委·枢忆 OSAgent / ASI-Memory Environment
> 文档：v0.4 / v0.5 权威参考资料清单
> 说明：本清单区分「顶会已发表」「前沿预印本 / 大机构研究」「行业治理 / 标准」三级，避免把预印本或工程资料误写成顶刊已发表论文。所有 arXiv 条目均已核验存在（标题、ID、发表日期一致）。

# 0. 使用原则

引用分三级，写进答辩/文档时必须按级别措辞：

- A 级：顶会已发表（可写「发表于 ICML 2024 / AAAI 2024」）。
- B 级：前沿预印本 / 大机构综述（必须写「arXiv 预印本」「综述性参考」，不得写「顶刊已发表」）。
- C 级：行业治理 / 标准化资料（写「行业安全治理参考」「标准化项目」，不是论文）。

核验状态说明：本轮通过 arXiv API 逐条核验了 6 篇预印本的存在性与元数据；OWASP / Microsoft 资料以官方站点为准。用户外部资料中出现的 cn.dubbo.apache.org、toutiao.com、bing.com 等链接为不可靠转述来源，已替换为真实一手链接。

野心与严谨声明：本项目不声称实现 ASI，也不声称模型具备真实自主超级智能；而是面向 ASI-Oriented Agent 的偏好与知识记忆优化问题，设计可治理、可追溯、可演化、可人类确认的长期记忆基座。所有 ASI / superalignment 资料仅作为“方向对标与问题定义”参考，不作为“本项目已实现”的依据。

---

# 1. v0.4：安全治理 + 精准遗忘 + 纵向评测

## 1.1 A Survey on Long-Term Memory Security in LLM Agents（B 级，核心）

- arXiv：https://arxiv.org/abs/2604.16548
- PDF：https://arxiv.org/pdf/2604.16548
- 本地：papers_v04_v05/V04__2604.16548__Long-Term_Memory_Security_in_LLM_Agents_Survey.pdf
- 发表：2026-04-17（arXiv 预印本，已核验）
- 级别：前沿预印本综述

核心贡献（可引用）：
- 记忆生命周期六阶段：Write / Store / Retrieve / Execute / Share & Propagate / Forget & Rollback。
- 四类安全目标：Integrity / Confidentiality / Availability / Governance。
- 提出 Verifiable Memory Governance（VMG）：安全不能只在检索/执行时补救，必须从 storage-time provenance、versioning、policy-aware retention 起。

项目落点：
- 司契护栏 → Write/Store 准入 + Integrity/Confidentiality。
- 忘机机制 → Forget & Rollback。
- 兰台鉴证 → Governance + 审计。
- MemoryCapsule provenance / version → VMG storage-time provenance。

## 1.2 Memory Poisoning Attack and Defense on Memory Based LLM-Agents（B 级）

- arXiv：https://arxiv.org/abs/2601.05504
- 本地：papers/Memory_Agents__2601.05504v2__Memory_Poisoning_Attack_and_Defense_on_Memory_Based_LLM-Agents.pdf
- 落点：司契护栏投毒防御、trust-aware retrieval、记忆净化。

## 1.3 Remembering More, Risking More: Longitudinal Safety Risks（B 级）

- arXiv：https://arxiv.org/abs/2605.17830
- 本地：papers/Memory_Agents__2605.17830v1__Remembering_More_Risking_More_Longitudinal_Safety_Risks_in_Memory-Equipped_LLM_A.pdf
- 落点：兰台鉴证纵向安全评测、NullMemory 对照、记忆前缀快照测试。

## 1.4 OWASP Agent Memory Guard（C 级，工程治理）

- 官方：https://owasp.org/www-project-agent-memory-guard/
- 级别：OWASP 项目 / 行业安全治理参考（非论文）
- 能力（已核验官方描述）：memory read/write 运行时防御层、SHA-256 完整性基线、注入/敏感泄露/受保护键改动/异常检测、YAML 安全策略、snapshots、forensic analysis、rollback。直接对应 ASI06: Memory Poisoning。
- 落点：司契护栏 3.0、Snapshot & Rollback 层、Memory Policy Engine。

## 1.5 OWASP Agentic Security Initiative（C 级）

- 官方：https://genai.owasp.org/initiatives/agentic-security-initiative/
- 级别：行业安全倡议（非论文）
- 要点（已核验）：聚焦 autonomous agents 与 multi-step AI workflows；点名 LangGraph / AutoGPT / CrewAI；配套 OWASP Top 10 for Agentic Applications。
- 落点：ASI 风险映射（ASI01/02/03/06/07）。

## 1.6 Microsoft: Manage AI memory safety in agentic systems（C 级）

- 官方：https://learn.microsoft.com/en-us/security/zero-trust/sfi/manage-agentic-memory-safety
- 级别：厂商安全治理文档（非论文）
- 要点（已核验）：把 AI memory 同时当成 high-value data 与 control plane；建议对写入做 intent + provenance gate（验证调用者授权、确认用户意图、避免从不可信来源隐式/自主创建记忆）；对 credentials/API keys/支付/证件等直接 block from memory。
- 落点：Memory Ingress Gateway 写入准入、L2 Policy Engine、「Memory is a control plane」首页论断。

---

# 2. v0.5：ASI-Oriented 偏好与知识记忆优化系统

## 2.1 The Road to Artificial SuperIntelligence: Survey of Superalignment（B 级，顶层理论）

- arXiv：https://arxiv.org/abs/2412.16468
- PDF：https://arxiv.org/pdf/2412.16468
- 本地：papers_v04_v05/V05__2412.16468__Road_to_ASI_Superalignment_Survey.pdf
- 发表：2024-12-21（arXiv 预印本，已核验）
- 要点：superalignment 两大目标——scalability in supervision 与 robust governance；综述 scalable oversight 方法。
- 落点：v0.5 为什么要做 ASI-Oriented 记忆基座、为什么需要可扩展监督与治理。

## 2.2 Scalable AI Safety via Doubly-Efficient Debate（A 级，顶会）

- arXiv：https://arxiv.org/abs/2311.14125
- PDF：https://arxiv.org/pdf/2311.14125
- 本地：papers_v04_v05/V05__2311.14125__Scalable_AI_Safety_via_Doubly-Efficient_Debate.pdf
- 发表：ICML 2024（PMLR v235；arXiv 首发 2023-11-23，已核验）
- 级别：顶会已发表（可写「发表于 ICML 2024」）
- 要点：任务复杂到人类难以直接判断时，用 debate 把识别 misalignment 拆成可验证子任务。
- 落点：v0.5 监督指挥层的多方案互证 / 批评者机制。

## 2.3 Constitutional AI: Harmlessness from AI Feedback（B 级，Anthropic）

- arXiv：https://arxiv.org/abs/2212.08073
- PDF：https://arxiv.org/pdf/2212.08073
- 本地：papers_v04_v05/V05__2212.08073__Constitutional_AI_Harmlessness_from_AI_Feedback.pdf
- 发表：2022-12-15（arXiv 预印本，已核验）
- 要点：人类只提供规则/原则；SL + RL 两阶段；RL 阶段用 AI preference model + RLAIF。
- 落点：v0.5 偏好与规则记忆层（policy memory / 原则库 / AI critique）。

## 2.4 Scalable agent alignment via reward modeling（B 级，DeepMind）

- arXiv：https://arxiv.org/abs/1811.07871
- PDF：https://arxiv.org/pdf/1811.07871
- 本地：papers_v04_v05/V05__1811.07871__Scalable_Agent_Alignment_via_Reward_Modeling.pdf
- 发表：2018-11-19（arXiv 预印本，已核验）
- 要点：从用户交互学习 reward function，再用 RL 优化 learned reward。
- 落点：v0.5 把人类/组织意图抽象成可更新的 reward / preference memory。

## 2.5 MemOS: A Memory OS for AI System（B 级，记忆基座核心）

- arXiv：https://arxiv.org/abs/2507.03724
- 本地：papers/MemOS__2507.03724v4__MemOS_A_Memory_OS_for_AI_System.pdf
- 要点：memory 作为可管理系统资源；统一 plaintext / activation / parameter 三类记忆的表示、调度、演化；MemCube 封装内容 + provenance + versioning。
- 落点：MemoryCapsule / MemCube、记忆调度与演化、v0.5 长期认知记忆基座。

## 2.6 Memory for Autonomous LLM Agents: Mechanisms, Evaluation, Frontiers（B 级，综述）

- arXiv：https://arxiv.org/abs/2603.07670
- PDF：https://arxiv.org/pdf/2603.07670
- 本地：papers_v04_v05/V05__2603.07670__Memory_for_Autonomous_LLM_Agents_Survey.pdf
- 发表：2026-03-08（arXiv 预印本，已核验）
- 要点：把 agent memory 形式化为 Write–Manage–Read loop；覆盖 write-path filtering、contradiction handling、latency budgets、privacy governance。
- 落点：v0.5 Write-Manage-Read 生产记忆闭环、评测与隐私治理。

## 2.7 MemoryBank: Enhancing LLMs with Long-Term Memory（A 级，顶会）

- arXiv：https://arxiv.org/abs/2305.10250
- 本地：papers_affective_memory/Agent_Memory__MemoryBank2023__MemoryBank_Enhancing_Large_Language_Models_with_Long-Term_Memory.pdf
- 发表：AAAI 2024（可写「发表于 AAAI 2024」）
- 要点：长期记忆机制 + 受艾宾浩斯遗忘曲线启发的记忆更新；SiliconFriend 长期陪伴。
- 落点：retention_score、遗忘曲线、长期用户画像。

---

# 3. v0.5 逻辑链（可直接讲）

```text
ASI / Superalignment（2412.16468）
  ↓ 需要可扩展监督
Scalable Oversight / Debate（2311.14125, ICML 2024）
  ↓ 需要偏好/规则/奖励建模
Constitutional AI（2212.08073） + Reward Modeling（1811.07871）
  ↓ 落到长期记忆基座
Memory OS（2507.03724）
  ↓ 落到生产记忆闭环
Write-Manage-Read（2603.07670）
  ↓
生产监督与指挥
```

---

# 4. 措辞红线

- 可写「发表于 ICML 2024」：仅 Doubly-Efficient Debate（2311.14125）。
- 可写「发表于 AAAI 2024」：仅 MemoryBank（2305.10250）。
- 其余 arXiv 条目一律写「arXiv 预印本 / 综述性参考」，不得写「顶刊已发表」。
- OWASP / Microsoft 写「行业安全治理 / 标准化参考」，不是论文。
- 2604.16548 与 2603.07670 是 2026 年新预印本，答辩时如被追问，说明「最新前沿预印本，用于方向对标，非既成定论」。

# 5. 一句话

v0.4 的权威依据在 Memory Security / Governance；v0.5 的权威依据在 Superalignment / Scalable Oversight / Memory OS / Agent Memory。顶会级硬支撑 = ICML 2024 Debate + AAAI 2024 MemoryBank；最前沿架构 = arXiv 综述 + MemOS + OWASP/Microsoft 治理资料。
