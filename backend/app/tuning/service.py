from __future__ import annotations


TUNING_DEFAULTS = {
    "retrieval": {
        "top_k": 5,
        "trust_threshold": 0.65,
        "retrieval_score_weight": 0.55,
        "retention_score_weight": 0.25,
        "emotional_salience_weight": 0.10,
        "recency_weight": 0.10,
        "latency_target_ms": "pending_measurement",
    },
    "policy": {
        "confirmation_threshold": 0.70,
        "quarantine_threshold": 0.45,
        "high_risk_requires_confirmation": True,
        "inferred_preference_requires_confirmation": True,
        "source_layer_required_for_high_risk": True,
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
    {"id": "autopilot", "name_cn": "自动驾驶模式", "status": "planned", "description": "v0.7 不开放真实危险自动化，仅保留目标形态。"},
]


def get_defaults() -> dict:
    return {"defaults": TUNING_DEFAULTS}


def list_policy_modes() -> dict:
    return {"items": POLICY_MODES}