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

"""空列表时自动兜底一个智能体 —— 消除「必须先新建才能用」。

约束（每条都有对应测试）：
- 幂等：已有智能体时绝不干预
- per-owner：A 身份不会看到 B 身份的默认智能体
- 不复活：用户删掉默认智能体后不再重建
- 不越权：默认智能体不带provider 绑定，走端点回退链
- 不阻断：创建失败时列表仍返回空列表而非 500
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

HEADER = {"x-api-key": "test-key"}


def _client(tmp_path, *, api_key: str = "test-key"):
    os.environ["WANWEI_API_KEY"] = api_key
    os.environ["WANWEI_MEMORY_DB"] = str(tmp_path / "memory.db")
    os.environ.pop("WANWEI_PRODUCTION", None)
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    import backend.app.app_runtime as runtime_mod
    import backend.app.main as main_mod
    importlib.reload(runtime_mod)
    importlib.reload(main_mod)
    return TestClient(main_mod.app, raise_server_exceptions=False)


@pytest.fixture()
def client(tmp_path):
    return _client(tmp_path)


@pytest.fixture()
def fresh(tmp_path):
    """每个用例一份干净的 agents 存储。"""
    import backend.app.platform_api.agents as agents_mod

    agents_mod._agents._write({})  # noqa: SLF001
    yield agents_mod


def test_empty_list_gets_usable_agent_immediately(client, fresh):
    """核心诉求：不新建也能用。"""
    r = client.get("/platform/agents", headers=HEADER)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    agent = body["items"][0]
    assert agent["name"] == "枢忆"
    assert agent["is_default"] is True
    # 关键：必须能直接发起对话的完整形态
    assert agent["id"]
    assert agent["depth"]
    assert agent["gear"]
    assert "permissions" in agent


def test_bootstrap_is_idempotent(client, fresh):
    """反复拉列表不会造出一堆默认智能体。"""
    first = client.get("/platform/agents", headers=HEADER).json()
    second = client.get("/platform/agents", headers=HEADER).json()
    third = client.get("/platform/agents", headers=HEADER).json()
    assert first["total"] == second["total"] == third["total"] == 1
    assert first["items"][0]["id"] == third["items"][0]["id"]


def test_existing_agents_are_never_touched(client, fresh):
    """已有智能体时不做任何干预——不改名、不覆盖、不追加。"""
    created = client.post(
        "/platform/agents",
        json={"name": "我的分析师", "role": "数据", "depth": "high", "gear": "sandbox"},
        headers=HEADER,
    )
    assert created.status_code == 201, created.text
    aid = created.json()["id"]

    body = client.get("/platform/agents", headers=HEADER).json()
    assert body["total"] == 1
    only = body["items"][0]
    assert only["id"] == aid
    assert only["name"] == "我的分析师"
    assert only["role"] == "数据"
    assert only["depth"] == "high"
    assert only.get("is_default") is not True


def test_deleted_default_is_not_resurrected(client, fresh):
    """用户删掉默认智能体后，必须尊重这个选择。"""
    seeded = client.get("/platform/agents", headers=HEADER).json()["items"][0]
    deleted = client.delete(f"/platform/agents/{seeded['id']}", headers=HEADER)
    assert deleted.status_code == 200, deleted.text

    again = client.get("/platform/agents", headers=HEADER).json()
    assert again["total"] == 0, "被用户删除的默认智能体不应复活"
    assert again["items"] == []

    # 再拉一次仍为空，墓碑必须持久生效
    assert client.get("/platform/agents", headers=HEADER).json()["total"] == 0


def test_default_binds_no_provider(client, fresh):
    """默认智能体不绑 provider —— 这样后配好的端点无需重建智能体即可生效。"""
    agent = client.get("/platform/agents", headers=HEADER).json()["items"][0]
    assert agent["provider_pid"] == ""
    assert agent["model"] == ""


def test_tombstone_key_is_hidden_from_listing(client, fresh):
    """墓碑是下划线开头的内部键，绝不能混进智能体列表。"""
    import backend.app.platform_api.agents as agents_mod

    seeded = client.get("/platform/agents", headers=HEADER).json()["items"][0]
    client.delete(f"/platform/agents/{seeded['id']}", headers=HEADER)

    raw = agents_mod._agents.all()  # noqa: SLF001
    assert agents_mod._DEFAULT_AGENT_DELETED in raw
    public_ids = {a["id"] for a in client.get("/platform/agents", headers=HEADER).json()["items"]}
    assert agents_mod._DEFAULT_AGENT_DELETED not in public_ids
    # _agents_map 过滤掉下划线键
    assert agents_mod._DEFAULT_AGENT_DELETED not in agents_mod._agents_map()  # noqa: SLF001


def test_bootstrap_failure_does_not_break_listing(client, fresh, monkeypatch):
    """兜底逻辑出错时，列表必须仍返回 200 + 空列表，而不是 500。"""
    import backend.app.platform_api.agents as agents_mod

    def boom(_agent):
        raise RuntimeError('store offline')

    monkeypatch.setattr(agents_mod._agents, 'set', boom)
    r = client.get("/platform/agents", headers=HEADER)
    assert r.status_code == 200, r.text
    assert r.json() == {'items': [], 'total': 0}


def test_bootstrap_does_not_fabricate_agent_for_every_owner(client, fresh):
    """系统里已有智能体时，新身份不得凭空获得一个默认智能体。

    兜底只解决「全新安装的第一次使用」，不该给每个身份都造一个——
    那等于凭空扩大数据面，并破坏「某身份名下为空就是为空」的既有语义。
    """
    import backend.app.platform_api.agents as agents_mod
    original = agents_mod.actor_id_for_request

    def as_owner_b(request):
        return original(request) if request.headers.get('x-owner') != 'b' else 'owner-b'

    agents_mod.actor_id_for_request = as_owner_b
    try:
        a = client.get("/platform/agents", headers=HEADER).json()
        assert a["total"] == 1, "身份 a 首次进入应获得默认智能体"
        seed_a = a["items"][0]["id"]

        b = client.get("/platform/agents", headers={**HEADER, 'x-owner': 'b'}).json()
        assert b["total"] == 0, "系统非空时，身份 b 不得被凭空塞一个智能体"
        assert seed_a not in {item["id"] for item in b["items"]}
    finally:
        agents_mod.actor_id_for_request = original


def test_fresh_owner_gets_own_default_when_system_is_empty(client, fresh):
    """系统为空时，换个身份访问，得到的是绑定自己的默认智能体。"""
    import backend.app.platform_api.agents as agents_mod
    original = agents_mod.actor_id_for_request

    def as_owner_b(request):
        return original(request) if request.headers.get('x-owner') != 'b' else 'owner-b'

    agents_mod.actor_id_for_request = as_owner_b
    try:
        # 身份 b 先来，系统此刻为空
        b = client.get("/platform/agents", headers={**HEADER, 'x-owner': 'b'}).json()
        assert b["total"] == 1
        seed_b = b["items"][0]["id"]
        # 身份 a 再来：系统已非空，a 应为空列表且看不到 b 的
        a = client.get("/platform/agents", headers=HEADER).json()
        assert a["total"] == 0
        assert seed_b not in {item["id"] for item in a["items"]}
    finally:
        agents_mod.actor_id_for_request = original


def test_default_agent_can_be_renamed_and_kept(client, fresh):
    """默认智能体就是普通智能体：改名后不应被重置或替换。"""
    seeded = client.get("/platform/agents", headers=HEADER).json()["items"][0]
    r = client.put(
        f"/platform/agents/{seeded['id']}",
        json={"name": "我的枢忆", "persona": "严谨"},
        headers=HEADER,
    )
    assert r.status_code == 200, r.text
    items = client.get("/platform/agents", headers=HEADER).json()["items"]
    assert len(items) == 1
    assert items[0]["name"] == "我的枢忆"
    assert items[0]["persona"] == "严谨"