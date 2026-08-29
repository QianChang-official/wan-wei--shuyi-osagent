"""deepening 模块测试 — 推理深度路由 / RedQueen 评估器 / 契约真相。

覆盖:
1. reasoning_depth — 4 档模式配置完整性 + simulate 的行为(已知 mode / 未知 mode 回退 / dry_run 标记 / 诚实边界字段)
2. redqueen_evaluator — 5 项标准权重和 = 1.0 + evaluate_dry_run 的罚分规则
3. contract_truth — source_of_truth / drift_check 的结构与诚实边界

设计说明:
- 这些模块全部是 dry-run 设计(不改任何状态),测试锁定的核心是「诚实边界字段」
  与「罚分规则」— 它们是 REVIEW.md 诚实条款在代码层的具体化
- _MODES / _CRITERIA 的权重、档位字段是契约,漂移必须报警
"""
from __future__ import annotations

from backend.app.deepening import (
    contract_truth,
    redqueen_evaluator,
    reasoning_depth,
)
from backend.app.deepening.schemas import (
    ReasoningDepthSimulateIn,
    RedQueenEvaluateIn,
)


# ---------------------------------------------------------------------------
# reasoning_depth
# ---------------------------------------------------------------------------


def test_design_lists_four_modes():
    modes = reasoning_depth.design()["modes"]
    names = {m["mode"] for m in modes}
    assert names == {"shallow", "normal", "deep", "audit"}


def test_design_modes_carry_required_fields():
    """每档模式必须携带契约字段 — 缺一即漂移。"""
    required = {
        "memory_depth", "evidence_requirement", "reflection_loops",
        "estimated_token_multiplier", "retrieval_top_k",
        "evidence_cards_required", "visual_checks",
    }
    for mode in reasoning_depth.design()["modes"]:
        missing = required - set(mode.keys())
        assert not missing, f"{mode['mode']} 缺字段: {missing}"


def test_design_modes_monotonic_depth():
    """档位越深,retrieval_top_k / evidence_cards_required / reflection_loops 单调不减。"""
    modes = {m["mode"]: m for m in reasoning_depth.design()["modes"]}
    order = ["shallow", "normal", "deep", "audit"]
    for field in ("retrieval_top_k", "evidence_cards_required", "reflection_loops"):
        values = [modes[m][field] for m in order]
        assert values == sorted(values), f"{field} 非单调: {values}"


def test_design_honest_boundary_present():
    d = reasoning_depth.design()
    assert "no_model_training" in d["boundary"]


def test_simulate_known_mode():
    out = reasoning_depth.simulate(ReasoningDepthSimulateIn(mode="deep"))
    assert out["selected_mode"] == "deep"
    assert out["dry_run"] is True
    assert out["retrieval_top_k"] == 8
    assert out["evidence_cards_required"] == 4


def test_simulate_unknown_mode_falls_back_to_normal():
    out = reasoning_depth.simulate(ReasoningDepthSimulateIn(mode="nonexistent"))
    assert out["selected_mode"] == "normal"


def test_simulate_token_cost_model_honest():
    """token_cost_model 必须带 honest_boundary — 不允许伪造具体节省数字。"""
    out = reasoning_depth.simulate(ReasoningDepthSimulateIn(mode="audit"))
    assert "honest_boundary" in out["token_cost_model"]
    assert out["token_cost_model"]["estimated_multiplier"] == 2.6


def test_simulate_task_risk_fallback():
    """task_risk 缺省时用 task_type 兜底。"""
    out = reasoning_depth.simulate(
        ReasoningDepthSimulateIn(mode="shallow", task_type="typo_fix", task_risk="")
    )
    # schemas 里 task_risk 默认 "medium",显式传空串时代码回退 task_type
    assert out["task_risk"] in ("typo_fix", "medium")


# ---------------------------------------------------------------------------
# redqueen_evaluator
# ---------------------------------------------------------------------------


def test_evaluator_criteria_weights_sum_to_one():
    criteria = redqueen_evaluator.evaluator_design()["criteria"]
    total = sum(c["weight"] for c in criteria)
    assert abs(total - 1.0) < 1e-9


