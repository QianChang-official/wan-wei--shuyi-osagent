def schema() -> dict:
    return {
        "status": "memcube_capsule_2_1_planned",
        "boundary": "Schema extension over MemoryCapsule 2.0; no migration is executed in v0.9.",
        "fields": {
            "memory_scope": ["user", "project", "team", "system"],
            "memory_tier": ["working", "active", "archival", "cold"],
            "scheduler_policy": {"refresh_after_days": 30, "decay_after_days": 90, "pinning": "optional"},
            "access_policy": {"mode": "readonly|advisory|supervised", "allowed_tools": [], "requires_confirmation": True},
            "migration_state": ["local", "staged", "migrating", "migrated", "failed"],
            "sync_state": ["local_only", "pending_export", "pending_merge", "synced", "conflict"],
            "version_vector": {"device_id": "counter"},
        },
        "compatibility_with_v2": "All fields can live under production_context/state/alignment_metadata without breaking v2 readers.",
    }
