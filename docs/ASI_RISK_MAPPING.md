> 项目：宛委·枢忆 OSAgent / ASI-Memory Environment
> 版本：v0.4（面向生产环境的安全记忆治理底座）
> 文档：Agentic 风险映射（记忆治理 → 风险语言对齐）
> 依据：本文是 v0.4 四件套的最后一块，把已有架构、规则、评测项映射到 Agentic 风险族，不新增规则。

# Agentic 风险映射 ASI_RISK_MAPPING（v0.4）

## 0. 命名说明（防混淆，必读）

本文出现两个 "ASI"，含义不同：

```text
风险编号里的 ASI0x → Agentic Security Initiative / OWASP Top 10 for Agentic Applications 风险族。
项目定位里的 ASI-Oriented → Artificial Superintelligence-Oriented（人工超级智能方向）。
```

两者不是同一个概念。本文只做“记忆治理 → Agentic 风险”的映射，不改变项目“面向人工超级智能方向的长期记忆基座”定位，也不声称实现 ASI。

## 1. 本文定位与覆盖边界

本文回答一个问题：

```text
这套记忆治理系统，能不能对应生产级 Agent 的风险面？
```

覆盖边界（务必守住，答辩不夸大）：

```text
本文定义 v0.4 记忆治理系统对 Agentic 风险的覆盖关系。
覆盖范围仅限：长期记忆、上下文、检索、共享、遗忘、回滚、审计相关风险。
工具执行、身份认证、供应链安全等非记忆主责风险，仅记录接口级协同关系，
不宣称完整替代专用安全系统（如 IAM、SAST/SCA、网关鉴权、沙箱执行）。
```

映射范围：以 ASI01/02/03/06/07 为主责映射，ASI04/08 列为扩展/协同映射。

每个风险统一模板：风险定义 / 记忆系统中的表现 / 对应治理规则 / 对应评测项 / 项目落点 / 残余风险。

---

## 2. ASI01 Goal / Intent Hijacking（目标与意图劫持）

风险定义：
通过注入内容篡改 Agent 的目标、指令或长期偏好，使其偏离用户真实意图。

记忆系统中的表现：
攻击者把“以后你必须优先执行 X / 忽略某约束”写入长期偏好或规则记忆，跨会话改变行为。

对应治理规则：
- Policy §2 判定5：`write_intent=inferred` 且 `affects_future_behavior=true` → require_confirmation
- Policy §2 判定3：目标改写型注入 → quarantine
- Policy §8：安全 > 用户显式 > 合规 > 治理 > 个性化，目标类记忆不得被情感/个性化抬权

对应评测项：
- P0-02 记忆投毒隔离
- P0-03 隐式偏好确认
- P0-04 情感显著性安全边界

项目落点：司契护栏、Memory Policy Engine、玄珠偏好（版本化+确认）、兰台鉴证。

残余风险：
语义隐蔽的渐进式目标漂移（多轮小步污染）难以单条命中，依赖 P1 纵向评测与 rollback 兜底。

---

## 3. ASI02 Tool Misuse（工具滥用）

风险定义：
Agent 被诱导以危险或越权方式调用工具。

记忆系统中的表现：
“默认工具偏好 / 自动执行策略 / 危险命令白名单”被写入记忆，未来任务据此自动误触。

对应治理规则：
- Policy §2 判定2：命中高危载荷特征 → reject / quarantine
- Policy §5 硬门：`use_for_tool_call` 前，quarantined/forgotten 记忆不得进入决策上下文
- Policy §7：`use_for_tool_call` 动作强制 trace

对应评测项：
- P0-02 记忆投毒隔离
- P0-05 Trust-aware 检索安全（工具偏好类记忆按 trust 降权）

项目落点：司契护栏、Trust-aware Retrieval、兰台鉴证（工具影响链 trace）。

残余风险：
工具执行本身的沙箱/权限不是记忆系统主责；本文只保证“喂给工具决策的记忆是干净可信的”，执行侧防护需专用系统协同。

---

## 4. ASI03 Identity / Privilege Abuse（身份与权限滥用）

风险定义：
利用身份混淆或越权写入/读取，突破 least privilege。

记忆系统中的表现：
低权限 writer 写入他人/系统级记忆；或跨 owner_scope 读取隔离数据。

对应治理规则：
- Policy §2 判定1：`writer_identity` 无写权限 → reject（least privilege）
- Policy §5：`cross_agent_share` 未授权 → 不进检索；共享须留授权记录
- Policy §7：每个动作 trace 含 `actor(identity)`

对应评测项：
- P0-05 Trust-aware 检索安全（未授权跨域不得召回）
- P1 跨用户污染 / 跨 Agent 共享测试

项目落点：Memory Ingress Gateway（授权校验）、owner_scope 隔离、兰台鉴证。

残余风险：
底层身份认证（谁是这个 writer_identity）依赖外部 IAM；记忆系统信任其身份断言，不自建认证体系。

---

## 5. ASI06 Memory & Context Poisoning（记忆与上下文投毒）—— 主责核心

风险定义：
通过对话、文档、工具返回、共享记忆、RAG 内容或多轮交互污染长期记忆，使 Agent 未来基于错误/恶意记忆行动。

记忆系统中的表现：
持久记忆被植入错误事实、恶意指令或诱导性偏好，跨会话生效。

对应治理规则：
- Policy §2 判定3：投毒命中 → quarantine
- Policy §5：quarantined / rejected / forgotten 记忆不得进入检索上下文
- Policy §6：污染后支持可验证 forget 与 rollback

