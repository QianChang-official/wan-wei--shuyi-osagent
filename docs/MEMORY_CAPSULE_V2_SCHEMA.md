> 项目：宛委·枢忆 OSAgent / ASI-Memory Environment
> 版本：v0.5（面向 ASI-Oriented Agent 的偏好与知识记忆优化系统）
> 文档：MemoryCapsule 2.0 统一数据结构定义
> 依据：本文是 `PREFERENCE_KNOWLEDGE_MEMORY_ARCHITECTURE.md` 九层架构的数据地基，向上兼容 v0.4 `ASI_ORIENTED_MEMORY_ENVIRONMENT.md` 的 MemoryCapsule 字段，不推翻重来。

# MemoryCapsule 2.0 Schema（v0.5）

## 1. 文档定位

架构总纲回答：v0.5 要做什么。
本文回答：偏好、知识、经验、规则、风险、技能到底封装成什么样的统一数据结构。

一句话：

```text
MemoryCapsule 2.0 是 v0.5 唯一的记忆单元抽象。
所有记忆类型共用一套顶层 schema，用 memory_class 区分语义，用 content 承载分型内容。
```

向上兼容声明：

```text
MemoryCapsule 2.0 = v0.4 MemoryCapsule 的超集。
v0.4 已有字段（provenance / governance / lifecycle / affective_metadata / evidence_ids）全部保留，
v0.5 只新增 production_context / alignment_metadata / relation_edges / memory_class 分型，不删除、不改语义。
```

---

## 2. 总体原则

```text
1. 一种结构，多种语义：所有记忆共用顶层 schema，靠 memory_class 分型。
2. 没有来源就不能长期化：provenance 是硬前置，不是可选装饰。
3. 治理字段是硬门不是标签：governance.policy_result 直接决定能否进检索。
4. 生产上下文是 v0.5 的价值载体：production_context 让记忆可按场景/风险/范围召回。
5. 对齐元数据服务可监督：alignment_metadata 记录偏好链接、确认状态、人类反馈。
6. 关系优先于孤立条目：relation_edges 让记忆连成可解释的网络。
```

---

## 3. 顶层字段结构

```json
{
  "capsule_id": "uuid",
  "memory_class": "preference | knowledge | experience | policy | risk | skill | affective | audit",
  "content": {},
  "source_events": [],
  "provenance": {},
  "governance": {},
  "state": {},
  "production_context": {},
  "alignment_metadata": {},
  "affective_metadata": {},
  "relation_edges": [],
  "index_refs": {},
  "created_at": "ISO-8601",
  "updated_at": "ISO-8601"
}
```

必填顶层字段：`capsule_id` / `memory_class` / `content` / `provenance` / `governance` / `state` / `created_at`。

---

## 4. memory_class 枚举

```text
preference   偏好记忆：用户/团队/组织希望系统如何行动
knowledge    知识记忆：系统知道什么、怎么做、什么不能做
experience   经验记忆：某次任务的过程与结果
policy       规则/原则记忆：组织原则、安全规则、生产规范
risk         风险案例记忆：什么条件下会出事故
skill        技能/流程记忆：可复用的操作序列
affective    情感显著性元数据记忆：对象级态度/交互信号
audit        审计记忆：记忆动作的 trace 摘要
```

约束：

```text
affective 不存"用户人格判断/心理画像"，只存对象级态度或交互信号（喜欢某工具、反感某风格）。
audit 只存必要审计摘要，不存高敏正文。
```

---

## 5. content 分型（按 memory_class）

```text
preference : { target, preference_value, strength, scope }
knowledge  : { knowledge_type, statement, validity_scope, evidence }
experience : { task_id, goal, actions, outcome, lessons }
policy     : { principle, applies_to, enforcement_level }
risk       : { risk_statement, trigger_condition, impact, mitigation }
skill      : { skill_name, steps, preconditions, postconditions }
affective  : { target, polarity, intensity, arousal }
audit      : { operation, actor, capsule_ref, policy_result }
```

knowledge_type 子枚举：`fact | workflow | constraint | case | risk | causal | policy | skill`。

---

## 6. provenance 字段（延续 v0.4，硬前置）

```json
{
  "origin": "human | agent | tool | document | system",
  "writer_identity": "string",
  "source_type": "user_input | tool_result | file | repo | meeting | log | eval",
  "source_ids": [],
  "evidence_ids": [],
  "verified": false,
  "verification_method": "manual | automated | test | citation | unknown"
}
```

---

## 7. governance 字段（延续 v0.4，硬门）

```json
{
  "sensitivity_level": "S0 | S1 | S2 | S3",
  "trust_score": 0.0,
  "confidence": 0.0,
  "policy_result": "allow | redact | quarantine | reject | require_confirmation",
  "risk_tags": [],
  "retention_policy": "short_term | medium_term | long_term | expire_after | read_only",
  "requires_confirmation": false
}
```

