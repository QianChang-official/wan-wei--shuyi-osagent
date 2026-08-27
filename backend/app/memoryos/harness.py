"""MEB / MHEB 评测 harness —— 记忆体验基准的可运行实现。

规范来源：``AI优化/MemoryOS-BenchmarkHarness.md`` + ``MemoryOS-白皮书结构.md`` 第 5 章

一处重要的设计选择：断言对象是「召回的记忆」，不是「LLM 的回答」
------------------------------------------------------------------
规范骨架里的 harness 接口是 ``query(question) -> {"text": 回答}``，断言
``must_contain`` 匹配的是模型回答文本。本项目**不能**这么做，原因有两条：

1. 工程上：模型网关默认未配置，``_chat_complete`` 会如实返回
   ``provider_error``（issue #45 已明确删掉 local_mock 回退）。基于回答文本的
   断言在离线 CI 里根本跑不起来，或者只能靠 mock 回答——那测的是 mock，不是记忆。
2. 概念上：按 ``MemoryOS-IQMQ双轴框架.md`` 的划分，MQ 测的是
   「写入精度 / 检索效率 / 更新正确性 / 遗忘可控性 / 安全治理」，这五项**全都
   不需要 LLM**。把 LLM 回答混进断言，等于用 IQ 的噪声污染 MQ 的测量。

因此断言匹配的是**召回胶囊内容的拼接文本 + 治理元数据**。这是有意为之的口径，
不是简化：它让分数纯粹反映记忆层的表现，且完全可离线复现。

用例 schema（step 序列，规范 §2.1 的扩展）
-------------------------------------------
规范原 schema 是 ``setup`` / ``queries`` / ``negative_cases`` 三段式，表达不了
「写 → 查 → 改写 → 再查」这类交错流程，而 conflict_update 与 forgetting 两类
本质上就需要交错。这里改成 step 序列，``must_contain`` / ``must_not_contain``
等字段名沿用规范原名::

    {
      "case_id": "MEB-PREF-001",
      "category": "preference_extraction",
      "weight_dimension": "ux",
      "title": "...",
      "steps": [
        {"op": "write",  "capsule": {...}, "expect": {"policy_result": "allow"}},
        {"op": "search", "query": "...",
         "expect": {"must_contain": ["美式"], "must_not_contain": ["拿铁"],
                    "relevant_refs": [0]}},
        {"op": "forget", "capsule_ref": 0, "expect": {"deletion_complete": true}},
        {"op": "transition", "capsule_ref": 0, "to_state": "active",
         "expect": {"illegal": true}}
      ]
    }

``capsule_ref`` 是本 case 内**先前 write step 的序号**（从 0 计），因为 capsule_id
是运行时生成的，用例里写不出来。

``relevant_refs`` 是该次检索的相关性标注，用于算 precision@5 / recall@5。
只有声明了它的 step 才参与精度统计；**没有任何用例声明时，报告里的
precision@5 如实为 ``null``**，不用占位值充数。
"""

from __future__ import annotations

import json
import hashlib
import logging
import math
import os
import platform as platform_module
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from ..utils.datetime_utils import utc_now, utc_now_iso_compact
from . import accounting, governance, health
from .report_contract import CATEGORIES, DIMENSIONS, MHEB_WEIGHTS, score_report_validation_error

logger = logging.getLogger(__name__)

_HERE = Path(__file__).resolve().parent
PUBLIC_CASES_DIR = _HERE / "cases" / "public"
REPORTS_DIR = _HERE.parents[2] / "reports"

# The public case corpus is intentionally small and versioned with the runner.
# Keep the suite contract in one place so CI, the report, and the UI cannot
# silently drift apart when a case is added or loses its ``mini`` tag.
PUBLIC_SUITE_EXPECTED_CASES: dict[str, int] = {"mini": 14, "full": 20}
RUNNER_VERSION = "meb-harness-1.1"

#: 隐藏集目录。仓库内**不含**隐藏用例（否则就不隐藏了），通过环境变量指向
#: 外部目录加载。未配置时套件只跑公开集，报告里如实标注 ``hidden_cases: 0``。
HIDDEN_CASES_ENV = "WANWEI_MEB_HIDDEN_DIR"

#: 类别 → MHEB 加权维度的默认映射。用例可用 ``weight_dimension`` 覆盖。
DEFAULT_DIMENSION_BY_CATEGORY: dict[str, str] = {
    "preference_extraction": "ux",
    "knowledge_recall": "ux",
    "conflict_update": "product",
    "forgetting": "safety",
    "poisoning": "safety",
}


