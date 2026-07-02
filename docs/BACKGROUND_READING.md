> 项目：宛委·枢忆 OSAgent
> 文档：工程背景 / 基础共识 / 入门参考（D 类 · Background Reading）
> 重要声明：本文所列资料均为行业科普文章、博客、框架实践解释与转载镜像，**不是学术论文，也不构成 v0.4 / v0.5 / v0.6 的核心创新依据**。它们仅用于解释 Agent 记忆系统的基础共识（为什么要做记忆、短期/长期记忆是什么、Record/Retrieve 基础闭环、上下文工程为什么必要）。

# 0. 分级说明（与权威参考严格区分）

本项目引用资料分级如下：

```text
A 级：顶会已发表（ICML / NeurIPS / AAAI）—— 可写“发表于 XXX”
B 级：arXiv 前沿预印本 / 大机构综述 —— 写“预印本 / 综述性参考”
C 级：行业安全治理 / 标准化资料（OWASP / Microsoft）—— 写“行业治理参考”
D 级：工程背景 / 科普文章 / 博客 / 转载（本文）—— 写“工程背景，非权威依据”
```

A/B/C 三级见 `docs/V04_V05_AUTHORITATIVE_REFERENCES.md`。
**本文（D 级）绝不与 A/B/C 混列**，也不得在答辩中作为"权威支撑/顶刊依据/核心 SOTA"引用。

# 1. 用途定位

| 资料内容 | 对当前架构的用途 | 最适合放哪 |
|----------|------------------|-----------|
| 短期/长期记忆定义 | 有用，但基础 | v0.1 / v0.2 / README |
| Record / Retrieve | 有用，作为基础闭环 | v0.2 起步 |
| 上下文工程（压缩/摘要/卸载） | 有用，可支撑 Working Memory | v0.3 / v0.6 Runtime |
| 向量库 / RAG | 有用，但不是创新 | v0.1–v0.3 背景 |
| 用户偏好 / 历史交互 | 有用，可映射到 v0.5 | v0.5 背景补充 |
| 作为 v0.4/v0.5/v0.6 核心依据 | **不够** | 不建议 |

一句话：**这些资料给 v0.1–v0.3 补"行业共识底座"，v0.4–v0.6 的亮点仍靠安全治理、演化、监督指挥与多会话评测。**

# 2. 基础概念（可从这些资料引用的通俗定义）

```text
会话级记忆 / 跨会话记忆
短期记忆（单次会话上下文）/ 长期记忆（跨会话偏好、历史交互、领域知识）
Record（从短期提取事实/偏好/经验写入长期）
Retrieve（按查询从长期检索并注入短期上下文）
上下文工程：压缩、摘要、卸载（应对 maxToken 限制）
```

对应本项目：Record/Retrieve 是基础版，v0.5 的 Write–Manage–Read–Reflect 是增强版。

# 3. 背景阅读清单（D 级 · 仅供入门理解）

## 3.1 记忆系统基础科普

1. 阿里云开发者社区｜AI Agent 记忆系统：从短期到长期的技术架构与实践 — https://developer.aliyun.com/article/1710635
2. 阿里云开发者社区｜同主题（另一篇）— https://developer.aliyun.com/article/1704117
3. 知乎｜Agent 记忆系统深度解析：4 种记忆架构对比 — https://zhuanlan.zhihu.com/p/2043027385675670935
4. JavaGuide｜AI Agent 记忆系统：短期、长期与记忆演化机制 — https://javaguide.cn/ai/agent/agent-memory.html
5. 知乎｜6 个 AI Agent 记忆框架 — https://zhuanlan.zhihu.com/p/2017613664149059246
6. CSDN｜Agent 长期记忆系统设计实战 — https://blog.csdn.net/Python_cocola/article/details/159114336
7. CSDN｜AI Agent 记忆系统开发实战与优化技巧 — https://blog.csdn.net/weixin_32830601/article/details/162501275
8. AI Insight｜Agent Memory 全景：从 MemGPT 到 A-MEM — https://www.ai-insight.org/reports/agent-memory
9. 知乎｜一文读懂 AI Agent 记忆系统 — https://zhuanlan.zhihu.com/p/1989019657500386299
10. 知乎｜智能体记忆架构：短期与长期记忆 — https://zhuanlan.zhihu.com/p/1961183774369887317
11. 博客园｜从上下文工程到长期记忆组件集成 — https://www.cnblogs.com/alisystemsoftware/p/19417127

## 3.2 转载 / 镜像（同源，仅备查）

12. 腾讯新闻转载 — https://news.qq.com/rain/a/20260130A01VTD00
13. 腾讯云开发者社区转载 — https://cloud.tencent.com/developer/news/3534554
14. 51CTO｜技术架构与实践指南 — https://www.51cto.com/aigc/9666.html
15. SegmentFault｜技术原理、架构设计与实战 — https://segmentfault.com/a/1190000047526306
16. CSDN｜AI Agent 记忆系统全解析 — https://blog.csdn.net/EnjoyEDU/article/details/156417471

## 3.3 Hermes / Hindsight 方向（框架背景，非本项目依据）

> 说明：本项目原型运行在 Hermes Agent 之上，以下为该框架记忆系统的第三方解读博客，仅作运行环境背景，不作学术依据。

17. Hermes Agent 记忆系统深度研究：三层架构 — https://wujiaming88.github.io/2026/04/23/hermes-memory-system-research.html
18. Hermes Agent 自动 Skill 创建机制 — https://wujiaming88.github.io/2026/04/22/hermes-agent-skill-creation-research.html
19. Hermes Agent 进化机制深度分析 — https://www.daoyuly.cn/2026/2026-04-13-hermes-agent-evolution-mechanism/
20. 博客园｜Hindsight + Hermes-Agent 记忆与检索系统 — https://www.cnblogs.com/fengyege/p/19933035

# 4. 与版本路线的对应

```text
短期/长期记忆        → v0.1 基础记忆原型
Record / Retrieve    → v0.2 MemoryCapsule 起步
上下文压缩/摘要/卸载 → v0.3 Memory OS 工作记忆 / v0.6 Runtime working memory
用户偏好/历史交互    → v0.5 preference / knowledge / experience memory
```

# 5. 诚实边界

```text
本文资料 = 基础工程背景（D 级）
本文资料 ≠ 高级创新依据
```

不得将本文任何链接写作"权威论文支撑""顶刊依据""核心 SOTA"。
真正支撑 v0.4/v0.5/v0.6 的权威依据（Agent Memory Survey、MemoryArena、MemOS、HippoRAG、Superalignment、Reflexion、Generative Agents 等）见 `docs/V04_V05_AUTHORITATIVE_REFERENCES.md` 与 `docs/ADVANCED_MEMORY_TECH.md`。
