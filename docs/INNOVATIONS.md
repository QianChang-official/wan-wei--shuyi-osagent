# 创新点与证据

## 1. 可证明删除
- 问题：删除后索引、关系或遗留表可能残留。
- 设计：五处探针逐项核验并生成证书。
- 实现位置：`backend/app/memoryos/governance.py`、`backend/app/memory_runtime/capsule_store.py`。
- 效果/证据：`scripts/demo_governance.py` 第 4-5 步；`test_memoryos_certificate.py`。

## 2. 生命周期状态机
- 问题：自由字符串赋值会让已删除记忆复活。
- 设计：10 态转移表，非法转移 422。
- 实现位置：`backend/app/memoryos/lifecycle.py`。
- 效果/证据：`test_memoryos_lifecycle.py`。

## 3. 不可变账本
- 问题：审计记录可被 UPDATE/DELETE 篡改。
- 设计：SQLite append-only 触发器与前后哈希。
- 实现位置：`backend/app/memoryos/governance.py`、`backend/app/init_db.py`。
- 效果/证据：`test_memoryos_governance.py`、`test_ledger_score_dos.py`。

## 4. Provenance Card
- 问题：召回内容缺少来源、置信和版本上下文。
- 设计：单记忆 provenance 卡片与版本链。
- 实现位置：`backend/app/memoryos/governance.py`、`backend/app/memory_runtime/capsule_store.py`。
- 效果/证据：`test_memoryos_api.py`、`test_capsule_store.py`。

## 5. EGPM 偏好治理闭环
- 问题：偏好推断可能误写、受情感噪声影响且缺少结果反馈。
- 设计：Phase-1 提取、Phase-2 情感证据权重与 Outcome Validation、Phase-3 漂移代理检测；候选强制确认。
- 实现位置：`backend/app/memory_runtime/policy_gate.py`、`preference_confidence.py`、`preference_outcome.py`、`preference_drift.py`、`sequence_mining.py`。
- 效果/证据：`test_preference_confidence.py`、`test_preference_outcome.py`、`test_preference_drift.py`、`test_sequence_mining.py`；真实漂移与统一对照仍未验证。Preference Graph：规划中。

## 与赛题创新点命名对照

issue 中点名的创新点与上述条目的对应关系：

| 赛题命名 | 对应条目 | 关键实现 |
|---|---|---|
| MemoryCapsule 2.0 | #4 Provenance Card | `backend/app/memory_runtime/capsule_store.py`，`test_capsule_store.py` |
| Policy Gate | #5 EGPM 偏好治理闭环（写入侧） | `backend/app/memory_runtime/policy_gate.py`，`test_policy_gate.py` |
| Affective Memory | #5 EGPM Phase-1/2（情感证据权重） | `backend/app/memory_runtime/preference_confidence.py`，`test_affective_evidence.py`、`test_affective_retrieval.py`、`scripts/ablation_affective_weight.py` |
| Trustworthy Forgetting | #1 可证明删除 + #2 生命周期状态机 | 五处残留验证 + PDF 证书，10 态转移裁决 |
| Preference Graph | 规划中 | 未实现，不作为已有能力宣称 |

Affective Memory 的三臂消融由 `scripts/ablation_affective_weight.py` 合成证据流完成，结果与局限按 CHANGELOG（#181）口径如实记录。
