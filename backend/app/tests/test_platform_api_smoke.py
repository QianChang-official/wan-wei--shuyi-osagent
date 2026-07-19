"""D1: platform_api 八模块 TestClient 级 CRUD/契约冒烟。

每个模块只做最小 happy path + 一个边界断言，确保路由、鉴权、请求模型、
响应形状对齐。测试使用隔离的 WANWEI_PLATFORM_DIR + WANWEI_MEMORY_DB，不污染
本机 data/platform/。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _client(tmp_path, *, api_key: str = "test-key"):
    """构造隔离的 TestClient。"""
    os.environ["WANWEI_API_KEY"] = api_key
    os.environ["WANWEI_MEMORY_DB"] = str(tmp_path / "memory.db")
    os.environ["WANWEI_PLATFORM_DIR"] = str(tmp_path / "platform")
    os.environ.pop("WANWEI_PRODUCTION", None)

    import importlib
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    import backend.app.init_db
    import backend.app.main as main_mod

    importlib.reload(main_mod)
    backend.app.init_db.main()
    return TestClient(main_mod.app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# providers
# ---------------------------------------------------------------------------


def test_providers_catalog_and_aux(tmp_path):
    client = _client(tmp_path)
    h = {"x-api-key": "test-key"}

    r = client.get("/platform/providers/catalog", headers=h)
    assert r.status_code == 200, r.text
    catalog = r.json()
    assert isinstance(catalog, list)
    assert len(catalog) >= 1
    assert "pid" in catalog[0] or "id" in catalog[0]

    r = client.get("/platform/providers/aux", headers=h)
    assert r.status_code == 200, r.text

    r = client.put(
        "/platform/providers/aux",
        json={"pid": "openrouter", "model": "test-model"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json().get("pid") == "openrouter"


# ---------------------------------------------------------------------------
# agents
# ---------------------------------------------------------------------------


def test_agents_crud_and_context_size(tmp_path):
    client = _client(tmp_path)
    h = {"x-api-key": "test-key"}

    r = client.post(
        "/platform/agents",
        json={"name": "冒烟智能体", "depth": "medium", "gear": "sandbox"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    aid = r.json()["id"]

    r = client.get("/platform/agents", headers=h)
    assert r.status_code == 200, r.text
    agents = r.json().get("items", r.json())
    assert any(a.get("id") == aid for a in agents)

    r = client.get(f"/platform/agents/{aid}", headers=h)
    assert r.status_code == 200, r.text

    r = client.put(
        f"/platform/agents/{aid}",
        json={"goal": "完成冒烟测试"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json().get("goal") == "完成冒烟测试"

    r = client.get(f"/platform/agents/context-size?agent_id={aid}", headers=h)
    assert r.status_code == 200, r.text
    assert "total_tokens" in r.json()


# ---------------------------------------------------------------------------
# spaces
# ---------------------------------------------------------------------------


def test_spaces_project_crud(tmp_path):
    client = _client(tmp_path)
    h = {"x-api-key": "test-key"}

    r = client.post(
        "/platform/spaces/projects",
        json={"name": "冒烟项目", "desc": "测试", "kind": "project_space"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    pid = r.json()["id"]

    r = client.get("/platform/spaces/projects", headers=h)
    assert r.status_code == 200, r.text
    payload = r.json()
    projects = payload if isinstance(payload, list) else payload.get("items", [])
    assert any(p.get("id") == pid for p in projects)

    r = client.get(f"/platform/spaces/projects/{pid}", headers=h)
    assert r.status_code == 200, r.text

    r = client.put(
        f"/platform/spaces/projects/{pid}",
        json={"name": "冒烟项目改名"},
        headers=h,
    )
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# automation
# ---------------------------------------------------------------------------


def test_automation_flows_crud(tmp_path):
    client = _client(tmp_path)
    h = {"x-api-key": "test-key"}

    r = client.get("/platform/automation/flows", headers=h)
    assert r.status_code == 200, r.text

    r = client.post(
        "/platform/automation/flows",
        json={"name": "冒烟工作流", "desc": "测试", "trigger": "manual"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    fid = r.json()["id"]

    r = client.get(f"/platform/automation/flows/{fid}", headers=h)
    assert r.status_code == 200, r.text

    r = client.put(
        f"/platform/automation/flows/{fid}",
        json={"enabled": False},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json().get("enabled") is False


# ---------------------------------------------------------------------------
# knowledge
# ---------------------------------------------------------------------------


def test_knowledge_doc_and_search(tmp_path):
    client = _client(tmp_path)
    h = {"x-api-key": "test-key"}

    r = client.post(
        "/platform/knowledge/docs",
        json={"title": "冒烟文档", "body": "这是测试内容", "tags": ["test"]},
        headers=h,
    )
    assert r.status_code == 201, r.text
    did = r.json()["id"]

    r = client.get(f"/platform/knowledge/docs/{did}", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "冒烟文档"

    r = client.get("/platform/knowledge/search?q=测试", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("engine") in ("fts5", "like")


# ---------------------------------------------------------------------------
# memory_center
# ---------------------------------------------------------------------------


def test_memory_center_remember_and_sessions(tmp_path):
    client = _client(tmp_path)
    h = {"x-api-key": "test-key"}

    r = client.post(
        "/platform/memory/remember",
        json={"text": "记住：冒烟测试通过后要归档"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    r = client.get("/platform/memory/instructions", headers=h)
    assert r.status_code == 200, r.text
    lines = r.json().get("lines", [])
    assert any("冒烟测试" in line for line in lines)

    r = client.get("/platform/memory/sessions", headers=h)
    assert r.status_code == 200, r.text
    assert "source" in r.json()

    r = client.get("/platform/memory/dreams/schedule", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is False


# ---------------------------------------------------------------------------
# system_svc
# ---------------------------------------------------------------------------


def test_system_settings_and_health(tmp_path):
    client = _client(tmp_path)
    h = {"x-api-key": "test-key"}

    r = client.get("/platform/system/health", headers=h)
    assert r.status_code == 200, r.text

    r = client.get("/platform/system/settings", headers=h)
    assert r.status_code == 200, r.text
    assert "theme" in r.json()

    r = client.put(
        "/platform/system/settings",
        json={"theme": "auto"},
        headers=h,
    )
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# mcp_hub
# ---------------------------------------------------------------------------


def test_mcp_servers_crud_and_enabled_gate(tmp_path):
    client = _client(tmp_path)
    h = {"x-api-key": "test-key"}

    r = client.get("/platform/mcp/servers", headers=h)
    assert r.status_code == 200, r.text

    r = client.post(
        "/platform/mcp/servers",
        json={
            "name": "冒烟 MCP",
            "transport": "stdio",
            "command": "echo",
            "enabled": False,
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]

    r = client.get(f"/platform/mcp/servers/{sid}", headers=h)
    assert r.status_code == 200, r.text

    # 未启用时调用应被门禁拦截（403），而不是去拉真实进程
    r = client.post(
        f"/platform/mcp/servers/{sid}/call",
        json={"tool": "test", "arguments": {}},
        headers=h,
    )
    assert r.status_code == 403, r.text