def test_evaluator_design_forbidden_actions():
    """禁止动作清单是治理边界,改动必须报警。"""
    design = redqueen_evaluator.evaluator_design()
    forbidden = design["utility_epoch_contract"]["forbidden_actions"]
    assert "mutate_memory" in forbidden
    assert "claim_unverified_metric" in forbidden
    assert "rewrite_runtime_without_review" in forbidden


def test_evaluate_dry_run_clean_output():
    out = redqueen_evaluator.evaluate_dry_run(
        RedQueenEvaluateIn(agent_output="done partial planned visual check passed")
    )
    assert out["dry_run"] is True
    assert out["penalties"] == []
    assert out["score"] == 0.82
    assert out["utility_update_proposal"]["action"] == "keep_current_policy"
    assert out["utility_update_proposal"]["requires_human_review"] is True


def test_evaluate_dry_run_done_without_boundary():
    """只声称 done 而无 partial/planned 边界语言 → 罚分。"""
    out = redqueen_evaluator.evaluate_dry_run(
        RedQueenEvaluateIn(agent_output="all done with visual sync")
    )
    assert "done_claim_without_boundary_language" in out["penalties"]
    assert out["score"] < 0.82


def test_evaluate_dry_run_cost_without_metrics():
    """声称 cost 但 metrics 为空 → 罚分。"""
    out = redqueen_evaluator.evaluate_dry_run(
        RedQueenEvaluateIn(agent_output="cost reduced, visual done, partial planned")
    )
    assert "cost_claim_without_metric_payload" in out["penalties"]


def test_evaluate_dry_run_missing_visual():
    out = redqueen_evaluator.evaluate_dry_run(
        RedQueenEvaluateIn(agent_output="done partial planned")
    )
    assert "missing_visual_sync_reference" in out["penalties"]


def test_evaluate_dry_run_score_floor():
    """全部罚分命中时 score 不低于下限 0.35。"""
    out = redqueen_evaluator.evaluate_dry_run(
        RedQueenEvaluateIn(agent_output="done cost")  # 命中全部 3 条罚则
    )
    assert len(out["penalties"]) == 3
    assert out["score"] == max(0.35, round(0.82 - 0.08 * 3, 3))
    assert out["score"] >= 0.35


def test_evaluate_dry_run_never_mutates():
    """dry-run 契约:任何输入下 requires_human_review 恒为 True。"""
    for text in ("", "done", "perfect output with visual and partial planned"):
        out = redqueen_evaluator.evaluate_dry_run(
            RedQueenEvaluateIn(agent_output=text, metrics={"k": 1})
        )
        assert out["utility_update_proposal"]["requires_human_review"] is True
        assert out["dry_run"] is True


# ---------------------------------------------------------------------------
# contract_truth
# ---------------------------------------------------------------------------


def test_source_of_truth_structure():
    sot = contract_truth.source_of_truth()
    assert sot["version"]
    assert sot["boundary"] == "repository_contract_only_no_external_claims"
    assert len(sot["contracts"]) >= 4
    # source_layers 划分是诚实边界的核心:chat_render/copied_text 不算证据
    assert "chat_render" in sot["source_layers"]["ignored_for_residue"]
    assert "runtime_log" in sot["source_layers"]["accepted"]


def test_source_of_truth_contracts_have_status():
    for c in contract_truth.source_of_truth()["contracts"]:
        assert c["status"] in ("implemented", "verification_required", "partial", "planned")
        assert c["layer"]
        assert c["artifact"]


def test_drift_check_structure():
    dc = contract_truth.drift_check()
    assert dc["drift_status"] == "requires_runtime_verification"
    assert len(dc["checks"]) >= 3
    for check in dc["checks"]:
        assert check["status"] in ("pass_by_contract", "verification_required")


def test_drift_check_not_all_pass_by_contract():
    """如果全部 check 都标 pass_by_contract,说明漂移检查退化成橡皮图章。"""
    dc = contract_truth.drift_check()
    statuses = [c["status"] for c in dc["checks"]]
    assert "verification_required" in statuses
