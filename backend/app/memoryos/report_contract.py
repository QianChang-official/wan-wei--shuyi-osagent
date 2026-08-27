"""``meb_score_report.json`` 的校验契约。

与 ``app/memory_arena/metrics_contract.py`` 同款形状与用法（``main()`` 读 stdin、
返回稳定错误码），这样 CI 里两份报告的校验步骤写法一致。

存在意义：报告是给 CI 门禁和控制台消费的。字段缺失或比率越界时，要在**产出时**
就失败，而不是等面板渲染出一个 ``undefined`` 才发现。
"""

from __future__ import annotations

import json
import sys
from typing import Any

#: 五类评测（规范 BenchmarkHarness §2.1 的 category 取值）。
CATEGORIES = (
    "preference_extraction",
    "knowledge_recall",
    "conflict_update",
    "forgetting",
    "poisoning",
)

#: MHEB 四个加权维度（规范 Harm×Economics §3）。
DIMENSIONS = ("ux", "safety", "product", "academic")

#: MHEB 权重。和必须为 1。
MHEB_WEIGHTS: dict[str, float] = {
    "ux": 0.40,
    "safety": 0.25,
    "product": 0.25,
    "academic": 0.10,
}

_COUNT_FIELDS = ("total_cases", "passed", "failed")
_REQUIRED_RATE_FIELDS = ("pass_rate",)
#: 允许为 ``null`` 的比率字段：没有实测数据时必须如实为空，
#: 不接受用占位数字填满报告（REVIEW.md 把「模拟当实测」列为阻断级问题）。
_NULLABLE_RATE_FIELDS = ("retrieval_precision_at_5", "retrieval_recall_at_5")
_COMPETITION_RATE_FIELDS = (
    "preference_extraction_accuracy",
    "knowledge_recall",
    "conflict_correctness",
)


def _is_rate(value: Any, *, allow_null: bool = False) -> bool:
    if allow_null and value is None:
        return True
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and 0 <= value <= 1
    )


