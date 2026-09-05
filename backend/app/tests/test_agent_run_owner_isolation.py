"""Regression tests for agent, team, run, and context-history ownership.

Ownerless legacy records belong only to the configured actor. New subagents
and floating sessions belong to the authenticated actor that creates them.
"""
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

    import backend.app.security.auth as auth
    import backend.app.init_db
    import backend.app.app_runtime as runtime_mod
    import backend.app.main as main_mod
    from backend.app.platform_api import agents as agents_mod

    verify = lambda provided: provided in {OWNER_A, OWNER_B}  # noqa: E731
    monkeypatch.setattr(auth, "_verify_api_key", verify)
    # Ownership assertions must not race background execution or call providers.
    monkeypatch.setattr(agents_mod, "_spawn", lambda coro: coro.close())
    monkeypatch.setattr(agents_mod, "_runs_agent_index", None)

    importlib.reload(runtime_mod)
    importlib.reload(main_mod)
    backend.app.init_db.main()
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
    assert isinstance(payload.get("owner_id"), str) and payload["owner_id"]
    return payload["id"]


def test_run_reads_and_mutations_are_owner_scoped(client):
    agent_id = _create_agent(client, HEADERS_A)
    run_id = _create_run(client, HEADERS_A, agent_id)

    assert client.get(f"/platform/agents/runs/{run_id}", headers=HEADERS_A).status_code == 200
    listed_a = client.get("/platform/agents/runs", headers=HEADERS_A)
    assert listed_a.status_code == 200
    assert run_id in {item["id"] for item in listed_a.json()["items"]}

    assert client.get(f"/platform/agents/runs/{run_id}", headers=HEADERS_B).status_code == 404
    listed_b = client.get("/platform/agents/runs", headers=HEADERS_B)
    assert listed_b.status_code == 200
    assert run_id not in {item["id"] for item in listed_b.json()["items"]}
    assert client.post(f"/platform/agents/runs/{run_id}/approve", headers=HEADERS_B).status_code == 404
    assert client.post(f"/platform/agents/runs/{run_id}/cancel", headers=HEADERS_B).status_code == 404

    for field in ("parent_run_id", "parent_id"):
        for parent_id in (run_id, "run_missing_parent"):
            attempt = client.post(
                "/platform/agents/subagent",
                json={"task": "inaccessible-parent", field: parent_id},
                headers=HEADERS_B,
            )
            assert attempt.status_code == 404, attempt.text


@pytest.mark.parametrize("headers,other_headers", [(HEADERS_A, HEADERS_B), (HEADERS_B, HEADERS_A)])
def test_subagent_and_floating_workspace_are_owner_scoped(client, headers, other_headers):
    from backend.app.platform_api import agents as agents_mod

    agent_id = _create_agent(client, headers)
    parent_id = _create_run(client, headers, agent_id)
    owner_id = agents_mod._runs.get(parent_id)["owner_id"]
    child = client.post(
        "/platform/agents/subagent",
        json={"task": "child", "parent_run_id": parent_id},
        headers=headers,
    )
    assert child.status_code == 201, child.text
    child_payload = child.json()
    child_id = child_payload["run"]["id"]
    session_id = child_payload["session"]["id"]
    assert child_payload["run"]["owner_id"] == owner_id
    assert child_payload["session"]["owner_id"] == owner_id
    assert agents_mod._runs.get(child_id)["owner_id"] == owner_id
    assert agents_mod._floating_map()[session_id]["owner_id"] == owner_id

    workspace = client.get("/platform/agents/workspace/floating", headers=headers)
    assert workspace.status_code == 200
    assert session_id in {item["id"] for item in workspace.json()["items"]}
    assert all("owner_id" not in item for item in workspace.json()["items"])
    assert client.get(f"/platform/agents/runs/{child_id}", headers=headers).status_code == 200

    workspace_other = client.get("/platform/agents/workspace/floating", headers=other_headers)
    assert workspace_other.status_code == 200
    assert session_id not in {item["id"] for item in workspace_other.json()["items"]}
    assert client.get(f"/platform/agents/runs/{child_id}", headers=other_headers).status_code == 404


@pytest.mark.parametrize("record", [{}, {"owner_id": None}, {"owner_id": ""}])
@pytest.mark.parametrize("helper_name", ["_agent_visible", "_team_visible", "_run_visible"])
def test_ownerless_visibility_requires_configured_actor(monkeypatch, record, helper_name):
    from backend.app.platform_api import agents as agents_mod

    monkeypatch.setattr(agents_mod, "configured_actor_id", lambda: "configured-actor")
    visible = getattr(agents_mod, helper_name)
    assert visible(record, "configured-actor")
    assert not visible(record, "other-actor")
    assert not visible(record, "")
    assert visible({"owner_id": "other-actor"}, "other-actor")
    assert not visible({"owner_id": "other-actor"}, "configured-actor")