def _case_manifest_sha256() -> str:
    """Hash the ordered public corpus, including paths and bytes.

    This is deliberately independent of the generated report directory.  A
    report can therefore identify the exact benchmark inputs without hashing
    itself (which would be self-referential).
    """
    digest = hashlib.sha256()
    for path in sorted(PUBLIC_CASES_DIR.glob("*.json")):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _source_tree_sha256() -> str:
    """Hash the runner and case corpus for reproducible evidence metadata."""
    digest = hashlib.sha256()
    source_files = [
        *_HERE.glob("*.py"),
        *PUBLIC_CASES_DIR.glob("*.json"),
    ]
    for path in sorted(source_files, key=lambda item: item.as_posix()):
        digest.update(path.relative_to(_HERE.parents[2]).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _evaluation_metadata(*, suite: str, hidden_count: int, total_cases: int) -> dict[str, Any]:
    """Return honest, machine-readable provenance for a benchmark run."""
    configured_revision = os.getenv("WANWEI_SOURCE_REVISION", "").strip()
    source_revision = configured_revision or "working-tree"
    return {
        "kind": "internal_memory_layer_regression",
        "runner_version": RUNNER_VERSION,
        "source_revision": source_revision,
        # A source-tree hash identifies the bytes used by this run, but it is
        # not a release/commit identifier. Keep that distinction explicit so
        # a local working-tree result cannot be presented as a pinned build.
        "source_revision_pinned": bool(
            configured_revision and configured_revision != "working-tree"
        ),
        "source_revision_source": (
            "env:WANWEI_SOURCE_REVISION" if configured_revision else "default:working-tree"
        ),
        "source_tree_sha256": os.getenv("WANWEI_SOURCE_TREE_SHA256") or _source_tree_sha256(),
        "case_manifest_sha256": _case_manifest_sha256(),
        "suite_contract": {
            "suite": suite,
            "expected_public_cases": PUBLIC_SUITE_EXPECTED_CASES.get(suite),
            "actual_cases_in_report": total_cases - hidden_count,
            "hidden_cases": hidden_count,
        },
        "environment": {
            "python": platform_module.python_version(),
            "platform": platform_module.platform(),
            "architecture": platform_module.machine(),
            "sqlite": sqlite3.sqlite_version,
            "execution": "in_process",
        },
        "seed": os.getenv("WANWEI_MEB_SEED") or None,
        "reproducibility": (
            "deterministic case runner; no model-generated answer is used"
        ),
        "limitations": [
            "source_revision defaults to working-tree unless WANWEI_SOURCE_REVISION is set; this is not a pinned git revision.",
            "source_tree_sha256 identifies the measured runner/case bytes but does not prove a signed release.",
            "environment and latency describe the local in-process run; HTTP, model generation, and remote Kylin/native SDK time are excluded.",
        ],
    }


class AssertionFailure(Exception):
    """单个 step 断言失败。携带可读原因，直接进 failures 列表。"""


# ---------------------------------------------------------------------------
# 被测系统适配器
# ---------------------------------------------------------------------------


class InProcessHarness:
    """直接调用 runtime 函数的适配器（不走 HTTP，可在 pytest 内跑完）。

    刻意不经过 FastAPI：HTTP 层测的是路由与鉴权，那有独立的端点测试；
    这里要测的是记忆层本身，少一层就少一处失败归因的歧义。
    """

    def __init__(self, *, owner_id: str | None = None, soul_id: str | None = None):
        self.owner_id = owner_id
        self.soul_id = soul_id

    def write(self, capsule: dict[str, Any]) -> dict[str, Any]:
        from ..memory_runtime.capsule_store import write_capsule

        payload = dict(capsule)
        payload.setdefault("memory_class", "knowledge")
        payload.setdefault("source_type", "eval")
        if self.owner_id:
            payload["owner_id"] = self.owner_id
        if self.soul_id:
            payload["soul_id"] = self.soul_id
        return write_capsule(**payload)

    def search(self, query: str, *, top_k: int = 5, high_risk: bool = False) -> dict[str, Any]:
        from ..memory_runtime.retrieval import search_capsules_with_status

        results, status = search_capsules_with_status(
            query, top_k=top_k, high_risk=high_risk,
            owner_id=self.owner_id, soul_id=self.soul_id,
            with_trace=True,
        )
        return {"results": results, "status": status, "trace": status.get("trace")}

    def forget(self, capsule_id: str, *, mode: str = "soft_delete") -> dict[str, Any]:
        from ..memory_runtime.capsule_store import forget_capsules

        return forget_capsules(
            [capsule_id], mode=mode, owner_id=self.owner_id, soul_id=self.soul_id,
        )

    def transition(self, capsule_id: str, to_state: str, reason: str) -> dict[str, Any]:
        from .lifecycle import apply_transition

        return apply_transition(
            capsule_id, to_state, reason,
            actor="eval", owner_id=self.owner_id, soul_id=self.soul_id,
        )

    def confirm(self, capsule_id: str) -> dict[str, Any]:
        from .lifecycle import confirm_candidate

        return confirm_candidate(
            capsule_id, actor="eval", owner_id=self.owner_id, soul_id=self.soul_id,
        )

    def resolve_conflict(self, winner_id: str, loser_id: str, reason: str) -> dict[str, Any]:
        from .lifecycle import resolve_conflict

        return resolve_conflict(
            winner_id, loser_id, reason,
            actor="eval", owner_id=self.owner_id, soul_id=self.soul_id,
        )

    def verify_deletion(self, capsule_id: str) -> dict[str, Any]:
        return governance.verify_deletion(capsule_id)


# ---------------------------------------------------------------------------
# 用例加载
# ---------------------------------------------------------------------------


def load_cases(*, suite: str = "mini", include_hidden: bool = True) -> tuple[list[dict], int]:
    """加载用例集。返回 ``(用例列表, 隐藏用例数)``。

    ``suite``: ``mini`` 只取标了 ``mini`` 标签的核心用例（每 PR 跑）；
    ``full`` 取公开集全部（每日跑）；``redteam`` 只取 safety 维度用例（每周跑）。
    """
    cases: list[dict] = []
    for path in sorted(PUBLIC_CASES_DIR.glob("*.json")):
        cases.extend(_load_case_file(path))

    hidden_dir = os.environ.get(HIDDEN_CASES_ENV, "").strip()
    if include_hidden and hidden_dir:
        hidden_path = Path(hidden_dir)
        if hidden_path.is_dir():
            for path in sorted(hidden_path.glob("*.json")):
                loaded = _load_case_file(path)
                for case in loaded:
                    case["_hidden"] = True
                cases.extend(loaded)

    if suite == "mini":
        cases = [case for case in cases if "mini" in (case.get("tags") or [])]
    elif suite == "redteam":
        cases = [case for case in cases if _dimension_of(case) == "safety"]
    # Count only hidden cases selected by this suite.  A hidden knowledge case
    # must not inflate the mini suite's hidden count when it lacks the ``mini``
    # tag (and redteam has the same dimension-selection rule).
    hidden_count = sum(1 for case in cases if case.get("_hidden"))
    return cases, hidden_count


def _load_case_file(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, list) else [payload]


def _dimension_of(case: dict) -> str:
    explicit = case.get("weight_dimension")
    if explicit in DIMENSIONS:
        return explicit
    return DEFAULT_DIMENSION_BY_CATEGORY.get(case.get("category", ""), "product")


# ---------------------------------------------------------------------------
# step 执行与断言
# ---------------------------------------------------------------------------


def _retrieved_text(results: list[dict[str, Any]]) -> str:
    """召回胶囊内容的拼接文本 —— 断言的匹配对象（见模块 docstring）。"""
    return "\n".join(
        json.dumps(item.get("content") or {}, ensure_ascii=False) for item in results
    )


def _assert_search(step: dict, response: dict, written: list[dict]) -> dict[str, Any]:
    expect = step.get("expect") or {}
    results = response["results"]
    text = _retrieved_text(results)
    retrieved_ids = [item["capsule_id"] for item in results]

    for needle in expect.get("must_contain", []):
        if needle not in text:
            raise AssertionFailure(
                f"must_contain 未命中: {needle!r}（召回 {len(results)} 条）"
            )
    for needle in expect.get("must_not_contain", []):
        if needle in text:
            raise AssertionFailure(f"must_not_contain 泄漏: {needle!r}")
    if "min_hits" in expect and len(results) < expect["min_hits"]:
        raise AssertionFailure(f"召回条数 {len(results)} < min_hits {expect['min_hits']}")
    if "max_hits" in expect and len(results) > expect["max_hits"]:
        raise AssertionFailure(f"召回条数 {len(results)} > max_hits {expect['max_hits']}")

    for ref in expect.get("must_retrieve_refs", []):
        expected_id = written[ref]["capsule_id"]
        if expected_id not in retrieved_ids:
            raise AssertionFailure(f"应召回 ref#{ref} ({expected_id}) 但未出现在结果中")
    for ref in expect.get("must_not_retrieve_refs", []):
        expected_id = written[ref]["capsule_id"]
        if expected_id in retrieved_ids:
            raise AssertionFailure(f"不应召回 ref#{ref} ({expected_id}) 但出现了")

    # 相关性标注 → precision/recall 统计（只有声明了才参与）
    precision_sample = None
    if "relevant_refs" in expect:
        relevant = {written[ref]["capsule_id"] for ref in expect["relevant_refs"]}
        top5 = retrieved_ids[:5]
        hits = len(set(top5) & relevant)
        precision_sample = {
            "precision": hits / len(top5) if top5 else 0.0,
            "recall": hits / len(relevant) if relevant else 0.0,
        }
    return {"retrieved": retrieved_ids, "precision_sample": precision_sample,
            "trace": response.get("trace")}


def _assert_write(step: dict, result: dict) -> None:
    expect = step.get("expect") or {}
    if "policy_result" in expect:
        actual = result["governance"]["policy_result"]
        if actual != expect["policy_result"]:
            raise AssertionFailure(
                f"policy_result 期望 {expect['policy_result']!r} 实际 {actual!r}"
            )
    if "lifecycle" in expect:
        actual = result["state"]["lifecycle"]
        if actual != expect["lifecycle"]:
            raise AssertionFailure(
                f"lifecycle 期望 {expect['lifecycle']!r} 实际 {actual!r}"
            )
    if "risk_tags_include" in expect:
        tags = result["governance"].get("risk_tags") or []
        for tag in expect["risk_tags_include"]:
            if tag not in tags:
                raise AssertionFailure(f"risk_tags 缺少 {tag!r}，实际 {tags}")


def _run_step(
    step: dict,
    harness: InProcessHarness,
    written: list[dict],
    collected: dict[str, Any],
) -> None:
    op = step.get("op")
    if op == "write":
        result = harness.write(step["capsule"])
        written.append(result)
        _assert_write(step, result)
    elif op == "search":
        response = harness.search(
            step["query"],
            top_k=step.get("top_k", 5),
            high_risk=step.get("high_risk", False),
        )
        outcome = _assert_search(step, response, written)
        if outcome["precision_sample"]:
            collected["precision_samples"].append(outcome["precision_sample"])
        if outcome["trace"]:
            collected["traces"].append(outcome["trace"])
    elif op == "forget":
        capsule_id = written[step["capsule_ref"]]["capsule_id"]
        result = harness.forget(capsule_id, mode=step.get("mode", "soft_delete"))
        expect = step.get("expect") or {}
        if expect.get("deletion_complete"):
            verdict = harness.verify_deletion(capsule_id)
            if not verdict["complete"]:
                raise AssertionFailure(
                    f"删除不完整: residue={verdict['residue']} "
                    f"pending={verdict['vector_pending']}"
                )
            collected["deletion_checks"].append(verdict)
        if "deleted_count" in expect and len(result["deleted_capsule_ids"]) != expect["deleted_count"]:
            raise AssertionFailure(
                f"删除条数期望 {expect['deleted_count']} 实际 {len(result['deleted_capsule_ids'])}"
            )
    elif op == "transition":
        from .lifecycle import IllegalTransitionError

        capsule_id = written[step["capsule_ref"]]["capsule_id"]
        expect = step.get("expect") or {}
        if expect.get("illegal"):
            try:
                harness.transition(capsule_id, step["to_state"], step.get("reason", "eval"))
            except IllegalTransitionError:
                return
            raise AssertionFailure(
                f"期望非法转移被拒绝，但 {step['to_state']} 竟然成功了"
            )
        result = harness.transition(capsule_id, step["to_state"], step.get("reason", "eval"))
        if "to_state" in expect and result["to_state"] != expect["to_state"]:
            raise AssertionFailure(f"转移后状态 {result['to_state']} != {expect['to_state']}")
    elif op == "confirm":
        harness.confirm(written[step["capsule_ref"]]["capsule_id"])
    elif op == "resolve_conflict":
        harness.resolve_conflict(
            written[step["winner_ref"]]["capsule_id"],
            written[step["loser_ref"]]["capsule_id"],
            step.get("reason", "eval"),
        )
    else:
        raise AssertionFailure(f"未知 step op: {op!r}")


def run_case(case: dict, *, harness: InProcessHarness | None = None) -> dict[str, Any]:
    """跑单个用例。返回结果 + 收集到的 trace / 精度样本。

    未显式传 harness 时，为本 case 分配一个**独立 owner 作用域**
    （``meb::{case_id}``）。同一次套件运行共用一个数据库，若不隔离，
    A 用例写入的记忆会污染 B 用例的 ``must_not_contain`` 断言，用例结果就
    依赖执行顺序了。走 owner 作用域隔离而不是每例重建库，是因为作用域过滤
    本身也是被测能力之一（跨属主不可见）。
    """
    harness = harness or InProcessHarness(owner_id=f"meb::{case['case_id']}")
    written: list[dict] = []
    collected: dict[str, Any] = {"precision_samples": [], "traces": [], "deletion_checks": []}
    started = time.monotonic()
    passed, reason, failed_step = True, "", None
    for index, step in enumerate(case.get("steps") or []):
        try:
            _run_step(step, harness, written, collected)
        except AssertionFailure as exc:
            passed, reason, failed_step = False, str(exc), index
            break
        except Exception as exc:  # 用例本身写错 / runtime 异常，都算失败但要能区分
            passed = False
            reason = f"{type(exc).__name__}: {exc}"
            failed_step = index
            break
    return {
        "case_id": case["case_id"],
        "category": case.get("category"),
        "dimension": _dimension_of(case),
        "title": case.get("title", ""),
        "passed": passed,
        "reason": reason,
        "failed_step": failed_step,
        "steps_run": len(case.get("steps") or []) if passed else (failed_step or 0) + 1,
        "hidden": bool(case.get("_hidden")),
        "latency_ms": round((time.monotonic() - started) * 1000, 2),
        "collected": collected,
    }


# ---------------------------------------------------------------------------
# 套件执行与报告
# ---------------------------------------------------------------------------


def _aggregate_precision(
    results: list[dict], *, category: str | None = None,
) -> tuple[float | None, float | None]:
    """聚合 precision@5 / recall@5。**无相关性标注时返回 (None, None)**。"""
    samples = [
        sample
        for result in results
        if category is None or result.get("category") == category
        for sample in result["collected"]["precision_samples"]
    ]
    if not samples:
        return None, None
    precision = sum(item["precision"] for item in samples) / len(samples)
    recall = sum(item["recall"] for item in samples) / len(samples)
    return round(precision, 4), round(recall, 4)


def _category_rate(results: list[dict], category: str) -> tuple[float | None, int]:
    subset = [item for item in results if item.get("category") == category]
    if not subset:
        return None, 0
    return round(sum(1 for item in subset if item["passed"]) / len(subset), 4), len(subset)


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1))
    return round(ordered[index], 2)


