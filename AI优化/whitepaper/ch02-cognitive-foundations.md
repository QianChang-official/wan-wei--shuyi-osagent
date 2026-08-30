# 第 2 章:认知科学根基

> **Canonical**:本章是「认知科学依据」的唯一权威处;第 7 章只引用结论。
> **来源**:1.docx(早期超前 AI 记忆理论研究报告)
> **状态**:✅ 已从 docx 提取并整合

## 2.1 核心结论

最超前的历史思想不是单一「长上下文」,而是「多记忆系统协同」。

## 2.2 Tulving:情景/语义记忆二分

Tulving 1972 年把长期记忆拆成 episodic memory(个人事件与时空关系)与 semantic memory(词、概念、关系和规则)。这一划分至今仍是认知神经科学关键概念,且 Tulving 从一开始就强调两者相互依赖。

**对应现代 Agent**:会话日志/事件记忆 + 知识库/RAG + 技能/workflow 三分法。注意:Tulving 原始框架是 episodic/semantic 二分,procedural memory 是后续扩展;现代 Agent 的三分法是对 Tulving 的工程化扩展,不是 Tulving 本人的原始定义。

## 2.3 Marr 1971 + Hippocampal Index Theory 1986 + CLS 1995

- **Marr 1971**:把 archicortex/hippocampus 看作简单记忆系统,提出稀疏表示(约 10^5 细胞中约 200 个激活、可存约 10^5 个简单表示,少量线索即可触发回忆);已预见「白天存储事件、用部分线索检索、夜间转移到新皮层」的方向。
- **Teyler & DiScenna 1986**:把海马定义为「新皮层激活区域的索引」——索引重激活可带动新皮层阵列重激活并产生记忆体验。
- **CLS 1995**:把「快速海马学习 + 慢速新皮层结构学习」形式化为互补学习系统(Complementary Learning Systems)。

**对 Memory OS 的约束**:长期记忆系统需要同时处理快速编码(会话内即时写入)与慢速巩固(周期性整理/合并),两者不可互相替代。

## 2.4 ACT-R / Soar / GWT / Minsky / Schank

共同启发:Agent 需要「结构化工作记忆 + 可执行程序记忆 + 全局工作区 + 案例/脚本」。

- **ACT-R**:procedural knowledge(production rules)+ declarative knowledge(chunks)互动;ACT-R 5.0 用模块与 buffers 连接感知、动作、目标和陈述性记忆。
- **Soar 1987**:general intelligence architecture 的实现提案,目标是支持完整任务范围、问题求解方法、知识表示和学习。
- **GWT(Baars Global Workspace)**:意识/工作记忆是广播机制,使大量专门网络共享信息并协同解决单个模块不能解决的问题。

## 2.5 与现代 AI 的差距

截至 2026-08,现代 AI 部分验证了这些预测,但远未充分实现:

- 已有雏形:成功经验沉淀、失败教训、知识检索、工具调度与安全审计
- 显著距离:持续巩固(Marr/CLS 意义)、情景-语义互相转化(Tulving 意义)、全局广播与多专家竞争(GWT 意义)、行动-感知统一最优化(FEP 意义)

## 2.6 七大主线 → Memory OS 设计约束

| 认知科学主线 | 对 Memory OS 的约束 |
|---|---|
| Tulving 情景/语义二分 | 记忆必须区分事件型与知识型,检索策略不同 |
| Marr 稀疏编码 | 少量线索即可触发完整回忆 → 索引设计的理论基础 |
| CLS 快慢互补 | 必须有快速写入通道 + 慢速巩固通道,不可合并 |
| ACT-R 程序/陈述分离 | 技能(workflow)与事实(knowledge)分开存储和检索 |
| GWT 全局广播 | 记忆系统需要全局可访问的工作区,不是孤立存储 |
| Schank 案例脚本 | 记忆检索需要案例匹配与脚本泛化能力 |
| FEP 行动-感知统一 | 记忆写入与行动决策是同一优化过程的两面 |
