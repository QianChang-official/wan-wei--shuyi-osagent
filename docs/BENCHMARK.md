# Benchmark

## 偏好提取
MEB mini 中 2/2 通过（`reports/meb_score_report.json`）。无独立线上 precision 报告的项标为未实跑。

## 知识检索
MEB mini 知识召回 3/3；本机 SQLite FTS5 p95 0.8072ms（README 实测表）。

## 检索延迟
麒麟原生 SDK 30 次样本 p50 195.320ms、p95 246.473ms（`reports/kylin-native-sdk-evidence/latency.json`）。消融报告中 FTS-only p95 1.01ms、hybrid 8.13ms、vector-only 7.37ms（`reports/baseline_compare.json`）。

## 遗忘验证
MEB mini 遗忘 3/3；删除证据链由五处残留验证覆盖。未实跑跨部署长期恢复测试。

## 对照实验
MEB full（非官方）结果：fts_only 60/60，hybrid 59/60，vector_only 58/60，no_governance 46/60。EGPM Phase-3 的真实漂移与 Phase-2 Outcome Validation 尚未接入统一对照，标为未验证。

## 延迟规模曲线
端侧 SQLite FTS5，1k/10k/50k 条记忆、50 条中文 query、冷热两态：1k cold p95 4.61ms，10k 77.06ms，50k 447.94ms（`reports/latency_scale.json`，逐次原始延迟可复现）。

## 知识演化与时序（TKE Benchmark）
四场景（软件演化 Firefox→Chrome→Edge / 流程演化 v1→v2→v3 / 规范替换 / 延迟导入——transaction_time 与 valid_time 错位场景）全部真实写路径：
- **Active Knowledge Accuracy（as-of/truth 历史回放正确率）：100%**
- **Evolution Chain Accuracy（演化链重建正确率）：100%**

复现：`PYTHONPATH=. python scripts/bench_tke.py`；原始逐采样判定见 `reports/tke_benchmark.json`，报告 `reports/tke_benchmark_report.md`。

## 偏好演化（Preference Graph）
节点/边建模、preference_score 四因子、演化幂等、冲突建议式裁决、级联遗忘与 preference-aware 重排由 45 条测试锁定（`test_preference_graph.py` 等四件套）；消融对照实验未跑，接入统一基准后补充。
