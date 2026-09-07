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

"""Identity and LAN credential boundaries exercised against an isolated database."""
from __future__ import annotations

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app import db
from backend.app.security import auth


@pytest.fixture()
def identity_context(tmp_path, monkeypatch):
    from backend.app.init_db import main as init_db

    owner_key = "pr215-owner-key-0123456789abcdef012345"
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(tmp_path / "identity.db"))
    monkeypatch.setenv("WANWEI_PLATFORM_DIR", str(tmp_path / "platform"))
    monkeypatch.setenv("WANWEI_API_KEY", owner_key)
    db.close_all()
    init_db()
    owner_id = auth.actor_id_from_api_key(owner_key)
    yield owner_key, owner_id
    db.close_all()


@pytest.fixture()
def identity_client(identity_context):
    from backend.app.app_runtime import memory_router

    app = FastAPI()
    app.add_middleware(auth.APIKeyMiddleware)
    app.include_router(memory_router)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def test_revoke_foreign_keys_are_indistinguishable_from_unknown_keys(
    identity_context, identity_client, seed_identity,
):
    owner_key, _ = identity_context
    foreign_active = "pr215-foreign-active-0123456789abcdef"
    foreign_inactive = "pr215-foreign-inactive-0123456789abcdef"
    seed_identity(foreign_active)
    seed_identity(foreign_inactive, is_active=False)

    responses = [
        identity_client.post(
            "/memory/identity/revoke",
            headers={"x-api-key": owner_key},
            json={"api_key": target},
        )
        for target in (foreign_active, foreign_inactive, "pr215-unknown-key")
    ]
    assert [response.status_code for response in responses] == [404, 404, 404]
    assert responses[0].json() == responses[1].json() == responses[2].json()
    assert auth._verify_api_key(foreign_active)


@pytest.mark.parametrize("endpoint, field", [("rotate", "new_key"), ("revoke", "api_key")])
@pytest.mark.parametrize("invalid_key", [123, ["key"], {"key": "value"}])
def test_identity_key_fields_reject_non_string_values(
    identity_context, identity_client, endpoint, field, invalid_key,
):
    owner_key, _ = identity_context
    response = identity_client.post(
        f"/memory/identity/{endpoint}",
        headers={"x-api-key": owner_key},
        json={field: invalid_key},
    )
    assert response.status_code == 422
    assert auth._verify_api_key(owner_key)


@pytest.mark.parametrize("foreign_active", [True, False])
def test_rotation_collision_returns_conflict_without_changing_either_identity(
    identity_context, identity_client, seed_identity, foreign_active,
):
    owner_key, owner_id = identity_context
    target_key = "pr215-unavailable-key-0123456789abcdef"
    foreign_id = seed_identity(target_key, is_active=foreign_active)
    response = identity_client.post(
        "/memory/identity/rotate",
        headers={"x-api-key": owner_key},
        json={"new_key": target_key},
    )
    assert response.status_code == 409
    assert owner_id not in response.text and foreign_id not in response.text
    assert auth._verify_api_key(owner_key)
    assert auth.actor_id_from_api_key(target_key) == foreign_id
    assert auth._verify_api_key(target_key) is foreign_active


def test_revoke_preserves_the_callers_read_transaction(identity_context, seed_identity):
    owner_key, owner_id = identity_context
    target_key = "pr215-second-key-for-same-owner"
    seed_identity(target_key, identity_id=owner_id)
    conn = db.get_conn()
    conn.execute("BEGIN")
    before = conn.execute("SELECT SUM(is_active) FROM identity").fetchone()[0]
    try:
        result = auth.revoke_api_key(
            target_key, current_key=owner_key, current_identity_id=owner_id,
        )
        assert result["revoked"]
        assert conn.in_transaction
        assert conn.execute("SELECT SUM(is_active) FROM identity").fetchone()[0] == before
    finally:
        conn.rollback()
    assert not auth._verify_api_key(target_key)
    assert auth._verify_api_key(owner_key)


@pytest.mark.parametrize("operation", ["bootstrap", "rotate", "revoke", "issue_lan", "revoke_lan"])
def test_credential_writes_reject_a_replaced_database(
    identity_context, monkeypatch, seed_identity, operation,
):
    owner_key, owner_id = identity_context
    target_key = "pr215-secondary-key-for-revocation"
    seed_identity(target_key, identity_id=owner_id)
    auth.issue_lan_session(owner_id, ttl_seconds=60)
    bootstrap_key = "pr215-new-configured-owner-key"
    actions = {
        "bootstrap": lambda: auth.actor_id_from_api_key(bootstrap_key),
        "rotate": lambda: auth.rotate_api_key(owner_key, "pr215-new-rotation-key"),
        "revoke": lambda: auth.revoke_api_key(
            target_key, current_key=owner_key, current_identity_id=owner_id,
        ),
        "issue_lan": lambda: auth.issue_lan_session(owner_id, ttl_seconds=60),
        "revoke_lan": auth.revoke_lan_sessions,
    }
    if operation == "bootstrap":
        monkeypatch.setenv("WANWEI_API_KEY", bootstrap_key)
    # Simulate the recorded file identity changing without relying on Windows
    # allowing an open SQLite database to be renamed.
    db._db_fingerprints[str(db.database_path())] = (0, -1)
    with pytest.raises(db.DatabaseIdentityError):
        actions[operation]()


@pytest.mark.parametrize("identity_state", ["unknown", "inactive"])
def test_lan_credentials_require_an_active_identity(identity_context, seed_identity, identity_state):
    owner_id = "id_unregistered"
    if identity_state == "inactive":
        owner_id = seed_identity("pr215-inactive-key", is_active=False)
    before = db.get_conn().execute("SELECT COUNT(*) FROM lan_sessions").fetchone()[0]
    with pytest.raises(ValueError, match="identity"):
        auth.issue_lan_session(owner_id, ttl_seconds=60)
    assert db.get_conn().execute("SELECT COUNT(*) FROM lan_sessions").fetchone()[0] == before


def test_lan_session_stops_authenticating_after_identity_deactivation(identity_context):
    _, owner_id = identity_context
    credential, _ = auth.issue_lan_session(owner_id, ttl_seconds=60)
    assert auth.authenticated_identity(credential) == (owner_id, True)
    with db.transaction() as conn:
        conn.execute("UPDATE identity SET is_active=0 WHERE identity_id=?", (owner_id,))
    assert auth.authenticated_identity(credential) == (None, False)


def test_lan_session_survives_key_rotation_for_the_same_identity(identity_context):
    owner_key, owner_id = identity_context
    credential, _ = auth.issue_lan_session(owner_id, ttl_seconds=60)
    assert auth.rotate_api_key(owner_key, "pr215-rotated-owner-key") == owner_id
    assert auth.authenticated_identity(credential) == (owner_id, True)


def test_lan_revocation_does_not_report_success_when_database_open_fails(identity_context, monkeypatch):
    _, owner_id = identity_context
    credential, _ = auth.issue_lan_session(owner_id, ttl_seconds=60)

    def unavailable_database(*args, **kwargs):
        raise sqlite3.OperationalError("injected database open failure")

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", unavailable_database)
        with pytest.raises(sqlite3.OperationalError, match="injected"):
            auth.revoke_lan_sessions()
    assert auth.authenticated_identity(credential) == (owner_id, True)
    assert auth.revoke_lan_sessions() == 1
    assert auth.authenticated_identity(credential) == (None, False)
