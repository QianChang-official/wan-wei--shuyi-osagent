#!/usr/bin/env python3
"""TKE Benchmark:Active Knowledge Accuracy(as-of)与 Evolution Chain Accuracy。

issue #204(#TKE)的评测口径。回答评审两个追问:

1. 「你说双时态,那 as-of 查询到底准不准?」——Active Knowledge Accuracy:
   对演化链上的每个采样时刻跑 ``knowledge_as_of(truth)``,与 ground truth
   对比(哪个版本在该时刻为真)。
2. 「演化链重建对不对?」——Evolution Chain Accuracy:``trace_evolution``
   回溯的链与 ground truth 的版本序列对比(顺序+成员全对才算过)。

场景(延迟导入是 TKE 的立身场景,单列):
- software_evolution  Firefox → Chrome → Edge(valid_time 顺次衔接)
- workflow_evolution  工作流 v1 → v2 → v3
- spec_replacement    旧规范 → 新规范
- delayed_import      历史知识在今天导入(transaction_time 与 valid_time
  错位——按 created_at 排序会全错的场景)

诚实口径:
- 全部走真实写路径(write_capsule → set_valid_time → evolve_knowledge),
  不直写 SQL 伪造 state;
- 每场景独立临时库,跑完清理;
- 原始判定逐条留 JSON(reports/tke_benchmark.json),报告由数据生成。

用法:
  PYTHONPATH=. python scripts/bench_tke.py
输出:
  reports/tke_benchmark.json     — 原始数据 + 汇总
  reports/tke_benchmark_report.md — 报告(由 JSON 渲染,不手写数字)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
for _p in (str(_REPO), str(_REPO / "backend")):
    if _p not in sys.path:
        sys.path.append(_p)

#: 采样时刻密度:每条 valid_time 区间取首/中/尾三个 as-of 采样点。
SAMPLE_PER_INTERVAL = 3

#: 场景定义:versions 顺次衔接(前者的 valid_until = 后者的 valid_from)。
SCENARIOS = [
    {
        "name": "software_evolution",
        "desc": "Firefox → Chrome → Edge(软件演化)",
        "versions": [
            {"text": "默认浏览器 = Firefox", "from": "2025-01-01T00:00:00Z", "until": "2025-09-01T00:00:00Z"},
            {"text": "默认浏览器 = Chrome", "from": "2025-09-01T00:00:00Z", "until": "2026-05-01T00:00:00Z"},
            {"text": "默认浏览器 = Edge", "from": "2026-05-01T00:00:00Z", "until": None},
        ],
    },
    {
        "name": "workflow_evolution",
        "desc": "工作流 v1 → v2 → v3(流程演化)",
        "versions": [
            {"text": "构建流程 = 单体脚本", "from": "2025-03-01T00:00:00Z", "until": "2025-12-01T00:00:00Z"},
            {"text": "构建流程 = Makefile", "from": "2025-12-01T00:00:00Z", "until": "2026-06-01T00:00:00Z"},
            {"text": "构建流程 = CI 流水线", "from": "2026-06-01T00:00:00Z", "until": None},
        ],
    },
    {
        "name": "spec_replacement",
        "desc": "旧规范 → 新规范(规范替换)",
        "versions": [
            {"text": "代码规范 = Google Style", "from": "2025-06-01T00:00:00Z", "until": "2026-02-01T00:00:00Z"},
            {"text": "代码规范 = PEP 8 扩展版", "from": "2026-02-01T00:00:00Z", "until": None},
        ],
    },
    {
        "name": "delayed_import",
        "desc": "历史知识延迟导入(transaction_time 与 valid_time 错位)",
        "versions": [
            {"text": "服务器地址 = 192.168.1.10", "from": "2025-01-01T00:00:00Z", "until": "2025-10-01T00:00:00Z"},
            {"text": "服务器地址 = 192.168.1.20", "from": "2025-10-01T00:00:00Z", "until": None},
        ],
    },
]


def _iso_midpoint(a: str, b: str) -> str:
    from datetime import datetime, timezone

    ta = datetime.fromisoformat(a.replace("Z", "+00:00"))
    tb = datetime.fromisoformat(b.replace("Z", "+00:00"))
    return (ta + (tb - ta) / 2).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _build_scenario(scn: dict) -> dict:
    """真实写路径构建一条演化链,返回 capsule ids 与 ground truth。"""
    import backend.app.db as dbmod
    from backend.app import init_db
    from backend.app.memory_runtime import knowledge_evolution as ke
    from backend.app.memory_runtime.capsule_store import write_capsule
    from backend.app.memory_runtime.temporal_knowledge import set_valid_time

    dbmod.close_all()
    init_db.main()

    ids = []
    for v in scn["versions"]:
        cid = write_capsule(
            memory_class="knowledge", content={"text": v["text"]},
            source_type="user_input",
        )["capsule_id"]
        set_valid_time(cid, valid_from=v["from"], valid_until=v["until"])
        ids.append(cid)
    # versions 列表是旧→新;演化边方向是「新 supersedes 旧」。
    for older, newer in zip(ids, ids[1:]):
        ke.evolve_knowledge(newer, older)
    dbmod.close_all()
    return {"ids": ids}


def _sample_points(scn: dict) -> list[tuple[str, str]]:
    """采样点 ``(at, expected_text)``:每段区间取首/中/尾三点。"""
    pts: list[tuple[str, str]] = []
    for i, v in enumerate(scn["versions"]):
        f, u = v["from"], v["until"]
        pts.append((f, v["text"]))
        if u:
            pts.append((_iso_midpoint(f, u), v["text"]))
            # 尾点:区间结束前一秒(半开区间,at==until 已属下一段)。
            from datetime import datetime, timedelta, timezone

            tu = datetime.fromisoformat(u.replace("Z", "+00:00"))
            pts.append(
                ((tu - timedelta(seconds=1)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), v["text"])
            )
        elif i > 0:
            # 最后一段无界:取与上一段衔接点之后一天验证「已切换」。
            prev_u = scn["versions"][i - 1]["until"]
            from datetime import datetime, timedelta, timezone

            tp = datetime.fromisoformat(prev_u.replace("Z", "+00:00"))
            pts.append(
                ((tp + timedelta(days=1)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), v["text"])
            )
    return pts


def run_benchmark() -> dict:
    results = []
    for scn in SCENARIOS:
        tmpdir = tempfile.mkdtemp()
        os.environ["WANWEI_MEMORY_DB"] = os.path.join(tmpdir, "tke_bench.db")
        try:
            built = _build_scenario(scn)
            ids = built["ids"]

            from backend.app.memory_runtime.temporal_knowledge import knowledge_as_of
            import backend.app.db as dbmod
            dbmod.close_all()

            # --- 指标 1: Active Knowledge Accuracy(as-of truth)---
            samples = []
            correct = 0
            for at, expected in _sample_points(scn):
                got = knowledge_as_of(ids, at=at, mode="truth")
                got_text = got["active"]["text"] if got.get("active") else None
                ok = got_text == expected
                correct += ok
                samples.append({"at": at, "expected": expected, "got": got_text, "pass": ok})
            aka = correct / len(samples) if samples else 0.0

            # --- 指标 2: Evolution Chain Accuracy(链重建)---
            # ground truth:从最新版本回溯应是 旧→…→新 的完整逆序。
            from backend.app.memory_runtime.temporal_knowledge import knowledge_timeline
            tl = knowledge_timeline(ids[-1])
            chain_ids = [c["capsule_id"] for c in tl["chain"]]
            # trace_evolution 从 root(最新)向旧回溯:期望 [最新, …, 最旧]。
            expected_chain = list(reversed(ids))
            chain_ok = chain_ids == expected_chain

            results.append({
                "scenario": scn["name"],
                "desc": scn["desc"],
                "active_knowledge_accuracy": round(aka, 4),
                "as_of_samples": samples,
                "evolution_chain_accuracy": 1.0 if chain_ok else 0.0,
                "chain_rebuilt": chain_ids,
                "chain_expected": expected_chain,
            })
        finally:
            import shutil
            import backend.app.db as dbmod
            dbmod.close_all()
            shutil.rmtree(tmpdir, ignore_errors=True)

    aka_all = sum(r["active_knowledge_accuracy"] for r in results) / len(results) if results else 0.0
    eca_all = sum(r["evolution_chain_accuracy"] for r in results) / len(results) if results else 0.0
    return {
        "meta": {
            "benchmark": "TKE",
            "note": "Active Knowledge Accuracy=as-of(truth)正确率;Evolution Chain Accuracy=链重建全对率。真实写路径,每场景独立临时库。",
        },
        "scenarios": results,
        "summary": {
            "active_knowledge_accuracy": round(aka_all, 4),
            "evolution_chain_accuracy": round(eca_all, 4),
        },
    }


def render_report(data: dict) -> str:
    lines = [
        "# TKE Benchmark Report",
        "",
        f"Active Knowledge Accuracy (as-of/truth): **{data['summary']['active_knowledge_accuracy']:.2%}**",
        f"Evolution Chain Accuracy: **{data['summary']['evolution_chain_accuracy']:.2%}**",
        "",
        "| 场景 | Active Knowledge Acc | Evolution Chain Acc |",
        "|---|---|---|",
    ]
    for r in data["scenarios"]:
        lines.append(
            f"| {r['scenario']}({r['desc']}) | {r['active_knowledge_accuracy']:.2%} "
            f"| {r['evolution_chain_accuracy']:.2%} |"
        )
    lines += [
        "",
        "## 复现",
        "",
        "```bash",
        "PYTHONPATH=. python scripts/bench_tke.py",
        "```",
        "",
        "原始逐采样判定见 `reports/tke_benchmark.json`。",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    data = run_benchmark()
    out_dir = _REPO / "reports"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "tke_benchmark.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "tke_benchmark_report.md").write_text(
        render_report(data), encoding="utf-8"
    )
    print(f"Active Knowledge Accuracy: {data['summary']['active_knowledge_accuracy']:.2%}")
    print(f"Evolution Chain Accuracy:  {data['summary']['evolution_chain_accuracy']:.2%}")
    print("报告: reports/tke_benchmark_report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
