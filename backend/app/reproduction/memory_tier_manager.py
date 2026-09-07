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

from ..memory_runtime.capsule_store import list_capsules


def tiers(*, owner_id: str | None = None, soul_id: str | None = None) -> dict:
    if owner_id is None and soul_id is None:
        capsules = [cap for cap in list_capsules(100) if cap]
    else:
        capsules = [
            cap
            for cap in list_capsules(100, owner_id=owner_id, soul_id=soul_id)
            if cap
        ]
    active = [cap["capsule_id"] for cap in capsules if cap.get("state", {}).get("lifecycle") == "active"]
    archival = [cap["capsule_id"] for cap in capsules if cap.get("state", {}).get("lifecycle") in {"deprecated", "forgotten"}]
    working = active[:5]
    return {
        "status": "memory_tier_manager_planned",
        "boundary": "MemGPT-like tier manager simulation; no real context paging is performed.",
        "working_context": working,
        "active_capsules": active,
        "archival_capsules": archival,
        "paging_policy": {
            "promote_on_recall": True,
            "demote_when_retention_below": 0.2,
            "high_risk_requires_trust_check": True,
        },
        "context_budget": {"max_working_capsules": 5, "estimated_tokens": "pending_measurement"},
    }
