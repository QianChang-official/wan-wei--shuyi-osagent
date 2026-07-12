from __future__ import annotations

_CONTRACTS = [
    {"layer": "api", "artifact": "backend/app/main.py", "contract": "/deepening/* mounted", "status": "implemented"},
    {"layer": "schema", "artifact": "backend/app/deepening/schemas.py", "contract": "POST payloads are dry-run inputs", "status": "implemented"},
    {"layer": "frontend", "artifact": "frontend/console-vue/src/views/DeepeningView.vue", "contract": "page calls real same-origin APIs", "status": "implemented"},
    {"layer": "smoke", "artifact": "curl /deepening/*", "contract": "runtime response evidence", "status": "verification_required"},
    {"layer": "docs", "artifact": "文档中心_DOCUMENTATION_HUB.md#doc-v091-deep-expansion-visual-verification-9bd18cef", "contract": "done/partial/planned/pending boundary", "status": "implemented"},
]


def source_of_truth() -> dict:
    return {
        "version": "v0.9.1",
        "inspiration": "TriadJS single source of truth discipline",
        "boundary": "repository_contract_only_no_external_claims",
        "contracts": _CONTRACTS,
        "source_layers": {
            "accepted": ["file_content", "git_tracked", "runtime_log"],
            "ignored_for_residue": ["chat_render", "copied_text", "tool_display"],
        },
    }


def drift_check() -> dict:
    checks = [
        {"id": "api_schema", "expected": "main.py route imports match schemas", "status": "pass_by_contract"},
        {"id": "frontend_route", "expected": "/console/#/deepening route exists", "status": "verification_required"},
        {"id": "dist_sync", "expected": "npm run build refreshes dist", "status": "verification_required"},
        {"id": "arena_metrics", "expected": "v0.6 Arena remains 16/16", "status": "verification_required"},
        {"id": "docs_boundary", "expected": "partial/planned/pending not overstated", "status": "pass_by_contract"},
    ]
    return {"version": "v0.9.1", "drift_status": "requires_runtime_verification", "checks": checks}
