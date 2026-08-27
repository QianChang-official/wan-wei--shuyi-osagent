"""Regression tests for per-API-key agent run ownership."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


OWNER_A = "owner-a-key"
OWNER_B = "owner-b-key"
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


def _create_agent(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post(
        "/platform/agents",
        json={"name": "owner-isolation", "gear": "human_review", "depth": "low"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_run(client: TestClient, headers: dict[str, str], agent_id: str) -> str:
    response = client.post(
        "/platform/agents/run",
        json={"agent_id": agent_id, "task": "owner-isolation"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert "owner_id" not in payload
    return payload["id"]


def test_run_reads_and_mutations_are_owner_scoped(client):
    agent_id = _create_agent(client, HEADERS_A)
    run_id = _create_run(client, HEADERS_A, agent_id)

    assert client.get(f"/platform/agents/runs/{run_id}", headers=HEADERS_A).status_code == 200
    listed_a = client.get("/platform/agents/runs", headers=HEADERS_A)
    assert listed_a.status_code == 200
    assert run_id in {item["id"] for item in listed_a.json()["items"]}

    # A second valid principal cannot discover or mutate the first principal's run.
    assert client.get(f"/platform/agents/runs/{run_id}", headers=HEADERS_B).status_code == 404
    listed_b = client.get("/platform/agents/runs", headers=HEADERS_B)
    assert listed_b.status_code == 200
    assert run_id not in {item["id"] for item in listed_b.json()["items"]}
    assert client.post(f"/platform/agents/runs/{run_id}/approve", headers=HEADERS_B).status_code == 404
    assert client.post(f"/platform/agents/runs/{run_id}/cancel", headers=HEADERS_B).status_code == 404

    child_attempt = client.post(
        "/platform/agents/subagent",
        json={"task": "cross-owner-child", "parent_run_id": run_id},
        headers=HEADERS_B,
    )
    assert child_attempt.status_code == 404, child_attempt.text


def test_subagent_and_floating_workspace_are_owner_scoped(client):
    agent_id = _create_agent(client, HEADERS_A)
    parent_id = _create_run(client, HEADERS_A, agent_id)
    child = client.post(
        "/platform/agents/subagent",
        json={"task": "child", "parent_run_id": parent_id},
        headers=HEADERS_A,
    )
    assert child.status_code == 201, child.text
    child_payload = child.json()
    child_id = child_payload["run"]["id"]
    session_id = child_payload["session"]["id"]
    assert "owner_id" not in child_payload["run"]
    assert "owner_id" not in child_payload["session"]

    own_workspace = client.get("/platform/agents/workspace/floating", headers=HEADERS_A)
    assert own_workspace.status_code == 200
    assert session_id in {item["id"] for item in own_workspace.json()["items"]}

    other_workspace = client.get("/platform/agents/workspace/floating", headers=HEADERS_B)
    assert other_workspace.status_code == 200
    assert session_id not in {item["id"] for item in other_workspace.json()["items"]}
    assert client.get(f"/platform/agents/runs/{child_id}", headers=HEADERS_B).status_code == 404
    assert client.post(f"/platform/agents/runs/{child_id}/cancel", headers=HEADERS_B).status_code == 404

    parent_attempt = client.post(
        "/platform/agents/subagent",
        json={"task": "cross-owner-parent", "parent_run_id": parent_id},
        headers=HEADERS_B,
    )
    assert parent_attempt.status_code == 404, parent_attempt.text


def test_ownerless_legacy_agents_and_teams_are_not_global(client):
    """Migration compatibility must not make unowned rows cross-key visible."""
    from backend.app.platform_api import agents as agents_mod

    agent_id = _create_agent(client, HEADERS_A)
    raw_agent = agents_mod._agents.get(agent_id)  # noqa: SLF001
    raw_agent.pop("owner_id", None)
    agents_mod._agents.set(agent_id, raw_agent)  # noqa: SLF001

    assert client.get(f"/platform/agents/{agent_id}", headers=HEADERS_A).status_code == 200
    assert client.get(f"/platform/agents/{agent_id}", headers=HEADERS_B).status_code == 404

    team = client.post(
        "/platform/agents/teams",
        json={"name": "legacy-team", "member_ids": [agent_id]},
        headers=HEADERS_A,
    )
    assert team.status_code == 201, team.text
    team_id = team.json()["id"]
    raw_team = agents_mod._teams_map().get(team_id)  # noqa: SLF001
    raw_team.pop("owner_id", None)
    agents_mod._save_team(team_id, raw_team)  # noqa: SLF001

    assert client.get(f"/platform/agents/teams/{team_id}", headers=HEADERS_A).status_code == 200
    assert client.get(f"/platform/agents/teams/{team_id}", headers=HEADERS_B).status_code == 404
