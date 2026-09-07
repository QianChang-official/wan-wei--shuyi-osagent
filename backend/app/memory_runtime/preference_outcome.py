# Copyright (c) 2026 QianChang-official
#
# 宛委·枢忆 is licensed under Mulan PSL v2.
# You can use this software according to the terms of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
# http://license.coscl.org.cn/MulanPSL2
#
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

"""Outcome validation for preferences.

Formation ≠ Validation——形成证据与执行结果反馈是两个阶段，Outcome 权重大于推测。
"""
import math
import os
from typing import Any

from ..utils.datetime_utils import utc_now_iso_compact
from .capsule_store import get_capsule, update_capsule
from .preference_confidence import ALPHA_KEY, BETA_KEY, confidence

REWARD = 1.0
PENALTY = 1.0
STRONG_PENALTY = 2.0
WEAK_PENALTY = 0.5
MAX_DELTA = 1000.0
OUTCOME_LOG_LIMIT = 20
OUTCOME_TYPES = {"accept", "reject", "undo", "retry", "unknown"}

def outcome_validation_enabled() -> bool:
    return os.getenv("WANWEI_OUTCOME_VALIDATION", "").strip().lower() in {"1", "true", "yes", "on"}

def _value(value: Any, default: float) -> float:
    try:
        value = float(value)
        if not math.isfinite(value) or value < 0:
            raise ValueError
        return min(value, MAX_DELTA)
    except (TypeError, ValueError):
        return default

def apply_outcome(meta: dict[str, Any], outcome_type: str, *, reward=REWARD, penalty=PENALTY,
                  strong_penalty=STRONG_PENALTY, weak_penalty=WEAK_PENALTY,
                  action_id: str | None = None) -> dict[str, Any]:
    """Apply an execution outcome in place when outcome validation is enabled.

    With the feature flag disabled this is a strict no-op: posterior counters and
    the audit log are left untouched.
    """
    if not outcome_validation_enabled():
        return meta
    if outcome_type not in OUTCOME_TYPES:
        raise ValueError(f"未知 outcome_type: {outcome_type!r}")
    def posterior() -> dict[str, float]:
        a = 1.0 + float(meta.get(ALPHA_KEY, 0) or 0)
        b = 1.0 + float(meta.get(BETA_KEY, 0) or 0)
        return {"alpha": a, "beta": b}
    before = posterior()
    def count(key: str) -> float:
        try:
            v = float(meta.get(key, 0) or 0)
            return v if math.isfinite(v) and v >= 0 else 0.0
        except (TypeError, ValueError):
            return 0.0
    if outcome_type == "accept":
        meta[ALPHA_KEY] = count(ALPHA_KEY) + _value(reward, REWARD)
    elif outcome_type in {"reject", "undo", "retry"}:
        delta = {"reject": penalty, "undo": strong_penalty, "retry": weak_penalty}[outcome_type]
        meta[BETA_KEY] = count(BETA_KEY) + _value(delta, {"reject": PENALTY, "undo": STRONG_PENALTY, "retry": WEAK_PENALTY}[outcome_type])
    after = posterior()
    log = list(meta.get("outcome_log") or [])
    log.append({"outcome_type": outcome_type, "action_id": action_id, "posterior_before": {"alpha": before["alpha"], "beta": before["beta"]}, "posterior_after": {"alpha": after["alpha"], "beta": after["beta"]}, "created_at": utc_now_iso_compact()})
    meta["outcome_log"] = log[-OUTCOME_LOG_LIMIT:]
    return meta


def record_outcome(
    capsule_id: str,
    outcome_type: str,
    *,
    owner_id: str | None = None,
    soul_id: str | None = None,
    action_id: str | None = None,
    **delta_kwargs: Any,
) -> dict[str, Any]:
    """Record an outcome on a preference capsule and persist its updated state."""
    cap = get_capsule(capsule_id, owner_id=owner_id, soul_id=soul_id)
    if not cap:
        raise ValueError(f"Capsule not found: {capsule_id}")
    if cap.get("memory_class") != "preference":
        raise ValueError("Outcome validation requires a preference capsule")
    state = dict(cap.get("state") or {})
    apply_outcome(state, outcome_type, action_id=action_id, **delta_kwargs)
    if not outcome_validation_enabled():
        return cap
    if outcome_type != "unknown":
        state.setdefault(ALPHA_KEY, 0.0)
        state.setdefault(BETA_KEY, 0.0)
    return update_capsule(
        capsule_id,
        state=state,
        owner_id=owner_id,
        soul_id=soul_id,
        reason=f"outcome:{outcome_type}",
    )

def outcome_summary(meta: dict[str, Any]) -> dict[str, Any]:
    log = list(meta.get("outcome_log") or [])
    return {"accepts": sum(x.get("outcome_type") == "accept" for x in log), "rejects": sum(x.get("outcome_type") == "reject" for x in log), "undos": sum(x.get("outcome_type") == "undo" for x in log), "retries": sum(x.get("outcome_type") == "retry" for x in log), "last_validation_at": log[-1].get("created_at") if log else None}

__all__ = ["apply_outcome", "record_outcome", "outcome_summary", "outcome_validation_enabled"]
