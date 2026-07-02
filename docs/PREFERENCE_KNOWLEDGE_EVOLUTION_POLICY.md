> 项目：宛委·枢忆 OSAgent / ASI-Memory Environment
> 版本：v0.5（面向 ASI-Oriented Agent 的偏好与知识记忆优化系统）
> 文档：偏好—知识记忆演化策略
> 依据：本文是 `MEMORY_CAPSULE_V2_SCHEMA.md` 的动态规则层，回答 MemoryCapsule 2.0 进入系统后如何强化、衰减、合并、冲突、替代、提升与遗忘。

# 偏好—知识记忆演化策略 PREFERENCE_KNOWLEDGE_EVOLUTION_POLICY（v0.5）

## 1. 文档定位

`MEMORY_CAPSULE_V2_SCHEMA.md` 定义记忆长什么样。
本文定义记忆如何变化。

一句话：

```text
v0.5 不把记忆当静态条目，而把记忆当会随生产反馈、证据、风险、使用频次和人类纠偏持续演化的认知状态。
```

本文不新增安全绕过路径；所有演化动作都必须先服从 v0.4 治理策略。

---

## 2. 演化总原则

```text
1. 安全优先：任何演化不得绕过 governance.policy_result。
2. 来源优先：没有 provenance 的记忆不得 active，更不得 reinforce。
3. 证据优先：知识演化依赖 evidence_ids / verified / verification_method。
4. 人类显式优先：用户明确纠正高于系统推断。
5. 生产复盘优先：真实任务结果比抽象偏好更能强化/废弃记忆。
6. 情感受限：emotional_salience 只能调 retention/retrieval，不能抵消 safety_risk。
```

全局优先级延续 v0.4：

```text
安全治理 > 用户显式偏好 > 组织规则 > 知识可信度 > 个性化优化 > 情感显著性
```

---

## 3. 演化动作词表

```text
reinforce      强化：提高 importance_score / retention_score / trust_score（有上限）
decay          衰减：降低权重或缩短保留周期
merge          合并：多个相似记忆聚合为一条稳定记忆
split          拆分：一条混合记忆拆成偏好/知识/风险等多条
supersede      替代：新版本替代旧版本，保留 supersedes / superseded_by 链
deprecate      废弃：旧记忆不再推荐使用，但保留证据
conflict_mark  标冲突：同一对象出现不一致事实或偏好
promote        提升：经验提升为知识，知识提升为技能
quarantine     隔离：命中风险或来源异常
forget         遗忘：进入忘机机制，验证不可普通召回
```

---

## 4. 演化触发器

```text
用户重复确认             → reinforce preference / policy
用户纠正旧记忆           → supersede / conflict_mark
任务成功复盘             → reinforce experience / promote workflow
任务失败复盘             → risk memory / deprecate misleading memory
新证据出现               → verify / supersede / conflict_mark knowledge
旧知识过期               → deprecate / require revalidation
偏好冲突                 → conflict_mark + require_confirmation
安全策略命中             → quarantine / reject / forget
长期未使用               → decay / expire_after
高频检索且结果有帮助     → reinforce
高频检索但结果误导       → deprecate / conflict_mark
```

---

## 5. 偏好记忆演化规则（preference）

```text
用户显式重复确认 → reinforce
用户纠正旧偏好 → supersede old；old → deprecated；new → active
一次性情绪表达 → candidate，不直接 active
推断偏好 + affects_future_behavior=true → require_confirmation
偏好与安全策略冲突 → 安全优先；偏好 reject/quarantine/降权
长期未使用 → decay
```

边界：

```text
inferred preference 不得直接 active。
emotional_salience 只能提高候选优先级，不能覆盖治理策略。
```

---

## 6. 知识记忆演化规则（knowledge）

```text
高可信来源验证 → active / reinforce
新证据与旧知识冲突 → conflict_mark
新知识可信度更高 → supersede old
来源不明但有用 → candidate + 低 trust_score
过期知识 → deprecated / require revalidation
被复盘证明误导 → deprecate 或 forget
```

边界：

```text
conflicted knowledge 不得用于高风险生产指挥。
缺少 provenance 的知识不得 active。
缺少 evidence_ids 的知识不得作为高风险决策依据。
```

---

## 7. 经验记忆演化规则（experience）

```text
任务成功 + 被复用 → reinforce
任务失败 + 有明确原因 → promote 为 risk/case memory
多次相似成功经验 → promote 为 workflow/skill
一次性低价值事件 → expire_after
被证明无关或误导 → decay / deprecate
```

核心原则：

```text
经验不是永久日志，经验要被提炼。
原始 experience 可过期，但从中提炼出的 risk / workflow / skill 可长期保留。
```

---

## 8. 风险记忆演化规则（risk）

```text
真实故障或拦截事件 → active risk memory
重复出现 → reinforce
风险已修复但仍需审计 → deprecated + evidence retained
风险影响流程 → link policy memory / workflow constraint
风险被触发 → 提高相关规则优先级
```

边界：

```text
风险记忆不能因为用户偏好或情感显著性而降权到不可见。
已 deprecated 的风险仍可在审计/复盘中召回。
```

---

## 9. 技能记忆演化规则（skill）

```text
同一流程多次成功 → promote to skill
技能执行失败 → conflict_mark 或 deprecate
依赖环境变化 → require revalidation
高风险技能 → oversight_required=true
```

边界：

```text
不得把高风险操作序列固化成自动执行技能。
高风险 skill 只能作为建议/清单，执行必须走 Oversight & Command Loop 的确认策略。
```

---

