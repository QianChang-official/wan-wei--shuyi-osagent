"""FIX-06/07: durable Soul ownership and scoped memory retrieval."""

from __future__ import annotations

import importlib
import json
import sqlite3

from fastapi.testclient import TestClient


OWNER_A_KEY = "owner-a-test-key"
OWNER_B_KEY = "owner-b-test-key"


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("WANWEI_API_KEY", OWNER_A_KEY)
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.delenv("WANWEI_PRODUCTION", raising=False)
    monkeypatch.delenv("WANWEI_OPENAI_COMPATIBLE_BASE", raising=False)
    monkeypatch.delenv("WANWEI_OPENAI_COMPATIBLE_MODEL", raising=False)

    from backend.app import init_db
    from backend.app import main as main_module
    from backend.app.db import close_all

    close_all()
    importlib.reload(main_module)
    init_db.main()
    return TestClient(main_module.app, raise_server_exceptions=False)


def _headers(api_key: str) -> dict[str, str]:
    return {"x-api-key": api_key}


def _switch_actor(monkeypatch, api_key: str) -> None:
    # APIKeyMiddleware and the owner resolver both read the current configured
    # key on each request, allowing one process to exercise key rotation and
    # cross-principal denial without weakening authentication.
    monkeypatch.setenv("WANWEI_API_KEY", api_key)


