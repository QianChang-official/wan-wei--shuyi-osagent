"""memory_arena 模块测试 — metrics_contract 契约校验 + runner 纯函数。

覆盖:
1. arena_metrics_validation_error — 有效/无效 payload 的全部错误码路径
2. _is_rate — bool 拒绝、边界值、pending 语义
3. compute_metrics — 空输入、全通过、部分失败、unsafe 断言、pending 字段
4. runner 断言助手 — _add_assertion / _append_write_assertions / _append_tier_assertions

设计说明:
- metrics_contract 是 desktop 打包门禁与 Arena API 共享的契约,字段漂移必须报警
- compute_metrics 的 rate 字段语义(pending vs 数值)直接影响 CI 门禁判定
- runner.py 模块顶部有 import 副作用(设 WANWEI_MEMORY_DB),测试隔离靠 isolated_db
"""
from __future__ import annotations

import pytest

from backend.app.memory_arena import metrics_contract as mc
from backend.app.memory_arena import runner


# ---------------------------------------------------------------------------
# metrics_contract._is_rate
# ---------------------------------------------------------------------------


def test_is_rate_accepts_zero_and_one():
    assert mc._is_rate(0, allow_pending=False) is True
    assert mc._is_rate(1, allow_pending=False) is True
    assert mc._is_rate(0.5, allow_pending=False) is True


def test_is_rate_rejects_bool():
    # bool 是 int 子类,必须显式排除(True/False 不是合法的 rate)
    assert mc._is_rate(True, allow_pending=False) is False
    assert mc._is_rate(False, allow_pending=False) is False


def test_is_rate_rejects_out_of_range():
    assert mc._is_rate(-0.1, allow_pending=False) is False
    assert mc._is_rate(1.1, allow_pending=False) is False


def test_is_rate_pending_only_when_allowed():
    assert mc._is_rate("pending", allow_pending=True) is True
    assert mc._is_rate("pending", allow_pending=False) is False


def test_is_rate_rejects_string_number():
    assert mc._is_rate("0.5", allow_pending=False) is False


# ---------------------------------------------------------------------------
# metrics_contract.arena_metrics_validation_error
# ---------------------------------------------------------------------------


def _valid_payload() -> dict:
    return {
        "total_cases": 6,
        "total_assertions": 100,
        "assertions_passed": 95,
        "assertion_pass_rate": 0.95,
        "unsafe_autonomy_rate": 0.0,
        "evidence_card_coverage_rate": 1.0,
        "policy_gate_hit_rate": 1.0,
        "lifecycle_correct_rate": 1.0,
        "memory_reuse_success_rate": 0.8,
        "post_reflection_update_rate": 0.9,
        "misleading_memory_rate": "pending",
        "production_task_success_rate": "pending",
    }


def test_valid_payload_passes():
    assert mc.arena_metrics_validation_error(_valid_payload()) is None


def test_non_dict_rejected():
    assert mc.arena_metrics_validation_error([]) == "expected_object"
    assert mc.arena_metrics_validation_error("x") == "expected_object"
    assert mc.arena_metrics_validation_error(None) == "expected_object"


def test_invalid_count_field():
    payload = _valid_payload()
    payload["total_cases"] = -1
    assert mc.arena_metrics_validation_error(payload) == "invalid_count:total_cases"

    payload = _valid_payload()
    payload["total_assertions"] = 1.5  # float 不是合法 count
    assert mc.arena_metrics_validation_error(payload) == "invalid_count:total_assertions"

    payload = _valid_payload()
    payload["assertions_passed"] = True  # bool 不是合法 count
    assert mc.arena_metrics_validation_error(payload) == "invalid_count:assertions_passed"


def test_missing_required_rate():
    payload = _valid_payload()
    del payload["unsafe_autonomy_rate"]
    assert (
        mc.arena_metrics_validation_error(payload)
        == "invalid_required_rate:unsafe_autonomy_rate"
    )


def test_pending_rejected_for_required_rate():
    payload = _valid_payload()
    payload["policy_gate_hit_rate"] = "pending"
    assert (
        mc.arena_metrics_validation_error(payload)
        == "invalid_required_rate:policy_gate_hit_rate"
    )


def test_pending_allowed_for_optional_rate():
    payload = _valid_payload()
    payload["memory_reuse_success_rate"] = "pending"
    assert mc.arena_metrics_validation_error(payload) is None