def _competition_metrics(
    results: list[dict], *, suite: str, hidden_count: int,
) -> dict[str, Any]:
    """Build transparent competition-facing metrics without inventing scores."""
    preference_accuracy, preference_cases = _category_rate(results, "preference_extraction")
    conflict_correctness, conflict_cases = _category_rate(results, "conflict_update")
    knowledge_case_rate, knowledge_cases = _category_rate(results, "knowledge_recall")
    _, knowledge_recall = _aggregate_precision(results, category="knowledge_recall")
    trace_latencies = [
        trace.get("latency_ms")
        for result in results
        for trace in result["collected"]["traces"]
        if isinstance(trace.get("latency_ms"), (int, float))
    ]
    return {
        "schema_version": "1.0",
        "official": False,
        "source": "MEB public cases in this repository",
        "suite": suite,
        "public_cases": max(0, len(results) - hidden_count),
        "hidden_cases": hidden_count,
        "preference_extraction_accuracy": preference_accuracy,
        "knowledge_recall": knowledge_recall,
        "conflict_correctness": conflict_correctness,
        "retrieval_latency_p95_ms": _p95(trace_latencies),
        "sample_counts": {
            "preference_extraction": preference_cases,
            "knowledge_recall": knowledge_cases,
            "knowledge_recall_queries": sum(
                1 for result in results
                if result.get("category") == "knowledge_recall"
                for _ in result["collected"]["precision_samples"]
            ),
            "conflict_update": conflict_cases,
            "retrieval_traces": len(trace_latencies),
        },
        "case_pass_rates": {
            "preference_extraction": preference_accuracy,
            "knowledge_recall": knowledge_case_rate,
            "conflict_update": conflict_correctness,
        },
        "metric_definitions": {
            "preference_extraction_accuracy": (
                "category case-pass rate; not field-level extraction precision/recall/F1"
            ),
            "knowledge_recall": (
                "mean Recall@5 over search steps declaring relevant_refs"
            ),
            "conflict_correctness": (
                "category case-pass rate for conflict lifecycle assertions"
            ),
            "retrieval_latency_p95_ms": (
                "p95 of recorded in-process retrieval trace latency"
            ),
        },
        # Targets remain explicitly unconfigured until the current official
        # challenge notice is attached to the submission evidence package.
        "targets": {
            "preference_extraction_accuracy": None,
            "knowledge_recall": None,
            "conflict_correctness": None,
            "retrieval_latency_p95_ms": None,
        },
        "limitations": [
            "公开样例为仓库自建 MEB cases，不等同于官方隐藏集成绩。",
            "knowledge_recall 使用带 relevant_refs 的知识检索步骤计算 Recall@5。",
            "延迟来自本地 harness 的 retrieval trace，未代表麒麟物理机或跨架构实测。",
        ],
    }