def test_ownerless_legacy_records_are_only_visible_to_configured_actor(client):
    from backend.app.platform_api import agents as agents_mod

    agent_id = _create_agent(client, HEADERS_A)
    team = client.post(
        "/platform/agents/teams",
        json={"name": "legacy-team", "member_ids": [agent_id]},
        headers=HEADERS_A,
    )
    assert team.status_code == 201, team.text
    team_id = team.json()["id"]
    run_id = _create_run(client, HEADERS_A, agent_id)

    raw_agent = agents_mod._agents.get(agent_id)
    raw_agent.pop("owner_id")
    agents_mod._agents.set(agent_id, raw_agent)
    raw_team = agents_mod._teams_map()[team_id]
    raw_team.pop("owner_id")
    agents_mod._save_team(team_id, raw_team)
    raw_run = agents_mod._runs.get(run_id)
    raw_run.pop("owner_id")
    raw_run["status"] = "awaiting_review"
    agents_mod._runs.set(run_id, raw_run)
    session = agents_mod._register_floating(raw_run)

    for collection, record_id in (("", agent_id), ("/teams", team_id), ("/runs", run_id)):
        path = f"/platform/agents{collection}"
        assert client.get(f"{path}/{record_id}", headers=HEADERS_A).status_code == 200
        assert client.get(f"{path}/{record_id}", headers=HEADERS_B).status_code == 404
        for headers, expected in ((HEADERS_A, {record_id}), (HEADERS_B, set())):
            listed = client.get(path, headers=headers)
            assert listed.status_code == 200, listed.text
            assert {item["id"] for item in listed.json()["items"]} == expected
            assert listed.json()["total"] == len(expected)

    for path, patch in ((f"/platform/agents/{agent_id}", {"goal": "blocked"}),
                        (f"/platform/agents/teams/{team_id}", {"name": "blocked"})):
        assert client.put(path, json=patch, headers=HEADERS_B).status_code == 404
        assert client.delete(path, headers=HEADERS_B).status_code == 404
    for binding, record_id in (("agent_id", agent_id), ("team_id", team_id)):
        denied = client.post("/platform/agents/run", json={binding: record_id, "task": "blocked"}, headers=HEADERS_B)
        assert denied.status_code == 404, denied.text
    assert client.post("/platform/agents/chat", json={"agent_id": agent_id, "message": "blocked"}, headers=HEADERS_B).status_code == 404
    assert client.post("/platform/agents/teams", json={"name": "blocked", "member_ids": [agent_id]}, headers=HEADERS_B).status_code == 422
    assert client.get("/platform/agents/context-size", params={"agent_id": agent_id}, headers=HEADERS_B).status_code == 404
    for action in ("approve", "cancel"):
        assert client.post(f"/platform/agents/runs/{run_id}/{action}", headers=HEADERS_B).status_code == 404
    for headers, expected_status in ((HEADERS_B, 404), (HEADERS_A, 201)):
        spawned = client.post("/platform/agents/subagent", json={"parent_run_id": run_id, "task": "child"}, headers=headers)
        assert spawned.status_code == expected_status, spawned.text
        workspace = client.get("/platform/agents/workspace/floating", headers=headers)
        assert workspace.status_code == 200
        assert (session["id"] in {item["id"] for item in workspace.json()["items"]}) == (headers == HEADERS_A)

    assert client.post(f"/platform/agents/runs/{run_id}/approve", headers=HEADERS_A).status_code == 200
    assert client.post(f"/platform/agents/runs/{run_id}/cancel", headers=HEADERS_A).status_code == 200
    assert client.put(f"/platform/agents/{agent_id}", json={"goal": "allowed"}, headers=HEADERS_A).status_code == 200
    assert client.put(f"/platform/agents/teams/{team_id}", json={"name": "allowed"}, headers=HEADERS_A).status_code == 200
    assert client.delete(f"/platform/agents/teams/{team_id}", headers=HEADERS_A).status_code == 200
    assert client.delete(f"/platform/agents/{agent_id}", headers=HEADERS_A).status_code == 200


@pytest.mark.parametrize("headers", [HEADERS_A, HEADERS_B])
def test_context_size_filters_history_before_counting_and_truncating(client, headers):
    from backend.app.platform_api import agents as agents_mod

    agent_id = _create_agent(client, headers)
    owner_id = agents_mod._agents.get(agent_id)["owner_id"]
    visible_runs = []
    for i in range(12):
        run = {
            "id": f"run_owned_{i}", "agent_id": agent_id, "owner_id": owner_id,
            "task": f"owned-{i}", "result": "r" * 250,
            "created_at": f"2024-01-{i + 1:02d}",
        }
        agents_mod._runs.set(run["id"], run)
        visible_runs.append(run)
    legacy = {
        "id": "run_legacy", "agent_id": agent_id, "task": "legacy-history",
        "result": "legacy result", "created_at": "2024-02-01",
    }
    agents_mod._runs.set(legacy["id"], legacy)
    if headers == HEADERS_A:
        visible_runs.append(legacy)
    visible_runs.sort(key=lambda run: run["created_at"], reverse=True)
    expected_text = "".join(
        f'任务：{run["task"]}\n结果：{run["result"][:200]}\n'
        for run in visible_runs[:10]
    )
    # Newer foreign runs must not displace the owner's recent history.
    for i in range(12):
        agents_mod._runs.set(f"run_foreign_{i}", {
            "id": f"run_foreign_{i}", "agent_id": agent_id, "owner_id": "foreign-actor",
            "task": "private" * 500, "result": "private-result" * 100,
            "created_at": f"2025-01-{i + 1:02d}",
        })
    agents_mod._runs.set("run_other_agent", {
        "id": "run_other_agent", "agent_id": "another-agent", "owner_id": owner_id,
        "task": "unrelated", "created_at": "2026-01-01",
    })

    response = client.get("/platform/agents/context-size", params={"agent_id": agent_id}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["previews"]["history_runs"] == len(visible_runs)
    assert payload["history"] == agents_mod._est_tokens(expected_text)
    assert payload["total_tokens"] == payload["system_prompt"] + payload["memory_instructions"] + payload["history"]

    unbound = client.get("/platform/agents/context-size", headers=headers)
    assert unbound.status_code == 200, unbound.text
    assert unbound.json()["history"] == 0
    assert unbound.json()["previews"]["history_runs"] == 0