def _competition_metrics_error(metrics: Any) -> str | None:
    if not isinstance(metrics, dict):
        return "invalid_competition_metrics"
    if metrics.get("schema_version") != "1.0":
        return "invalid_competition_metrics:schema_version"
    if not isinstance(metrics.get("official"), bool):
        return "invalid_competition_metrics:official"
    for field in ("source", "suite"):
        if not isinstance(metrics.get(field), str) or not metrics[field]:
            return f"invalid_competition_metrics:{field}"
    for field in _COMPETITION_RATE_FIELDS:
        if not _is_rate(metrics.get(field), allow_null=True):
            return f"invalid_competition_metrics:{field}"
    latency = metrics.get("retrieval_latency_p95_ms")
    if latency is not None and (
        not isinstance(latency, (int, float))
        or isinstance(latency, bool)
        or latency < 0
    ):
        return "invalid_competition_metrics:retrieval_latency_p95_ms"
    for count_field in ("public_cases", "hidden_cases"):
        value = metrics.get(count_field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return f"invalid_competition_metrics:{count_field}"
    sample_counts = metrics.get("sample_counts")
    if not isinstance(sample_counts, dict):
        return "invalid_competition_metrics:sample_counts"
    for key, value in sample_counts.items():
        if not isinstance(key, str) or not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return "invalid_competition_metrics:sample_counts"
    targets = metrics.get("targets")
    if not isinstance(targets, dict):
        return "invalid_competition_metrics:targets"
    for field in (*_COMPETITION_RATE_FIELDS, "retrieval_latency_p95_ms"):
        value = targets.get(field)
        if value is not None and (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or value < 0
            or (field in _COMPETITION_RATE_FIELDS and value > 1)
        ):
            return f"invalid_competition_metrics:targets.{field}"
    limitations = metrics.get("limitations")
    if not isinstance(limitations, list) or not all(isinstance(item, str) for item in limitations):
        return "invalid_competition_metrics:limitations"
    definitions = metrics.get("metric_definitions")
    if definitions is not None and (
        not isinstance(definitions, dict)
        or not definitions
        or not all(isinstance(key, str) and isinstance(value, str) and value for key, value in definitions.items())
    ):
        return "invalid_competition_metrics:metric_definitions"
    return None


def score_report_validation_error(payload: object) -> str | None:
    """校验 MEB 报告。合法返回 ``None``，否则返回稳定错误码。"""
    if not isinstance(payload, dict):
        return "expected_object"

    for field in ("benchmark", "run_id", "timestamp", "suite"):
        if not isinstance(payload.get(field), str) or not payload[field]:
            return f"missing_field:{field}"

    summary = payload.get("summary")
    if not isinstance(summary, dict):
        return "missing_field:summary"
    for field in _COUNT_FIELDS:
        value = summary.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return f"invalid_count:summary.{field}"
    if summary["passed"] + summary["failed"] != summary["total_cases"]:
        return "summary_counts_mismatch"
    for field in _REQUIRED_RATE_FIELDS:
        if not _is_rate(summary.get(field)):
            return f"invalid_rate:summary.{field}"
    expected_pass_rate = round(summary["passed"] / max(summary["total_cases"], 1), 4)
    if round(float(summary["pass_rate"]), 4) != expected_pass_rate:
        return "pass_rate_mismatch"

    weights = payload.get("weights")
    if not isinstance(weights, dict) or set(weights) != set(DIMENSIONS):
        return "invalid_weights"
    if round(sum(float(value) for value in weights.values()), 6) != 1.0:
        return "weights_do_not_sum_to_one"

    scores = payload.get("scores")
    if not isinstance(scores, dict):
        return "missing_field:scores"
    for dimension in DIMENSIONS:
        if not _is_rate(scores.get(dimension), allow_null=True):
            return f"invalid_rate:scores.{dimension}"
    if not _is_rate(scores.get("mheb_overall")):
        return "invalid_rate:scores.mheb_overall"
    for field in _NULLABLE_RATE_FIELDS:
        if not _is_rate(scores.get(field), allow_null=True):
            return f"invalid_rate:scores.{field}"

    breakdown = payload.get("category_breakdown")
    if not isinstance(breakdown, dict):
        return "missing_field:category_breakdown"
    for category, stats in breakdown.items():
        if category not in CATEGORIES:
            return f"unknown_category:{category}"
        if not isinstance(stats, dict):
            return f"invalid_category_stats:{category}"
        for field in ("passed", "total"):
            value = stats.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                return f"invalid_count:category_breakdown.{category}.{field}"
        if stats["passed"] > stats["total"]:
            return f"category_passed_exceeds_total:{category}"
        if not _is_rate(stats.get("rate")):
            return f"invalid_rate:category_breakdown.{category}.rate"

    if not isinstance(payload.get("failures"), list):
        return "missing_field:failures"
    if len(payload["failures"]) != summary["failed"]:
        return "failures_length_mismatch"

    if "competition_metrics" in payload:
        competition_error = _competition_metrics_error(payload["competition_metrics"])
        if competition_error is not None:
            return competition_error

    # Provenance is optional for legacy reports, but when present it must be
    # structured.  This keeps the dashboard from presenting an untraceable
    # score as if it came from the current runner.
    evaluation = payload.get("evaluation")
    if evaluation is not None:
        if not isinstance(evaluation, dict):
            return "invalid_evaluation_metadata"
        for field in ("kind", "runner_version", "source_revision", "source_tree_sha256", "case_manifest_sha256"):
            if not isinstance(evaluation.get(field), str) or not evaluation[field]:
                return f"invalid_evaluation_metadata:{field}"
        for field in ("source_revision_pinned",):
            if field in evaluation and not isinstance(evaluation[field], bool):
                return f"invalid_evaluation_metadata:{field}"
        for field in ("source_revision_source",):
            if field in evaluation and (
                not isinstance(evaluation[field], str) or not evaluation[field]
            ):
                return f"invalid_evaluation_metadata:{field}"
        contract = evaluation.get("suite_contract")
        if not isinstance(contract, dict):
            return "invalid_evaluation_metadata:suite_contract"
        for field in ("suite", "expected_public_cases", "actual_cases_in_report", "hidden_cases"):
            if field not in contract:
                return f"invalid_evaluation_metadata:suite_contract.{field}"
        if not isinstance(contract["suite"], str) or contract["suite"] != payload.get("suite"):
            return "invalid_evaluation_metadata:suite_contract.suite"
        for field in ("expected_public_cases", "actual_cases_in_report", "hidden_cases"):
            value = contract[field]
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
                return f"invalid_evaluation_metadata:suite_contract.{field}"
        environment = evaluation.get("environment")
        if not isinstance(environment, dict) or not all(
            isinstance(environment.get(field), str) and environment[field]
            for field in ("python", "platform", "sqlite")
        ):
            return "invalid_evaluation_metadata:environment"
        for field in ("architecture", "execution"):
            if field in environment and (
                not isinstance(environment[field], str) or not environment[field]
            ):
                return f"invalid_evaluation_metadata:environment.{field}"
        limitations = evaluation.get("limitations")
        if limitations is not None and (
            not isinstance(limitations, list)
            or not limitations
            or not all(isinstance(item, str) and item for item in limitations)
        ):
            return "invalid_evaluation_metadata:limitations"

    # economics / health 是规范 §5 要求报告必须自带的两段，缺了报告就不完整。
    for field in ("economics", "health"):
        if not isinstance(payload.get(field), dict):
            return f"missing_field:{field}"
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"MEB score report JSON could not be loaded: {exc}", file=sys.stderr)
        return 2
    error = score_report_validation_error(payload)
    if error is not None:
        print(f"MEB score report contract failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
