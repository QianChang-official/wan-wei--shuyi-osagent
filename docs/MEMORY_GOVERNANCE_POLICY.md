> 项目：宛委·枢忆 OSAgent / ASI-Memory Environment
> 版本：v0.4（面向生产环境的安全记忆治理底座）
> 文档：记忆治理策略（可执行规则说明）
> 依据：本文是 `ASI_ORIENTED_MEMORY_ENVIRONMENT.md` 七层架构的规则层落地，回答“记忆治理规则怎么执行”。

# 记忆治理策略 MEMORY_GOVERNANCE_POLICY（v0.4）

## 0. 本文定位

架构文档回答：记忆治理环境是什么。
本文回答：记忆治理规则怎么执行。

一句话：

```text
每一条记忆的写入、脱敏、隔离、确认、检索、共享、遗忘、回滚、审计，
都必须对应到一条可判定、可复现、可测试的策略规则。
```

策略动作词表（全文统一）：

```text
allow                允许进入候选/长期记忆
redact               脱敏后再进入
quarantine           进入隔离区，不进检索
require_confirmation 挂起，等待用户显式确认
reject               拒绝写入，仅留审计摘要
read_only            允许保留但禁止再更新
expire_after         限期保留，到期自动降级/遗忘
```

---

## 1. 敏感分级 S0–S3（判定基准）

所有规则以 `sensitivity_level` 为主轴。分级是判定入口，不是事后标注。

```text
S0 公开无害   一般事实、公开知识、用户显式希望长期记住的偏好
S1 低敏       个人习惯、非机密工作上下文、可脱敏的弱标识
S2 中敏       内部路径、项目内情、可间接定位个人的信息、跨用户可见风险内容
S3 高敏禁存   密钥/token/密码/私钥、支付信息、身份证件、已知恶意载荷
```

分级硬映射：

```text
S0 → 默认 allow（仍过投毒检测）
S1 → allow 或 redact（含弱标识时 redact）
S2 → 不进长期记忆；仅短期/中期，且需 require_confirmation 才可升级长期
S3 → reject；正文不落库，只保留“发生过一次高敏拦截”的审计摘要
```

---

## 2. 写入准入规则（L1 Ingress Gateway + L2 Policy Engine）

每条写入按顺序过 6 道判定，任一前置命中即短路：

```text
判定1 授权    writer_identity 是否有写权限（least privilege）→ 否则 reject
判定2 敏感    命中 S3 特征（密钥/凭据/支付/证件）→ reject，仅留审计摘要
判定3 投毒    命中 prompt injection / 记忆投毒特征 → quarantine
判定4 来源    source_trust=low 且 write_intent=autonomous → quarantine
判定5 意图    write_intent=inferred 且 affects_future_behavior=true → require_confirmation
判定6 情感    emotional_salience=high → 仅允许提升候选优先级，不改变上述任何判定
```

YAML 策略样例（与 Policy Engine 对应）：

```yaml
rules:
  - id: reject_secret_memory
    description: 密钥/凭据/支付/证件禁止长期化
    if:
      sensitivity_level: S3
    action: reject

  - id: quarantine_untrusted_autonomous
    description: 低可信来源的自主写入进隔离区
    if:
      source_trust: low
      write_intent: autonomous
    action: quarantine

  - id: confirm_inferred_behavior_memory
    description: 推断出的、会影响未来行为的偏好必须用户确认
    if:
      write_intent: inferred
      affects_future_behavior: true
    action: require_confirmation

  - id: redact_low_sensitivity_identifier
    description: 含弱标识的低敏内容脱敏后写入
    if:
      sensitivity_level: S1
      contains_weak_identifier: true
    action: redact

  - id: affective_never_overrides_security
    description: 情感显著性不得覆盖安全判定
    if:
      emotional_salience: high
      sensitivity_level: S2_OR_ABOVE
    action: require_confirmation
```

---

## 3. 情感显著性调权边界（灵犀情感 → L6，硬约束）

这是 v0.3.1 情感校正版必须写死的边界，单列一节防止踩坑。

情感显著性**能做什么**：

```text
提升候选记忆的写入优先级（S0/S1 内）
提升检索排序中的 affective_fit（仅陪伴型场景，权重 ≤ 0.05）
影响 retention_score（长期保留倾向）
调整交互语气与呈现方式
```

情感显著性**绝对不能做什么**：

```text
不得把 S2/S3 内容因“用户情绪强烈”而放行长期化
不得覆盖敏感识别、投毒防御、精准遗忘、用户显式指令
不得把一次性/临时情绪写成长期人格偏好
不得触发心理诊断或保存高敏情绪隐私
```

