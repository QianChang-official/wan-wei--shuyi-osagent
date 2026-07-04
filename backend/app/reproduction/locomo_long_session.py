def template() -> dict:
    sessions = [
        {
            "session_id": f"locomo_s{i:02d}",
            "event_type": "preference" if i in {2, 5, 8} else "task_event",
            "expected_memory_link": f"locomo_s{max(1, i-2):02d}" if i > 2 else None,
            "qa_probe": "Ask a timeline or consistency question about previous sessions.",
        }
        for i in range(1, 11)
    ]
    return {
        "status": "locomo_long_session_template_planned",
        "boundary": "10-session template only; no LoCoMo benchmark score is claimed.",
        "sessions": sessions,
        "event_graph_schema": {"nodes": ["session", "event", "entity"], "edges": ["mentions", "updates", "contradicts", "depends_on"]},
        "timeline_qa_schema": {"question": "string", "answer_session_ids": [], "consistency_required": True},
        "long_range_consistency_check": ["entity_state_consistency", "preference_update_order", "contradiction_detection"],
    }