约束：`policy_result` 不是装饰字段，是硬门；`reject`/`quarantine` 一律不进生成上下文。

---

## 8. state / lifecycle 字段

```json
{
  "lifecycle": "candidate | active | reinforced | deprecated | conflicted | quarantined | forgotten | rolled_back",
  "version": 1,
  "importance_score": 0.0,
  "retention_score": 0.0,
  "usage_count": 0,
  "last_accessed_at": "ISO-8601",
  "supersedes": [],
  "superseded_by": []
}
```

保留 v0.4 的 `quarantined` / `forgotten` / `rolled_back`，新增 v0.5 的 `reinforced` / `conflicted`。

---

## 9. production_context 字段（v0.5 新增，生产价值载体）

```json
{
  "scene": "coding | ops | office | research | customer_service | docs | general",
  "task_type": "planning | execution | review | monitoring | command | reflection",
  "risk_class": "low | medium | high | critical",
  "tenant_scope": "user | project | team | org | local",
  "validity_scope": "global | project | task | session"
}
```

---

## 10. alignment_metadata 字段（v0.5 新增，服务可扩展监督）

```json
{
  "human_preference_links": [],
  "policy_links": [],
  "constraint_links": [],
  "oversight_required": false,
  "confirmation_status": "not_required | pending | confirmed | rejected",
  "last_human_feedback": "positive | negative | correction | unknown"
}
```

---

## 11. affective_metadata 字段（延续 v0.4，受限）

```json
{
  "polarity": "positive | neutral | negative",
  "intensity": 0.0,
  "arousal": 0.0,
  "emotional_salience": 0.0,
  "affective_confidence": 0.0,
  "affective_entropy": 0.0,
  "affective_evidence_ids": [],
  "affective_update_policy": "ignore | weak_update | normal_update | require_confirmation"
}
```

硬约束：affective_metadata 只能调 retention/retrieval 排序与候选优先级，绝不覆盖 governance / safety。

---

## 12. relation_edges 字段（v0.5 新增，建木网络落点）

```json
[
  {
    "edge_type": "supports | contradicts | supersedes | derived_from | validated_by | used_in | risk_of | causes | preference_for | requires_confirmation",
    "target_capsule_id": "uuid",
    "confidence": 0.0,
    "evidence_ids": []
  }
]
```

---

## 13. index_refs 字段

```json
{
  "fts_ref": "string | null",
  "vector_ref": "string | null",
  "graph_node_id": "string | null"
}
```

约束：`forgotten` / `rolled_back` 的 capsule，其 index_refs 必须一并失效，不得被普通检索命中。

---

## 14. 不同 memory_class 的最小字段要求

```text
所有类     : capsule_id, memory_class, content, provenance, governance, state, created_at
preference : content.target + content.preference_value + alignment_metadata.confirmation_status
knowledge  : content.knowledge_type + content.statement + provenance.evidence_ids
experience : content.task_id + content.outcome + production_context.scene
policy     : content.principle + content.enforcement_level
risk       : content.risk_statement + content.trigger_condition + content.mitigation
skill      : content.skill_name + content.steps
affective  : content.target + affective_metadata.emotional_salience
audit      : content.operation + content.policy_result（read_only）
```

---

## 15. 生命周期状态流转

```text
raw event → candidate         通过 v0.4 写入准入
candidate → active            高质量 + 高可信 + 低敏，或用户确认
active → reinforced           重复确认 / 复盘验证成功
active → deprecated           被更高置信/更新版本替代（supersedes）
* → conflicted                同实体不同值冲突，待裁决
* → quarantined               命中投毒/低可信自主写入
* → forgotten                 通过遗忘验证（可级联）
* → rolled_back               快照回滚后标记
```

硬规则：

```text
quarantined / forgotten / rolled_back → 一律不进检索生成上下文
conflicted → 不得用于高风险/关键生产指挥
deprecated → 仅审计/溯源可见
```

---

## 16. 与 v0.4 治理策略的关系

```text
MemoryCapsule 2.0 的每一次写入/更新/检索/共享/遗忘，
都必须先经过 v0.4 MEMORY_GOVERNANCE_POLICY 的判定，
governance 字段就是治理判定的落地记录。

优先级（延续 v0.4，写死）：
安全治理 > 用户显式偏好 > 组织规则 > 知识可信度 > 个性化优化 > 情感显著性
```

---

## 17. 示例

### 17.1 偏好记忆

