#!/usr/bin/env python3
"""MEB baseline 对比实验 — 四组检索/治理配置对同一批用例的消融对比。

赛题评审要求「对比实验设计」:不能只报最终系统的成绩,要有 baseline 对照
证明每个组件的贡献。本脚本对 MEB 公开用例(full 套件)跑四组配置:

| 组 | 配置 | 验证的组件贡献 |
|---|---|---|
| hybrid | 完整(native→local→fts + 治理) | 最终系统(对照组) |
| fts_only | 仅 FTS5 词面检索 + 治理 | 向量/语义通道的贡献 |
| vector_only | 仅本地向量语义 + 治理 | 词面检索的贡献 |
| no_governance | 完整检索,绕过 policy_gate 治理门 | 治理层的贡献 |

产出:每组的三项赛题指标(偏好提取准确率/知识召回率/冲突正确率)+ pass_rate,
写 reports/baseline_compare.json + 打印对比表。

诚实口径:
- 用例集是仓内公开集(MEB public),official=False — 不冒充官方成绩
- 每组独立临时 db,跑完清理
- vector_only 需要本地 embedding 模型(WANWEI_LOCAL_EMBED_DIR);无模型时
  该组跳过并如实标注,不伪造数字

用法:
  python scripts/bench_baseline_compare.py
  WANWEI_LOCAL_EMBED_DIR=<模型目录> python scripts/bench_baseline_compare.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

GROUPS = ["hybrid", "fts_only", "vector_only", "no_governance"]


def _patches_for(group: str):
    """返回该组需要的 mock.patch 列表(不启动,由调用方进上下文)。"""
    from backend.app.memory_runtime import local_embedding, retrieval

    def _native_none(q, *, top_k, **kw):
        return None, {"backend": "fts_fallback", "native_index": {}}

    patches = []
    if group in ("fts_only", "vector_only"):
        patches.append(mock.patch.object(retrieval, "native_candidates", _native_none))
    if group == "fts_only":
        patches.append(mock.patch.object(local_embedding, "search", lambda *a, **k: None))
    if group == "vector_only":
        patches.append(mock.patch.object(
            retrieval, "_fts_candidates",
            lambda *a, **k: ([], {}, 0),
        ))
    if group == "no_governance":
        patches.append(mock.patch.object(
            retrieval, "allowed_for_context", lambda cap, *, high_risk=False: True
        ))
    return patches


def _run_group(group: str, db_path: str) -> dict:
    os.environ["WANWEI_MEMORY_DB"] = db_path
    import backend.app.db as dbmod

    dbmod.close_all()
    from backend.app.init_db import main as init_db
    init_db()
    from backend.app.memoryos.harness import run_suite

    patches = _patches_for(group)
    for p in patches:
        p.start()
    try:
        report = run_suite(suite="full", write_report=False)
    finally:
        for p in patches:
            p.stop()
    cm = report.get("competition_metrics", {})
    return {
        "pass_rate": report["summary"]["pass_rate"],
        "passed": report["summary"]["passed"],
        "total": report["summary"]["total_cases"],
        "preference_extraction_accuracy": cm.get("preference_extraction_accuracy"),
        "knowledge_recall": cm.get("knowledge_recall"),
        "conflict_correctness": cm.get("conflict_correctness"),
        "retrieval_latency_p95_ms": cm.get("retrieval_latency_p95_ms"),
        "mheb_overall": report["scores"].get("mheb_overall"),
        "failures": [
            {"case_id": f["case_id"], "reason": f["reason"]}
            for f in report.get("failures", [])
        ],
    }


def main() -> int:
    has_model = bool(os.environ.get("WANWEI_LOCAL_EMBED_DIR"))
    results = {}
    skipped = []
    for group in GROUPS:
        if group == "vector_only" and not has_model:
            skipped.append("vector_only(无本地模型,未跑)")
            continue
        db_path = os.path.join(tempfile.mkdtemp(), f"baseline_{group}.db")
        try:
            results[group] = _run_group(group, db_path)
            print(f"[{group:>14}] pass {results[group]['passed']}/{results[group]['total']} "
                  f"| pref {results[group]['preference_extraction_accuracy']} "
                  f"| recall {results[group]['knowledge_recall']} "
                  f"| conflict {results[group]['conflict_correctness']}")
        except Exception as exc:
            results[group] = {"error": str(exc)}
            print(f"[{group:>14}] ERROR: {exc}")

    out = {
        "meta": {
            "date": __import__("time").strftime("%Y-%m-%d"),
            "suite": "MEB full(公开集)",
            "official": False,
            "note": "消融对比:四组检索/治理配置。official=False,不冒充官方成绩。",
            "skipped": skipped,
            "has_local_embedding_model": has_model,
        },
        "groups": results,
    }
    out_path = Path("reports/baseline_compare.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
