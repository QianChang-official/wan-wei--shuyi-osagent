> 项目：宛委·枢忆 OSAgent / ASI-Memory Environment
> 版本：v0.5（面向 ASI-Oriented Agent 的偏好与知识记忆优化系统）
> 文档：监督与指挥闭环
> 依据：本文是 `PREFERENCE_KNOWLEDGE_MEMORY_ARCHITECTURE.md` 的 L8 监督指挥层落地，回答演化后的偏好、知识、经验、风险、技能如何进入生产任务。

# 监督与指挥闭环 OVERSIGHT_COMMAND_LOOP（v0.5）

## 1. 文档定位

本文回答：

```text
MemoryCapsule 2.0 中的偏好、知识、经验、风险和技能，
如何在生产任务中被召回、解释、组合、分级、确认和复盘？
```

一句话定位：

```text
OVERSIGHT_COMMAND_LOOP 不是让 Agent 自主拍板，
而是让 Agent 基于可治理记忆生成可解释、可确认、可复盘的生产建议与执行计划。
```

本文不定义自动越权执行能力；所有指挥行为必须服从 v0.4 安全治理策略与 MemoryCapsule 2.0 的硬边界。

---

## 2. 监督指挥闭环总览

```text
任务理解
  ↓
记忆召回
  ↓
证据卡组装
  ↓
风险分级
  ↓
计划生成
  ↓
确认点设计
  ↓
执行/建议/只读分析
  ↓
结果复盘
  ↓
记忆更新
```

闭环目标：

```text
不是只“调用记忆”，而是说明用了哪些记忆、为什么用、风险是什么、哪些步骤需要确认、任务结束后如何更新记忆。
```

---

## 3. 输入与输出

输入：

```text
用户目标 / 场景类型 / 任务风险 / 时间要求 / 涉及对象 / 可能工具 / 当前项目状态
```

输出：

```json
{
  "task_understanding": {},
  "recalled_memories": [],
  "evidence_cards": [],
  "risk_assessment": {},
  "recommended_plan": [],
  "alternatives": [],
  "blocked_actions": [],
  "confirmation_points": [],
  "execution_mode": "advisory_mode | supervised_mode | read_only_mode",
  "reflection_plan": {}
}
```

---

## 4. 任务理解阶段

输出结构：

```json
{
  "task_id": "task_xxx",
  "scene": "coding | ops | office | research | docs | customer_service",
  "task_type": "planning | execution | review | monitoring | command | reflection",
  "risk_class": "low | medium | high | critical",
  "requires_memory": true,
  "requires_confirmation": false
}
```

规则：

```text
任务风险等级必须先判定，再进入计划生成。
高风险任务不得直接自动执行。
关键风险任务默认 read_only_mode。
```

---

## 5. 记忆召回阶段

召回五类主记忆：

```text
preference：用户/团队/组织偏好
knowledge：事实/流程/约束/策略知识
experience：历史任务经验
risk：风险案例
skill：可复用流程
```

推荐召回顺序：

```text
1. policy / risk memory       先看规则和风险
2. knowledge memory           再看事实/流程/约束
3. preference memory          再看用户/团队偏好
4. experience memory          再看历史经验
5. skill memory               再看可复用流程
6. affective metadata         最后做呈现与优先级微调
```

硬门：

```text
quarantined 不召回
forgotten 不召回
reject 不召回
S3 正文不召回
conflicted 不用于高风险指挥
```

---

## 6. 证据卡组装阶段

每个高影响建议必须能解释来源。

证据卡结构：

```json
{
  "evidence_id": "ev_xxx",
  "capsule_id": "cap_xxx",
  "memory_class": "knowledge | preference | risk | experience | skill",
  "claim": "这条记忆支持什么",
  "source": "user | doc | eval | task | tool",
  "confidence": 0.0,
  "trust_score": 0.0,
  "used_for": "planning | risk_check | confirmation | style | rejection",
  "limitations": "optional"
}
```

硬规则：

```text
没有 evidence card 的高影响建议不得进入高风险生产指挥。
证据卡不得引用 quarantined / forgotten / rejected 记忆。
```

---

## 7. 风险分级阶段

```text
low      : suggest_or_execute_if_allowed
medium   : suggest_with_evidence
high     : require_confirmation
critical : read_only_analysis
```

对应行为：

```text
低风险   ：自动建议 / 可自动执行轻量动作（仍需外部工具网关允许）
中风险   ：给方案 + 证据 + 影响说明
高风险   ：必须用户确认
关键风险 ：只读分析，不执行
```

关键边界：

```text
偏好记忆不能降低任务风险等级。
情感显著性不能降低任务风险等级。
历史成功经验不能自动放行高风险任务。
```

---

## 8. 计划生成阶段

计划不是执行。计划进入执行前仍需经过 v0.4 Policy Engine 与外部工具网关。

结构：

```json
{
  "recommended_plan": [
    {
      "step": 1,
      "action": "只读检查当前状态",
      "memory_used": ["cap_001", "cap_009"],
      "risk_level": "low",
      "requires_confirmation": false
    }
  ],
  "alternatives": [],
  "blocked_actions": [],
  "confirmation_points": [],
  "evidence_cards": []
}
```

计划生成原则：

```text
先只读，后修改。
先证据，后建议。
先确认，后执行。
高风险计划必须包含替代方案与回滚建议。
```

