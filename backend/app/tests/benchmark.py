"""
v0.9.6 T1 — 性能基线采集工具 (perf baseline harness)

对关键控制回路路径做多次采样，输出 p50/p95/mean 到 reports/perf_baseline.json。
用途：
- 为 v0.9.6 的 N+1 优化 / connection reuse 提供 before/after 对比基线。
- 明确区分 OSAgent 控制回路延迟与模型生成延迟（本工具不触发模型生成）。

诚实边界：
- 数值受硬件、磁盘、Python 版本影响，仅用于同机 before/after 相对对比。
- 不作为绝对性能承诺。
- 不测网络 / 模型推理延迟。

运行：
    PYTHONPATH=. python3 -m backend.app.tests.benchmark
    PYTHONPATH=. python3 -m backend.app.tests.benchmark --iterations 200 --out reports/perf_baseline.json
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any, Callable


def _percentile(values: list[float], pct: float) -> float:
    """线性插值百分位数（无第三方依赖）。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (pct / 100.0) * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    frac = rank - low
    return ordered[low] + (ordered[high] - ordered[low]) * frac


def _time_calls(fn: Callable[[], Any], iterations: int, warmup: int) -> dict[str, float]:
    """对 fn 采样 iterations 次，返回毫秒级统计（warmup 次不计入）。"""
    for _ in range(max(0, warmup)):
        fn()
    samples: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000.0)
    return {
        "iterations": iterations,
        "mean_ms": round(statistics.fmean(samples), 4),
        "p50_ms": round(_percentile(samples, 50), 4),
        "p95_ms": round(_percentile(samples, 95), 4),
        "p99_ms": round(_percentile(samples, 99), 4),
        "min_ms": round(min(samples), 4),
        "max_ms": round(max(samples), 4),
    }


def _seed_capsules(n: int) -> None:
    """写入 n 个 capsule，供检索基线使用。"""
    from backend.app.memory_runtime.capsule_store import write_capsule

    for i in range(n):
        write_capsule(
            memory_class="knowledge",
            content={"text": f"周报模板 正式语气 三段式结构 样本 {i}", "idx": i},
            source_type="user_input",
            scene="weekly_report",
        )


def run_benchmarks(iterations: int, warmup: int, seed_n: int) -> dict[str, Any]:
    """在隔离的临时数据库上运行全部基线。"""
    from backend.app.memory_runtime.capsule_store import write_capsule
    from backend.app.memory_runtime.retrieval import search_capsules
    from backend.app.memory_runtime.command_loop import run_command_loop
    from backend.app.memory_runtime.policy_gate import evaluate_policy
    from backend.app.workflow.service import create_run, WorkflowRunIn
    from backend.app.workflow.persistence import init_workflow_persistence
    from backend.app import version

    init_workflow_persistence()
    _seed_capsules(seed_n)

    counter = {"n": 0}

    def _write_once() -> None:
        counter["n"] += 1
        write_capsule(
            memory_class="knowledge",
            content={"text": f"基准写入样本 {counter['n']}"},
            source_type="user_input",
            scene="benchmark",
        )

    results: dict[str, Any] = {
        "version": version.VERSION,
        "kind": "osagent_control_loop_baseline",
        "boundary": "excludes model generation latency; single-process; local sqlite; same-machine before/after only",
        "config": {"iterations": iterations, "warmup": warmup, "seed_capsules": seed_n},
        "paths": {},
    }

    results["paths"]["policy_evaluate"] = _time_calls(
        lambda: evaluate_policy(text="生成本周项目周报，记住正式语气"),
        iterations, warmup,
    )
    results["paths"]["capsule_search_zh"] = _time_calls(
        lambda: search_capsules("周报 正式语气 三段式结构", top_k=5),
        iterations, warmup,
    )
    results["paths"]["capsule_write"] = _time_calls(_write_once, iterations, warmup)
    results["paths"]["command_loop"] = _time_calls(
        lambda: run_command_loop(goal="生成本周项目周报并复用偏好", scene="weekly_report"),
        iterations, warmup,
    )
    results["paths"]["workflow_create_run"] = _time_calls(
        lambda: create_run(WorkflowRunIn()),
        iterations, warmup,
    )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="v0.9.6 perf baseline harness")
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--seed", type=int, default=50, help="number of capsules to seed before search benchmark")
    parser.add_argument("--out", type=str, default="reports/perf_baseline.json")
    args = parser.parse_args()

    # 使用隔离的临时数据库，避免污染真实内存库
    tmp = tempfile.NamedTemporaryFile(suffix="_bench.db", delete=False)
    tmp.close()
    os.environ["WANWEI_MEMORY_DB"] = tmp.name
    try:
        results = run_benchmarks(args.iterations, args.warmup, args.seed)
    finally:
        Path(tmp.name).unlink(missing_ok=True)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[benchmark] wrote {out_path}")
    for name, stats in results["paths"].items():
        print(f"  {name:24s} p50={stats['p50_ms']:.3f}ms  p95={stats['p95_ms']:.3f}ms  mean={stats['mean_ms']:.3f}ms")


if __name__ == "__main__":
    main()
