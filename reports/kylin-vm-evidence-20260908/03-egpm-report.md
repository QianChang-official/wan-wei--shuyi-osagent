# EGPM Benchmark Report
Usage: `PYTHONPATH=. python scripts/bench_egpm.py` (CI entry point).

| Method | preference_accuracy | false_preference_rate | drift_precision | drift_recall | drift_f1 | calibration_error | brier |
|---|---|---|---|---|---|---|---|
| Baseline | 0.6111 | 0.9474 | 0.0000 | 0.0000 | 0.0000 | 0.1111 | 0.2500 |
| +Beta | 0.6111 | 0.9474 | 0.0000 | 0.0000 | 0.0000 | 0.1491 | 0.2278 |
| +Drift | 0.6111 | 0.9474 | 0.3333 | 0.5000 | 0.4000 | 0.1491 | 0.2278 |
| +Emotion | 未验证（组件未实现） | 未验证（组件未实现） | 未验证（组件未实现） | 未验证（组件未实现） | 未验证（组件未实现） | 未验证（组件未实现） | 未验证（组件未实现） |

## 结论
基于真实运行结果生成；Emotion、Persona、Safety Consistency 组件未实现（超出本次范围），相关指标标记为未验证。
