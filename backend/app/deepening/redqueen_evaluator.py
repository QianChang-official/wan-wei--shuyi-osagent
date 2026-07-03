from __future__ import annotations

from .schemas import RedQueenEvaluateIn

_CRITERIA = [
    {"id": "utility_alignment", "weight": 0.25, "question": "Does the change improve task utility without hiding risk?"},
    {"id": "truth_boundary", "weight": 0.25, "question": "Are done, partial, planned, and pending boundaries explicit?"},
    {"id": "evidence_pressure", "weight": 0.20, "question": "Are claims backed by source/build/runtime evidence?"},
    {"id": "regression_guard", "weight": 0.15, "question": "Does it preserve v0.6-v0.9 metrics and routes?"},
    {"id": "visual_sync", "weight": 0.15, "question": "Is frontend state synchronized with API and dist artifacts?"},
]


def evaluator_design() -> dict:
    return {
        "version": "v0.9.1",
        "inspiration": "Red Queen Godel Machine controlled utility evolution",
        "boundary": "evaluator_proposes_updates_only_no_self_modifying_code",
        "criteria": _CRITERIA,
        "utility_epoch_contract": {
            "epoch": "epoch_v091",
            "allowed_actions": ["propose_weight_change", "flag_missing_evidence", "request_visual_check"],
            "forbidden_actions": ["rewrite_runtime_without_review", "mutate_memory", "claim_unverified_metric"],
        },
    }


def evaluate_dry_run(req: RedQueenEvaluateIn) -> dict:
    output = (req.agent_output or "").lower()
    penalties = []
    if "done" in output and "partial" not in output and "planned" not in output:
        penalties.append("done_claim_without_boundary_language")
    if "cost" in output and not req.metrics:
        penalties.append("cost_claim_without_metric_payload")
    if "visual" not in output:
        penalties.append("missing_visual_sync_reference")

    base_score = 0.82 - 0.08 * len(penalties)
    score = max(0.35, round(base_score, 3))
    return {
        "dry_run": True,
        "utility_epoch": req.utility_epoch,
        "adversarial_objective": req.adversarial_objective,
        "score": score,
        "penalties": penalties,
        "utility_update_proposal": {
            "action": "increase_evidence_pressure" if penalties else "keep_current_policy",
            "delta": 0.05 if penalties else 0.0,
            "requires_human_review": True,
        },
        "notes": [
            "dry-run evaluator only returns a proposal",
            "no code, memory, or configuration is mutated",
            "score is heuristic and not an external benchmark",
        ],
    }
