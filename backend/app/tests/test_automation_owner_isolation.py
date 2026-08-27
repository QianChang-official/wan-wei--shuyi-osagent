"""Cross-principal isolation tests for platform automation flows and runs."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
for _path in (str(_PROJECT_ROOT), str(_PROJECT_ROOT / 'backend')):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from app.platform_api import automation  # noqa: E402


KEY_A = 'automation-owner-a'
KEY_B = 'automation-owner-b'
HEADERS_A = {'x-api-key': KEY_A}
HEADERS_B = {'x-api-key': KEY_B}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('WANWEI_API_KEY', KEY_A)
    monkeypatch.setenv('WANWEI_PLATFORM_DIR', str(tmp_path / 'platform'))
    automation._schedule_state.clear()
    app = FastAPI()
    app.include_router(automation.router)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    automation._schedule_state.clear()


def _create(client: TestClient, headers: dict[str, str]) -> dict:
    response = client.post(
        '/automation/flows',
        json={
            'name': 'owner-isolated',
            'steps': [{'type': 'agent', 'config': {'task': 'safe'}}],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert 'owner_id' not in body
    return body


def test_flow_and_run_are_isolated_between_api_keys(client):
    flow = _create(client, HEADERS_A)
    fid = flow['id']

    assert client.get('/automation/flows', headers=HEADERS_B).json() == []
    assert client.get(f'/automation/flows/{fid}', headers=HEADERS_B).status_code == 404
    assert client.put(
        f'/automation/flows/{fid}',
        json={'name': 'foreign-write'},
        headers=HEADERS_B,
    ).status_code == 404
    assert client.delete(f'/automation/flows/{fid}', headers=HEADERS_B).status_code == 404
    assert client.post(
        f'/automation/flows/{fid}/run',
        headers=HEADERS_B,
    ).status_code == 404

    started = client.post(f'/automation/flows/{fid}/run', headers=HEADERS_A)
    assert started.status_code == 202, started.text
    run = started.json()
    rid = run['id']
    assert 'owner_id' not in run
    assert client.get(f'/automation/runs/{rid}', headers=HEADERS_B).status_code == 404
    assert client.get('/automation/runs', headers=HEADERS_B).json() == []

    own_runs = client.get('/automation/runs', headers=HEADERS_A)
    assert own_runs.status_code == 200
    assert any(item['id'] == rid for item in own_runs.json())


def test_ai_edit_and_apply_cannot_cross_owners(client):
    flow = _create(client, HEADERS_A)
    fid = flow['id']
    instruction = {'flow_id': fid, 'instruction': '改名为 foreign'}

    assert client.post('/automation/flows/ai-edit', json=instruction, headers=HEADERS_B).status_code == 404
    proposed = client.post(
        '/automation/flows/ai-edit',
        json={'flow_id': fid, 'instruction': '改名为 owned'},
        headers=HEADERS_A,
    )
    assert proposed.status_code == 200, proposed.text
    assert 'owner_id' not in proposed.json()['proposed_flow']

    payload = {'proposed_flow': {'name': 'foreign-apply', 'steps': []}}
    assert client.post(
        f'/automation/flows/{fid}/ai-apply',
        json=payload,
        headers=HEADERS_B,
    ).status_code == 404
    assert client.post(
        f'/automation/flows/{fid}/ai-apply?create=true',
        json=payload,
        headers=HEADERS_B,
    ).status_code == 404
    applied = client.post(
        f'/automation/flows/{fid}/ai-apply',
        json=payload,
        headers=HEADERS_A,
    )
    assert applied.status_code == 200, applied.text
    assert 'owner_id' not in applied.json()
    assert client.get(f'/automation/flows/{fid}', headers=HEADERS_A).json()['name'] == 'foreign-apply'


def test_legacy_ownerless_rows_are_only_claimable_by_configured_actor(client):
    automation._flows.set(
        'legacy-flow',
        {
            'id': 'legacy-flow',
            'name': 'legacy',
            'trigger': 'manual',
            'steps': [],
            'enabled': True,
        },
    )
    automation._runs.set(
        'legacy-run',
        {
            'id': 'legacy-run',
            'flow_id': 'legacy-flow',
            'status': 'done',
            'done': True,
        },
    )

    assert client.get('/automation/flows', headers=HEADERS_B).json() == []
    assert client.get('/automation/runs/legacy-run', headers=HEADERS_B).status_code == 404

    own_flow = client.get('/automation/flows/legacy-flow', headers=HEADERS_A)
    assert own_flow.status_code == 200, own_flow.text
    assert 'owner_id' not in own_flow.json()
    stored_flow = automation._flows.get('legacy-flow')
    assert stored_flow['owner_id']

    own_run = client.get('/automation/runs/legacy-run', headers=HEADERS_A)
    assert own_run.status_code == 200, own_run.text
    assert 'owner_id' not in own_run.json()


def test_scheduler_run_inherits_flow_owner(client, monkeypatch):
    flow = _create(
        client,
        HEADERS_A,
    )
    update = client.put(
        f"/automation/flows/{flow['id']}",
        json={'trigger': 'schedule', 'cron': '* * * * *'},
        headers=HEADERS_A,
    )
    assert update.status_code == 200, update.text

    launched: list[str] = []
    monkeypatch.setattr(
        automation,
        '_launch_run',
        lambda run_id, flow: launched.append(run_id),
    )
    start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    automation._schedule_state.clear()
    assert automation._scheduler_tick(start) == []
    fired = automation._scheduler_tick(start + timedelta(minutes=2))
    assert fired and fired == launched
    stored = automation._runs.get(fired[0])
    assert stored and stored.get('owner_id')
    assert client.get('/automation/runs', headers=HEADERS_B).json() == []
    assert any(item['id'] == fired[0] for item in client.get('/automation/runs', headers=HEADERS_A).json())
