"""Validation contract shared by the Arena API and desktop package gate."""

from __future__ import annotations

import json
import sys
from typing import Any


COUNT_FIELDS = ("total_cases", "total_assertions", "assertions_passed")
REQUIRED_RATE_FIELDS = (
    "assertion_pass_rate",
    "unsafe_autonomy_rate",
    "evidence_card_coverage_rate",
    "policy_gate_hit_rate",
    "lifecycle_correct_rate",
)
PENDING_ALLOWED_RATE_FIELDS = (
    "memory_reuse_success_rate",
    "post_reflection_update_rate",
    "misleading_memory_rate",
    "production_task_success_rate",
)


def _is_rate(value: Any, *, allow_pending: bool) -> bool:
    if allow_pending and value == "pending":
        return True
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and 0 <= value <= 1
    )


def arena_metrics_validation_error(payload: object) -> str | None:
    """Return a stable error code, or ``None`` when the report is valid."""
    if not isinstance(payload, dict):
        return "expected_object"

    for field in COUNT_FIELDS:
        value = payload.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return f"invalid_count:{field}"

    for field in REQUIRED_RATE_FIELDS:
        if not _is_rate(payload.get(field), allow_pending=False):
            return f"invalid_required_rate:{field}"

    for field in PENDING_ALLOWED_RATE_FIELDS:
        if not _is_rate(payload.get(field), allow_pending=True):
            return f"invalid_optional_rate:{field}"

    if payload["assertions_passed"] > payload["total_assertions"]:
        return "assertions_passed_exceeds_total"

    expected_pass_rate = round(
        payload["assertions_passed"] / max(payload["total_assertions"], 1),
        4,
    )
    if round(float(payload["assertion_pass_rate"]), 4) != expected_pass_rate:
        return "assertion_pass_rate_mismatch"
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"Arena metrics JSON could not be loaded: {exc}", file=sys.stderr)
        return 2

    error = arena_metrics_validation_error(payload)
    if error is not None:
        print(f"Arena metrics contract failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
