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

SYSTEMS = [
    {"id": "memoryarena_workbench", "name": "MemoryArena Workbench", "source": "MemoryArena", "status": "partial", "api_count": 1},
    {"id": "hippo_lite", "name": "Hippo-Lite Graph Recall", "source": "HippoRAG", "status": "partial", "api_count": 2},
    {"id": "memorybank_retention", "name": "MemoryBank Retention Engine", "source": "MemoryBank", "status": "partial", "api_count": 2},
    {"id": "reflexion_evaluator", "name": "Reflexion Evaluator", "source": "Reflexion", "status": "partial", "api_count": 2},
    {"id": "memory_tools_api", "name": "Memory Tools API", "source": "AgeMem / Agentic Memory", "status": "partial", "api_count": 2},
    {"id": "memcube_capsule", "name": "MemCube / MemoryCapsule 2.1", "source": "MemOS", "status": "planned", "api_count": 1},
    {"id": "memory_tier_manager", "name": "Memory Tier Manager", "source": "MemGPT", "status": "planned", "api_count": 1},
    {"id": "locomo_long_session", "name": "LoCoMo Long-Session Template", "source": "LoCoMo", "status": "planned", "api_count": 1},
    {"id": "generative_memory_stream", "name": "Generative Agents Memory Stream", "source": "Generative Agents", "status": "planned", "api_count": 1},
]


def list_systems() -> dict:
    return {
        "edition": "v0.9 lightweight research system reproduction layer",
        "boundary": "lightweight_reproduction_not_full_official_reproduction",
        "items": SYSTEMS,
        "summary": {
            "systems": len(SYSTEMS),
            "partial": sum(1 for item in SYSTEMS if item["status"] == "partial"),
            "planned": sum(1 for item in SYSTEMS if item["status"] == "planned"),
            "api_count": sum(item["api_count"] for item in SYSTEMS),
        },
    }
