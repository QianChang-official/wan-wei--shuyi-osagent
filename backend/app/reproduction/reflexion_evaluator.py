from __future__ import annotations

from .schemas import ReflexionEvaluateIn

FAILURE_TAXONOMY = [
    "missing_memory",
    "unsafe_plan",
    "weak_evidence",
    "conflict_ignored",
    "false_positive_echo",
    "no_failure",
]


def evaluator() -> dict:
    return {
        "status": "reflexion_evaluator_partial",
        "structure": ["actor", "evaluator", "self_reflection"],
        "failure_taxonomy": FAILURE_TAXONOMY,
        "outputs": [
            "failure_type",
            "reflection_quality_score",
            "suggested_memory_update",
            "before_after_comparison",
        ],
    }


def _classify_failure(req: ReflexionEvaluateIn) -> tuple[str, float]:
    notes = req.notes.lower()
    evidence_count = len(req.evidence_cards)
    if req.goal_achieved and evidence_count > 0:
        return "no_failure", 0.88
    if "unsafe" in notes or "越权" in notes:
        return "unsafe_plan", 0.35
    if "false_positive" in notes or "误报" in notes:
        return "false_positive_echo", 0.42
    if evidence_count == 0:
        return "weak_evidence", 0.45
    if len(req.used_memories) == 0:
        return "missing_memory", 0.5
    return ("conflict_ignored" if "conflict" in notes else "missing_memory"), 0.55


_SUGGESTED_ACTIONS = {
    "weak_evidence": "require evidence cards before writing reflection memory",
    "missing_memory": "add retrieval trace and memory class expectation",
    "false_positive_echo": "separate tool_display/chat_render from file_content/runtime_log",
    "unsafe_plan": "force supervised mode and add confirmation point",
    "no_failure": "record successful before/after comparison as reusable pattern",
}


def evaluate(req: ReflexionEvaluateIn) -> dict:
    evidence_count = len(req.evidence_cards)
    failure_type, quality = _classify_failure(req)
    action = _SUGGESTED_ACTIONS.get(failure_type)
    suggested_actions = [action] if action else []
    return {
        "status": "dry_run_only",
        "task_id": req.task_id,
        "actor": {"goal_achieved": req.goal_achieved, "used_memories": req.used_memories},
        "evaluator": {
            "failure_type": failure_type,
            "reflection_quality_score": quality,
            "evidence_card_count": evidence_count,
        },
        "self_reflection": {
            "suggested_actions": suggested_actions,
            "suggested_memory_update": failure_type != "no_failure",
        },
        "before_after_comparison": {
            "before": "task_result_input",
            "after": "reflection_plan_dry_run",
        },
        "mutates_real_memory": False,
    }
