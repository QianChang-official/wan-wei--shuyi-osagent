"""
测试 v0.9.5 workflow persistence 功能

验证：
1. Workflow runs 可以持久化到数据库
2. 进程重启后可以读取
3. TTL 清理功能正常工作
4. 列表和统计功能正常
"""

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
