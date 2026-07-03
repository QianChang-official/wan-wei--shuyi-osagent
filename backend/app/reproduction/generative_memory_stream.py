def template() -> dict:
    return {
        "status": "generative_memory_stream_template_planned",
        "boundary": "Generative Agents-inspired stream schema; no autonomous social simulation is claimed.",
        "observation_stream_schema": {
            "observation_id": "obs_xxx",
            "timestamp": "iso8601",
            "actor": "agent_or_user",
            "content": "string",
            "source_layer": "runtime_log|file_content|user_input",
        },
        "importance_score": {"range": [0, 1], "default": 0.5, "signals": ["novelty", "user_feedback", "risk", "task_relevance"]},
        "reflection_trigger": {"importance_threshold": 0.75, "batch_size": 5, "requires_evidence": True},
        "plan_timeline": [
            {"phase": "observe", "output": "observation_stream"},
            {"phase": "reflect", "output": "candidate_reflections"},
            {"phase": "plan", "output": "auditable_plan_steps"},
        ],
    }
