from __future__ import annotations

from datetime import datetime, timezone

from ..memory_runtime.capsule_store import list_capsules
from .schemas import RetentionSimulateIn


def _score(importance: float, strength: float, age_days: float) -> float:
    return round(max(0.0, importance) * max(0.0, strength) / (1.0 + max(0.0, age_days)), 4)


def _state_for_capsule(cap: dict, index: int) -> dict:
    state = cap.get("state", {})
    importance = float(state.get("importance_score") or 0.5)
    usage = int(state.get("usage_count") or 0)
    strength = min(1.0, 0.55 + usage * 0.05)
    created = cap.get("created_at") or ""
    age_days = float(index)
    return {
        "capsule_id": cap.get("capsule_id"),
        "memory_strength": round(strength, 3),
        "recall_count": usage,
        "last_recalled_at": state.get("last_accessed_at"),
        "age_days": age_days,
        "importance": importance,
        "retention_score": _score(importance, strength, age_days),
        "created_at": created,
        "status": "retention_partial_from_capsule_state",
    }


def state() -> dict:
    capsules = [cap for cap in list_capsules(50) if cap]
    items = [_state_for_capsule(cap, i) for i, cap in enumerate(capsules)]
    if not items:
        items = [
            {
                "capsule_id": "demo_retention_capsule",
                "memory_strength": 0.8,
                "recall_count": 0,
                "last_recalled_at": None,
                "age_days": 3,
                "importance": 0.7,
                "retention_score": _score(0.7, 0.8, 3),
                "status": "demo_empty_db",
            }
        ]
    return {
        "status": "memorybank_retention_partial",
        "formula": "retention_score = importance * memory_strength / (1 + age_days)",
        "items": items,
    }


def simulate(req: RetentionSimulateIn) -> dict:
    strength = req.memory_strength
    recall_count = req.recall_count
    age_days = float(req.days)
    if req.action == "reinforce":
        strength = min(1.0, strength + 0.15)
        recall_count += 1
    elif req.action == "recall":
        strength = min(1.0, strength + 0.05)
        recall_count += 1
    elif req.action == "decay":
        strength = max(0.0, strength - 0.08)
        age_days += 7
    return {
        "status": "dry_run_only",
        "action": req.action,
        "capsule_id": req.capsule_id or "dry_run_capsule",
        "before": {
            "memory_strength": req.memory_strength,
            "recall_count": req.recall_count,
            "age_days": req.days,
            "retention_score": _score(req.importance, req.memory_strength, req.days),
        },
        "after": {
            "memory_strength": round(strength, 3),
            "recall_count": recall_count,
            "age_days": age_days,
            "importance": req.importance,
            "retention_score": _score(req.importance, strength, age_days),
            "last_recalled_at": datetime.now(timezone.utc).isoformat() if req.action in {"recall", "reinforce"} else None,
        },
        "mutates_real_capsule": False,
    }
