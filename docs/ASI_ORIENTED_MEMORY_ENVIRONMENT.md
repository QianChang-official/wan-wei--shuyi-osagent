> 项目：宛委·枢忆 OSAgent / ASI-Memory Environment
> 版本：v0.4（面向生产环境的安全记忆治理底座）
> 命名说明：本文中 ASI 指 Artificial Superintelligence（人工超级智能）方向，仅作“问题定位与长期目标对标”，不等同于 OWASP Agentic Security Initiative；本项目不声称实现 ASI。

# 面向 ASI-Oriented Agent 的安全记忆治理环境（v0.4）

## 0. 一句话定位

v0.4 不做“实现 ASI”，而是做一件更务实、更有生产价值的事：

```text
让 Agent 的长期记忆能够安全、可控、可追溯、可回滚、可遗忘、可审计地进入生产环境。
```

先解决“记忆能不能安全进生产”，再在 v0.5 谈“面向 ASI-Oriented Agent 的偏好与知识优化”。

核心论断（对标 Microsoft AI memory safety）：

```text
Memory is a control plane.
记忆不是普通数据，而是会影响 Agent 未来工具选择、拒绝行为与推理路径的控制平面。
```

---

## 1. 设计原则（写进架构首页）

```text
1. Memory is a control plane.        记忆是行为控制平面，不是普通数据。
2. No memory without provenance.     没有来源证明的内容不得长期化。
3. No personalization without governance. 没有治理的个性化就是风险。
4. No retrieval without trust.       检索不能只看相关性，必须看可信度。
5. No deletion without verification. 遗忘必须可验证，不只是写日志。
6. No humanization without boundaries. 人性化必须服从安全、合规与用户显式授权。
```

---

## 2. 安全记忆治理七层（v0.4 底座）

```text
L1 Memory Ingress Gateway   记忆写入网关：来源识别、意图确认、敏感识别、投毒初筛
L2 Memory Policy Engine     记忆策略引擎：YAML 策略、风险标签、allow/redact/quarantine/reject/require_confirm
L3 MemoryCapsule Store      统一安全记忆容器：provenance + governance + lifecycle
L4 Trust-aware Retrieval    可信检索层：权限过滤 + 安全过滤 + 可信排序 + 证据卡
L5 Snapshot & Rollback      快照与回滚层：污染溯源、回滚 known-good state
L6 Humanized Decision Layer 人性化决策层：风险分级自动/建议/确认/拒绝
L7 Audit / Eval / Compliance 审计评测合规层：记忆动作 trace + 纵向安全 + 投毒评测
```

映射到项目既有模块：

```text
石渠校验   → L1 写入网关
司契护栏   → L1/L2 准入 + 策略
枢忆核     → L3 MemoryCapsule 生命周期
建木网络   → L4 关系召回
灵犀情感   → L6 情感调权（不覆盖安全）
忘机机制   → L5 精准遗忘 + 回滚
兰台鉴证   → L7 审计评测
```

---

## 3. 记忆生命周期六阶段（对标 Long-Term Memory Security Survey, arXiv 2604.16548 预印本）

```text
Write            写入准入：intent + provenance gate
Store            存储：storage-time provenance、versioning、policy-aware retention
Retrieve         检索：trust-aware rerank、安全/权限过滤
Execute          执行：记忆影响工具调用前的拦截
Share & Propagate 共享传播：跨 Agent / 跨用户授权校验
Forget & Rollback 遗忘回滚：可验证删除、级联清理、快照回滚
```

四类安全目标：

```text
Integrity        完整性：SHA 基线、异常变更检测
Confidentiality  机密性：敏感信息识别、脱敏、S0-S3 分级
Availability     可用性：隔离不误伤主链、回滚可恢复
Governance       治理：审计链、策略命中、合规映射
```

Verifiable Memory Governance（VMG）落点：安全不在检索/执行时补救，而从 storage-time provenance 起（对应 MemoryCapsule 的 provenance/version 字段）。

---

## 4. 写入准入（Memory Ingress Gateway）

对标 Microsoft：gate writes on intent and provenance。

```text
输入事件
  ↓ 谁写？（writer_identity 授权校验，least privilege）
  ↓ 为什么写？（write_intent: explicit / inferred / autonomous）
  ↓ 来源可信？（source_type + source_trust）
  ↓ 是否敏感？（credentials/API key/支付/证件 → block from memory）
  ↓ 是否注入/投毒？（prompt injection 特征）
  ↓ 是否影响未来行为？（affects_future_behavior）
准入决策：allow / redact / quarantine / reject / require_confirmation
```

硬规则：

```text
S3（密钥/凭据/支付/证件）→ 直接 reject，仅留审计摘要
低可信来源的 autonomous 写入 → quarantine
inferred 的行为类偏好 → require_confirmation
emotional_salience 高 → 只能提优先级，绝不覆盖上述安全判定
```

---

## 5. 可信检索排序（Trust-aware Retrieval）

```text
final_score =
  0.30 * relevance_score
+ 0.15 * relation_score
+ 0.15 * confidence
+ 0.15 * trust_score
+ 0.10 * recency_score
+ 0.05 * affective_fit
+ 0.05 * usage_value
- safety_penalty
- poisoning_risk
```

进入生成上下文前的硬门（任一命中即排除）：

```text
policy_result in [reject, quarantine]
sensitivity_level == S3
cross_agent_share 未授权
lifecycle in [forgotten, rolled_back]
```

---

## 6. 快照与回滚（对标 OWASP Agent Memory Guard，C 级工程治理）

```text
记忆快照 snapshot
版本对比 diff
异常变更检测（rapid changes / size anomalies）
污染溯源 forensic
回滚到 known-good state
回滚审计
```

价值点：企业不只问“能不能记住”，更问“记忆被污染后能不能恢复”。

---

## 7. 纵向安全评测（对标 Remembering More, Risking More）

```text
NullMemory 对照
不同记忆前缀长度快照测试
记忆诱导风险 delta
投毒拦截率 / 敏感写入阻断率
遗忘验证成功率 / 回滚成功率
Safety Override Rate（情感权重绕过安全的次数，应为 0）
```

---

## 8. 与 v0.5 的边界

```text
v0.4：安全记忆治理底座 —— 记忆能不能安全进生产。
v0.5：ASI-Oriented 偏好与知识优化 —— 高智能体如何长期吸收人类偏好、组织知识、生产经验与监督信号。
```

v0.4 先立“可信、可治理、可回滚”，v0.5 再谈“可扩展监督与偏好演化”。

---

## 9. 权威参考

见 `docs/V04_V05_AUTHORITATIVE_REFERENCES.md`（A/B/C 三级分级 + 措辞红线）。本文所引：

- Long-Term Memory Security Survey（arXiv 2604.16548 预印本）
- OWASP Agent Memory Guard（行业安全治理参考，非论文）
- Microsoft: Manage AI memory safety in agentic systems（厂商治理文档，非论文）
- Memory Poisoning Attack and Defense（arXiv 2601.05504 预印本）
- Remembering More, Risking More（arXiv 2605.17830 预印本）

先进技术填充见 `docs/ADVANCED_MEMORY_TECH.md`。