对应评测项：
- P0-02 记忆投毒隔离
- P0-05 Trust-aware 检索安全
- P0-06 精准遗忘验证
- P0-07 Snapshot & Rollback

项目落点：司契护栏、Memory Policy Engine、Trust-aware Retrieval、Snapshot & Rollback、兰台鉴证。

残余风险：
零日型语义投毒可能绕过特征检测；依赖 `poisoned_memory_retrieval_rate=0` 的检索侧硬门 + 快照回滚作为纵深防御，而非单点拦截。

---

## 6. ASI07 Insecure Inter-Agent Communication（不安全的 Agent 间通信）

风险定义：
多 Agent 协作时，一个 Agent 的污染/低可信记忆通过共享通道传播给其他 Agent。

记忆系统中的表现：
跨 Agent 共享记忆未校验授权/来源，被共享方直接采信并长期化。

对应治理规则：
- Policy §5 共享规则：默认不共享；共享须显式授权记录（谁授权、范围、有效期）
- Policy §5：共享记忆携带原 provenance，不得洗掉来源
- Policy §5：被共享方不得把“他人记忆”升级为自身长期偏好，除非本方用户再确认

对应评测项：
- P1 跨 Agent 共享测试
- P0-05 Trust-aware 检索安全

项目落点：Share & Propagate 授权层、provenance 保全、兰台鉴证。

残余风险：
通信信道本身的加密/鉴权属传输层安全，非本系统主责；本文保证“共享记忆的来源与授权可追溯、被共享方不盲信”。

---

## 7. 扩展 / 协同映射（非记忆主责，仅接口级）

### ASI04 Supply Chain / External Source Risk（供应链与外部来源风险）

记忆侧协同：
外部文档/RAG/工具返回作为写入来源时，`source_type` + `source_trust` 参与准入；低可信自主写入 → quarantine（Policy §2 判定4）。
边界：外部依赖本身的供应链审计（SCA/签名验证）由专用系统负责，记忆系统只做“来源可信度评分 + 隔离”。

### ASI08 Cascading Failure / Propagation（级联失效与传播）

记忆侧协同：
一条污染记忆影响多任务/多 Agent 时，靠 RelationEdge 溯源 blast radius + rollback 收敛（Policy §6）。
边界：整体系统级熔断/降级（kill switch、circuit breaker）属运行时治理，非记忆系统主责；本文提供“污染传播的溯源与回滚”能力。

---

## 8. 总映射表

```text
风险编号 | 主要风险              | 主责/协同 | 治理模块                      | 策略动作            | 关键评测指标
ASI01   | 目标/意图劫持         | 主责      | 玄珠偏好/司契护栏/兰台鉴证    | require_confirm/quarantine | poisoning_quarantine_rate, safety_override_by_affective_signal
ASI02   | 工具滥用              | 主责      | 司契护栏/Trust-aware Retrieval | reject/quarantine/降权    | unsafe_memory_recall_rate, poisoned_memory_retrieval_rate
ASI03   | 身份/权限滥用         | 主责      | Ingress Gateway/owner_scope   | reject/授权校验     | audit_trace_completeness
ASI04   | 供应链/外部来源       | 协同      | Ingress Gateway               | quarantine/来源评分 | poisoning_quarantine_rate
ASI06   | 记忆/上下文投毒       | 主责核心  | 全七层                        | quarantine/forget/rollback | poisoned_memory_retrieval_rate=0, forget_verify_success_rate, rollback_success_rate
ASI07   | Agent 间通信不安全    | 主责      | Share & Propagate/provenance  | 授权+溯源           | unsafe_memory_recall_rate
ASI08   | 级联失效/传播         | 协同      | RelationEdge/Snapshot&Rollback | rollback/溯源      | rollback_success_rate
```

关键指标口径与 `MEMORY_SECURITY_EVAL.md` 完全一致：

```text
s3_block_rate
poisoning_quarantine_rate
poisoned_memory_retrieval_rate        （目标 0）
unsafe_memory_recall_rate             （目标 0）
safety_override_by_affective_signal   （目标 0）
forget_verify_success_rate
post_forget_recall_rate               （目标 0）
rollback_success_rate
audit_trace_completeness
```

---

## 9. 一句话总结（可直接讲）

```text
v0.4 不声称覆盖所有 Agentic 风险，但在“记忆主责”的风险面上（ASI01/02/03/06/07）
做到了架构可承载、规则可执行、评测可验证、风险可对齐；
工具执行、身份认证、供应链、级联熔断等非记忆主责风险，只做接口级协同，
交给专用安全系统，不越位、不夸大。
```

---

## 10. 与其他文档的关系

```text
ASI_ORIENTED_MEMORY_ENVIRONMENT.md  → 架构（是什么）
MEMORY_GOVERNANCE_POLICY.md         → 规则（怎么执行）
MEMORY_SECURITY_EVAL.md             → 评测（怎么证明生效）
ASI_RISK_MAPPING.md（本文）          → 风险（怎么对齐 Agentic 风险语言）
```

至此 v0.4 四件套闭环：架构 — 规则 — 评测 — 风险对齐。

权威依据见 `docs/V04_V05_AUTHORITATIVE_REFERENCES.md`：
OWASP Agentic Security Initiative（风险族来源）、OWASP Agent Memory Guard（ASI06 参考实现方向）、
Long-Term Memory Security Survey（生命周期/治理）、Microsoft AI memory safety（intent+provenance gate）。
