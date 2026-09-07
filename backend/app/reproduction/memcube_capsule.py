# Copyright (c) 2026 QianChang-official
#
# 宛委·枢忆 is licensed under Mulan PSL v2.
# You can use this software according to the terms of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
# http://license.coscl.org.cn/MulanPSL2
#
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

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
