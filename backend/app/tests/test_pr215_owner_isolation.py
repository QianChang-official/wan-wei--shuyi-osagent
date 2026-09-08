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

"""Owner isolation for work that runs outside an HTTP request context."""
from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def owners(tmp_path, monkeypatch, seed_identity):
    monkeypatch.setenv("WANWEI_API_KEY", "pr215-configured-owner")
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.setenv("WANWEI_PLATFORM_DIR", str(tmp_path / "platform"))
    monkeypatch.delenv("WANWEI_DEVICE_GEAR_ENABLED", raising=False)

    from backend.app.init_db import main as init_db
    from backend.app.soul.ownership import configured_actor_id

    init_db()
    return configured_actor_id(), seed_identity("pr215-other-owner")


@pytest.mark.parametrize("gear,expected_status", [("sandbox", "done"), ("device", "failed")])
def test_background_flow_audits_use_persisted_run_owner(owners, gear, expected_status):
    from backend.app.audit import service as audit
    from backend.app.platform_api import automation

    configured_owner, run_owner = owners
    flow = {
        "id": "flow_background_private",
        "owner_id": run_owner,
        "gear": gear,
        "steps": [{"id": "private-step", "type": "condition", "config": {"expr": "1 < 2"}}],
    }
    automation._flows.set(flow["id"], flow)
    run = automation._try_create_run(flow, triggered_by="manual", mode="real")
    assert run is not None

    # A scheduler or recovered task has no authenticated request to inherit.
    # A stale outer context must not override the persisted run's owner either.
    with audit.audit_owner_context(configured_owner):
        asyncio.run(automation._dispatch_run(run["id"], flow, "real"))
        assert audit.current_audit_owner() == configured_owner

    assert automation._runs.get(run["id"])["status"] == expected_status
    owned_events = audit.list_logs(owner_id=run_owner)
    assert any(event["event_type"] == "flow_run_finished" for event in owned_events)
    if gear == "device":
        assert any(event["event_type"] == "gear_denied" for event in owned_events)
    assert audit.list_logs(owner_id=configured_owner) == []


def test_scheduler_audits_use_each_flow_owner(owners, monkeypatch):
    from backend.app.audit import service as audit
    from backend.app.platform_api import automation

    configured_owner, flow_owner = owners
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    flow = {
        "id": "flow_scheduled_private",
        "owner_id": flow_owner,
        "name": "Private scheduled flow",
        "trigger": "schedule",
        "cron": "* * * * *",
        "enabled": True,
        "gear": "sandbox",
        "updated_at": now.isoformat(),
        "steps": [],
    }
    automation._flows.set(flow["id"], flow)
    monkeypatch.setattr(automation, "_schedule_state", {
        flow["id"]: {"updated_at": flow["updated_at"], "due": now},
    })
    monkeypatch.setattr(automation, "_launch_run", lambda *_args: None)
    monkeypatch.setattr(
        automation, "_next_cron_dt", lambda _cron, current: (current + timedelta(minutes=1), False),
    )

    first = automation._scheduler_tick(now)
    assert len(first) == 1
    assert automation._scheduler_tick(now + timedelta(minutes=1)) == []
    owned_events = audit.list_logs(owner_id=flow_owner)
    assert {event["event_type"] for event in owned_events} == {
        "flow_run_started", "flow_run_skipped",
    }
    assert all(json.loads(event["payload"])["flow_id"] == flow["id"] for event in owned_events)
    assert audit.list_logs(owner_id=configured_owner) == []


@pytest.fixture
def owner_audit_records(owners):
    from backend.app.audit import service as audit
    from backend.app.db import transaction

    configured_owner, other_owner = owners
    payload = {"trace_id": "audit-owner-boundary"}
    audit.record("configured-owner-event", payload, owner_id=configured_owner)
    audit.record("other-owner-event", payload, owner_id=other_owner)
    with transaction() as conn:
        conn.execute(
            "INSERT INTO audit_logs(audit_id, event_type, payload, created_at, owner_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                "audit_ownerless_boundary", "legacy-owner-event", json.dumps(payload),
                "2026-01-01T00:00:00Z", "",
            ),
        )
    return owners


@pytest.mark.parametrize("trace_id", [None, "audit-owner-boundary"])
def test_audit_reads_without_an_owner_fail_closed(owner_audit_records, monkeypatch, trace_id):
    from backend.app.audit import service as audit
    from backend.app.security import auth

    def unavailable_configured_key():
        raise OSError("injected configured key read failure")

    monkeypatch.setattr(auth, "get_api_key", unavailable_configured_key)
    with audit.audit_owner_context(None):
        assert audit.list_logs(trace_id=trace_id) == []


@pytest.mark.parametrize("trace_id", [None, "audit-owner-boundary"])
def test_an_empty_audit_owner_cannot_read_legacy_rows(owner_audit_records, trace_id):
    from backend.app.audit import service as audit

    assert audit.list_logs(trace_id=trace_id, owner_id="") == []


@pytest.mark.parametrize("owner_source", ["explicit", "context"])
@pytest.mark.parametrize("trace_id", [None, "audit-owner-boundary"])
def test_audit_owner_scope_survives_configured_key_failure(
    owner_audit_records, monkeypatch, owner_source, trace_id,
):
    from backend.app.audit import service as audit
    from backend.app.security import auth

    _, other_owner = owner_audit_records

    def unavailable_configured_key():
        raise OSError("injected configured key read failure")

    monkeypatch.setattr(auth, "get_api_key", unavailable_configured_key)
    context_owner = other_owner if owner_source == "context" else None
    explicit_owner = other_owner if owner_source == "explicit" else None
    with audit.audit_owner_context(context_owner):
        events = audit.list_logs(trace_id=trace_id, owner_id=explicit_owner)
    assert [event["event_type"] for event in events] == ["other-owner-event"]


def test_audit_trace_fallback_preserves_owner_scope(owner_audit_records, monkeypatch):
    from backend.app.audit import service as audit

    class ConnectionWithoutJson:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, sql, parameters=()):
            if "json_extract" in sql:
                raise sqlite3.OperationalError("no such function: json_extract")
            return self.connection.execute(sql, parameters)

        def __getattr__(self, name):
            return getattr(self.connection, name)

    configured_owner, other_owner = owner_audit_records
    connection = ConnectionWithoutJson(audit.get_conn())
    monkeypatch.setattr(audit, "get_conn", lambda: connection)
    other_events = audit.list_logs(trace_id="audit-owner-boundary", owner_id=other_owner)
    assert [event["event_type"] for event in other_events] == ["other-owner-event"]
    configured_events = audit.list_logs(
        trace_id="audit-owner-boundary", owner_id=configured_owner,
    )
    assert {event["event_type"] for event in configured_events} == {
        "configured-owner-event", "legacy-owner-event",
    }
