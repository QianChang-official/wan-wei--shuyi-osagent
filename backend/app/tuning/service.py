from __future__ import annotations


TUNING_DEFAULTS = {
    "retrieval": {
        "top_k": 5,
        "trust_threshold": 0.65,
        "retrieval_score_weight": 0.55,
        "retention_score_weight": 0.25,
        "emotional_salience_weight": 0.10,
        "recency_weight": 0.10,
        "latency_target_ms": "retrieval_p95_lte_500ms",
    },
    "policy": {
        "confirmation_threshold": 0.70,
        "quarantine_threshold": 0.45,
        "high_risk_requires_confirmation": True,
        "inferred_preference_requires_confirmation": True,
        "source_layer_required_for_high_risk": True,
    },
    "control_loop_measurements": {
        "workflow_dry_run_latency_ms": "sum_stage_budget_current_248ms",
        "retrieval_latency_ms": "target_lte_500ms; current_stage_budget_46ms",
        "policy_gate_latency_ms": "current_stage_budget_12ms",
        "command_loop_latency_ms": "current_stage_budget_29ms",
        "audit_write_latency_ms": "sqlite_insert_expected_single_digit_ms",
        "model_generation_latency_ms": "reported_separately_from_osagent_control_loop",
    },
    "arena": {
        "assertion_pass_rate_target": 0.95,
        "unsafe_autonomy_rate_target": 0.0,
        "memory_reuse_success_rate_target": "pending_baseline",
        "misleading_memory_rate_target": "pending_baseline",
    },
}

POLICY_MODES = [
    {"id": "readonly", "name_cn": "只读模式", "status": "available", "description": "只读检索和报告，不写入记忆。"},
    {"id": "advisory", "name_cn": "建议模式", "status": "available", "description": "生成建议和证据卡，写入需显式确认。"},
    {"id": "supervised", "name_cn": "监督模式", "status": "partial", "description": "低风险自动化，高风险人工确认。"},
    {"id": "autopilot", "name_cn": "自动驾驶模式", "status": "planned", "description": "v0.9.3 不开放真实危险自动化，仅保留目标形态。"},
]


def get_defaults() -> dict:
    return {"defaults": TUNING_DEFAULTS}


def list_policy_modes() -> dict:
    return {"items": POLICY_MODES}