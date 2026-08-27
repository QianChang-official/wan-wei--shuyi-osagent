# Memory OS 白皮书结构（8 章）

> 来源：6.docx 第 5 节"重叠与合并建议"的 A 方案（白皮书定位）
> 状态：结构草案，供浅唱审阅
> 日期：2026-08-20

## 设计原则

- 一本白皮书 + 附录库，不再无限增加 docx
- 每个章节引用来源文档，正文统一术语
- 代码作为"规范草案"，以可运行的 Python/SQLite 形式给出

---

## 第 1 章：问题定义与 Memory OS 愿景

**来源**：0.docx + 4.docx

核心内容：
1. AI Memory 从"把历史塞进上下文"演化为"可治理的系统资源"
2. 现状问题：能记 ≠ 记得准 ≠ 记得安全 ≠ 记得值
3. 愿景：Memory 是 first-class operational resource（MemOS 对齐）
4. 定义 Memory OS = Memory Lifecycle + Memory Governance + Memory Economics + Memory Harm Budget + MQ Evaluation

---

## 第 2 章：认知科学根基

**来源**：1.docx

核心内容：
1. Tulving：情景/语义/程序记忆三分
2. Marr 1971 + Hippocampal Index Theory 1986：快速编码 + 索引到分布式痕迹
3. CLS 1995：快速海马编码 + 慢速皮层巩固
4. ACT-R / Soar / GWT / Minsky / Schank：工作记忆 + 程序记忆 + 全局工作区 + 案例脚本
5. 七大主线 → Memory OS 的对应设计约束

---

## 第 3 章：技术地图与 L0-L4 架构

**来源**：0.docx + 1.txt

核心内容：
1. 技术路线综述：LongMem / LongMemEval / SimpleMem / MemOS / AgeMem / Generative Agents / Reflexion / RAG / GraphRAG
2. 数据库不是四选一：SQL（真相）+ 全文（精确）+ 向量（语义）+ 图（关系）
3. L0-L4 分层动态记忆：
   | 层级 | 内容 | 载体 | 更新速度 |
   |------|------|------|---------|
   | L0 | 当前对话 | KV cache / 上下文 | 实时 |
   | L1 | 近期经历 | 向量/隐状态 | 秒级 |
   | L2 | 用户事实/项目状态 | SQL + 原文库 | 实时写入 |
   | L3 | 稳定偏好/技能 | LoRA Adapter | 小时/周期 |
   | L4 | 通用能力 | 基础模型 | 极慢 |
4. 关键原则：越动态的内容越不应写入权重

---

## 第 4 章：OSAgent 项目现状与 Gap

**来源**：2.docx

核心内容：
1. 打分：产品工程 6.5/10，记忆智能深度 3.5/10，SOTA 对齐 3/10
2. 领先点：端侧治理、麒麟集成、安全边界、边界诚实
3. 五大缺口（ROI 排序）：
   - 评测与 Trace
   - 混合检索（FTS5 + 向量 + reranker）
   - 工具轨迹 → 经验记忆
   - 冲突与版本链
   - GuardedMemory 安全层

---

## 第 5 章：Memory Experience Benchmark

**来源**：3.docx

核心内容：
1. 定位：产品回归型 Memory QA，不是复刻 LongMemEval
2. 五类评测：偏好提取、知识召回、冲突更新、遗忘、安全投毒
3. 权重：用户体验 40% > 安全 25% > 产品能力 25% > 学术价值 10%
4. CI/CD：每 PR 跑 Mini-MEB（14 例）、每日 Full-MEB（当前公开集 20 例）、每周 RedTeam-MEB、每月 Benchmark Sync
5. Memory Trace 必存：query rewrite → 候选 → 过滤 → rerank → 注入片段

---

## 第 6 章：Memory Harm × Economics 标准

**来源**：4.docx

核心内容：
1. Memory Harm Framework：MHG 分级、MHS 评分、Harm Budget、一票否决
2. Memory Economics：ROI、Utility、Density、Noise Ratio、Compression Gain
3. MHEB 综合分 = 0.40 UX + 0.25 Safety_inverse + 0.25 Product + 0.10 Academic
4. Safety 一票否决：MHG-4/5、跨租户泄漏、删除残留、投毒触发 → 只进 incident report
5. Memory Health / Decay / Self-Knowledge 三面板

---

## 第 7 章：IQ/MQ 双轴智能模型

**来源**：5.docx + 本草案补充

核心内容：
1. 记忆与智能是四种关系同时成立：高度相关、局部因果、功能互补、评测独立
2. IQ × MQ 二维矩阵：
   | | MQ 低 | MQ 高 |
   |---|---|---|
   | IQ 低 | 普通助手 | 大号知识库 |
   | IQ 高 | GPT 类模型 | 真正 Agent |
3. MQ 定义：跨会话/跨任务下记忆全生命周期操作的效能（写入/检索/更新/遗忘/安全）
4. 评测分化预测：ARC-AGI 测 IQ，LongMemEval → MHEB 测 MQ
5. 战略含义：宛委·枢忆 = MQ 高 + IQ 借用（端侧治理 + 任意强模型）

---

## 第 8 章：Governance / Accounting / Lifecycle 规范

**来源**：新增（4.docx 扩展）

核心内容：
1. Memory Ledger：每次 write/update/retrieve/inject/delete 入账
2. Provenance Card：owner / scope / source / confidence / valid_from / valid_until / supersedes
3. Lifecycle 状态机：candidate → active → reinforced → stale → conflicted → archived → quarantined → deleted
4. Quarantine 触发条件与发布冻结
5. 删除验证：覆盖原文、摘要、向量、图边、缓存
6. MHG-3/4/5 事故响应协议

---

## 附录建议

- 附录 A：原典理论列表（Tulving/Marr/CLS/ACT-R/Soar/GWT/Minsky/FEP）
- 附录 B：术语表（统一 Memory OS / Harm / Economics / MQ / Ledger / Lifecycle）
- 附录 C：Benchmark case schema（memory_case.json）
- 附录 D：实现代码（随各章规范附 Python 草案）
