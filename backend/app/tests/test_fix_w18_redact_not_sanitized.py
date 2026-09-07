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

"""FIX-05: redact capsules are sanitized at every outbound boundary."""

from copy import deepcopy
import json

import pytest


SEARCH_TOKEN = "fix05redactionboundary"
SENSITIVE_EMAILS = {
    "alice@example.com",
    "summary@example.com",
    "statement@example.com",
    "nested@example.com",
    "list@example.com",
    "deep@example.com",
}


def _serialized(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _assert_sanitized(value) -> None:
    serialized = _serialized(value)
    for email in SENSITIVE_EMAILS:
        assert email not in serialized
    assert "[REDACTED_EMAIL]" in serialized


def _find_by_capsule_id(items: list[dict], capsule_id: str) -> dict:
    target = next(
        (
            item for item in items
            if item.get("capsule_id") == capsule_id or item.get("id") == capsule_id
        ),
        None,
    )
    assert target is not None, f"capsule {capsule_id} was not returned"
    return target


@pytest.fixture()
def soul_with_redact_memory(isolated_db):
    """Create a retrievable redact capsule with secrets in varied shapes."""
    from backend.app.memory_runtime.capsule_store import write_capsule
    from backend.app.soul.persona import create_persona

    soul_id = create_persona()
    original_content = {
        "text": f"{SEARCH_TOKEN} 我的邮箱是 alice@example.com，请记住",
        "summary": "摘要联系人 summary@example.com",
        "statement": "证据联系人 statement@example.com",
        "arbitrary_field": "任意字段 nested@example.com",
        "nested": {
            "items": [
                "列表联系人 list@example.com",
                {"deep": "深层联系人 deep@example.com"},
            ]
        },
    }
    capsule = write_capsule(
        memory_class="knowledge",
        soul_id=soul_id,
        content=original_content,
        provenance={"source": "user", "soul_id": soul_id},
        source_type="user_input",
        write_intent="explicit",
    )
    assert capsule["governance"]["policy_result"] == "redact"

    from backend.app.db import get_conn
    conn = get_conn()
    conn.execute(
        """UPDATE memory_capsules_v2 
           SET state = json_set(state, '$.importance_score', ?)
           WHERE capsule_id = ?""",
        (0.9, capsule["capsule_id"]),
    )
    conn.commit()

    return soul_id, capsule["capsule_id"], original_content


# --- 系统提示注入脱敏 -------------------------------------------------


def test_redact_memory_sanitized_in_injection_prompt(soul_with_redact_memory):
    from backend.app.soul.injector import build_injection_prompt

    soul_id, _, _ = soul_with_redact_memory

    prompt = build_injection_prompt(soul_id)
    _assert_sanitized(prompt)


# --- v2 API 返回脱敏（通过直接调用函数测试）--------------------------


def test_redact_memory_sanitized_in_get_capsule(soul_with_redact_memory):
    from backend.app.app_runtime import v2_get_capsule

    _, capsule_id, _ = soul_with_redact_memory

    cap = v2_get_capsule(capsule_id)
    _assert_sanitized(cap)


def test_redact_memory_sanitized_in_list_capsules(soul_with_redact_memory):
    from backend.app.app_runtime import v2_list_capsules

    _, capsule_id, _ = soul_with_redact_memory

    response = v2_list_capsules(limit=50)
    target = _find_by_capsule_id(response["items"], capsule_id)
    _assert_sanitized(target)


def test_redact_memory_sanitized_in_search(soul_with_redact_memory):
    from backend.app.app_runtime import v2_search

    _, capsule_id, _ = soul_with_redact_memory

    response = v2_search(q=SEARCH_TOKEN, top_k=5, high_risk=False)
    target = _find_by_capsule_id(response["results"], capsule_id)
    evidence = _find_by_capsule_id(response["evidence_cards"], capsule_id)
    _assert_sanitized(target)
    _assert_sanitized(evidence)


def test_redact_memory_sanitized_in_command(soul_with_redact_memory):
    from backend.app.app_runtime import v2_command
    from backend.app.schemas import CommandLoopIn

    _, capsule_id, _ = soul_with_redact_memory

    response = v2_command(CommandLoopIn(goal=SEARCH_TOKEN, top_k=5))
    memory = _find_by_capsule_id(response["recalled_memories"], capsule_id)
    evidence = _find_by_capsule_id(response["evidence_cards"], capsule_id)
    _assert_sanitized(memory)
    _assert_sanitized(evidence)


def test_redact_memory_sanitized_in_forget_preview(soul_with_redact_memory):
    from backend.app.app_runtime import forget_preview
    from backend.app.schemas import ForgetPreviewIn

    _, capsule_id, _ = soul_with_redact_memory

    response = forget_preview(ForgetPreviewIn(instruction=SEARCH_TOKEN))
    candidate = _find_by_capsule_id(response["candidates"], capsule_id)
    _assert_sanitized(candidate)


def test_redact_memory_sanitized_in_soul_state(soul_with_redact_memory):
    from backend.app.soul.injector import get_soul_state

    soul_id, capsule_id, _ = soul_with_redact_memory

    state = get_soul_state(soul_id)
    memory = _find_by_capsule_id(state["core_memories"], capsule_id)
    _assert_sanitized(memory)


def test_redact_memory_sanitized_in_reproduction_graph(soul_with_redact_memory):
    from backend.app.reproduction.hippo_lite import graph

    _, capsule_id, _ = soul_with_redact_memory

    node = _find_by_capsule_id(graph()["nodes"], capsule_id)
    assert "alice@example.com" not in _serialized(node)
    assert "[REDACTED_EMAIL]" in _serialized(node)


def test_redact_policy_sanitizes_complete_injection_prompt(isolated_db):
    from backend.app.soul.injector import build_injection_prompt
    from backend.app.soul.persona import create_persona, update_persona

    soul_id = create_persona()
    update_persona(soul_id, self_narrative="Contact persona@example.com")

    prompt = build_injection_prompt(soul_id)
    assert "persona@example.com" not in prompt
    assert "[REDACTED_EMAIL]" in prompt


def test_outbound_paths_do_not_mutate_stored_capsule(soul_with_redact_memory):
    from backend.app.app_runtime import (
        forget_preview,
        v2_command,
        v2_get_capsule,
        v2_list_capsules,
        v2_search,
    )
    from backend.app.memory_runtime.capsule_store import get_capsule
    from backend.app.schemas import CommandLoopIn, ForgetPreviewIn
    from backend.app.soul.injector import build_injection_prompt, get_soul_state

    soul_id, capsule_id, original_content = soul_with_redact_memory
    stored_before = deepcopy(get_capsule(capsule_id))

    v2_get_capsule(capsule_id)
    v2_list_capsules(limit=50)
    v2_search(q=SEARCH_TOKEN, top_k=5, high_risk=False)
    v2_command(CommandLoopIn(goal=SEARCH_TOKEN, top_k=5))
    forget_preview(ForgetPreviewIn(instruction=SEARCH_TOKEN))
    build_injection_prompt(soul_id)
    get_soul_state(soul_id)

    stored_after = get_capsule(capsule_id)
    assert stored_after["content"] == stored_before["content"] == original_content
    assert stored_after["governance"] == stored_before["governance"]
    assert stored_after["provenance"] == stored_before["provenance"]


def test_output_helper_returns_independent_copy(soul_with_redact_memory):
    from backend.app.memory_runtime.capsule_store import get_capsule
    from backend.app.security.redaction import redact_capsule_for_output

    _, capsule_id, _ = soul_with_redact_memory
    stored_capsule = get_capsule(capsule_id)
    original_snapshot = deepcopy(stored_capsule)

    output = redact_capsule_for_output(stored_capsule)

    assert stored_capsule == original_snapshot
    assert output is not stored_capsule
    assert output["content"] is not stored_capsule["content"]
    _assert_sanitized(output)


# --- allow 记忆不误伤 --------------------------------------------------


def test_allow_memory_not_affected(isolated_db):
    from backend.app.memory_runtime.capsule_store import get_capsule, write_capsule
    from backend.app.security.redaction import redact_capsule_for_output
    from backend.app.soul.injector import build_injection_prompt
    from backend.app.soul.persona import create_persona

    soul_id = create_persona()
    original_content = {
        "text": "今天天气很好，去公园散步了",
        "nested": {"items": ["带一瓶水", {"note": "下午回来"}]},
    }
    capsule = write_capsule(
        memory_class="knowledge",
        soul_id=soul_id,
        content=original_content,
        provenance={"source": "user", "soul_id": soul_id},
        source_type="user_input",
    )

    from backend.app.db import get_conn
    conn = get_conn()
    conn.execute(
        """UPDATE memory_capsules_v2 
           SET state = json_set(state, '$.importance_score', ?)
           WHERE capsule_id = ?""",
        (0.8, capsule["capsule_id"]),
    )
    conn.commit()

    prompt = build_injection_prompt(soul_id)
    assert "今天天气很好" in prompt
    assert "去公园散步了" in prompt

    from backend.app.app_runtime import v2_get_capsule
    cap = v2_get_capsule(capsule["capsule_id"])
    assert cap["content"] == original_content

    stored_capsule = get_capsule(capsule["capsule_id"])
    output_copy = redact_capsule_for_output(stored_capsule)
    assert output_copy == stored_capsule
    assert output_copy is not stored_capsule
    assert output_copy["content"] is not stored_capsule["content"]
    assert output_copy["content"]["nested"] is not stored_capsule["content"]["nested"]
