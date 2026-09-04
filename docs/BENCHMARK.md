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
