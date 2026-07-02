import uuid
from typing import Any
from ..audit.service import record
from .retrieval import search_capsules
from .evidence import build_evidence_card

HIGH_RISK_WORDS = ["修改系统配置", "删除", "重启", "rm -rf", "写入", "push", "commit", "部署"]
CRITICAL_WORDS = ["格式化", "私钥", "生产数据库", "critical", "root"]


def classify_risk(goal: str) -> str:
    low = goal.lower()
    if any(w.lower() in low for w in CRITICAL_WORDS):
        return "critical"
    if any(w.lower() in low for w in HIGH_RISK_WORDS):
        return "high"
    return "medium" if any(w in goal for w in ["计划", "审查", "评测", "引用"]) else "low"


def execution_mode_for(risk_class: str) -> str:
    return {"low": "advisory_mode", "medium": "advisory_mode", "high": "supervised_mode", "critical": "read_only_mode"}[risk_class]


def run_command_loop(*, goal: str, scene: str = "general", top_k: int = 5) -> dict[str, Any]:
    task_id = "task_" + uuid.uuid4().hex[:12]
    risk_class = classify_risk(goal)
    high_risk = risk_class in {"high", "critical"}
    memories = search_capsules(goal, top_k=top_k, high_risk=high_risk)
    evidence_cards = [build_evidence_card(m, used_for="planning") for m in memories]
    confirmation_points = []
    if risk_class == "high":
        confirmation_points.append({
            "confirmation_id": "confirm_" + uuid.uuid4().hex[:8],
            "reason": "high_risk",
            "question": "该任务可能修改系统状态，是否允许进入确认后执行流程？",
            "evidence_ids": [e["evidence_id"] for e in evidence_cards],
            "default_action_if_no_response": "do_not_execute",
        })
    if risk_class == "critical":
        confirmation_points.append({
            "confirmation_id": "confirm_" + uuid.uuid4().hex[:8],
            "reason": "critical_risk",
            "question": "关键风险任务默认只读分析；是否需要人工另行审批？",
            "evidence_ids": [e["evidence_id"] for e in evidence_cards],
            "default_action_if_no_response": "read_only",
        })
    plan = [{
        "step": 1,
        "action": "基于召回记忆生成只读分析与建议",
        "memory_used": [m["capsule_id"] for m in memories],
        "risk_level": risk_class,
        "requires_confirmation": bool(confirmation_points),
    }]
    result = {
        "task_understanding": {"task_id": task_id, "scene": scene, "task_type": "planning", "risk_class": risk_class, "requires_memory": True, "requires_confirmation": bool(confirmation_points)},
        "recalled_memories": memories,
        "evidence_cards": evidence_cards,
        "risk_assessment": {"risk_class": risk_class, "unsafe_autonomy": False},
        "recommended_plan": plan,
        "alternatives": [],
        "blocked_actions": [] if risk_class != "critical" else ["execute_without_human_approval"],
        "confirmation_points": confirmation_points,
        "execution_mode": execution_mode_for(risk_class),
        "reflection_plan": {"required": True, "default_actions": ["reinforce helpful memories", "deprecate misleading memories"]},
    }
    record("command_loop_plan", {"task_id": task_id, "risk_class": risk_class, "memories": [m["capsule_id"] for m in memories]})
    return result
