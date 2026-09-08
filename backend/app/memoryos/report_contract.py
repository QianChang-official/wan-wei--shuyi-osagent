# Copyright (c) 2026 QianChang-official
#
# 宛委·枢忆 is licensed under Mulan PSL v2.
# You can use this software according to the terms of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
# http://license.coscl.org.cn/MulanPSL2
#
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

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

#: MQ（Memory Quotient）五个子能力 → 承载它的用例类别（规范 IQMQ双轴框架 §10.3）。
#:
#: 这不是新造一套评测，而是给已有的 5 个类别换一个**能力视角**的读法：
#: category_breakdown 回答「这类用例过了几条」，MQ 回答「记忆全生命周期里的哪一环
#: 弱」。两者数据同源，因此不会出现互相矛盾的两个分数。
#:
#: 映射是 1:1 的，这是规范设计如此而非巧合——五类用例本就按记忆生命周期切分。
MQ_SUBSKILLS: dict[str, str] = {
    "write_precision": "preference_extraction",
    "retrieval_efficiency": "knowledge_recall",
    "update_correctness": "conflict_update",
    "forgetting_control": "forgetting",
    "safety_governance": "poisoning",
}

#: MQ 子能力权重。和必须为 1。
#:
#: 安全治理权重最高（0.30）：一条被投毒的记忆造成的损害不与「少记住一条偏好」
#: 对称——前者会让 Agent 主动做错事，后者只是体验差一点。这与 MHEB 里
#: safety 一票否决的取向一致。写入精度权重最低（0.15）：写漏了还能再问一次，
#: 而更新错误与遗忘失控都会留下一条**错误但可被召回**的记忆，更难被发现。
MQ_WEIGHTS: dict[str, float] = {
    "write_precision": 0.15,
    "retrieval_efficiency": 0.20,
    "update_correctness": 0.20,
    "forgetting_control": 0.15,
    "safety_governance": 0.30,
}

_COUNT_FIELDS = ("total_cases", "passed", "failed")
_REQUIRED_RATE_FIELDS = ("pass_rate",)
#: 允许为 ``null`` 的比率字段：没有实测数据时必须如实为空，
#: 不接受用占位数字填满报告（REVIEW.md 把「模拟当实测」列为阻断级问题）。
_NULLABLE_RATE_FIELDS = ("retrieval_precision_at_5", "retrieval_recall_at_5")
#: competition_metrics 里的三张比率。含义各不相同（通过率 vs Recall@5），
#: 但取值域一致：null（未测量）或 [0,1]。
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


def _check_competition_rates(metrics: dict[str, Any]) -> str | None:
    """比率字段（null 表示未测量，如实放行）+ 检索延迟。"""
    for field in _COMPETITION_RATE_FIELDS:
        if not _is_rate(metrics.get(field), allow_null=True):
            return f"invalid_competition_metrics:{field}"
    latency = metrics.get("retrieval_latency_p95_ms")
    if latency is not None and (
        not isinstance(latency, (int, float)) or isinstance(latency, bool) or latency < 0
    ):
        return "invalid_competition_metrics:retrieval_latency_p95_ms"
    return None


def _check_competition_counts(metrics: dict[str, Any]) -> str | None:
    """用例计数与 sample_counts。"""
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
    return None


def _check_competition_targets(metrics: dict[str, Any]) -> str | None:
    """targets 段：未测量可 null，但不得填虚构数字。"""
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
    return None


def _check_competition_tail(metrics: dict[str, Any]) -> str | None:
    """limitations 与 metric_definitions。"""
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


def _competition_metrics_error(metrics: Any) -> str | None:
    """校验 competition_metrics 段。合法返回 ``None``，否则返回稳定错误码。

    这段存在的意义是**口径防伪装**：``official`` 必须是一个显式布尔、schema 必须
    版本化、比率必须落在 [0,1]（或如实为 null）、targets 不得把「未测量的目标」
    填成一个虚构数字。任何一个字段不对，报告就不该被当作可信成绩消费。
    """
    if not isinstance(metrics, dict):
        return "invalid_competition_metrics"
    if metrics.get("schema_version") != "1.0":
        return "invalid_competition_metrics:schema_version"
    if not isinstance(metrics.get("official"), bool):
        return "invalid_competition_metrics:official"
    for field in ("source", "suite"):
        if not isinstance(metrics.get(field), str) or not metrics[field]:
            return f"invalid_competition_metrics:{field}"
    return (
        _check_competition_rates(metrics)
        or _check_competition_counts(metrics)
        or _check_competition_targets(metrics)
        or _check_competition_tail(metrics)
    )


def _check_eval_basic(evaluation: dict[str, Any]) -> str | None:
    """evaluation 的标量溯源字段。"""
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
    return None


