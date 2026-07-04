from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CASES_DIR = PROJECT_ROOT / "backend" / "app" / "memory_arena" / "cases"
METRICS_FILE = PROJECT_ROOT / "reports" / "production_memory_eval_metrics.json"
REPORT_FILE = PROJECT_ROOT / "reports" / "production_memory_eval_report.md"


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _expected_assertions(session: dict) -> list[str]:
    items: list[str] = []
    if session.get("expect_evidence_cards"):
        items.append("evidence_cards_present")
    if session.get("expect_unsafe_autonomy") is False:
        items.append("unsafe_autonomy_rate=0")
    if "expect_memory_classes" in session:
        items.append("memories_recalled")
    if "expect_policy_result" in session:
        items.append(f"policy_result={session['expect_policy_result']}")
    if "expect_lifecycle" in session:
        items.append(f"lifecycle={session['expect_lifecycle']}")
    return items


def _phase(session: dict) -> str:
    if session.get("write_capsules"):
        return "write"
    if session.get("command_goal"):
        return "command"
    if session.get("reflect"):
        return "reflect"
    return "unknown"


def _timeline_for_case(case: dict) -> list[dict]:
    timeline = []
    for session in case.get("sessions", []):
        memory_classes = []
        for cap in session.get("write_capsules", []):
            memory_classes.append(cap.get("memory_class", "unknown"))
        if session.get("expect_memory_classes"):
            memory_classes.extend(session["expect_memory_classes"])
        timeline.append(
            {
                "session_id": session.get("session_id", "unknown"),
                "phase": _phase(session),
                "expected_assertions": _expected_assertions(session),
                "memory_classes": sorted(set(memory_classes)),
                "risk_focus": session.get("risk_focus") or session.get("expect_policy_result") or "general",
                "has_command": "command_goal" in session,
                "has_reflection": "reflect" in session,
                "write_count": len(session.get("write_capsules", [])),
            }
        )
    return timeline


def workbench() -> dict:
    cases = [_load_json(path, {}) for path in sorted(CASES_DIR.glob("*.json"))]
    cases = [case for case in cases if case]
    metrics = _load_json(METRICS_FILE, {})
    pass_rate = metrics.get("assertion_pass_rate")
    failure_diagnosis = {
        "status": "no_failure" if pass_rate == 1.0 else "has_failure",
        "failed_assertions": [] if pass_rate == 1.0 else "see_report",
        "report_file": str(REPORT_FILE.relative_to(PROJECT_ROOT)) if REPORT_FILE.exists() else "missing",
    }
    return {
        "status": "memoryarena_workbench_partial",
        "boundary": "Workbench data model over existing MemoryArena-Lite, not full official MemoryArena reproduction.",
        "metrics": metrics,
        "cases": [
            {
                "case_id": case.get("case_id"),
                "title": case.get("title", ""),
                "session_count": len(case.get("sessions", [])),
                "sessions": case.get("sessions", []),
                "timeline": _timeline_for_case(case),
            }
            for case in cases
        ],
        "failure_diagnosis": failure_diagnosis,
    }
