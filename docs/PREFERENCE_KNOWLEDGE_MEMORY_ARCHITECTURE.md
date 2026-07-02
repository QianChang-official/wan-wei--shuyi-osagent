> 项目：宛委·枢忆 OSAgent / ASI-Memory Environment
> 版本：v0.5（面向 ASI-Oriented Agent 的偏好与知识记忆优化系统）
> 命名说明：本文中 ASI-Oriented 指 Artificial Superintelligence-Oriented（面向人工超级智能方向）。本项目不声称实现 ASI，仅为未来更强 Agent 准备一套可治理、可演化、可监督的长期认知记忆基座。
> 依据：本文是 v0.5 总纲，建立在 v0.4 安全记忆治理底座（`ASI_ORIENTED_MEMORY_ENVIRONMENT.md`）之上，不绕过其治理策略。

# 偏好与知识记忆优化系统架构 PREFERENCE_KNOWLEDGE_MEMORY_ARCHITECTURE（v0.5）

## 0. 一句话定位

v0.4 解决：记忆能不能安全进生产。
v0.5 解决：长期记忆如何真正产生生产价值。

```text
v0.5 要做的不是“记住更多”，而是让 Agent 长期记住
什么是重要的、什么是可信的、什么是用户偏好的、
什么是组织允许的、什么是生产中验证过的。
```

完整定位：

```text
在 v0.4 安全记忆治理底座之上，v0.5 将用户偏好、组织规则、生产知识、
任务经验、风险案例、反馈信号和复盘结论统一封装为可治理的 MemoryCapsule，
并通过写入、管理、检索、指挥、复盘和演化闭环，
让 Agent 在生产环境中长期积累认知状态，服务于可监督的生产辅助决策。
```

---

## 1. 与 v0.4 的关系（不可绕过）

```text
v0.4：安全记忆治理底座        v0.5：偏好与知识记忆优化层
├── 写入准入                  ├── 偏好建模
├── 策略引擎                  ├── 知识建模
├── 敏感分级                  ├── 经验沉淀
├── 投毒隔离                  ├── 关系演化
├── 可信检索                  ├── 冲突合并
├── 精准遗忘                  ├── 生产复盘
├── 快照回滚                  ├── 可扩展监督
└── 审计评测                  └── 辅助生产指挥
```

铁律：v0.5 的所有写入、检索、演化、指挥，都必须先经过 v0.4 治理策略。

优先级（写死，任何情况不被覆盖）：

```text
安全治理 > 用户显式偏好 > 组织规则 > 知识可信度 > 个性化优化 > 情感显著性
```

---

## 2. 理论依据（五条线，措辞守 A/B/C 分级）

```text
Superalignment 综述（arXiv 2412.16468 预印本）
  → 为什么要做“可扩展监督 + 稳健治理”的记忆底座
  → v0.5 把人类偏好/规则/纠偏沉淀为可复用监督记忆，作为 scalable supervision 的工程侧记忆基座

Agent Memory 综述（arXiv 2603.07670 预印本）
  → 为什么要 Write–Manage–Read 闭环
  → v0.5 扩展为 Write → Manage → Read → Act → Reflect → Update

MemOS（arXiv 2507.03724 预印本）
  → 为什么叫 Memory OS；记忆作为可管理系统资源
  → 借鉴 MemCube 思想，不声称完整实现其模型级记忆能力

Constitutional AI（arXiv 2212.08073 预印本）
  → 为什么要有“原则/规则记忆”（policy memory）
  → 组织原则、用户边界、安全规则作为可版本化、可审计、可引用的记忆

Reward Modeling（arXiv 1811.07871 预印本）
  → 为什么偏好可以变成监督信号
  → 不训练 reward model，但把偏好与反馈结构化为可治理记忆，为未来 RLAIF/AI feedback 提供数据基础
```

详见 `docs/V04_V05_AUTHORITATIVE_REFERENCES.md`（含措辞红线：仅 ICML 2024 Debate / AAAI 2024 MemoryBank 可写“已发表”）。

---

## 3. 五大核心目标

