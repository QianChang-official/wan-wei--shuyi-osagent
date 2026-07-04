> 项目：宛委·枢忆 OSAgent / ASI-Memory Environment
> 文档：可填充的先进记忆优化技术清单（v0.4 / v0.5 增强）
> 说明：本清单收录 2022-2025 与记忆优化直接相关的先进技术。所有 arXiv 条目均已逐条核验（ID / 标题 / 年份一致）。级别与措辞遵循 V04_V05_AUTHORITATIVE_REFERENCES.md 的三级原则。本项目吸收其思想，不声称已实现其全部机制。

# 0. 分类总览

按"能填进项目哪一层"分四组：

```text
A. 检索侧记忆结构升级：HippoRAG、MemoRAG
B. 测试期/长期神经记忆：Titans、Mamba
C. 参数化记忆编辑与遗忘：ROME、MEMIT
D. 上下文压缩与 Agent 记忆组织：LLMLingua、MemGPT、A-MEM
```

---

# A. 检索侧记忆结构升级

## A.1 HippoRAG（NeurIPS 2024）

- arXiv：https://arxiv.org/abs/2405.14831
- 本地：papers_advanced_memory/ADV__2405.14831__HippoRAG_Neurobiologically_Inspired_Long-Term_Memory.pdf
- 级别：顶会已发表（NeurIPS 2024，可写「发表于 NeurIPS 2024」）
- 核心：受海马体索引理论启发，用知识图谱 + Personalized PageRank 做单步多跳检索，模拟人脑跨记忆关联召回。
- 项目落点：**建木网络** 升级——把 RelationEdge 关系图 + PageRank 式扩散召回，作为"跨记忆关联检索"的理论支撑与算法参考。让检索不止 top-k，而是沿关系边一跳触达相关记忆簇。

## A.2 MemoRAG（arXiv 预印本）

- arXiv：https://arxiv.org/abs/2409.05591
- 本地：papers_advanced_memory/ADV__2409.05591__MemoRAG_Global_Memory-Enhanced_Retrieval.pdf
- 级别：arXiv 预印本
- 核心：用一个轻量"全局记忆"模型先形成对整库的草稿线索，再指导精确检索，解决长上下文/模糊查询召回。
- 项目落点：**句芒演化 + 检索规划**——先用全局记忆生成检索意图草稿，再落到 FTS/向量精确召回，对齐我们已有的"意图感知检索规划"。

---

# B. 测试期 / 长期神经记忆

## B.1 Titans: Learning to Memorize at Test Time（Google，arXiv 预印本）

- arXiv：https://arxiv.org/abs/2501.00663
- 本地：papers_advanced_memory/ADV__2501.00663__Titans_Learning_to_Memorize_at_Test_Time.pdf
- 级别：arXiv 预印本（Google Research）
- 核心：引入神经长期记忆模块，在推理期（test time）根据"惊奇度/surprise"决定记什么、忘什么，兼顾长期记忆与快速遗忘，可扩展到超长上下文。
- 项目落点：**灵犀情感 emotional_salience + retention_score 的理论近亲**——Titans 的 surprise 信号 ≈ 我们的显著性/重要性调制。可写成"记忆保留由显著性驱动"的先进对标；未来模型侧扩展方向。

## B.2 Mamba: Selective State Spaces（arXiv 预印本，被广泛采用）

- arXiv：https://arxiv.org/abs/2312.00752
- 本地：papers_advanced_memory/ADV__2312.00752__Mamba_Selective_State_Spaces.pdf
- 级别：arXiv 预印本（COLM 2024 接收）
- 核心：状态空间模型（SSM）以线性复杂度维护"压缩状态"作为序列记忆，selective 机制决定保留/丢弃哪些信息。
- 项目落点：**模型侧记忆机制参考**——作为"线性记忆/压缩状态"的理论背景，放到未来扩展池，不作为当前工程主线。

---

# C. 参数化记忆编辑与遗忘（直接改权重里的"记忆"）

## C.1 ROME: Locating and Editing Factual Associations in GPT（NeurIPS 2022）

- arXiv：https://arxiv.org/abs/2202.05262
- 本地：papers_advanced_memory/ADV__2202.05262__ROME_Locating_and_Editing_Factual_Associations_in_GPT.pdf
- 级别：顶会已发表（NeurIPS 2022）
- 核心：定位事实知识存储在哪些 MLP 层，并做因果干预式单条编辑。
- 项目落点：**忘机机制的高阶对标**——说明"遗忘"不止删外部记忆条目，前沿方向可深入到参数化知识定位与编辑。我们工程主线做外部记忆遗忘，参数编辑列为"高阶遗忘研究对标"。

## C.2 MEMIT: Mass-Editing Memory in a Transformer（ICLR 2023）