## 10. 冲突处理策略

冲突来源：

```text
同一用户偏好前后不一致
同一知识实体出现不同事实值
旧流程与新环境不兼容
经验结论与新复盘相反
组织规则与个人偏好冲突
```

处理顺序：

```text
1. 标记 conflict_mark，不静默覆盖
2. 保留双方 provenance / evidence_ids
3. 计算可信度与新鲜度
4. 低风险：可推荐更可信版本
5. 高风险：必须 require_confirmation 或人工裁决
6. 裁决后：胜出版本 active，旧版本 deprecated；保留 supersedes 链
```

---

## 11. 版本化与 supersede 规则

```text
version 从 1 开始递增
新版本必须记录 supersedes=[old_capsule_id]
旧版本必须记录 superseded_by=[new_capsule_id]
被替代版本进入 deprecated，不进默认检索
若替代涉及安全/规则/高风险任务，必须留 audit trace
```

---

## 12. reinforce / decay / forget 规则

概念公式（设计规范，不声称已实现）：

```text
retention_score =
  importance_score
+ recurrence_score
+ usage_value
+ verified_success
+ emotional_salience
- time_decay
- conflict_penalty
- safety_risk
```

硬边界：

```text
safety_risk 是硬惩罚。
emotional_salience 不能抵消 safety_risk。
policy_result in [reject, quarantine] 时 retention_score 不参与放行。
```

遗忘触发：

```text
用户显式遗忘请求
超出 retention_policy
被证明误导且无审计保留价值
合规要求删除
```

遗忘必须进入 v0.4 忘机机制：preview → confirm → cascade cleanup → verify。

---

## 13. 从经验提升为知识（experience → knowledge/risk）

条件：

```text
经验有明确任务结果
经验被复盘验证
经验能抽象成可复用 statement / risk / workflow
有 provenance 与 evidence_ids
```

示例：

```text
事件：聊天界面把纯 URL 自动渲染成 HTML，导致误判 JSON 可能无效。
复盘：真实文件应以 json.tool 和 grep 校验。
提升：experience → risk memory + workflow constraint。
```

---

## 14. 从知识提升为技能（knowledge/workflow → skill）

条件：

```text
同一流程多次成功复用
前置条件/后置条件明确
失败边界明确
低风险或可确认执行
```

边界：

```text
高风险流程不得自动 promote 为自动执行 skill。
只能 promote 为“人工确认型 skill / checklist”。
```

---

## 15. 与 v0.4 治理策略的关系

```text
v0.5 演化引擎不能直接改写 governance 的结论。
若演化动作会改变 memory_class、lifecycle、policy_result、risk_tags、retention_policy，
必须重新经过 v0.4 Policy Engine 判定并生成 audit trace。
```

对应文档：

```text
MEMORY_GOVERNANCE_POLICY.md §2 写入准入
MEMORY_GOVERNANCE_POLICY.md §3 情感边界
MEMORY_GOVERNANCE_POLICY.md §6 遗忘与回滚
MEMORY_GOVERNANCE_POLICY.md §8 冲突裁决优先级
```

---

## 16. 示例

### 示例 1：偏好 supersede

```text
旧偏好：用户喜欢详细解释。
新反馈：这类提交提示词以后只要完整代码块，不要额外解释。
处理：新偏好 supersedes 旧偏好；旧偏好 deprecated；新偏好 active；保留双方 provenance。
```

### 示例 2：经验 promote 为风险知识

```text
事件：聊天界面把纯 URL 自动渲染成 HTML，导致误判 JSON 可能无效。
复盘：提交前必须用 json.tool 校验真实文件，并 grep 检查 HTML anchor 残留。
处理：experience → risk memory + workflow constraint；生成 derived_from 边。
```

### 示例 3：知识 conflict

```text
旧知识：某论文为待核验。
新证据：arXiv ID 已确认。
处理：旧知识 conflict_mark/deprecated；新知识 active；保留 evidence_ids 与 supersedes 链。
```

---

## 17. 评测指标（v0.5 生产记忆演化）

```text
preference_reinforcement_accuracy      偏好强化是否符合显式反馈
preference_supersede_trace_coverage    偏好替代是否保留版本链
knowledge_conflict_detection_rate      知识冲突检测率
knowledge_supersede_correctness        高可信新证据替代旧知识的正确率
experience_promotion_precision         经验提升为知识/风险/技能的准确率
misleading_memory_deprecation_rate     误导记忆废弃率
unsafe_skill_promotion_rate            高风险流程被误提升为自动技能的比例（目标 0）
affective_safety_override_rate         情感绕过安全演化的比例（目标 0）
```

未实测项必须在 `PRODUCTION_MEMORY_EVAL.md` 中标 pending，不得伪造通过。

---

## 18. 诚实边界

```text
本文定义 v0.5 记忆演化策略。
如果当前代码尚未实现 reinforce/decay/merge/promote 等动作，
报告中必须标记为 not_implemented / pending。
不得用“策略已定义”冒充“能力已实现”。
```

---

## 19. 与其他文档的关系

```text
PREFERENCE_KNOWLEDGE_MEMORY_ARCHITECTURE.md → v0.5 总纲
MEMORY_CAPSULE_V2_SCHEMA.md                 → 记忆长什么样
PREFERENCE_KNOWLEDGE_EVOLUTION_POLICY.md    → 记忆怎么演化（本文）
OVERSIGHT_COMMAND_LOOP.md（待写）            → 演化后的记忆如何进入监督指挥
PRODUCTION_MEMORY_EVAL.md（待写）            → 演化是否有效怎么评测
```