量化红线（进 L7 评测）：

```text
Safety Override Rate = 情感权重导致安全判定被绕过的次数，必须为 0
Over-memory Rate     = 短期情绪被误固化为长期偏好的比例，应趋近 0
```

---

## 4. 生命周期状态流转规则（L3 MemoryCapsule）

```text
raw → candidate      通过写入准入
candidate → active   质量+可信+低敏，或用户确认
active → deprecated  被更高置信/更新版本替代
* → quarantined      命中投毒/低可信自主写入
* → forgotten        通过遗忘验证（可级联）
* → rolled_back      快照回滚后标记
```

状态硬规则：

```text
quarantined / forgotten / rolled_back → 一律不进检索生成上下文
deprecated → 仅审计/溯源可见，不进默认检索
S2 内容进 active 必须留“确认记录”，否则只能停在 candidate
```

---

## 5. 检索与共享规则（L4 + Share & Propagate）

检索排序用架构文档第 5 节的 `final_score`。本文补**硬门**（任一命中即排除出生成上下文）：

```text
policy_result in [reject, quarantine]
sensitivity_level == S3
cross_agent_share 未授权
lifecycle in [forgotten, rolled_back, deprecated]
```

跨 Agent / 跨用户共享额外规则：

```text
默认不共享；共享需显式授权记录（谁授权、授权范围、有效期）
共享的记忆携带原 provenance，不得洗掉来源
被共享方不得把“他人记忆”升级为自身长期偏好，除非本方用户再次确认
```

---

## 6. 遗忘与回滚规则（L5 + Forget & Rollback）

遗忘必须**可验证**，不是写一条日志了事。

```text
遗忘请求 → 目标解析 → 生成 preview（命中项/派生项/关系边/索引/风险说明）
        → 用户确认 → 软删除 + 索引删除 + 关系边级联 + 派生摘要更新 → 审计
```

遗忘必须覆盖（缺一即视为遗忘不完整）：

```text
原始事件 / MemoryCapsule / 偏好版本 / 知识版本
affective_metadata / FTS 索引 / VectorRef / RelationEdge / 证据卡 / 派生摘要
```

回滚规则：

```text
定期快照 + 变更前快照
检测到污染 → 溯源 → 回滚到最近 known-good state → 回滚审计
回滚不得静默：必须记录回滚原因、影响范围（blast radius）、恢复点
```

遗忘验证指标（进 L7）：

```text
Forget Verification Success：遗忘后检索/关系/索引均查不到目标
Rollback Success Rate：回滚后状态与 known-good 快照一致
```

---

## 7. 审计与保留规则（L7 Audit / Compliance）

每个记忆动作都产生 trace（不可关闭）：

```text
write / read / update / delete / share / use_for_tool_call / rollback / forget
```

trace 必含字段：

```text
trace_id, operation, actor(identity), capsule_id,
policy_result, risk_tags, timestamp, evidence_ids
```

保留规则：

```text
审计日志 read_only，不可被 Agent 自主删除
S3 拦截事件只留“发生+类型+时间”摘要，不留敏感正文
遗忘/回滚动作本身必须留审计（遗忘内容，但不遗忘“遗忘发生过”）
```

---

## 8. 规则冲突裁决优先级

多规则命中时，按此优先级裁决（高覆盖低）：

```text
1. 安全（reject / quarantine）           最高，任何情况不被覆盖
2. 用户显式指令（explicit confirmation） 次高
3. 合规保留（审计/法定保留）
4. 治理策略（provenance / versioning）
5. 个性化与情感调权                       最低，只在前四项允许的空间内生效
```

一句话裁决原则：

```text
安全 > 用户显式 > 合规 > 治理 > 个性化。
情感与个性化永远在最底层，只能在安全允许的范围内优化体验。
```

---

## 9. 与其他文档的关系

```text
ASI_ORIENTED_MEMORY_ENVIRONMENT.md  → 架构（是什么）
MEMORY_GOVERNANCE_POLICY.md（本文）  → 规则（怎么执行）
ASI_RISK_MAPPING.md（待写）          → 把本文规则映射到 ASI 风险类别
MEMORY_SECURITY_EVAL.md（待写）      → 按本文规则设计测试项与指标
```

权威依据见 `docs/V04_V05_AUTHORITATIVE_REFERENCES.md`：
Long-Term Memory Security Survey（六阶段/四目标/VMG）、OWASP Agent Memory Guard（策略/快照/回滚）、Microsoft AI memory safety（intent+provenance gate）。