- arXiv：https://arxiv.org/abs/2210.07229
- 本地：papers_advanced_memory/ADV__2210.07229__MEMIT_Mass-Editing_Memory_in_a_Transformer.pdf
- 级别：顶会已发表（ICLR 2023）
- 核心：ROME 的规模化版本，一次性批量编辑/更新数千条参数化记忆。
- 项目落点：**批量记忆更新/失效的理论支撑**——对标"知识记忆版本化 + 批量废弃(deprecated)"，说明大规模记忆治理有前沿方法论。

---

# D. 上下文压缩与 Agent 记忆组织

## D.1 LLMLingua: Compressing Prompts（微软，EMNLP 2023）

- arXiv：https://arxiv.org/abs/2310.05736
- 本地：papers_advanced_memory/ADV__2310.05736__LLMLingua_Compressing_Prompts.pdf
- 级别：顶会已发表（EMNLP 2023）
- 核心：用小模型对提示/上下文做高比例压缩（最高约 20x）而基本不掉性能。
- 项目落点：**SimpleMem 式语义压缩的工程近亲**——注入 Agent 上下文前先压缩记忆载荷，降低 token 成本与延迟；对齐检索闭环里的"高信息密度记忆单元"。

## D.2 MemGPT / Letta: LLMs as Operating Systems（arXiv 预印本）

- arXiv：https://arxiv.org/abs/2310.08560
- 本地：papers_advanced_memory/ADV__2310.08560__MemGPT_LLMs_as_Operating_Systems.pdf
- 级别：arXiv 预印本（影响力大，已产品化为 Letta）
- 核心：把 LLM 当操作系统，做主上下文/外部存储的"记忆分页(paging)"，自动换入换出，突破固定窗口。
- 项目落点：**枢忆核 + 建木网络分层流转的直接同宗**——短/中/长期记忆换入换出 ≈ MemGPT 的分页调度。可作为"端侧 Memory OS"定位的最强同类对标（连命名思路都一致）。

## D.3 A-MEM: Agentic Memory for LLM Agents（arXiv 预印本）

- arXiv：https://arxiv.org/abs/2502.12110
- 本地：papers_advanced_memory/ADV__2502.12110__A-MEM_Agentic_Memory_for_LLM_Agents.pdf
- 级别：arXiv 预印本
- 核心：受 Zettelkasten 卡片盒笔记法启发，记忆自动生成结构化笔记、打标签、建链接，并随新记忆演化旧记忆网络。
- 项目落点：**建木网络自组织 + 句芒演化的直接对标**——记忆自动建链、随新记忆更新旧记忆，正是我们"关系边 + 自演化"要做的事。

---

# 1. 一图映射（技术 → 项目层）

```text
HippoRAG / A-MEM        → 建木网络（关系图 + 自组织 + PageRank 式关联召回）
MemoRAG                 → 句芒演化 / 意图感知检索规划
Titans                  → 灵犀情感 emotional_salience + retention_score（显著性驱动记忆）
Mamba                   → 模型侧线性记忆（未来扩展池）
ROME / MEMIT            → 忘机机制高阶对标（参数化知识定位/批量编辑遗忘）
LLMLingua               → 记忆载荷语义压缩（检索闭环 token 优化）
MemGPT / Letta          → 枢忆核记忆分页调度（端侧 Memory OS 同宗对标）
```

# 2. 建议填充优先级

```text
P0 直接强化现有分支（写进 v0.4/v0.5 SOTA 对标）：
  HippoRAG、A-MEM、MemGPT、LLMLingua、MemoRAG

P1 作为高阶研究对标（答辩加分，不承诺实现）：
  Titans、ROME、MEMIT

P2 未来模型侧扩展池：
  Mamba
```

# 3. 措辞红线（沿用 references 规则）

- 可写「发表于顶会」：HippoRAG(NeurIPS 2024)、ROME(NeurIPS 2022)、MEMIT(ICLR 2023)、LLMLingua(EMNLP 2023)、Mamba(COLM 2024)。
- 其余（Titans、MemoRAG、MemGPT、A-MEM）写「arXiv 预印本」，不得写「顶刊已发表」。
- 参数化记忆编辑（ROME/MEMIT）写「高阶研究对标」，本项目工程主线是外部记忆治理，不声称已实现权重编辑。
- Titans 的 surprise 与本项目 emotional_salience 是"思想近亲/对标"，不声称等同实现。

# 4. 一句话

宛委·枢忆最强的三个可填充增强点：**MemGPT 式记忆分页调度**（坐实"端侧 Memory OS"定位）、**HippoRAG/A-MEM 式关系图自组织召回**（强化建木网络）、**LLMLingua 式记忆压缩**（降本增效）。它们都有顶会或大机构预印本支撑，且能自然落到现有分支，不是硬蹭。
