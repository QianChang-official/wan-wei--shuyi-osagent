# 创新点总览

七项创新的技术细节、真实代码位置和证据见 [docs/INNOVATIONS.md](../docs/INNOVATIONS.md)。

1. 删除证明：五处残留逐项取证并导出 PDF。
2. 生命周期状态机：10 态合法转移，阻断删除后复活。
3. 不可变治理账本：SQLite 触发器强制 append-only，记录哈希与风险。
4. Provenance Card：记录来源、置信度、有效期和版本链。
5. EGPM 偏好治理闭环：偏好提取、情感证据调制、结果反馈和漂移代理检测分阶段落地（PR #182/#184）。
6. Preference Graph 偏好演化图：preference_score 四因子评分、replaces 演化链、建议式冲突裁决与级联遗忘（PR #200，45 条测试）。
7. 知识演化与双时态 TKE：四类知识冲突检测、版本演化链、as-of 历史回放双模式（truth/belief）、Knowledge Timeline 与 freshness 老化（PR #203/#205，89 条测试 + TKE Benchmark 双 100%）。

EGPM 与 TKE 构成双演化体系：EGPM 管偏好记忆（情感→偏好→演化），TKE 管知识记忆（时间→真值→演化）。
