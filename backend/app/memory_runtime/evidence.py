from typing import Any


def build_evidence_card(cap: dict[str, Any], *, used_for: str = "planning") -> dict[str, Any]:
    content = cap.get("content", {})
    claim = content.get("statement") or content.get("preference_value") or content.get("risk_statement") or content.get("skill_name") or str(content)[:160]
    provenance = cap.get("provenance", {})
    governance = cap.get("governance", {})
    return {
        "evidence_id": "ev_" + cap["capsule_id"],
        "capsule_id": cap["capsule_id"],
        "memory_class": cap.get("memory_class"),
        "claim": claim,
        "source": provenance.get("source_type") or provenance.get("origin") or "unknown",
        "confidence": governance.get("confidence", 0.0),
        "trust_score": governance.get("trust_score", 0.0),
        "used_for": used_for,
        "limitations": "runtime-lite evidence card; verify source for high-risk decisions",
    }
