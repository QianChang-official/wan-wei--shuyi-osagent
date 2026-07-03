from ..memory_runtime.capsule_store import list_capsules


def tiers() -> dict:
    capsules = [cap for cap in list_capsules(100) if cap]
    active = [cap["capsule_id"] for cap in capsules if cap.get("state", {}).get("lifecycle") == "active"]
    archival = [cap["capsule_id"] for cap in capsules if cap.get("state", {}).get("lifecycle") in {"deprecated", "forgotten"}]
    working = active[:5]
    return {
        "status": "memory_tier_manager_planned",
        "boundary": "MemGPT-like tier manager simulation; no real context paging is performed.",
        "working_context": working,
        "active_capsules": active,
        "archival_capsules": archival,
        "paging_policy": {
            "promote_on_recall": True,
            "demote_when_retention_below": 0.2,
            "high_risk_requires_trust_check": True,
        },
        "context_budget": {"max_working_capsules": 5, "estimated_tokens": "pending_measurement"},
    }
