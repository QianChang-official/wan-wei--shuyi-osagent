#!/usr/bin/env python3
"""麒麟原生 embedding/vector SDK 端到端检索延迟基准（在麒麟 VM 内运行）。

赛题指标（4）：调用银河麒麟国产桌面操作系统 embedding SDK，检索响应延迟 ≤ 500ms。

口径（诚实声明）：
- **必须跑在麒麟系统里**：bridge（/usr/local/bin/wanwei-kylin-sdk-bridge）是
  麒麟向量引擎的 C++ ABI 封装，宿主机上不存在，本脚本在非麒麟环境会以
  ``available: false`` 退出而不是编造数字。
- **端到端测量**：一次 search = 模型 embedding + 向量检索全程（常驻 bridge
  进程内完成，不含进程冷启动；one-shot 冷启动模式见 kylin_sdk/native.py）。
- **原始数据留痕**：逐次延迟全部写入 JSON，p50/p95 由数据算出，不手写。
- 用后清理：探测用向量 90001/90002 测完即删，不留脏数据。

用法：
  python scripts/bench_kylin_sdk_latency.py                 # 30 次检索 + 1 次预热
  python scripts/bench_kylin_sdk_latency.py --searches 50 --warmup 3
输出：
  reports/kylin_sdk_latency.json — 状态 + 逐次延迟 + 分位数汇总
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
for _p in (str(_REPO), str(_REPO / "backend")):
    if _p not in sys.path:
        sys.path.append(_p)

# 探测向量使用独立的高位 id 段，避开业务库 AUTOINCREMENT 分配区间，测完即删。
PROBE_VECTOR_IDS = (90001, 90002)
PROBE_TEXTS = (
    "麒麟原生SDK延迟实测：检查工作流程知识检索",
    "历史案例沉淀：办公自动化偏好适配复用",
)
DEFAULT_QUERY = "工作流程知识检索复用"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Kylin native SDK end-to-end search latency benchmark.")
    parser.add_argument("--searches", type=int, default=30, help="计时检索次数（默认 30）")
    parser.add_argument("--warmup", type=int, default=1, help="预热检索次数，不计时（默认 1）")
    parser.add_argument("--query", type=str, default=DEFAULT_QUERY, help="检索文本")
    parser.add_argument(
        "--output", type=Path, default=_REPO / "reports" / "kylin_sdk_latency.json",
        help="结果 JSON 落盘路径",
    )
    return parser.parse_args()


def _percentile(sorted_values: list[float], q: float) -> float:
    index = max(0, min(len(sorted_values) - 1, int(q * (len(sorted_values) - 1))))
    return sorted_values[index]


def main() -> int:
    args = _parse_args()
    from app.kylin_sdk.native import KylinNativeSdk

    sdk = KylinNativeSdk()
    status = sdk.status()
    result: dict = {
        "benchmark": "kylin_native_sdk_latency",
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "backend": status.get("backend"),
        "available": bool(status.get("available")),
        "bridge": status.get("bridge_path"),
        "model": status.get("model"),
        "dimension": status.get("dimension"),
        "capabilities": status.get("capabilities"),
    }
    if not status.get("available"):
        print(json.dumps(result, ensure_ascii=False, indent=2))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return 1

    t0 = time.perf_counter()
    upserts = [
        sdk.upsert(vector_id=vid, capsule_id=f"latency-check-{chr(ord('a') + i)}", text=text)
        for i, (vid, text) in enumerate(zip(PROBE_VECTOR_IDS, PROBE_TEXTS))
    ]
    result["upsert_ok"] = all(bool(u.get("ok")) for u in upserts)
    result["upsert_ms"] = round((time.perf_counter() - t0) * 1000, 3)

    warmup_latencies = []
    for _ in range(max(0, args.warmup)):
        t = time.perf_counter()
        resp = sdk.search(text=args.query, top_k=5)
        warmup_latencies.append(round((time.perf_counter() - t) * 1000, 3))
        if not resp.get("ok"):
            result["warmup_failed"] = True
            break

    latencies = []
    for i in range(args.searches):
        t = time.perf_counter()
        resp = sdk.search(text=args.query, top_k=5)
        latencies.append(round((time.perf_counter() - t) * 1000, 3))
        if not resp.get("ok"):
            result["search_failed_at"] = i
            break

    result["warmup_count"] = len(warmup_latencies)
    result["warmup_ms"] = warmup_latencies
    if latencies and len(latencies) == args.searches:
        ordered = sorted(latencies)
        result["search_count"] = len(latencies)
        result["raw_ms"] = latencies
        result["p50_ms"] = round(statistics.median(ordered), 3)
        result["p95_ms"] = round(_percentile(ordered, 0.95), 3)
        result["mean_ms"] = round(statistics.fmean(latencies), 3)
        result["min_ms"] = round(min(latencies), 3)
        result["max_ms"] = round(max(latencies), 3)
        result["within_500ms"] = result["p95_ms"] <= 500

    for vid in PROBE_VECTOR_IDS:
        sdk.delete(vector_id=vid)
    result["cleanup_ok"] = True

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n报告: {args.output}")
    return 0 if result.get("within_500ms") else 1


if __name__ == "__main__":
    raise SystemExit(main())
