"""Cross-principal isolation tests for Spaces projects and integrations.

The second key is explicitly provisioned in the test identity registry;
requests exercise the production authentication middleware.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


KEY_A = "spaces-owner-a"
KEY_B = "spaces-owner-b"
HEADERS_A = {"x-api-key": KEY_A}
HEADERS_B = {"x-api-key": KEY_B}


@pytest.fixture()
def client(tmp_path, monkeypatch, seed_identity):
    monkeypatch.setenv("WANWEI_API_KEY", KEY_A)
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.setenv("WANWEI_PLATFORM_DIR", str(tmp_path / "platform"))
    monkeypatch.delenv("WANWEI_PRODUCTION", raising=False)
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

    import backend.app.init_db
    import backend.app.app_runtime as runtime_mod
    import backend.app.main as main_mod

    importlib.reload(runtime_mod)
    importlib.reload(main_mod)
    backend.app.init_db.main()
    seed_identity(KEY_B)
    with TestClient(main_mod.app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_project_access_and_mutation_are_owner_scoped(client):
    created = client.post(
        "/platform/spaces/projects",
        json={"name": "owner-a-project"},
        headers=HEADERS_A,
    )
    assert created.status_code == 201, created.text
    pid = created.json()["id"]
    assert "owner_id" not in created.json()

    listed_b = client.get("/platform/spaces/projects", headers=HEADERS_B)
    assert listed_b.status_code == 200
    assert all(item["id"] != pid for item in listed_b.json())
    assert client.get(f"/platform/spaces/projects/{pid}", headers=HEADERS_B).status_code == 404
    assert client.put(
        f"/platform/spaces/projects/{pid}",
        json={"name": "hijacked"},
        headers=HEADERS_B,
    ).status_code == 404
    assert client.delete(
        f"/platform/spaces/projects/{pid}",
        headers=HEADERS_B,
    ).status_code == 404
    assert client.get(f"/platform/spaces/{pid}/commit-template", headers=HEADERS_B).status_code == 404
    assert client.post(
        f"/platform/spaces/{pid}/commit",
        json={"message": "feat(spaces): blocked"},
        headers=HEADERS_B,
    ).status_code == 404


def test_integrations_are_owner_scoped(client):
    bound = client.post(
        "/platform/spaces/integrations/github/bind",
        json={"token": "token-a", "account": "owner-a"},
        headers=HEADERS_A,
    )
    assert bound.status_code == 200, bound.text

    visible_b = client.get("/platform/spaces/integrations", headers=HEADERS_B)
    assert visible_b.status_code == 200
    github_b = next(item for item in visible_b.json() if item["kind"] == "github")
    assert github_b["bound"] is False

    assert client.post(
        "/platform/spaces/integrations/github/unbind",
        headers=HEADERS_B,
    ).status_code == 200
    visible_a = client.get("/platform/spaces/integrations", headers=HEADERS_A)
    github_a = next(item for item in visible_a.json() if item["kind"] == "github")
    assert github_a["bound"] is True
    assert client.post(
        "/platform/spaces/integrations/github/test",
        headers=HEADERS_B,
    ).json()["ok"] is False