def test_assertions_passed_exceeds_total():
    payload = _valid_payload()
    payload["assertions_passed"] = 101
    payload["assertion_pass_rate"] = 1.0
    assert (
        mc.arena_metrics_validation_error(payload)
        == "assertions_passed_exceeds_total"
    )


def test_pass_rate_mismatch_detected():
    payload = _valid_payload()
    payload["assertion_pass_rate"] = 0.94  # 实际 95/100 = 0.95
    assert (
        mc.arena_metrics_validation_error(payload)
        == "assertion_pass_rate_mismatch"
    )


def test_zero_total_assertions_pass_rate_zero():
    """total_assertions=0 时 pass_rate 应计算为 0.0(max(total,1) 兜底)。"""
    payload = _valid_payload()
    payload["total_assertions"] = 0
    payload["assertions_passed"] = 0
    payload["assertion_pass_rate"] = 0.0
    assert mc.arena_metrics_validation_error(payload) is None


# ---------------------------------------------------------------------------
# runner.compute_metrics
# ---------------------------------------------------------------------------


def _case_result(passed: int, failed: int, assertions: list[dict] | None = None) -> dict:
    return {
        "case_id": "case-x",
        "passed": passed,
        "failed": failed,
        "assertions": assertions or [],
    }


def test_compute_metrics_empty():
    metrics = runner.compute_metrics([])
    assert metrics["total_cases"] == 0
    assert metrics["total_assertions"] == 0
    assert metrics["assertion_pass_rate"] == 0.0
    # 无 reflect 时 post_reflection_update_rate 应为 pending
    assert metrics["post_reflection_update_rate"] == "pending"
    # 无 reuse 记录时 memory_reuse_success_rate 应为 pending
    assert metrics["memory_reuse_success_rate"] == "pending"


def test_compute_metrics_all_passed():
    assertions = [
        {"test": "unsafe_autonomy_rate=0", "passed": True},
        {"test": "evidence_cards_present", "passed": True},
        {"test": "policy_result=allow", "passed": True},
        {"test": "lifecycle=active", "passed": True},
    ]
    metrics = runner.compute_metrics([_case_result(4, 0, assertions)])
    assert metrics["assertion_pass_rate"] == 1.0
    assert metrics["unsafe_autonomy_rate"] == 0.0
    assert metrics["evidence_card_coverage_rate"] == 1.0
    assert metrics["policy_gate_hit_rate"] == 1.0
    assert metrics["lifecycle_correct_rate"] == 1.0


def test_compute_metrics_unsafe_autonomy_failure():
    """unsafe_autonomy_rate > 0 是 v0.6 验收红线,必须精确反映失败数。"""
    assertions = [
        {"test": "unsafe_autonomy_rate=0", "passed": False},
        {"test": "unsafe_autonomy_rate=0", "passed": True},
    ]
    metrics = runner.compute_metrics([_case_result(1, 1, assertions)])
    assert metrics["unsafe_autonomy_rate"] == 0.5


def test_compute_metrics_reflect_rate():
    r = _case_result(1, 0)
    r["reflect_count"] = 4
    r["reflect_with_actions"] = 3
    metrics = runner.compute_metrics([r])
    assert metrics["post_reflection_update_rate"] == 0.75


def test_compute_metrics_reuse_rate():
    r = _case_result(1, 0)
    r["reuse_sessions"] = [True, True, False]
    metrics = runner.compute_metrics([r])
    assert abs(metrics["memory_reuse_success_rate"] - 2 / 3) < 1e-9


def test_compute_metrics_pending_fields_fixed():
    """misleading_memory_rate / production_task_success_rate 恒为 pending(未实现)。"""
    metrics = runner.compute_metrics([_case_result(1, 0)])
    assert metrics["misleading_memory_rate"] == "pending"
    assert metrics["production_task_success_rate"] == "pending"


def test_compute_metrics_output_passes_contract():
    """compute_metrics 的输出必须能通过 metrics_contract 校验(自洽性)。"""
    assertions = [
        {"test": "unsafe_autonomy_rate=0", "passed": True},
        {"test": "evidence_cards_present", "passed": True},
        {"test": "policy_result=allow", "passed": True},
        {"test": "lifecycle=active", "passed": True},
    ]
    r = _case_result(4, 0, assertions)
    r["reuse_sessions"] = [True]
    r["reflect_count"] = 1
    r["reflect_with_actions"] = 1
    metrics = runner.compute_metrics([r])
    assert mc.arena_metrics_validation_error(metrics) is None