def build_report(
    results: list[dict],
    *,
    suite: str,
    hidden_count: int,
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> dict[str, Any]:
    """按规范 §2.4 组装 score_report，含 economics 与 health 两段。"""
    total = len(results)
    passed = sum(1 for item in results if item["passed"])

    by_dimension: dict[str, dict[str, int]] = {dim: {"passed": 0, "total": 0} for dim in DIMENSIONS}
    for item in results:
        bucket = by_dimension[item["dimension"]]
        bucket["total"] += 1
        bucket["passed"] += 1 if item["passed"] else 0

    scores: dict[str, Any] = {}
    weighted_sum = 0.0
    weight_used = 0.0
    for dimension in DIMENSIONS:
        bucket = by_dimension[dimension]
        if bucket["total"] == 0:
            # 该维度没有用例 → 如实为 null，不按 0 也不按 1 计入
            scores[dimension] = None
            continue
        rate = bucket["passed"] / bucket["total"]
        scores[dimension] = round(rate, 4)
        weighted_sum += MHEB_WEIGHTS[dimension] * rate
        weight_used += MHEB_WEIGHTS[dimension]
    # 只按实际有用例的维度归一化，避免缺维度时综合分被无声压低
    scores["mheb_overall"] = round(weighted_sum / weight_used, 4) if weight_used else 0.0

    precision, recall = _aggregate_precision(results)
    scores["retrieval_precision_at_5"] = precision
    scores["retrieval_recall_at_5"] = recall

    breakdown: dict[str, dict[str, Any]] = {}
    for category in CATEGORIES:
        subset = [item for item in results if item["category"] == category]
        if not subset:
            continue
        category_passed = sum(1 for item in subset if item["passed"])
        breakdown[category] = {
            "passed": category_passed,
            "total": len(subset),
            "rate": round(category_passed / len(subset), 4),
        }

    traces = [trace for item in results for trace in item["collected"]["traces"]]
    deletion_checks = [
        check for item in results for check in item["collected"]["deletion_checks"]
    ]

    return {
        "benchmark": "MEB",
        "suite": suite,
        "run_id": f"run_{utc_now().strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:6]}",
        "timestamp": utc_now_iso_compact(),
        "evaluation": _evaluation_metadata(
            suite=suite, hidden_count=hidden_count, total_cases=total,
        ),
        "summary": {
            "total_cases": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": round(passed / max(total, 1), 4),
            "hidden_cases": hidden_count,
            "public_cases": total - hidden_count,
        },
        "weights": dict(MHEB_WEIGHTS),
        "scores": scores,
        "dimension_breakdown": by_dimension,
        "category_breakdown": breakdown,
        "competition_metrics": _competition_metrics(
            results, suite=suite, hidden_count=hidden_count,
        ),
        "failures": [
            {
                "case_id": item["case_id"],
                "category": item["category"],
                "reason": item["reason"],
                "failed_step": item["failed_step"],
            }
            for item in results
            if not item["passed"]
        ],
        "economics": accounting.summary(owner_id=owner_id, soul_id=soul_id),
        # 把本轮刚算出的精度传给 health，而不是让它去读磁盘上一轮的旧报告——
        # 否则同一份报告里 scores 段有精度、health 段说「未测量」，自相矛盾。
        "health": health.health_report(
            owner_id=owner_id,
            soul_id=soul_id,
            precision_override=(
                precision,
                "measured: current MEB run" if precision is not None
                else "unavailable: 本轮用例未提供相关性标注",
            ),
        ),
        "governance": {
            "ledger": governance.ledger_summary(owner_id=owner_id),
            "release_gate": governance.release_gate(),
            "deletion_checks": len(deletion_checks),
            "deletion_all_complete": all(check["complete"] for check in deletion_checks)
            if deletion_checks else None,
        },
        "traces": {
            "count": len(traces),
            "avg_latency_ms": round(sum(t["latency_ms"] for t in traces) / len(traces), 2)
            if traces else None,
            "avg_injected_tokens": round(
                sum(t["injected_tokens"] for t in traces) / len(traces), 2
            ) if traces else None,
        },
        "honesty_notes": [
            "断言对象是召回记忆内容而非 LLM 回答（见 harness 模块 docstring）——"
            "本报告测量 MQ（记忆治理效能），不测 IQ（推理能力）。",
            "成本金额基于 token 估算（字符数 × 0.3）而非实测用量，仅供相对比较。",
            "precision@5 为 null 表示用例集未提供相关性标注，不代表召回精度为 0。",
        ],
    }


def run_suite(
    *,
    suite: str = "mini",
    output_dir: Path | None = None,
    harness: InProcessHarness | None = None,
    write_report: bool = True,
    save_traces: bool = False,
) -> dict[str, Any]:
    """跑一个套件并（可选）落盘 ``meb_score_report.json``。

    Raises:
        RuntimeError: 生成的报告不满足 :mod:`report_contract` —— 宁可在产出时
            失败，也不要把一份字段缺失的报告喂给 CI 门禁和控制台。
    """
    cases, hidden_count = load_cases(suite=suite)
    expected_public = PUBLIC_SUITE_EXPECTED_CASES.get(suite)
    if expected_public is not None:
        actual_public = len(cases) - hidden_count
        if actual_public != expected_public:
            raise RuntimeError(
                f"{suite} public case manifest drift: expected {expected_public}, "
                f"loaded {actual_public}; update tags or PUBLIC_SUITE_EXPECTED_CASES."
            )
    # 未指定 harness 时按 case 隔离作用域（见 run_case docstring）；
    # 显式传入则整套共用，用于「跨用例记忆积累」这类刻意共享的场景。
    results = [run_case(case, harness=harness) for case in cases]
    scope_owner_id = harness.owner_id if harness else None
    scope_soul_id = harness.soul_id if harness else None
    report = build_report(
        results, suite=suite, hidden_count=hidden_count,
        owner_id=scope_owner_id,
        soul_id=scope_soul_id,
    )
    error = score_report_validation_error(report)
    if error is not None:
        raise RuntimeError(f"generated MEB report violates its own contract: {error}")

    if write_report:
        out_dir = output_dir or REPORTS_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "meb_score_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if save_traces:
            traces = [
                trace for item in results for trace in item["collected"]["traces"]
            ]
            (out_dir / "meb_traces.json").write_text(
                json.dumps(traces, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        # 落一条健康度快照，让每日评测自然积累出趋势曲线（Health 规范 §3.1）。
        # 只在真正产出报告时采样：write_report=False 是 pytest 里的一次性运行，
        # 让它往趋势表里灌数据会把曲线变成「测试跑了几次」的计数器。
        #
        # 只兜住运行时/IO 故障（快照表缺失、库被占用等）——采样失败不该让整轮
        # 评测白跑。但**不兜 NameError/TypeError 这类编码错误**：曾经就是宽
        # except 把一个 NameError 咽成 warning，采样静默失效了整整一轮而评测
        # 照常报「通过」。这类错误必须炸出来。
        try:
            health.record_snapshot(
                owner_id=scope_owner_id, soul_id=scope_soul_id, source=f"meb:{suite}",
                precision_override=(
                    report["scores"]["retrieval_precision_at_5"],
                    f"measured: {report['run_id']}",
                ),
            )
        except (NameError, TypeError, AttributeError):
            raise
        except Exception as exc:  # pragma: no cover - 环境性故障不该让评测失败
            logger.warning("health snapshot skipped: %s: %s", type(exc).__name__, exc)
    return report


def latest_report(*, output_dir: Path | None = None) -> dict[str, Any] | None:
    """读取上次落盘的报告（``GET /memoryos/bench/report`` 用）。"""
    path = (output_dir or REPORTS_DIR) / "meb_score_report.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# 回归基线（规范 §5「pass_rate 下降 >5% 报警」）
#
# 基线**按套件分文件**，不复用单槽的 ``meb_score_report.json``：后者的 suite 取决
# 于最后一次运行是谁（per-PR 写 mini、每日写 full、每周写 redteam），无论提交哪
# 一份，三种流程里至多一种能与之匹配，其余只会「因套件不同而跳过」——门禁看着在
# 跑却从不触发。按套件分文件后，套件不匹配在结构上不可能发生。
#
# 判定逻辑放在包内而不是 CLI 里，是为了让它能被常规 pytest 覆盖：一个悄悄跳过的
# 门禁比没有门禁更危险，因为它让人以为已经防住了，所以它自己也需要测试。
# ---------------------------------------------------------------------------

#: pass_rate 相对基线的默认允许跌幅（5 个百分点）。
DEFAULT_REGRESSION_THRESHOLD = 0.05


def baseline_path(suite: str, *, output_dir: Path | None = None) -> Path:
    return (output_dir or REPORTS_DIR) / f"meb_baseline_{suite}.json"


def write_baseline(report: dict[str, Any], *, output_dir: Path | None = None) -> Path:
    """把本次结果记为该套件的基线。

    只存被比较的指标与出处，不存整份报告——基线的用途是回答「和上次比退步了
    吗」，塞进完整 metrics 只会让 diff 无法一眼看出改了什么。
    """
    path = baseline_path(report["suite"], output_dir=output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "suite": report["suite"],
        "run_id": report["run_id"],
        "timestamp": report["timestamp"],
        "total_cases": report["summary"]["total_cases"],
        "pass_rate": report["summary"]["pass_rate"],
        "mheb_overall": report["scores"]["mheb_overall"],
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def compare_to_baseline(
    report: dict[str, Any],
    *,
    output_dir: Path | None = None,
    threshold: float = DEFAULT_REGRESSION_THRESHOLD,
) -> dict[str, Any]:
    """与本套件基线比较 pass_rate。

    返回 ``{'status': ..., 'ok': bool, 'message': str, ...}``。``status`` 取值：

    - ``ok``          —— 没有退步
    - ``regressed``   —— 跌幅超阈值，调用方应以非零码退出
    - ``no_baseline`` —— 该套件还没有基线（首次运行属正常），**不算失败**，
      但 message 里带上创建命令，不静默放过
    - ``malformed``   —— 基线文件存在但 pass_rate 不是数值，算失败：一份坏基线
      会让门禁永久失效，必须让人看见
    """
    suite = report["suite"]
    path = baseline_path(suite, output_dir=output_dir)
    current = report["summary"]["pass_rate"]
    try:
        baseline = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {
            "status": "no_baseline",
            "ok": True,
            "suite": suite,
            "path": str(path),
            "current_pass_rate": current,
            "baseline_pass_rate": None,
            "message": (
                f"套件 {suite} 无回归基线（{path.name} 不存在或不可读），跳过对比。\n"
                f"  建立基线: python scripts/run_meb.py --suite {suite} --write-baseline"
            ),
        }

    before = baseline.get("pass_rate")
    if not isinstance(before, (int, float)) or isinstance(before, bool):
        return {
            "status": "malformed",
            "ok": False,
            "suite": suite,
            "path": str(path),
            "current_pass_rate": current,
            "baseline_pass_rate": None,
            "message": f"基线 {path.name} 的 pass_rate 不是数值，无法比较",
        }

    # 判定用与展示**同一个已舍入的值**：直接比 before - current 会踩浮点表示，
    # 例如 1.0 - 0.95 = 0.050000000000000044 > 0.05 判成退步，而日志里打印的却是
    # 「下降 5.00%（阈值 5%）」——读日志的人只会以为门禁误报。舍入后两者一致，
    # 且恰好等于阈值不算退步（判定是 drop > threshold）。
    drop = round(before - current, 6)
    regressed = drop > threshold
    return {
        "status": "regressed" if regressed else "ok",
        "ok": not regressed,
        "suite": suite,
        "path": str(path),
        "baseline_run_id": baseline.get("run_id"),
        "baseline_pass_rate": before,
        "current_pass_rate": current,
        "drop": drop,
        "threshold": threshold,
        "message": (
            f"MEB {suite} pass_rate 相对基线下降 {drop:.2%}（阈值 {threshold:.0%}）"
            if regressed
            else f"pass_rate 基线 {before} ({baseline.get('run_id', '?')}) → 本次 {current}"
        ),
    }


__all__ = [
    "DEFAULT_DIMENSION_BY_CATEGORY",
    "DEFAULT_REGRESSION_THRESHOLD",
    "HIDDEN_CASES_ENV",
    "PUBLIC_CASES_DIR",
    "REPORTS_DIR",
    "AssertionFailure",
    "InProcessHarness",
    "baseline_path",
    "build_report",
    "compare_to_baseline",
    "latest_report",
    "load_cases",
    "run_case",
    "run_suite",
    "write_baseline",
]
