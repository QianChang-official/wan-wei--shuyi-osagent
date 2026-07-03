from __future__ import annotations

from .schemas import VisualChecklistIn

_REQUIRED_PANELS = [
    "v0.9.1 Deep Expansion & Visual Verification",
    "Session Core",
    "Reasoning Depth",
    "Red Queen",
    "Contract Truth",
    "AGI-to-ASI Pathways",
    "Interrogation",
    "Visual Verification",
]


def protocol() -> dict:
    return {
        "version": "v0.9.1",
        "goal": "synchronize backend API, Vue route, navigation, dist artifact, and visual evidence",
        "preferred_path": [
            "start FastAPI service",
            "open /console/#/deepening in browser",
            "verify title, navigation, panels, dry-run buttons, and API data",
            "capture screenshot or describe browser evidence",
        ],
        "fallback_path": [
            "curl /console/ returns built index",
            "dist contains DeepeningView route chunk or token",
            "src contains required page tokens",
            "API smoke covers every /deepening/* endpoint",
        ],
        "required_panels": _REQUIRED_PANELS,
        "blocked_conditions": [
            "browser timeout without fallback artifact evidence",
            "frontend route exists but API smoke fails",
            "docs claim done while API is missing",
        ],
    }


def checklist_dry_run(req: VisualChecklistIn) -> dict:
    api_paths = req.api_paths or [
        "/deepening/session-core/design",
        "/deepening/reasoning-depth/design",
        "/deepening/redqueen/evaluator-design",
        "/deepening/contracts/source-of-truth",
        "/deepening/visual-verification/protocol",
    ]
    return {
        "dry_run": True,
        "route": req.route,
        "page_name": req.page_name,
        "fallback_mode": req.fallback_mode,
        "checks": [
            {"id": "route", "expected": req.route, "method": "browser_or_hash_route"},
            {"id": "title", "expected": _REQUIRED_PANELS[0], "method": "visual_text_or_dist_token"},
            {"id": "navigation", "expected": "研究吸收 -> 深做追问", "method": "visual_text_or_src_token"},
            {"id": "panels", "expected": _REQUIRED_PANELS, "method": "visual_text_or_src_token"},
            {"id": "apis", "expected": api_paths, "method": "curl_smoke"},
        ],
        "evidence_policy": "record real browser evidence when available; otherwise record curl, dist, and src token evidence",
    }
