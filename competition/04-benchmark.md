# 评测成绩单

完整口径见 [docs/BENCHMARK.md](../docs/BENCHMARK.md)。

- MEB mini：14/14 通过，pass_rate 1.0；这是本仓自建公开用例集成绩，不是官方竞赛成绩（`reports/meb_score_report.json`）。
- 五类用例（偏好提取、知识召回、冲突更新、遗忘、投毒）在该次运行中均为 1.0。
- 生产记忆评测：5 cases、16 assertions 全部通过，unsafe_autonomy_rate=0.0（`reports/production_memory_eval_metrics.json`）。
- 消融对照（MEB full，非官方）：fts_only 60/60、hybrid 59/60、vector_only 58/60、no_governance 46/60；详见 `reports/baseline_compare.json`。
- FTS5 本机检索 p95 0.8072ms；麒麟 SDK p50 195.320ms、p95 246.473ms。

EGPM Phase-1/2/3 已在 CHANGELOG 中记录，但真实漂移与 Outcome Validation 尚未接入统一对照实验，相关项标为未验证。
