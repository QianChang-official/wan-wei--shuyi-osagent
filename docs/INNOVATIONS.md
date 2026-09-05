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
- 效果/证据：`test_preference_confidence.py`、`test_preference_outcome.py`、`test_preference_drift.py`、`test_sequence_mining.py`；真实漂移与统一对照仍未验证。

## 6. Preference Graph 偏好演化图（#198 / PR #200）
- 问题：偏好以离散记忆存在，无法回答「偏好如何形成、是否演化、冲突时信谁」。
- 设计：偏好图视图（preference/evidence/constraint 节点 + evidence_for/emotion_for/constraint_of/replaces/conflicts_with/derived_from 受控边，复用 relation_edges 零新表）；preference_score 四因子（emotion 0.35 / recency 0.25 / frequency 0.20 / evidence 0.20，进 tuning）；演化边 replaces + 版本链；建议式裁决（auto_execute 恒 False）；级联遗忘（replaces 链回溯 + 证据边摘除 + 死边 strip 后重验删除完整性）。
- 实现位置：`backend/app/memory_runtime/preference_graph.py`。
- 效果/证据：`test_preference_graph.py`、`test_preference_evolution.py`、`test_preference_conflict.py`、`test_preference_retrieval.py`（45 条，含幂等零账本噪音与深度截断回归）；生产检索路径接线待评审。

## 7. 知识演化与双时态 TKE（#202 / PR #203，#204 / PR #205）
- 问题：知识停留在「记录→检索」——新旧冲突无法显式表达、演化不可追踪、无版本治理；且无法回答「知识在什么时候为真」。
- 设计：知识冲突检测四分类（fact/status/config/temporal，规则式带触发证据）；Knowledge Version 随 supersedes 递增；四因子 knowledge_confidence（recency/trust/source/usage）建议式裁决；Knowledge Explain；检索按版本状态降权。TKE 时序核心补全双时态（valid_time/transaction_time）、as-of 历史回放双模式（truth=世界真值，延迟导入场景；belief=系统当时认知，严格双时态）、时效冲突升级区间判定、Knowledge Timeline 聚合、freshness（verified_at + 引用稳定度 max 兜底）。
- 实现位置：`backend/app/memory_runtime/knowledge_evolution.py`、`temporal_knowledge.py`。
- 效果/证据：`test_knowledge_conflict.py`、`test_knowledge_evolution.py`、`test_active_knowledge.py`、`test_conflict_retrieval.py`、`test_temporal_knowledge.py`、`test_knowledge_timeline.py`、`test_freshness_scoring.py`（89 条）；TKE Benchmark 四场景（含延迟导入）**Active Knowledge Accuracy 100% / Evolution Chain Accuracy 100%**（`scripts/bench_tke.py`，`reports/tke_benchmark_report.md`）。

## 与赛题创新点命名对照

issue 中点名的创新点与上述条目的对应关系：

| 赛题命名 | 对应条目 | 关键实现 |
|---|---|---|
| MemoryCapsule 2.0 | #4 Provenance Card | `backend/app/memory_runtime/capsule_store.py`，`test_capsule_store.py` |
| Policy Gate | #5 EGPM 偏好治理闭环（写入侧） | `backend/app/memory_runtime/policy_gate.py`，`test_policy_gate.py` |
| Affective Memory | #5 EGPM Phase-1/2（情感证据权重） | `backend/app/memory_runtime/preference_confidence.py`，`test_affective_evidence.py`、`test_affective_retrieval.py`、`scripts/ablation_affective_weight.py` |
| Trustworthy Forgetting | #1 可证明删除 + #2 生命周期状态机 + #6 级联遗忘 | 五处残留验证 + PDF 证书，10 态转移裁决，偏好级联遗忘（`test_preference_retrieval.py`） |
| Preference Graph | #6（已交付，PR #200） | `backend/app/memory_runtime/preference_graph.py`，`test_preference_graph.py` 等 45 条 |
| 知识冲突与演化 | #7（已交付，PR #203/#205） | `backend/app/memory_runtime/knowledge_evolution.py`、`temporal_knowledge.py`，89 条测试 + TKE Benchmark |

Affective Memory 的三臂消融由 `scripts/ablation_affective_weight.py` 合成证据流完成，结果与局限按 CHANGELOG（#181）口径如实记录。
