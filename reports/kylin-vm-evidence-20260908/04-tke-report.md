# TKE Benchmark Report

Active Knowledge Accuracy (as-of/truth): **100.00%**
Evolution Chain Accuracy: **100.00%**

| 场景 | Active Knowledge Acc | Evolution Chain Acc |
|---|---|---|
| software_evolution(Firefox → Chrome → Edge(软件演化)) | 100.00% | 100.00% |
| workflow_evolution(工作流 v1 → v2 → v3(流程演化)) | 100.00% | 100.00% |
| spec_replacement(旧规范 → 新规范(规范替换)) | 100.00% | 100.00% |
| delayed_import(历史知识延迟导入(transaction_time 与 valid_time 错位)) | 100.00% | 100.00% |

## 复现

```bash
PYTHONPATH=. python scripts/bench_tke.py
```

原始逐采样判定见 `reports/tke_benchmark.json`。
