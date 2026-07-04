from __future__ import annotations

from .schemas import ReasoningDepthSimulateIn

_MODES = {
    "shallow": {
        "memory_depth": "recent_context_only",
        "evidence_requirement": "one direct file or API result",
        "reflection_loops": 0,
        "visual_validation_intensity": "none_or_route_token_check",
        "estimated_token_multiplier": 1.0,
        "recommended_use": "fast status checks and low-risk UI copy edits",
        "retrieval_top_k": 3,
        "evidence_cards_required": 1,
        "visual_checks": ["route_exists"],
    },
    "normal": {
        "memory_depth": "project_docs_and_current_files",
        "evidence_requirement": "source file plus one runtime check",
        "reflection_loops": 1,
        "visual_validation_intensity": "fallback artifact check",
        "estimated_token_multiplier": 1.35,
        "recommended_use": "feature implementation with contained blast radius",
        "retrieval_top_k": 5,
        "evidence_cards_required": 2,
        "visual_checks": ["route_exists", "api_returns_data"],
    },
    "deep": {
        "memory_depth": "lineage_docs_runtime_reports_and_neighbor_code",
        "evidence_requirement": "source, build, smoke, and docs boundary",
        "reflection_loops": 2,
        "visual_validation_intensity": "browser_or_dist_chunk_plus_api_smoke",
        "estimated_token_multiplier": 1.9,
        "recommended_use": "architecture review, competition delivery, cross-layer feature work",
        "retrieval_top_k": 8,
        "evidence_cards_required": 4,
        "visual_checks": ["route_exists", "api_returns_data", "key_panels_render", "fallback_tokens_present"],
    },
    "audit": {
        "memory_depth": "full_contract_trace_with_negative_checks",
        "evidence_requirement": "source, runtime, git, and contradiction checks",
        "reflection_loops": 3,
        "visual_validation_intensity": "browser_pass_plus_fallback_artifact_or_explicit_blocker",
        "estimated_token_multiplier": 2.6,
        "recommended_use": "release gates, residual audits, security-sensitive claims",
        "retrieval_top_k": 12,
        "evidence_cards_required": 6,
        "visual_checks": ["route_exists", "api_returns_data", "key_panels_render", "navigation_present", "fallback_tokens_present"],
    },
}


def design() -> dict:
    return {
        "version": "v0.9.1",
        "inspiration": "OpenMythos recurrent-depth idea, adapted as routing policy only",
        "boundary": "no_model_training_no_claim_of_claude_mythos_reproduction",
        "modes": [{"mode": name, **payload} for name, payload in _MODES.items()],
    }


def simulate(req: ReasoningDepthSimulateIn) -> dict:
    selected = req.mode if req.mode in _MODES else "normal"
    cfg = _MODES[selected]
    risk = req.task_risk or req.task_type or "medium"
    return {
        "dry_run": True,
        "selected_mode": selected,
        "task_type": req.task_type,
        "task_risk": risk,
        "retrieval_top_k": cfg["retrieval_top_k"],
        "evidence_cards_required": cfg["evidence_cards_required"],
        "reflection_loops": cfg["reflection_loops"],
        "visual_checks": cfg["visual_checks"],
        "token_cost_model": {
            "baseline_units": 1.0,
            "estimated_multiplier": cfg["estimated_token_multiplier"],
            "savings_controls": [
                "source_layer filtering before retrieval",
                "top-k cap by risk mode",
                "reuse docs lineage instead of restating entire history",
                "visual fallback tokens instead of repeated browser retries",
            ],
            "honest_boundary": "relative multiplier only; no fabricated yuan or token savings number",
        },
        "risk_notes": [
            "mode controls evidence pressure, not model intelligence",
            "audit mode costs more and should be reserved for release or drift gates",
            "dry-run does not mutate memory or execute external tools",
        ],
    }