def _connect(client: TestClient, api_key: str, soul_id: str) -> dict:
    response = client.post(
        "/soul/connect",
        json={"soul_id": soul_id},
        headers=_headers(api_key),
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_actor_id_derivation_preserves_existing_agent_owner_ids():
    from backend.app.security.auth import actor_id_from_api_key

    # Platform agents already persist this identifier. Soul ownership must use
    # the exact same derivation so existing agent rows do not change owners.
    assert actor_id_from_api_key("test-key") == "api_7e5c6cf8ebac261866c7bd58"
    assert actor_id_from_api_key(" test-key ") == "api_7e5c6cf8ebac261866c7bd58"


def test_all_soul_endpoints_hide_cross_owner_rows(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _connect(client, OWNER_A_KEY, "soul_owner_a")

    _switch_actor(monkeypatch, OWNER_B_KEY)
    _connect(client, OWNER_B_KEY, "soul_owner_b")

    denied_requests = [
        client.post(
            "/soul/connect",
            json={"soul_id": "soul_owner_a"},
            headers=_headers(OWNER_B_KEY),
        ),
        client.get(
            "/soul/state/soul_owner_a",
            headers=_headers(OWNER_B_KEY),
        ),
        client.put(
            "/soul/persona/soul_owner_a",
            json={"name": "cross-owner"},
            headers=_headers(OWNER_B_KEY),
        ),
        client.get(
            "/soul/affect/soul_owner_a",
            headers=_headers(OWNER_B_KEY),
        ),
        client.put(
            "/soul/affect/soul_owner_a",
            params={"trigger": "manual", "intensity": 1},
            headers=_headers(OWNER_B_KEY),
        ),
        client.post(
            "/soul/dream",
            json={"soul_id": "soul_owner_a", "task_id": "denied"},
            headers=_headers(OWNER_B_KEY),
        ),
        client.post(
            "/soul/chat",
            json={
                "soul_id": "soul_owner_a",
                "messages": [{"role": "user", "content": "denied"}],
            },
            headers=_headers(OWNER_B_KEY),
        ),
    ]

    assert {response.status_code for response in denied_requests} == {404}
    assert all(response.json()["detail"]["error"] == "soul_not_found" for response in denied_requests)

    from backend.app.db import get_conn
    from backend.app.soul.ownership import actor_id_from_api_key

    rows = get_conn().execute(
        "SELECT soul_id,owner_id,name FROM soul_persona WHERE soul_id IN (?,?) ORDER BY soul_id",
        ("soul_owner_a", "soul_owner_b"),
    ).fetchall()
    assert [row["owner_id"] for row in rows] == [
        actor_id_from_api_key(OWNER_A_KEY),
        actor_id_from_api_key(OWNER_B_KEY),
    ]
    assert all(row["owner_id"] not in {OWNER_A_KEY, OWNER_B_KEY} for row in rows)
    assert rows[0]["name"] != "cross-owner"


def test_v2_and_legacy_memory_are_scoped_in_sql(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _connect(client, OWNER_A_KEY, "soul_owner_a")
    common_text = "owner-scope-shared-token"

    capsule_a = client.post(
        "/memory/v2/capsules",
        json={
            "soul_id": "soul_owner_a",
            "memory_class": "knowledge",
            "content": {"text": f"{common_text} alpha-only"},
        },
        headers=_headers(OWNER_A_KEY),
    ).json()["capsule_id"]
    event_a = client.post(
        "/memory/events",
        json={
            "soul_id": "soul_owner_a",
            "source_type": "user_input",
            "content": {"text": f"{common_text} legacy-alpha"},
        },
        headers=_headers(OWNER_A_KEY),
    ).json()["event_id"]

    _switch_actor(monkeypatch, OWNER_B_KEY)
    _connect(client, OWNER_B_KEY, "soul_owner_b")
    capsule_b = client.post(
        "/memory/v2/capsules",
        json={
            "soul_id": "soul_owner_b",
            "memory_class": "knowledge",
            "content": {"text": f"{common_text} beta-only"},
            "provenance": {
                "soul_id": "soul_owner_a",
                "owner_id": "spoofed-owner",
                "origin": "untrusted-client",
            },
        },
        headers=_headers(OWNER_B_KEY),
    ).json()["capsule_id"]
    event_b = client.post(
        "/memory/events",
        json={
            "soul_id": "soul_owner_b",
            "source_type": "user_input",
            "content": {"text": f"{common_text} legacy-beta"},
        },
        headers=_headers(OWNER_B_KEY),
    ).json()["event_id"]

    search_b = client.get(
        "/memory/v2/search",
        params={"q": common_text, "soul_id": "soul_owner_b"},
        headers=_headers(OWNER_B_KEY),
    ).json()["results"]
    legacy_b = client.get(
        "/memory/search",
        params={"q": common_text, "soul_id": "soul_owner_b"},
        headers=_headers(OWNER_B_KEY),
    ).json()["results"]
    listed_b = client.get(
        "/memory/v2/capsules",
        params={"soul_id": "soul_owner_b"},
        headers=_headers(OWNER_B_KEY),
    ).json()["items"]
    graph_b = client.get(
        "/reproduction/hippo-lite/graph",
        params={"soul_id": "soul_owner_b"},
        headers=_headers(OWNER_B_KEY),
    ).json()
    retention_b = client.get(
        "/reproduction/retention/state",
        params={"soul_id": "soul_owner_b"},
        headers=_headers(OWNER_B_KEY),
    ).json()
    tiers_b = client.get(
        "/reproduction/memory-tiers",
        params={"soul_id": "soul_owner_b"},
        headers=_headers(OWNER_B_KEY),
    ).json()

    assert {item["capsule_id"] for item in search_b} == {capsule_b}
    assert {item["event_id"] for item in legacy_b} == {event_b}
    assert capsule_b in {item["capsule_id"] for item in listed_b}
    assert capsule_a not in {item["capsule_id"] for item in listed_b}
    assert {node["id"] for node in graph_b["nodes"]} == {capsule_b}
    assert {item["capsule_id"] for item in retention_b["items"]} == {capsule_b}
    assert capsule_b in tiers_b["active_capsules"]
    assert capsule_a not in tiers_b["active_capsules"]
    assert all("owner_id" not in item.get("provenance", {}) for item in search_b + listed_b)
    assert client.get(
        f"/memory/v2/capsules/{capsule_a}",
        params={"soul_id": "soul_owner_b"},
        headers=_headers(OWNER_B_KEY),
    ).status_code == 404
    assert client.post(
        "/memory/v2/capsules",
        json={
            "soul_id": "soul_owner_a",
            "memory_class": "knowledge",
            "content": {"text": "cross-owner write"},
        },
        headers=_headers(OWNER_B_KEY),
    ).status_code == 404

    from backend.app.db import get_conn
    from backend.app.memory_runtime.capsule_store import get_capsule
    from backend.app.soul.ownership import actor_id_from_api_key

    stored_b = get_capsule(capsule_b)
    assert stored_b["provenance"]["soul_id"] == "soul_owner_b"
    assert stored_b["provenance"]["owner_id"] == actor_id_from_api_key(OWNER_B_KEY)
    event_rows = get_conn().execute(
        "SELECT event_id,soul_id,owner_id FROM memory_events WHERE event_id IN (?,?)",
        (event_a, event_b),
    ).fetchall()
    by_event = {row["event_id"]: row for row in event_rows}
    assert by_event[event_a]["soul_id"] == "soul_owner_a"
    assert by_event[event_b]["soul_id"] == "soul_owner_b"
    assert by_event[event_a]["owner_id"] != by_event[event_b]["owner_id"]


def test_memories_are_isolated_between_souls_for_same_owner(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _connect(client, OWNER_A_KEY, "soul_owner_a")
    _connect(client, OWNER_A_KEY, "soul_owner_a_second")
    common_text = "same-owner-different-soul-token"

    capsule_a = client.post(
        "/memory/v2/capsules",
        json={
            "soul_id": "soul_owner_a",
            "memory_class": "knowledge",
            "content": {"text": f"{common_text} first"},
        },
        headers=_headers(OWNER_A_KEY),
    ).json()["capsule_id"]
    capsule_second = client.post(
        "/memory/v2/capsules",
        json={
            "soul_id": "soul_owner_a_second",
            "memory_class": "knowledge",
            "content": {"text": f"{common_text} second"},
        },
        headers=_headers(OWNER_A_KEY),
    ).json()["capsule_id"]
    event_a = client.post(
        "/memory/events",
        json={
            "soul_id": "soul_owner_a",
            "source_type": "user_input",
            "content": {"text": f"{common_text} legacy-first"},
        },
        headers=_headers(OWNER_A_KEY),
    ).json()["event_id"]
    event_second = client.post(
        "/memory/events",
        json={
            "soul_id": "soul_owner_a_second",
            "source_type": "user_input",
            "content": {"text": f"{common_text} legacy-second"},
        },
        headers=_headers(OWNER_A_KEY),
    ).json()["event_id"]

    v2_results = client.get(
        "/memory/v2/search",
        params={"q": common_text, "soul_id": "soul_owner_a_second"},
        headers=_headers(OWNER_A_KEY),
    ).json()["results"]
    legacy_results = client.get(
        "/memory/search",
        params={"q": common_text, "soul_id": "soul_owner_a_second"},
        headers=_headers(OWNER_A_KEY),
    ).json()["results"]

    assert {item["capsule_id"] for item in v2_results} == {capsule_second}
    assert {item["event_id"] for item in legacy_results} == {event_second}
    assert capsule_a not in {item["capsule_id"] for item in v2_results}
    assert event_a not in {item["event_id"] for item in legacy_results}
    assert client.get(
        f"/memory/v2/capsules/{capsule_a}",
        params={"soul_id": "soul_owner_a_second"},
        headers=_headers(OWNER_A_KEY),
    ).status_code == 404


def test_candidate_quarantine_and_foreign_forget_ticket_are_not_readable(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _connect(client, OWNER_A_KEY, "soul_owner_a")

    candidate = client.post(
        "/memory/v2/capsules",
        json={
            "soul_id": "soul_owner_a",
            "memory_class": "preference",
            "content": {"text": "未经确认的偏好"},
            "write_intent": "inferred",
            "affects_future_behavior": True,
        },
        headers=_headers(OWNER_A_KEY),
    ).json()
    quarantined = client.post(
        "/memory/v2/capsules",
        json={
            "soul_id": "soul_owner_a",
            "memory_class": "knowledge",
            "content": {"text": "normal low-trust autonomous note"},
            "write_intent": "autonomous",
            "source_trust": "low",
        },
        headers=_headers(OWNER_A_KEY),
    ).json()
    assert candidate["state"]["lifecycle"] == "candidate"
    assert quarantined["state"]["lifecycle"] == "quarantined"

    # Lifecycle is an independent disclosure boundary.  Even if historical or
    # repaired governance metadata says "allow", unpublished states stay hidden.
    from backend.app.db import get_conn

    conn = get_conn()
    conn.execute(
        """UPDATE memory_capsules_v2
           SET governance=json_set(governance, '$.policy_result', 'allow')
           WHERE capsule_id IN (?,?)""",
        (candidate["capsule_id"], quarantined["capsule_id"]),
    )
    conn.commit()

    for capsule_id in (candidate["capsule_id"], quarantined["capsule_id"]):
        assert client.get(
            f"/memory/v2/capsules/{capsule_id}",
            params={"soul_id": "soul_owner_a"},
            headers=_headers(OWNER_A_KEY),
        ).status_code == 404
    listed = client.get(
        "/memory/v2/capsules",
        params={"soul_id": "soul_owner_a"},
        headers=_headers(OWNER_A_KEY),
    ).json()["items"]
    listed_ids = {item["capsule_id"] for item in listed}
    assert candidate["capsule_id"] not in listed_ids
    assert quarantined["capsule_id"] not in listed_ids

    active = client.post(
        "/memory/v2/capsules",
        json={
            "soul_id": "soul_owner_a",
            "memory_class": "knowledge",
            "content": {"text": "owner-only-forget-target"},
        },
        headers=_headers(OWNER_A_KEY),
    ).json()["capsule_id"]
    preview = client.post(
        "/memory/forget/preview",
        json={
            "soul_id": "soul_owner_a",
            "instruction": "owner-only-forget-target",
        },
        headers=_headers(OWNER_A_KEY),
    ).json()

    _switch_actor(monkeypatch, OWNER_B_KEY)
    _connect(client, OWNER_B_KEY, "soul_owner_b")
    denied = client.post(
        "/memory/forget/confirm",
        json={"forget_request_id": preview["forget_request_id"], "capsule_ids": [active]},
        headers=_headers(OWNER_B_KEY),
    )
    assert denied.status_code == 200
    assert denied.json()["status"] == "not_found"

    _switch_actor(monkeypatch, OWNER_A_KEY)
    confirmed = client.post(
        "/memory/forget/confirm",
        json={"forget_request_id": preview["forget_request_id"], "capsule_ids": [active]},
        headers=_headers(OWNER_A_KEY),
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["deleted_capsule_ids"] == [active]


def test_chat_intake_binds_owner_and_soul(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _connect(client, OWNER_A_KEY, "soul_owner_a")
    response = client.post(
        "/soul/chat",
        json={
            "soul_id": "soul_owner_a",
            "messages": [{"role": "user", "content": "intake-owner-binding-token"}],
        },
        headers=_headers(OWNER_A_KEY),
    )
    assert response.status_code == 200, response.text

    from backend.app.db import get_conn
    from backend.app.soul.ownership import actor_id_from_api_key

    rows = get_conn().execute(
        """SELECT provenance FROM memory_capsules_v2
           WHERE json_extract(content, '$.content')='intake-owner-binding-token'"""
    ).fetchall()
    assert len(rows) == 1
    provenance = json.loads(rows[0]["provenance"])
    assert provenance["soul_id"] == "soul_owner_a"
    assert provenance["owner_id"] == actor_id_from_api_key(OWNER_A_KEY)


def test_legacy_schema_migration_backfills_scope_idempotently(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy-memory.db"
    monkeypatch.setenv("WANWEI_API_KEY", OWNER_A_KEY)
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(db_path))
    monkeypatch.delenv("WANWEI_PRODUCTION", raising=False)

    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE soul_persona(
            soul_id TEXT PRIMARY KEY,
            name TEXT,
            core_traits TEXT,
            voice TEXT,
            soul_values TEXT,
            self_narrative TEXT,
            baseline_pleasure REAL,
            baseline_arousal REAL,
            baseline_dominance REAL,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE memory_events(
            event_id TEXT PRIMARY KEY,
            source_type TEXT,
            scene TEXT,
            content TEXT,
            quality_score REAL,
            sensitivity_level TEXT,
            trust_score REAL,
            created_at TEXT
        );
        CREATE TABLE memory_capsules_v2(
            capsule_id TEXT PRIMARY KEY,
            memory_class TEXT,
            content TEXT,
            source_events TEXT,
            provenance TEXT,
            governance TEXT,
            state TEXT,
            production_context TEXT,
            alignment_metadata TEXT,
            affective_metadata TEXT,
            relation_edges TEXT,
            index_refs TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO soul_persona VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            "soul_default",
            "legacy",
            "[]",
            "legacy voice",
            "[]",
            "legacy narrative",
            0.5,
            0.5,
            0.5,
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
        ),
    )
    conn.execute(
        "INSERT INTO memory_events VALUES (?,?,?,?,?,?,?,?)",
        (
            "evt_legacy",
            "user_input",
            "general",
            '{"text":"legacy event"}',
            0.9,
            "S0",
            0.9,
            "2026-01-01T00:00:00Z",
        ),
    )
    conn.execute(
        "INSERT INTO memory_capsules_v2 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "cap_legacy",
            "knowledge",
            '{"text":"legacy capsule"}',
            "[]",
            "{}",
            '{"policy_result":"allow","sensitivity_level":"S0"}',
            '{"lifecycle":"active","importance_score":0.5}',
            "{}",
            "{}",
            "{}",
            "[]",
            "{}",
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
        ),
    )
    conn.commit()
    conn.close()

    from backend.app import init_db
    from backend.app.db import close_all, get_conn
    from backend.app.soul.ownership import actor_id_from_api_key

    close_all()
    init_db.main()
    init_db.main()

    migrated = get_conn()
    expected_owner = actor_id_from_api_key(OWNER_A_KEY)
    persona = migrated.execute(
        "SELECT owner_id FROM soul_persona WHERE soul_id='soul_default'"
    ).fetchone()
    event = migrated.execute(
        "SELECT owner_id,soul_id FROM memory_events WHERE event_id='evt_legacy'"
    ).fetchone()
    capsule = migrated.execute(
        "SELECT provenance FROM memory_capsules_v2 WHERE capsule_id='cap_legacy'"
    ).fetchone()
    migration_count = migrated.execute(
        "SELECT COUNT(*) FROM memory_schema_migrations WHERE name=?",
        (init_db.SOUL_OWNERSHIP_MIGRATION,),
    ).fetchone()[0]

    assert persona["owner_id"] == expected_owner
    assert dict(event) == {"owner_id": expected_owner, "soul_id": "soul_default"}
    assert json.loads(capsule["provenance"]) == {
        "owner_id": expected_owner,
        "soul_id": "soul_default",
    }
    assert migration_count == 1
    assert {
        row[1]
        for row in migrated.execute("PRAGMA table_info(memory_events)").fetchall()
    } >= {"owner_id", "soul_id"}
    assert migrated.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memory_forget_request_scopes'"
    ).fetchone()