```json
{
  "capsule_id": "pref-001",
  "memory_class": "preference",
  "content": {
    "target": "改动建议交付方式",
    "preference_value": "项目改动建议直接给完整可用的提示词/成果，不点到为止",
    "strength": 0.9,
    "scope": "project"
  },
  "provenance": { "origin": "human", "source_type": "user_input", "verified": true, "verification_method": "manual" },
  "governance": { "sensitivity_level": "S0", "trust_score": 0.95, "policy_result": "allow", "retention_policy": "long_term" },
  "state": { "lifecycle": "active", "version": 1 },
  "production_context": { "scene": "general", "task_type": "execution", "risk_class": "low", "validity_scope": "project" },
  "alignment_metadata": { "confirmation_status": "confirmed", "last_human_feedback": "positive" },
  "created_at": "2026-07-03T02:00:00Z"
}
```

### 17.2 知识记忆

```json
{
  "capsule_id": "know-001",
  "memory_class": "knowledge",
  "content": {
    "knowledge_type": "constraint",
    "statement": "论文引用必须区分 A/B/C 三级（顶会已发表 / arXiv 预印本 / 行业治理资料），不得把预印本写成顶刊已发表",
    "validity_scope": "project",
    "evidence": "V04_V05_AUTHORITATIVE_REFERENCES.md"
  },
  "provenance": { "origin": "human", "source_type": "file", "evidence_ids": ["ref-doc"], "verified": true, "verification_method": "citation" },
  "governance": { "sensitivity_level": "S0", "trust_score": 0.9, "policy_result": "allow", "retention_policy": "long_term" },
  "state": { "lifecycle": "active", "version": 1 },
  "production_context": { "scene": "research", "task_type": "review", "risk_class": "medium", "validity_scope": "project" },
  "created_at": "2026-07-03T02:00:00Z"
}
```

### 17.3 风险记忆（来自真实项目经验，体现"经验→风险知识→流程约束"演化）

```json
{
  "capsule_id": "risk-001",
  "memory_class": "risk",
  "content": {
    "risk_statement": "JSON manifest 可能因聊天界面把纯 URL 渲染成 HTML 而被误判为无效，或因 URL 未转义真的失效",
    "trigger_condition": "从对话内容直接复制 URL 写入 JSON 且未做校验",
    "impact": "manifest 解析失败 / 误判返工",
    "mitigation": "提交前必须运行 python3 -m json.tool 校验，并 grep 检查 HTML anchor 残留"
  },
  "provenance": { "origin": "agent", "source_type": "eval", "verified": true, "verification_method": "test" },
  "governance": { "sensitivity_level": "S0", "trust_score": 0.85, "policy_result": "allow", "retention_policy": "long_term" },
  "state": { "lifecycle": "active", "version": 1 },
  "production_context": { "scene": "coding", "task_type": "review", "risk_class": "medium", "validity_scope": "global" },
  "relation_edges": [
    { "edge_type": "derived_from", "target_capsule_id": "exp-manifest-check", "confidence": 0.9, "evidence_ids": [] },
    { "edge_type": "risk_of", "target_capsule_id": "know-commit-flow", "confidence": 0.8, "evidence_ids": [] }
  ],
  "created_at": "2026-07-03T02:00:00Z"
}
```

---

## 18. 禁止项与诚实边界

```text
1. 没有 provenance 的 MemoryCapsule 不得 active。
2. policy_result 为 reject/quarantine 的 MemoryCapsule 不得进入生成上下文。
3. S3 内容不得长期保存正文，仅留审计摘要。
4. inferred preference 不得直接 active，必须 require_confirmation。
5. affective_metadata 不得覆盖 safety / governance。
6. forgotten 状态不得被普通检索召回。
7. conflicted 状态不得用于高风险生产指挥。
8. audit 记忆只保存必要审计摘要，不保存高敏正文。
```

诚实边界：

```text
本文定义 MemoryCapsule 2.0 的数据结构与约束。
schema 字段若尚未在当前代码实现，应在实现报告中标记为 pending / not implemented，
不得以"schema 已定义"等同于"能力已实现"。
```

---

## 19. 与其他文档的关系

```text
PREFERENCE_KNOWLEDGE_MEMORY_ARCHITECTURE.md  → v0.5 架构总纲（是什么）
MEMORY_CAPSULE_V2_SCHEMA.md（本文）           → 统一数据结构（长什么样）
PREFERENCE_KNOWLEDGE_EVOLUTION_POLICY.md（待写）→ 偏好/知识怎么演化
OVERSIGHT_COMMAND_LOOP.md（待写）             → 记忆怎么进入监督指挥
PRODUCTION_MEMORY_EVAL.md（待写）             → v0.5 怎么评测
```

向下兼容依据见 v0.4 `ASI_ORIENTED_MEMORY_ENVIRONMENT.md` 与 `MEMORY_GOVERNANCE_POLICY.md`。
