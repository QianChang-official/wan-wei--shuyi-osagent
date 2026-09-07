#!/usr/bin/env python3
"""EGPM 偏好记忆评测基准 — 偏好提取准确率等指标的量化证据。

赛题指标（3）：偏好提取准确率 ≥ 85%。

口径（诚实声明）：
- 数据集是仓内公开合成集（``memory_benchmark/dataset.py``，seed=42，
  6 场景 × 12 事件 = 72 条偏好事件：stable / weak / high_emotion /
  temporary / drift / wrong）——不是官方竞赛数据集。
- 指标定义见 ``memory_benchmark/metrics.py``：preference_accuracy =
  逐事件预测正确数 / 总事件数；另报 FPR、漂移精确率/召回率/F1、
  校准误差（ECE）与 Brier 分数。
- 消融臂 Baseline / +Beta / +Drift 为算法级对照；+Emotion 组件未实现，
  如实标记为未验证，不编造数字。
- 原始 JSON 与 Markdown 报告同时落盘，数字由同一次运行生成。

用法：
  PYTHONPATH=. python scripts/bench_egpm.py
输出：
  reports/egpm_benchmark.json      — 机器可读原始结果
  reports/egpm_benchmark_report.md — 人读报告（由同一数据渲染）
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
for _p in (str(_REPO), str(_REPO / "backend")):
    if _p not in sys.path:
        sys.path.append(_p)

from backend.app.memory_benchmark import DatasetLoader, BenchmarkRunner  # noqa: E402
from backend.app.memory_benchmark.dataset import generate_dataset  # noqa: E402
from backend.app.memory_benchmark.report import render_report  # noqa: E402

SEED = 42
REPEATS = 12


def main() -> int:
    records = generate_dataset(seed=SEED, repeats=REPEATS)
    results = BenchmarkRunner(DatasetLoader.synthetic(seed=SEED, repeats=REPEATS)).run()

    payload = {
        "benchmark": "EGPM",
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "dataset": {
            "source": "in-repo synthetic public set (memory_benchmark/dataset.py)",
            "seed": SEED,
            "repeats_per_scenario": REPEATS,
            "scenarios": sorted({r["scenario"] for r in records}),
            "events": len(records),
        },
        "note": "official=False；仓内公开合成集，不冒充官方竞赛成绩。",
        "results": results,
    }

    reports = _REPO / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    json_path = reports / "egpm_benchmark.json"
    md_path = reports / "egpm_benchmark_report.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_report(results), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\n报告: {json_path} / {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