```text
3.1 把偏好从“聊天习惯”升级为“生产决策约束”
    用户/团队/组织/任务/安全/成本/质量/流程/确认偏好

3.2 把知识从“检索文本”升级为“可治理知识状态”
    事实/流程/约束/经验/风险/策略/因果知识，均带来源与证据

3.3 把记忆从“条目”升级为“关系网络”
    偏好↔来源、知识↔证据、规则↔风险、经验↔结果、失败↔修复

3.4 把监督从“人工逐步审批”升级为“记忆驱动监督”
    人工监督 → 监督记忆 → 自动引用 → 风险升级 → 人类确认

3.5 把生产过程从“一次性执行”升级为“复盘学习闭环”
    每次任务后：用了哪些记忆、哪些有用、哪些误导、产生哪些新偏好/知识
```

---

## 4. 九层架构

```text
L1 Production Perception Layer   生产感知层：接入指令/工具/仓库/文档/日志/反馈
L2 Experience Event Layer        经验事件层：原始输入 → 标准经验事件（先 candidate）
L3 MemoryCapsule 2.0 Store       统一记忆容器层：偏好/知识/经验/规则/风险/技能
L4 Preference Memory Engine      偏好记忆引擎：分型、来源、写入、演化
L5 Knowledge Memory Engine       知识记忆引擎：分型、证据、冲突、版本
L6 Relation & Causal Graph       关系与因果网络：supports/contradicts/supersedes/causes…
L7 Memory Evolution Engine       记忆演化引擎：强化/衰减/合并/拆分/替代/废弃/提升
L8 Oversight & Command Loop      监督与指挥闭环：风险分级 自动/建议/确认/只读
L9 Production Reflection & Eval  生产复盘与评测层：任务后更新偏好与知识
```

映射到既有模块：

```text
石渠校验 → L1/L2 感知与事件标准化
司契护栏 → v0.4 治理，贯穿 L3 写入
玄珠偏好 → L4 偏好引擎
琅嬛知识 → L5 知识引擎
建木网络 → L6 关系与因果网络
句芒演化 → L7 演化引擎
灵犀情感 → 调 retention/retrieval，永不覆盖安全
兰台鉴证 → L9 复盘与评测
```

---

## 5. 核心闭环：Write–Manage–Read–Act–Reflect

```text
生产输入
  ↓
标准事件（L2）
  ↓
v0.4 安全准入（治理策略）
  ↓
MemoryCapsule 2.0（L3）
  ↓
偏好/知识分型（L4/L5）
  ↓
关系网络连接（L6）
  ↓
演化引擎维护（L7）
  ↓
监督指挥层召回（L8）
  ↓
生成计划/建议/确认点
  ↓
生产结果
  ↓
复盘学习（L9）
  ↓
偏好与知识更新
```

一句话：v0.5 是生产记忆的认知循环。

---

## 6. 监督指挥的风险分级（L8 核心边界）

系统不无条件自动执行：

```text
低风险   ：自动建议 / 自动处理
中风险   ：给出方案 + 证据卡 + 影响说明
高风险   ：必须用户确认
关键风险 ：只读分析，不执行
```

召回输出必须可解释（用了哪些偏好/知识/风险案例，附 evidence_card）。

---

## 7. v0.5 文档规划（本文为总纲，其余待落）

```text
1. PREFERENCE_KNOWLEDGE_MEMORY_ARCHITECTURE.md（本文）→ 架构是什么
2. MEMORY_CAPSULE_V2_SCHEMA.md                        → 统一数据结构
3. PREFERENCE_KNOWLEDGE_EVOLUTION_POLICY.md           → 偏好/知识如何演化
4. OVERSIGHT_COMMAND_LOOP.md                          → 如何辅助生产监督与指挥
5. PRODUCTION_MEMORY_EVAL.md                          → 如何评测（未实现项标 pending，不伪造）
```

---

## 8. 边界声明（防答辩误解）

```text
v0.5 是 ASI-Oriented，不是 ASI。不声称实现人工超级智能。
v0.5 建在 v0.4 之上，偏好与情感只能影响排序/风格/候选优先级，
不能覆盖安全策略、敏感分级、投毒隔离与人工确认要求。
生产指挥采用风险分级，关键风险只读不执行。
评测中未实现能力一律标 pending，不伪造通过结果。
```

---

## 9. 与其他文档的关系

```text
v0.4 四件套（安全底座）：
  ASI_ORIENTED_MEMORY_ENVIRONMENT.md / MEMORY_GOVERNANCE_POLICY.md
  MEMORY_SECURITY_EVAL.md / ASI_RISK_MAPPING.md

v0.5 总纲（本文）建在其上，权威依据见 V04_V05_AUTHORITATIVE_REFERENCES.md，
先进技术填充见 ADVANCED_MEMORY_TECH.md。
```
