from __future__ import annotations

from .schemas import MemoryToolDryRunIn

TOOLS = [
    {"tool_name": "memory.add", "mode": "mutating", "requires_confirmation": True, "audit_required": True, "current_status": "planned"},
    {"tool_name": "memory.update", "mode": "mutating", "requires_confirmation": True, "audit_required": True, "current_status": "planned"},
    {"tool_name": "memory.delete", "mode": "mutating", "requires_confirmation": True, "audit_required": True, "current_status": "planned"},
    {"tool_name": "memory.retrieve", "mode": "readonly", "requires_confirmation": False, "audit_required": False, "current_status": "partial"},
    {"tool_name": "memory.summarize", "mode": "readonly", "requires_confirmation": False, "audit_required": True, "current_status": "partial"},
    {"tool_name": "memory.filter", "mode": "readonly", "requires_confirmation": False, "audit_required": False, "current_status": "partial"},
]


def list_tools() -> dict:
    return {
        "status": "memory_tools_api_partial",
        "boundary": "Mutating tools are dry-run only in v0.9.",
        "items": TOOLS,
    }


def dry_run(req: MemoryToolDryRunIn) -> dict:
    tool = next((item for item in TOOLS if item["tool_name"] == req.tool_name), None)
    if not tool:
        return {
            "status": "unknown_tool",
            "tool_name": req.tool_name,
            "would_do": None,
            "blocked_reason": "tool is not registered",
            "required_confirmation": True,
        }
    mutating = tool["mode"] == "mutating"
    return {
        "status": "dry_run_only",
        "tool_name": req.tool_name,
        "payload_preview": req.payload,
        "would_do": f"Validate and stage {req.tool_name} operation" if mutating else f"Run readonly {req.tool_name} operation",
        "blocked_reason": "mutating memory tools require supervised confirmation" if mutating else None,
        "required_confirmation": tool["requires_confirmation"],
        "audit_required": tool["audit_required"],
        "mutates_real_memory": False,
    }
