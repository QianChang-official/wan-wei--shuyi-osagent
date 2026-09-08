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

"""incidents 作用域口径回归测试（issue #175，方案 1）。

钉住已定口径：``memory_incidents`` 无 owner 维度，是**平台级全局治理事件流**
（发布闸门 / CI 复盘 / 前端治理总览页消费）——
- ``GET /memory/governance/incidents`` 不做 per-owner 过滤，任意持 key 者看到
  同一份完整列表，含指向其他 owner 记忆的 ``capsule_id`` 元数据；
- ``POST`` 仅在带 ``capsule_id`` 时校验可见性（跨 owner 404）；
- 自由文本长度上限落在 schema 层：``description`` max_length=2000（对齐
  ``input_limits.MAX_GOAL_LENGTH``），``detected_by`` 为受控词表——超长 422。

这些用例防止未来把 GET 误改成 per-owner 作用域，或松动输入口径而未察觉。
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

OWNER_A_KEY = "incident-owner-a-key-0123456789"
OWNER_B_KEY = "incident-owner-b-key-0123456789"


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("WANWEI_API_KEY", OWNER_A_KEY)
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.delenv("WANWEI_PRODUCTION", raising=False)

    from backend.app import init_db
    from backend.app import main as main_module
    from backend.app.db import close_all

    close_all()
    importlib.reload(main_module)
    init_db.main()
    return TestClient(main_module.app, raise_server_exceptions=False)


def _headers(api_key: str = OWNER_A_KEY) -> dict[str, str]:
    return {"x-api-key": api_key}


def _switch_actor(monkeypatch, api_key: str) -> None:
    # 与 test_memoryos_api 同款双 key 模拟：改 WANWEI_API_KEY 让该 key 成为
    # 当前有效 key，经 actor_id_from_api_key 派生独立 owner_id。
    monkeypatch.setenv("WANWEI_API_KEY", api_key)


def _post_incident(
    client: TestClient,
    *,
    api_key: str = OWNER_A_KEY,
    **body,
):
    payload = {
        "mhg_level": 2,
        "incident_type": "other",
        "description": "incidents scope 钉住",
    }
    payload.update(body)
    return client.post(
        "/memory/governance/incidents",
        headers=_headers(api_key),
        json=payload,
    )


def _write_capsule(client: TestClient, statement: str, *, api_key: str = OWNER_A_KEY) -> str:
    response = client.post(
        "/memory/v2/capsules",
        headers=_headers(api_key),
        json={
            "memory_class": "knowledge",
            "content": {"knowledge_type": "fact", "statement": statement},
            "source_type": "manual_config",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["capsule_id"]


def test_incidents_get_is_global_stream_across_owners(client, monkeypatch):
    """GET 是平台级全局流：不同 owner 记录的事故出现在同一份列表里。

    若未来被误改成 per-owner 作用域（按调用方过滤），owner B 记录的事故
    在 owner A 的 GET 里就会消失——本用例钉住该行为。
    """
    created_a = _post_incident(
        client, mhg_level=3, incident_type="leakage", description="owner-A 事故",
    )
    assert created_a.status_code == 200
    incident_a = created_a.json()["incident_id"]

    _switch_actor(monkeypatch, OWNER_B_KEY)
    created_b = _post_incident(
        client, api_key=OWNER_B_KEY, mhg_level=2, incident_type="poisoning",
        description="owner-B 事故",
    )
    assert created_b.status_code == 200
    incident_b = created_b.json()["incident_id"]

    # 任一持 key 的调用方看到的都是同一份完整全局流
    for viewer in (OWNER_A_KEY, OWNER_B_KEY):
        _switch_actor(monkeypatch, viewer)
        listed = client.get(
            "/memory/governance/incidents", headers=_headers(viewer),
        )
        assert listed.status_code == 200
        ids = {item["incident_id"] for item in listed.json()["items"]}
        assert incident_a in ids, f"viewer={viewer} 缺 owner-A 事故"
        assert incident_b in ids, f"viewer={viewer} 缺 owner-B 事故"


def test_incident_post_rejects_overlong_description(client):
    """description 超长（>2000）由 schema 层 422 拒绝，与 input_limits 口径一致。"""
    overlong = _post_incident(client, mhg_level=3, incident_type="leakage", description="x" * 2001)
    assert overlong.status_code == 422

    boundary = _post_incident(client, mhg_level=3, incident_type="leakage", description="x" * 2000)
    assert boundary.status_code == 200


def test_incident_post_detected_by_is_controlled_vocabulary(client):
    """detected_by 不接受任意长度自由文本：词表外取值 422。"""
    response = _post_incident(
        client, mhg_level=2, incident_type="leakage", detected_by="x" * 300,
    )
    assert response.status_code == 422


def test_incident_post_with_capsule_id_visibility_check_unchanged(client, monkeypatch):
    """带 capsule_id 的 POST 沿用兄弟端点可见性校验：跨 owner 404，属主 200。"""
    capsule_id = _write_capsule(client, "owner-A 记忆 capsule")

    # owner B 引用 owner A 的 capsule → 404（不泄漏存在性）
    _switch_actor(monkeypatch, OWNER_B_KEY)
    denied = _post_incident(
        client, api_key=OWNER_B_KEY, mhg_level=3, incident_type="leakage",
        capsule_id=capsule_id,
    )
    assert denied.status_code == 404

    # owner A 引用自己的 capsule → 200，且指向该 capsule 的事故进全局流
    _switch_actor(monkeypatch, OWNER_A_KEY)
    allowed = _post_incident(
        client, mhg_level=3, incident_type="leakage", capsule_id=capsule_id,
    )
    assert allowed.status_code == 200
    assert allowed.json()["capsule_id"] == capsule_id

    listed = client.get("/memory/governance/incidents", headers=_headers()).json()
    assert any(item["capsule_id"] == capsule_id for item in listed["items"])


def test_incident_post_then_get_roundtrip(client):
    """正常创建 + GET 可见的往返，钉住 list_incidents 返回体契约。"""
    created = _post_incident(
        client, mhg_level=2, incident_type="conflict_escalation",
        description="roundtrip 事故", detected_by="policy_gate",
    )
    assert created.status_code == 200
    body = created.json()
    assert body["capsule_id"] is None
    assert body["description"] == "roundtrip 事故"
    assert body["detected_by"] == "policy_gate"

    items = client.get("/memory/governance/incidents", headers=_headers()).json()["items"]
    assert any(item["incident_id"] == body["incident_id"] for item in items)