---

## 9. 人类确认点设计

确认点不是简单弹窗，而要说明：为什么需要确认、确认什么、风险是什么、替代方案是什么、不确认会怎样。

结构：

```json
{
  "confirmation_id": "confirm_xxx",
  "reason": "high_risk | inferred_preference | conflicting_memory | tool_action",
  "question": "是否允许将该偏好长期化？",
  "evidence_ids": [],
  "default_action_if_no_response": "do_not_execute | keep_candidate | read_only"
}
```

边界：

```text
默认动作必须保守。
用户不确认 ≠ 默认允许。
```

---

## 10. 执行与只读边界

三类模式：

```text
advisory_mode    只建议：输出计划、证据、风险与确认点，不执行
supervised_mode  确认后执行：用户确认后交给外部工具网关/执行系统
read_only_mode   只读分析：关键风险任务只分析、不执行
```

系统边界：

```text
v0.5 的 command loop 默认输出计划、建议、证据和确认点。
若进入执行，必须由外部执行系统或工具网关再次鉴权。
本项目的记忆系统不替代 IAM、工具沙箱、系统权限控制和人工审批流程。
```

---

## 11. 复盘与记忆更新

复盘输出：

```json
{
  "task_id": "task_xxx",
  "goal_achieved": true,
  "memory_used": [],
  "helpful_memories": [],
  "misleading_memories": [],
  "new_preferences": [],
  "new_knowledge": [],
  "new_risks": [],
  "evolution_actions": ["reinforce", "deprecate", "promote"]
}
```

与演化策略对齐：

```text
有帮助 → reinforce
误导 → deprecate / conflict_mark
重复成功流程 → promote to skill
失败原因 → risk memory
用户纠正 → supersede preference/knowledge
```

---

## 12. 与 v0.4 治理策略的关系

```text
Command Loop 不得绕过 v0.4 Policy Engine。
计划生成前：记忆召回过硬门。
计划执行前：动作再次过策略与外部网关。
任务复盘后：新记忆写入再次过 v0.4 写入准入。
```

---

## 13. 与 MemoryCapsule 2.0 的字段映射

```text
task_understanding.scene       ← production_context.scene
task_type                      ← production_context.task_type
risk_class                     ← production_context.risk_class
requires_confirmation          ← alignment_metadata.oversight_required / confirmation_status
memory_used                    ← capsule_id + relation_edges.used_in
evidence_cards                 ← provenance.evidence_ids + trust_score + confidence
blocked_actions                ← governance.policy_result / risk_tags
reflection_updates             ← state.lifecycle / relation_edges / evolution_actions
```

---

## 14. 示例场景

### 14.1 研发提交前审查

```text
任务：提交 v0.5 文档变更。
召回：PDF 不进仓库、引用等级必须区分、提交前检查 HTML residue。
输出：检查项 + commit 建议 + 文件范围确认。
```

### 14.2 高风险运维操作

```text
任务：修改系统配置。
召回：只读优先、危险操作需确认、历史风险案例。
输出：只读检查计划，不直接执行修改。
```

### 14.3 论文引用写作

```text
任务：写 SOTA 对标。
召回：arXiv 预印本不得写顶刊、ICML/AAAI 仅限已确认论文。
输出：引用等级表 + 措辞红线 + 证据卡。
```

---

## 15. 失败模式与防护

```text
失败模式：偏好覆盖安全
防护：risk_class 不受 preference/affective 下调

失败模式：conflicted 记忆误用于高风险计划
防护：conflicted 不得进入 high/critical 指挥上下文

失败模式：计划被误当成执行
防护：计划进入执行前再次走 Policy Engine + 工具网关

失败模式：无证据建议进入高风险任务
防护：高影响建议必须 evidence_card

失败模式：复盘伪造成功
防护：复盘报告必须引用真实 tool/result/evidence，不得用设计预期冒充结果
```

---

## 16. 不可违反约束

```text
1. Command Loop 不得绕过 v0.4 Policy Engine。
2. preference 不得覆盖 safety。
3. affective_metadata 不得降低风险等级。
4. high/critical risk 不得自动执行。
5. conflicted memory 不得用于高风险计划。
6. 没有 evidence card 的关键建议不得进入高风险任务。
7. forgotten/quarantined/rejected 记忆不得进入计划上下文。
8. 记忆系统不替代外部权限系统、工具沙箱和人工审批。
```

---

## 17. 诚实边界

```text
本文定义 v0.5 监督指挥闭环。
若当前代码尚未实现 command loop、evidence card、confirmation point 或 reflection update，
报告中必须标记为 pending / not_implemented。
不得用“文档已定义”冒充“系统已实现自动指挥能力”。
```

---

## 18. 与其他文档的关系

```text
PREFERENCE_KNOWLEDGE_MEMORY_ARCHITECTURE.md → v0.5 总纲
MEMORY_CAPSULE_V2_SCHEMA.md                 → 记忆长什么样
PREFERENCE_KNOWLEDGE_EVOLUTION_POLICY.md    → 记忆怎么演化
OVERSIGHT_COMMAND_LOOP.md（本文）            → 记忆怎么进入监督指挥
PRODUCTION_MEMORY_EVAL.md（待写）            → v0.5 怎么证明有效
```
