"""
测试 v0.9.5 workflow persistence 功能

验证：
1. Workflow runs 可以持久化到数据库
2. 进程重启后可以读取
3. TTL 清理功能正常工作
4. 列表和统计功能正常
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def test_db(isolated_db):
    """使用临时数据库进行测试"""
    return isolated_db


def test_workflow_persistence_basic(test_db):
    """测试基本的 workflow 持久化功能"""
    from backend.app.workflow.persistence import init_workflow_persistence, save_run, get_run

    # 初始化表
    init_workflow_persistence()

    # 创建测试数据
    run_data = {
        'run_id': 'wfr_test123',
        'trace_id': 'trace_test123',
        'scenario': 'test_scenario',
        'user_goal': '测试目标',
        'status': 'completed',
        'dry_run': True,
        'created_at': '2026-07-05T12:00:00Z',
        'version': 'v0.9.5-workflow-persistence',
        'summary': {
            'total_stages': 10,
            'completed_stages': 8,
            'skipped_stages': 2,
            'latency_ms': 250,
            'risk_level': 'low',
        },
        'trace': [],
        'artifacts': {},
    }

    # 保存
    save_run('wfr_test123', run_data)

    # 读取
    retrieved = get_run('wfr_test123')

    assert retrieved is not None
    assert retrieved['run_id'] == 'wfr_test123'
    assert retrieved['scenario'] == 'test_scenario'
    assert retrieved['summary']['total_stages'] == 10


def test_workflow_list_and_filter(test_db):
    """测试列表和过滤功能"""
    from backend.app.workflow.persistence import init_workflow_persistence, save_run, list_runs

    init_workflow_persistence()

    # 创建多个 runs
    for i in range(5):
        run_data = {
            'run_id': f'wfr_test{i}',
            'trace_id': f'trace_test{i}',
            'scenario': 'scenario_a' if i < 3 else 'scenario_b',
            'user_goal': f'目标{i}',
            'status': 'completed',
            'dry_run': True,
            'created_at': f'2026-07-05T12:0{i}:00Z',
            'version': 'v0.9.5-workflow-persistence',
            'summary': {
                'total_stages': 10,
                'completed_stages': 10,
                'skipped_stages': 0,
                'latency_ms': 200 + i * 10,
                'risk_level': 'low',
            },
            'trace': [],
            'artifacts': {},
        }
        save_run(f'wfr_test{i}', run_data)

    # 列出所有
    all_runs = list_runs(limit=10)
    assert len(all_runs) == 5

    # 按场景过滤
    scenario_a_runs = list_runs(scenario='scenario_a')
    assert len(scenario_a_runs) == 3

    scenario_b_runs = list_runs(scenario='scenario_b')
    assert len(scenario_b_runs) == 2


def test_workflow_cleanup(test_db):
    """测试 TTL 清理功能"""
    from datetime import datetime, timedelta, timezone
    from backend.app.workflow.persistence import init_workflow_persistence, save_run, cleanup_old_runs, get_run_count

    init_workflow_persistence()

    # 创建新的和旧的 runs
    now = datetime.now(timezone.utc)
    old_time = (now - timedelta(days=10)).isoformat()
    recent_time = (now - timedelta(hours=1)).isoformat()

    # 旧的 run
    old_run = {
        'run_id': 'wfr_old',
        'trace_id': 'trace_old',
        'scenario': 'test',
        'user_goal': '旧目标',
        'status': 'completed',
        'dry_run': True,
        'created_at': old_time,
        'version': 'v0.9.5',
        'summary': {'total_stages': 10, 'completed_stages': 10, 'skipped_stages': 0, 'latency_ms': 200, 'risk_level': 'low'},
        'trace': [],
        'artifacts': {},
    }
    save_run('wfr_old', old_run)

    # 新的 run
    recent_run = {
        'run_id': 'wfr_recent',
        'trace_id': 'trace_recent',
        'scenario': 'test',
        'user_goal': '新目标',
        'status': 'completed',
        'dry_run': True,
        'created_at': recent_time,
        'version': 'v0.9.5',
        'summary': {'total_stages': 10, 'completed_stages': 10, 'skipped_stages': 0, 'latency_ms': 200, 'risk_level': 'low'},
        'trace': [],
        'artifacts': {},
    }
    save_run('wfr_recent', recent_run)

    # 清理 7 天前的数据
    initial_count = get_run_count()
    assert initial_count == 2

    deleted = cleanup_old_runs(ttl_days=7)
    assert deleted == 1

    final_count = get_run_count()
    assert final_count == 1


def test_workflow_cleanup_rejects_negative_ttl_without_deleting(test_db):
    from backend.app.workflow.persistence import init_workflow_persistence, save_run, cleanup_old_runs, get_run_count

    init_workflow_persistence()
    save_run(
        "wfr_keep",
        {
            "run_id": "wfr_keep",
            "trace_id": "trace_keep",
            "scenario": "keep",
            "user_goal": "must survive invalid cleanup",
            "status": "completed",
            "dry_run": True,
            "created_at": "2026-07-11T00:00:00Z",
            "version": "v0.9.5",
            "summary": {},
            "trace": [],
            "artifacts": {},
        },
    )

    with pytest.raises(ValueError, match="ttl_days"):
        cleanup_old_runs(ttl_days=-1)

    assert get_run_count() == 1


def test_workflow_storage_stats(test_db):
    """测试存储统计功能"""
    from backend.app.workflow.persistence import init_workflow_persistence, save_run, get_storage_stats

    init_workflow_persistence()

    # 创建不同状态和场景的 runs
    scenarios = ['scenario_a', 'scenario_a', 'scenario_b']
    statuses = ['completed', 'completed', 'failed']

    for i, (scenario, status) in enumerate(zip(scenarios, statuses)):
        run_data = {
            'run_id': f'wfr_stat{i}',
            'trace_id': f'trace_stat{i}',
            'scenario': scenario,
            'user_goal': f'目标{i}',
            'status': status,
            'dry_run': True,
            'created_at': f'2026-07-05T12:0{i}:00Z',
            'version': 'v0.9.5',
            'summary': {'total_stages': 10, 'completed_stages': 10, 'skipped_stages': 0, 'latency_ms': 200, 'risk_level': 'low'},
            'trace': [],
            'artifacts': {},
        }
        save_run(f'wfr_stat{i}', run_data)

    # 获取统计
    stats = get_storage_stats()

    assert stats['total_runs'] == 3
    assert stats['status_distribution']['completed'] == 2
    assert stats['status_distribution']['failed'] == 1
    assert stats['scenario_distribution']['scenario_a'] == 2
    assert stats['scenario_distribution']['scenario_b'] == 1


def test_workflow_service_integration(test_db):
    """测试 workflow service 与持久化的集成"""
    from backend.app.workflow.persistence import init_workflow_persistence
    from backend.app.workflow.service import WorkflowRunIn, create_run, get_run

    init_workflow_persistence()

    # 创建 workflow run
    req = WorkflowRunIn(
        scenario='weekly_report_preference_learning',
        user_goal='生成周报并记住偏好',
        include_model_gateway=False,
        include_forgetting=False,
        dry_run=True,
    )

    created_run = create_run(req)
    run_id = created_run['run_id']

    # 验证可以从数据库读取
    retrieved_run = get_run(run_id)

    assert retrieved_run['run_id'] == run_id
    assert retrieved_run['scenario'] == 'weekly_report_preference_learning'
    assert retrieved_run['status'] in ['completed', 'completed_with_skips']


def _owner_run(run_id: str, created_at: str, scenario: str = 'owner-test') -> dict:
    return {
        'run_id': run_id,
        'trace_id': f'trace_{run_id}',
        'scenario': scenario,
        'user_goal': f'goal for {run_id}',
        'status': 'completed',
        'dry_run': True,
        'created_at': created_at,
        'version': 'v0.11.0-wanshu',
        'summary': {
            'total_stages': 1,
            'completed_stages': 1,
            'skipped_stages': 0,
            'latency_ms': 1,
            'risk_level': 'low',
        },
        'trace': [{'stage_id': 'owner-test'}],
        'artifacts': {'proof': run_id},
    }


def test_workflow_persistence_isolates_reads_writes_cleanup_and_stats(
    test_db, monkeypatch,
):
    from backend.app.security.auth import actor_id_from_api_key
    from backend.app.workflow.persistence import (
        WorkflowOwnershipError,
        cleanup_old_runs,
        get_run,
        get_run_count,
        get_storage_stats,
        list_runs,
        save_run,
    )

    monkeypatch.setenv('WANWEI_API_KEY', 'workflow-owner-a')
    owner_a = actor_id_from_api_key('workflow-owner-a')
    owner_b = actor_id_from_api_key('workflow-owner-b')
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

    run_a = _owner_run('wfr_owner_a', old, scenario='scenario-a')
    run_b = _owner_run('wfr_owner_b', old, scenario='scenario-b')
    save_run(run_a['run_id'], run_a, owner_id=owner_a)
    save_run(run_b['run_id'], run_b, owner_id=owner_b)

    assert get_run(run_a['run_id'], owner_id=owner_b) is None
    assert [item['run_id'] for item in list_runs(owner_id=owner_b)] == [run_b['run_id']]
    assert get_run_count(owner_id=owner_a) == 1
    assert get_run_count(owner_id=owner_b) == 1
    assert get_storage_stats(owner_id=owner_b)['scenario_distribution'] == {'scenario-b': 1}

    replacement = _owner_run(run_a['run_id'], old, scenario='foreign-overwrite')
    with pytest.raises(WorkflowOwnershipError):
        save_run(run_a['run_id'], replacement, owner_id=owner_b)
    assert get_run(run_a['run_id'], owner_id=owner_a)['scenario'] == 'scenario-a'

    assert cleanup_old_runs(ttl_days=7, owner_id=owner_b) == 1
    assert get_run(run_b['run_id'], owner_id=owner_b) is None
    assert get_run(run_a['run_id'], owner_id=owner_a) is not None


def test_workflow_legacy_schema_migrates_and_only_configured_actor_claims(
    test_db, monkeypatch,
):
    from backend.app.db import close_all, get_conn
    from backend.app.security.auth import actor_id_from_api_key
    from backend.app.workflow.persistence import get_run, init_workflow_persistence

    close_all()
    legacy = _owner_run('wfr_legacy', '2026-07-05T12:00:00Z')
    with sqlite3.connect(test_db) as conn:
        conn.execute(
            '''
            CREATE TABLE workflow_runs (
                run_id TEXT PRIMARY KEY,
                trace_id TEXT NOT NULL,
                scenario TEXT NOT NULL,
                user_goal TEXT NOT NULL,
                status TEXT NOT NULL,
                dry_run INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                run_data TEXT NOT NULL,
                version TEXT NOT NULL,
                total_stages INTEGER,
                completed_stages INTEGER,
                skipped_stages INTEGER,
                latency_ms INTEGER,
                risk_level TEXT
            )
            '''
        )
        conn.execute(
            '''
            INSERT INTO workflow_runs(
                run_id,trace_id,scenario,user_goal,status,dry_run,created_at,
                completed_at,run_data,version,total_stages,completed_stages,
                skipped_stages,latency_ms,risk_level
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''',
            (
                legacy['run_id'], legacy['trace_id'], legacy['scenario'],
                legacy['user_goal'], legacy['status'], 1, legacy['created_at'],
                None, json.dumps(legacy, ensure_ascii=False), legacy['version'],
                1, 1, 0, 1, 'low',
            ),
        )

    monkeypatch.setenv('WANWEI_API_KEY', 'workflow-legacy-owner')
    owner = actor_id_from_api_key('workflow-legacy-owner')
    other = actor_id_from_api_key('workflow-legacy-other')
    init_workflow_persistence()
    init_workflow_persistence()

    columns = {
        row[1] for row in get_conn().execute('PRAGMA table_info(workflow_runs)')
    }
    assert 'owner_id' in columns
    assert get_run(legacy['run_id'], owner_id=other) is None
    assert get_conn().execute(
        'SELECT owner_id FROM workflow_runs WHERE run_id=?',
        (legacy['run_id'],),
    ).fetchone()[0] is None

    claimed = get_run(legacy['run_id'], owner_id=owner)
    assert claimed and claimed['run_id'] == legacy['run_id']
    assert 'owner_id' not in claimed
    assert get_conn().execute(
        'SELECT owner_id FROM workflow_runs WHERE run_id=?',
        (legacy['run_id'],),
    ).fetchone()[0] == owner


def test_workflow_http_routes_are_owner_scoped(test_db, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.app.app_runtime import workflow_router
    from backend.app.security.auth import APIKeyMiddleware, actor_id_from_api_key
    from backend.app.workflow.persistence import get_run, save_run

    key_a = 'workflow-http-owner-a'
    key_b = 'workflow-http-owner-b'
    monkeypatch.setenv('WANWEI_API_KEY', key_a)
    owner_a = actor_id_from_api_key(key_a)
    owner_b = actor_id_from_api_key(key_b)

    app = FastAPI()
    app.include_router(workflow_router)
    app.add_middleware(APIKeyMiddleware)
    headers_a = {'x-api-key': key_a}
    headers_b = {'x-api-key': key_b}

    with TestClient(app, raise_server_exceptions=False) as client:
        created_a = client.post(
            '/workflow/runs',
            json={'scenario': 'owner-a', 'user_goal': 'A private run'},
            headers=headers_a,
        )
        created_b = client.post(
            '/workflow/run-dry-run',
            json={'scenario': 'owner-b', 'user_goal': 'B private run'},
            headers=headers_b,
        )
        assert created_a.status_code == 200, created_a.text
        assert created_b.status_code == 200, created_b.text
        run_a = created_a.json()
        run_b = created_b.json()
        assert 'owner_id' not in run_a
        assert 'owner_id' not in run_b

        for suffix in ('', '/trace', '/artifacts'):
            denied = client.get(
                f"/workflow/runs/{run_a['run_id']}{suffix}",
                headers=headers_b,
            )
            assert denied.status_code == 404, denied.text
            assert denied.json()['detail'] == {'error': 'not_found'}

        listed_b = client.get('/workflow/runs', headers=headers_b)
        assert listed_b.status_code == 200
        assert [item['run_id'] for item in listed_b.json()['runs']] == [run_b['run_id']]
        assert client.get('/workflow/stats', headers=headers_b).json()['total_runs'] == 1

        old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        old_a = _owner_run('wfr_http_old_a', old)
        old_b = _owner_run('wfr_http_old_b', old)
        save_run(old_a['run_id'], old_a, owner_id=owner_a)
        save_run(old_b['run_id'], old_b, owner_id=owner_b)
        cleaned = client.post('/workflow/cleanup?ttl_days=7', headers=headers_b)
        assert cleaned.status_code == 200
        assert cleaned.json()['deleted_count'] == 1
        assert get_run(old_b['run_id'], owner_id=owner_b) is None
        assert get_run(old_a['run_id'], owner_id=owner_a) is not None

        own = client.get(f"/workflow/runs/{run_a['run_id']}", headers=headers_a)
        assert own.status_code == 200
        assert own.json()['run_id'] == run_a['run_id']
        assert 'owner_id' not in own.json()
