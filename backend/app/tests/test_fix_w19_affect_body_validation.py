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

"""Regression coverage for affect validation and knowledge body limits."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    backend_dir = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(backend_dir))
    monkeypatch.setenv("WANWEI_API_KEY", "test-key")
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.setenv("WANWEI_PLATFORM_DIR", str(tmp_path / "platform"))
    monkeypatch.delenv("WANWEI_PRODUCTION", raising=False)

    import importlib

    import backend.app.main as main_module
    from backend.app.db import close_all

    close_all()
    from backend.app import init_db

    init_db.main()
    importlib.reload(main_module)
    test_client = TestClient(main_module.app, raise_server_exceptions=False)
    yield test_client
    test_client.close()
    close_all()


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"x-api-key": "test-key"}


@pytest.mark.parametrize("raw_intensity", ["nan", "inf", "-inf"])
def test_non_finite_intensity_returns_serializable_422(
    client: TestClient,
    auth_headers: dict[str, str],
    raw_intensity: str,
):
    from backend.app.soul.persona import create_persona

    soul_id = create_persona()

    response = client.put(
        f"/soul/affect/{soul_id}",
        params={"trigger": "user_thank", "intensity": raw_intensity},
        headers=auth_headers,
    )

    assert response.status_code == 422, response.text
    payload = response.json()
    assert payload["detail"] == {
        "error": "invalid_intensity",
        "valid_range": [0.0, 10.0],
    }
    json.dumps(payload, allow_nan=False)


@pytest.mark.parametrize("intensity", [-0.01, 10.01])
def test_out_of_range_intensity_returns_422(
    client: TestClient,
    auth_headers: dict[str, str],
    intensity: float,
):
    from backend.app.soul.persona import create_persona

    soul_id = create_persona()

    response = client.put(
        f"/soul/affect/{soul_id}",
        params={"trigger": "user_thank", "intensity": intensity},
        headers=auth_headers,
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["error"] == "invalid_intensity"


def test_intensity_boundaries_are_accepted_and_zero_preserves_state(
    client: TestClient,
    auth_headers: dict[str, str],
):
    from backend.app.db import get_conn
    from backend.app.soul.persona import create_persona

    zero_soul_id = create_persona()
    before = client.get(
        f"/soul/affect/{zero_soul_id}",
        headers=auth_headers,
    ).json()

    zero_response = client.put(
        f"/soul/affect/{zero_soul_id}",
        params={"trigger": "user_thank", "intensity": 0},
        headers=auth_headers,
    )

    assert zero_response.status_code == 200, zero_response.text
    zero_affect = zero_response.json()["affect"]
    assert zero_affect == {
        "pleasure": before["pleasure"],
        "arousal": before["arousal"],
        "dominance": before["dominance"],
        "current_mood": before["current_mood"],
        "mood_intensity": before["mood_intensity"],
    }
    zero_event = get_conn().execute(
        "SELECT intensity FROM affect_events WHERE soul_id=? AND trigger=?",
        (zero_soul_id, "user_thank"),
    ).fetchone()
    assert zero_event is not None
    assert zero_event["intensity"] == 0.0

    max_soul_id = create_persona()
    max_response = client.put(
        f"/soul/affect/{max_soul_id}",
        params={"trigger": "user_thank", "intensity": 10},
        headers=auth_headers,
    )
    assert max_response.status_code == 200, max_response.text


def test_unknown_and_oversized_triggers_return_422(
    client: TestClient,
    auth_headers: dict[str, str],
):
    from backend.app.soul.persona import create_persona

    soul_id = create_persona()

    unknown = client.put(
        f"/soul/affect/{soul_id}",
        params={"trigger": "untrusted_trigger", "intensity": 1},
        headers=auth_headers,
    )
    oversized = client.put(
        f"/soul/affect/{soul_id}",
        params={"trigger": "x" * 101, "intensity": 1},
        headers=auth_headers,
    )

    assert unknown.status_code == 422, unknown.text
    assert unknown.json()["detail"]["error"] == "invalid_trigger"
    assert oversized.status_code == 422, oversized.text


def test_ghost_soul_returns_404_without_persisting_rows(
    client: TestClient,
    auth_headers: dict[str, str],
):
    from backend.app.db import get_conn

    ghost_soul_id = "soul_ghost_xyz_not_exist"

    response = client.put(
        f"/soul/affect/{ghost_soul_id}",
        params={"trigger": "user_thank", "intensity": 1},
        headers=auth_headers,
    )

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == {
        "error": "soul_not_found",
        "soul_id": ghost_soul_id,
    }
    conn = get_conn()
    assert conn.execute(
        "SELECT 1 FROM affect_state WHERE soul_id=?",
        (ghost_soul_id,),
    ).fetchone() is None
    assert conn.execute(
        "SELECT 1 FROM affect_events WHERE soul_id=?",
        (ghost_soul_id,),
    ).fetchone() is None


def test_transition_locks_persona_before_loading_state(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch,
):
    from backend.app.affect import state_machine
    from backend.app.soul.persona import create_persona

    soul_id = create_persona()
    original_load = state_machine._load_affect
    competing_write_blocked = False

    def load_while_competing_writer_attempts_delete(conn, target_soul_id):
        nonlocal competing_write_blocked
        competing = sqlite3.connect(os.environ["WANWEI_MEMORY_DB"], timeout=0)
        try:
            competing.execute("PRAGMA foreign_keys=ON")
            competing.execute("PRAGMA busy_timeout=0")
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                competing.execute(
                    "UPDATE soul_persona SET name=name WHERE soul_id=?",
                    (target_soul_id,),
                )
            competing_write_blocked = True
        finally:
            competing.close()
        return original_load(conn, target_soul_id)

    monkeypatch.setattr(state_machine, "_load_affect", load_while_competing_writer_attempts_delete)

    response = client.put(
        f"/soul/affect/{soul_id}",
        params={"trigger": "user_thank", "intensity": 1},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    assert competing_write_blocked is True


def test_knowledge_body_limit_covers_create_update_and_import(
    client: TestClient,
    auth_headers: dict[str, str],
):
    from backend.app.platform_api.knowledge import MAX_KNOWLEDGE_BODY_CHARS

    at_limit = "x" * MAX_KNOWLEDGE_BODY_CHARS
    over_limit = "x" * (MAX_KNOWLEDGE_BODY_CHARS + 1)

    created = client.post(
        "/platform/knowledge/docs",
        json={"title": "boundary", "body": at_limit},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    doc_id = created.json()["id"]

    updated = client.put(
        f"/platform/knowledge/docs/{doc_id}",
        json={"body": at_limit},
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text

    create_overflow = client.post(
        "/platform/knowledge/docs",
        json={"title": "too large", "body": over_limit},
        headers=auth_headers,
    )
    update_overflow = client.put(
        f"/platform/knowledge/docs/{doc_id}",
        json={"body": over_limit},
        headers=auth_headers,
    )
    import_overflow = client.post(
        "/platform/knowledge/import",
        json={
            "items": [
                {"title": "imported", "body": "valid"},
                {"title": "too large", "body": over_limit},
            ]
        },
        headers=auth_headers,
    )

    assert create_overflow.status_code == 422, create_overflow.text
    assert update_overflow.status_code == 422, update_overflow.text
    assert import_overflow.status_code == 200, import_overflow.text
    assert import_overflow.json() == {"imported": 1, "skipped": 1}
    persisted = client.get(
        f"/platform/knowledge/docs/{doc_id}",
        headers=auth_headers,
    )
    assert persisted.status_code == 200, persisted.text
    assert persisted.json()["body"] == at_limit
    documents = client.get(
        "/platform/knowledge/docs?full=true",
        headers=auth_headers,
    )
    assert documents.status_code == 200, documents.text
    titles = {item["title"] for item in documents.json()["items"]}
    assert "imported" in titles
    assert "too large" not in titles
