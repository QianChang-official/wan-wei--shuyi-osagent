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

from __future__ import annotations


def pathways() -> dict:
    return {
        "version": "v0.9.1",
        "source": "From AGI to ASI pathway mapping, adapted as OSAgent roadmap framing",
        "boundary": "roadmap_mapping_not_capability_claim",
        "items": [
            {
                "path": "memory_governance_to_agent_reliability",
                "osagent_mapping": "Policy Gate + Evidence Cards + MemoryCapsule lifecycle",
                "current_state": "partial_runtime",
                "next_gate": "misleading_memory_rate real measurement",
            },
            {
                "path": "tool_use_to_supervised_autonomy",
                "osagent_mapping": "Tool Registry + MCP Skills + dry-run mutating tools",
                "current_state": "stub_and_dry_run",
                "next_gate": "permissioned write sandbox and audit replay",
            },
            {
                "path": "reflection_to_controlled_self_improvement",
                "osagent_mapping": "Reflection/Evolution + Red Queen evaluator proposals",
                "current_state": "proposal_only",
                "next_gate": "human-reviewed policy update workflow",
            },
            {
                "path": "long_session_memory_to_operating_system_layer",
                "osagent_mapping": "Session Core + LoCoMo template + exportable audit trace",
                "current_state": "design_and_template",
                "next_gate": "multi-session benchmark and compression regression tests",
            },
        ],
    }
