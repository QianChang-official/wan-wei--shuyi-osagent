"""Cross-API-key isolation tests for the MCP hub persistence boundary."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


OWNER_A = "mcp-owner-a"
OWNER_B = "mcp-owner-b"
HEADERS_A = {"x-api-key": OWNER_A}
HEADERS_B = {"x-api-key": OWNER_B}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WANWEI_API_KEY", OWNER_A)
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.setenv("WANWEI_PLATFORM_DIR", str(tmp_path / "platform"))
    monkeypatch.delenv("WANWEI_PRODUCTION", raising=False)
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

    import app.security.auth as auth
    import backend.app.security.auth as backend_auth

    verify = lambda provided: provided in {OWNER_A, OWNER_B}
    monkeypatch.setattr(auth, "_verify_api_key", verify)
    monkeypatch.setattr(backend_auth, "_verify_api_key", verify)

    import backend.app.main as main_mod

    importlib.reload(main_mod)
    with TestClient(main_mod.app, raise_server_exceptions=False) as test_client:
        yield test_client


def _create_server(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post(
        "/platform/mcp/servers",
        json={
            "name": "owner-isolation",
            "transport": "stdio",
            "command": None,
            "enabled": True,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert "owner_id" not in payload
    return payload["id"]


def test_mcp_server_crud_and_runtime_actions_are_owner_scoped(client):
    sid = _create_server(client, HEADERS_A)

    own = client.get(f"/platform/mcp/servers/{sid}", headers=HEADERS_A)
    assert own.status_code == 200, own.text
    assert "owner_id" not in own.json()
    assert sid in {item["id"] for item in client.get(
        "/platform/mcp/servers", headers=HEADERS_A,
    ).json()["servers"]}

    other_list = client.get("/platform/mcp/servers", headers=HEADERS_B)
    assert other_list.status_code == 200, other_list.text
    assert sid not in {item["id"] for item in other_list.json()["servers"]}

    # A foreign principal cannot read, mutate, delete, discover, or call it.
    assert client.get(f"/platform/mcp/servers/{sid}", headers=HEADERS_B).status_code == 404
    assert client.put(
        f"/platform/mcp/servers/{sid}",
        json={"name": "hijacked"},
        headers=HEADERS_B,
    ).status_code == 404
    assert client.delete(f"/platform/mcp/servers/{sid}", headers=HEADERS_B).status_code == 404
    assert client.get(f"/platform/mcp/servers/{sid}/tools", headers=HEADERS_B).status_code == 404
    assert client.post(
        f"/platform/mcp/servers/{sid}/call",
        json={"tool": "probe"},
        headers=HEADERS_B,
    ).status_code == 404

    # The owner can still use the existing honest-not-connected behavior.
    own_call = client.post(
        f"/platform/mcp/servers/{sid}/call",
        json={"tool": "probe"},
        headers=HEADERS_A,
    )
    assert own_call.status_code == 503, own_call.text


def test_mcp_recent_calls_and_overview_are_owner_scoped(client):
    sid_a = _create_server(client, HEADERS_A)
    sid_b = _create_server(client, HEADERS_B)

    response_a = client.post(
        f"/platform/mcp/servers/{sid_a}/call",
        json={"tool": "owner-a-tool", "arguments": {"query": "a"}},
        headers=HEADERS_A,
    )
    response_b = client.post(
        f"/platform/mcp/servers/{sid_b}/call",
        json={"tool": "owner-b-tool", "arguments": {"query": "b"}},
        headers=HEADERS_B,
    )
    assert response_a.status_code == 503
    assert response_b.status_code == 503

    overview_a = client.get("/platform/mcp/overview", headers=HEADERS_A)
    overview_b = client.get("/platform/mcp/overview", headers=HEADERS_B)
    assert overview_a.status_code == 200
    assert overview_b.status_code == 200
    assert overview_a.json()["servers"] >= 1
    assert overview_b.json()["servers"] >= 1
    assert sid_a in {
        item["id"]
        for item in client.get("/platform/mcp/servers", headers=HEADERS_A).json()["servers"]
    }
    assert sid_a not in {
        item["id"]
        for item in client.get("/platform/mcp/servers", headers=HEADERS_B).json()["servers"]
    }
    history_a = overview_a.json()["recent_calls"]
    history_b = overview_b.json()["recent_calls"]
    assert [item["tool"] for item in history_a] == ["owner-a-tool"]
    assert [item["tool"] for item in history_b] == ["owner-b-tool"]
    assert all("owner_id" not in item for item in history_a + history_b)


def test_ownerless_legacy_mcp_server_binds_only_to_compatible_actor(client):
    from backend.app.platform_api import mcp_hub

    mcp_hub._store.set(  # noqa: SLF001
        "srv_legacy_ownerless",
        {
            "id": "srv_legacy_ownerless",
            "name": "legacy-ownerless",
            "transport": "sse",
            "url": "https://example.invalid/mcp",
            "enabled": False,
            "status": "unknown",
        },
    )

    assert client.get(
        "/platform/mcp/servers/srv_legacy_ownerless",
        headers=HEADERS_A,
    ).status_code == 200
    assert client.get(
        "/platform/mcp/servers/srv_legacy_ownerless",
        headers=HEADERS_B,
    ).status_code == 404

    stored = mcp_hub._store.get("srv_legacy_ownerless")  # noqa: SLF001
    assert stored["owner_id"]
    assert stored["owner_id"] != "anonymous"