def _check_eval_contract(contract: Any, suite: str | None) -> str | None:
    """suite_contract：套件口径必须与报告本体一致。"""
    if not isinstance(contract, dict):
        return "invalid_evaluation_metadata:suite_contract"
    for field in ("suite", "expected_public_cases", "actual_cases_in_report", "hidden_cases"):
        if field not in contract:
            return f"invalid_evaluation_metadata:suite_contract.{field}"
    if not isinstance(contract["suite"], str) or contract["suite"] != suite:
        return "invalid_evaluation_metadata:suite_contract.suite"
    for field in ("expected_public_cases", "actual_cases_in_report", "hidden_cases"):
        value = contract[field]
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
            return f"invalid_evaluation_metadata:suite_contract.{field}"
    return None


def _check_eval_environment(environment: Any) -> str | None:
    """environment：运行环境自述，必须完整可审计。"""
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
    return None


def _evaluation_metadata_error(evaluation: Any, suite: str | None) -> str | None:
    """校验 evaluation（provenance）段。合法返回 ``None``，否则返回稳定错误码。"""
    if not isinstance(evaluation, dict):
        return "invalid_evaluation_metadata"
    limitations = evaluation.get("limitations")
    if limitations is not None and (
        not isinstance(limitations, list)
        or not limitations
        or not all(isinstance(item, str) and item for item in limitations)
    ):
        return "invalid_evaluation_metadata:limitations"
    return (
        _check_eval_basic(evaluation)
        or _check_eval_contract(evaluation.get("suite_contract"), suite)
        or _check_eval_environment(evaluation.get("environment"))
    )


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

    error = _validate_mq(payload.get("mq"))
    if error is not None:
        return error

    if "competition_metrics" in payload:
        competition_error = _competition_metrics_error(payload["competition_metrics"])
        if competition_error is not None:
            return competition_error

    # Provenance 对旧报告是可选的，但只要出现就必须是结构化、可审计的——
    # 否则面板会把一份无从追溯的分数当作当前 runner 的成绩展示。
    evaluation = payload.get("evaluation")
    if evaluation is not None:
        evaluation_error = _evaluation_metadata_error(evaluation, payload.get("suite"))
        if evaluation_error is not None:
            return evaluation_error

    # economics / health 是规范 §5 要求报告必须自带的两段，缺了报告就不完整。
    for field in ("economics", "health"):
        if not isinstance(payload.get(field), dict):
            return f"missing_field:{field}"
    return None


def _validate_mq(mq: object) -> str | None:
    """校验 MQ 段（规范 IQMQ双轴框架 §10.3）。

    两条硬要求：

    1. **未覆盖的子能力必须是 ``null``**，不能是 0。套件没跑到某一环时把它记 0
       会让 MQ 总分被无声压低，读起来像「这项能力很差」，而事实是「没测」。
    2. **``iq`` 必须是 ``null``**。IQ 由所接模型提供，本系统不测量它。留一个可以
       被填成数字的字段，早晚会有人往里塞一个估算值——契约层直接钉死。
    """
    if not isinstance(mq, dict):
        return "missing_field:mq"

    weights = mq.get("weights")
    if not isinstance(weights, dict) or set(weights) != set(MQ_SUBSKILLS):
        return "invalid_mq_weights"
    if round(sum(float(value) for value in weights.values()), 6) != 1.0:
        return "mq_weights_do_not_sum_to_one"

    subskills = mq.get("subskills")
    if not isinstance(subskills, dict) or set(subskills) != set(MQ_SUBSKILLS):
        return "invalid_mq_subskills"
    for name, value in subskills.items():
        if not _is_rate(value, allow_null=True):
            return f"invalid_rate:mq.subskills.{name}"

    if not _is_rate(mq.get("mq_overall"), allow_null=True):
        return "invalid_rate:mq.mq_overall"
    covered = [name for name, value in subskills.items() if value is not None]
    if covered and mq.get("mq_overall") is None:
        return "mq_overall_missing_despite_coverage"
    if not covered and mq.get("mq_overall") is not None:
        return "mq_overall_present_without_coverage"

    uncovered = mq.get("uncovered_subskills")
    if not isinstance(uncovered, list):
        return "missing_field:mq.uncovered_subskills"
    if sorted(uncovered) != sorted(set(MQ_SUBSKILLS) - set(covered)):
        return "mq_uncovered_mismatch"

    # IQ 轴由所接模型决定，本系统不测量——契约层钉死为 null。
    if "iq" not in mq:
        return "missing_field:mq.iq"
    if mq["iq"] is not None:
        return "iq_must_be_null_this_system_does_not_measure_it"
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