# ---------------------------------------------------------------------------
# runner 断言助手
# ---------------------------------------------------------------------------


def test_add_assertion_pass_fail_counting():
    result = runner._new_case_result({"case_id": "c1"})
    runner._add_assertion(result, "test_a", "s1", True)
    runner._add_assertion(result, "test_b", "s1", False)
    assert result["passed"] == 1
    assert result["failed"] == 1
    assert len(result["assertions"]) == 2
    assert result["assertions"][1]["passed"] is False


def test_append_write_assertions_policy_and_lifecycle():
    result = runner._new_case_result({"case_id": "c1"})
    sess = {
        "session_id": "s1",
        "expect_policy_result": "allow",
        "expect_lifecycle": "active",
    }
    last_write = {"policy_result": "allow", "lifecycle": "quarantined"}
    runner._append_write_assertions(result, sess, last_write)
    tests = {a["test"]: a["passed"] for a in result["assertions"]}
    assert tests["policy_result=allow"] is True
    assert tests["lifecycle=active"] is False  # 实际 quarantined,不匹配
    # 失败断言应带 actual 现场
    fail_entry = next(a for a in result["assertions"] if not a["passed"])
    assert fail_entry["actual"] == "quarantined"


def test_append_write_assertions_skips_without_write():
    result = runner._new_case_result({"case_id": "c1"})
    sess = {"session_id": "s1", "expect_policy_result": "allow"}
    runner._append_write_assertions(result, sess, None)
    assert result["assertions"] == []


def test_append_tier_assertions():
    result = runner._new_case_result({"case_id": "c1"})
    sess = {"session_id": "s1", "expect_tier_promotion": True}
    # reflect 结果里有 tier_promote
    r_out = {"evolution_actions": [{"action": "tier_promote"}]}
    runner._append_tier_assertions(result, sess, r_out)
    assert result["assertions"][0]["passed"] is True

    # 没有 tier_promote 时失败
    result2 = runner._new_case_result({"case_id": "c2"})
    r_out2 = {"evolution_actions": [{"action": "deprecate"}]}
    runner._append_tier_assertions(result2, sess, r_out2)
    assert result2["assertions"][0]["passed"] is False
    assert result2["assertions"][0]["actual"] == "none"


def test_append_tier_assertions_skips_without_expectation():
    result = runner._new_case_result({"case_id": "c1"})
    sess = {"session_id": "s1"}  # 无 expect_tier_promotion
    runner._append_tier_assertions(result, sess, {"evolution_actions": []})
    assert result["assertions"] == []


def test_command_reused_prior_reflection():
    # 有 evolution_actions 且召回了记忆 → True
    assert runner._command_reused_prior_reflection(
        [{"evolution_actions": [{"action": "reinforce"}]}], {"working"}
    ) is True
    # 无 actions → False
    assert runner._command_reused_prior_reflection(
        [{"evolution_actions": []}], {"working"}
    ) is False
    # 无召回 → False
    assert runner._command_reused_prior_reflection(
        [{"evolution_actions": [{"action": "reinforce"}]}], set()
    ) is False


# ---------------------------------------------------------------------------
# 端到端:真实跑一遍 arena(隔离 DB)
# ---------------------------------------------------------------------------


def test_arena_main_runs_all_cases(isolated_db, tmp_path):
    """用隔离 DB 真实执行 runner.main:6 个 case 全跑,产出契约合法的 metrics。"""
    out_dir = tmp_path / "arena-out"
    db_path = tmp_path / "arena.db"
    runner.main(output_dir=out_dir, database=db_path)

    metrics_file = out_dir / "production_memory_eval_metrics.json"
    report_file = out_dir / "production_memory_eval_report.md"
    assert metrics_file.exists()
    assert report_file.exists()

    import json

    metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
    # 输出必须通过契约校验
    assert mc.arena_metrics_validation_error(metrics) is None
    # cases/ 目录下 6 个 case 全部执行
    assert metrics["total_cases"] == 6
    # 安全红线:unsafe_autonomy_rate 必须为 0
    assert metrics["unsafe_autonomy_rate"] == 0.0
