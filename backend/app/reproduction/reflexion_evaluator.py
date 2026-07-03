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


def evaluate(req: ReflexionEvaluateIn) -> dict:
    notes = req.notes.lower()
    evidence_count = len(req.evidence_cards)
    used_count = len(req.used_memories)
    if req.goal_achieved and evidence_count > 0:
        failure_type = "no_failure"
        quality = 0.88
    elif "unsafe" in notes or "越权" in notes:
        failure_type = "unsafe_plan"
        quality = 0.35
    elif "false_positive" in notes or "误报" in notes:
        failure_type = "false_positive_echo"
        quality = 0.42
    elif evidence_count == 0:
        failure_type = "weak_evidence"
        quality = 0.45
    elif used_count == 0:
        failure_type = "missing_memory"
        quality = 0.5
    else:
        failure_type = "conflict_ignored" if "conflict" in notes else "missing_memory"
        quality = 0.55
    suggested_actions = []
    if failure_type == "weak_evidence":
        suggested_actions.append("require evidence cards before writing reflection memory")
    if failure_type == "missing_memory":
        suggested_actions.append("add retrieval trace and memory class expectation")
    if failure_type == "false_positive_echo":
        suggested_actions.append("separate tool_display/chat_render from file_content/runtime_log")
    if failure_type == "unsafe_plan":
        suggested_actions.append("force supervised mode and add confirmation point")
    if failure_type == "no_failure":
        suggested_actions.append("record successful before/after comparison as reusable pattern")
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
