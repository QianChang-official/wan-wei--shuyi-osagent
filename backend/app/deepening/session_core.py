from __future__ import annotations


def design() -> dict:
    fields = [
        {"name": "session_id", "purpose": "stable conversation or task run id", "source_layer": "runtime_log"},
        {"name": "title", "purpose": "human-readable task label", "source_layer": "file_content"},
        {"name": "source", "purpose": "cli, console, gateway, eval, or imported trace", "source_layer": "runtime_log"},
        {"name": "messages_summary", "purpose": "compressed user/assistant intent summary", "source_layer": "runtime_log"},
        {"name": "tool_trace_summary", "purpose": "tool calls, status, and evidence handles", "source_layer": "runtime_log"},
        {"name": "memory_trace_summary", "purpose": "retrieval/write/forget/reflection decisions", "source_layer": "file_content"},
        {"name": "compression_state", "purpose": "token pressure and compression boundary", "source_layer": "runtime_log"},
        {"name": "background_task_state", "purpose": "cron, worker, or pending async job status", "source_layer": "runtime_log"},
        {"name": "visual_validation_state", "purpose": "browser or fallback verification artifact", "source_layer": "runtime_log"},
        {"name": "searchable_index", "purpose": "FTS/vector-ready searchable fields", "source_layer": "file_content"},
        {"name": "export_format", "purpose": "JSON/Markdown/report package contract", "source_layer": "file_content"},
    ]
    return {
        "version": "v0.9.1",
        "inspiration": "Hermes-style session core, adapted without reading Hermes private data",
        "boundary": "design_contract_only_no_private_session_access",
        "fields": fields,
        "design_rules": [
            "session traces are immutable evidence records once exported",
            "visual validation is recorded beside tool evidence, not treated as decoration",
            "compression stores summaries and source handles instead of mutating past evidence",
            "background tasks must expose pending/running/done/error states",
        ],
    }


def demo_trace() -> dict:
    return {
        "trace_id": "demo_v091_deepening_trace",
        "flow": [
            {"stage": "user_intent", "item": "review OSAgent full chain and find weak assumptions"},
            {"stage": "tool_calls", "item": ["read source files", "run compile/build", "smoke API"]},
            {"stage": "memory_events", "item": ["retrieve project lineage", "avoid copied_text residue false positives"]},
            {"stage": "evidence_cards", "item": ["git status", "compileall", "npm build", "Arena metrics"]},
            {"stage": "visual_validation", "item": ["browser screenshot if available", "dist chunk + API smoke fallback"]},
            {"stage": "audit_record", "item": "partial/planned/pending boundary written into docs"},
        ],
        "source_layer_policy": {
            "ignored_layers": ["chat_render", "copied_text", "tool_display"],
            "accepted_layers": ["file_content", "git_tracked", "runtime_log"],
        },
    }
