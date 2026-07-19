"""W08 自动化舱修复回归测试。

覆盖任务包条目：
1. 05-#5  最小 cron 调度循环（router lifespan + _scheduler_tick 到期触发）。
2. 05-#8  _simulate_run 全程兜底（异常 → failed + error + done）与僵尸 running 启动回收。
3. 05-#7  ai-edit 诚实化：edit_mode='full_rebuild'，understood 如实说明全量重建。
4. 05-#17 cron 写入口校验：5 段格式 + 取值范围，非法 422。
5. 05-#18 _next_cron_run 显式本地时区 aware datetime。
6. 05-#19 分句/连接词正则不再误伤「合并/并发/并行」，连词「并」仍可分句。
7. 05-#20 delete_flow 级联清理 runs。
8. 05-#21 ai-apply 不再静默创建：缺 flow 404，显式 create=true 才新建。
9. 05-#22 运行重入限制：同 flow 已有 running → 409。
10. 05-#24/25 cron 死代码移除；steps:null 保持原值，steps:[] 显式清空。
契约：flow dict 带 next_run（ISO8601 或 null）；run dict 带 done/simulated。
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(_PROJECT_ROOT), str(_PROJECT_ROOT / 'backend')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.platform_api import automation  # noqa: E402


# ---------------------------------------------------------------------------
# 夹具与工具
# ---------------------------------------------------------------------------

@pytest.fixture
def store_dir(tmp_path, monkeypatch):
    """隔离的 platform 存储目录（JsonStore 惰性解析路径，换 env 即隔离）。"""
    monkeypatch.setenv('WANWEI_PLATFORM_DIR', str(tmp_path / 'platform'))
    return tmp_path / 'platform'


@pytest.fixture
def client(store_dir):
    """只挂 automation 路由的轻量 TestClient（不走主 app 的鉴权中间件）。"""
    app = FastAPI()
    app.include_router(automation.router)
    return TestClient(app, raise_server_exceptions=False)


def _steps(n: int, **overrides) -> list[dict]:
    out = []
    for i in range(1, n + 1):
        st = {
            'id': f'st{i}',
            'type': 'agent',
            'name': f'步骤{i}',
            'config': {'task': f'任务{i}'},
            'on_error': 'stop',
        }
        st.update(overrides)
        out.append(st)
    return out


def _create_flow(client: TestClient, **payload) -> dict:
    body = {'name': '测试流程', 'trigger': 'manual'}
    body.update(payload)
    r = client.post('/automation/flows', json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _wait_done(run_id: str, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = automation._runs.get(run_id)
        if isinstance(run, dict) and run.get('status') != 'running':
            return run
        time.sleep(0.05)
    raise AssertionError(f'运行 {run_id} 超时未终结')


# ---------------------------------------------------------------------------
# 4. 05-#17 cron 写入口校验
# ---------------------------------------------------------------------------

def test_cron_validate_unit():
    automation._validate_cron_expr('0 7 * * *')
    automation._validate_cron_expr('*/15 1-6 1,15 * 0,7')
    automation._validate_cron_expr('* * ? * ?')
    for bad in ('61 * * * *', '0 25 * * *', '0 7 32 * *', '0 7 * 13 *',
                '0 7 * * 8', '0 7 * *', '0 7 * * * *', 'a b c d e', '*/0 * * * *'):
        with pytest.raises(ValueError):
            automation._validate_cron_expr(bad)


def test_create_flow_rejects_invalid_cron(client):
    r = client.post('/automation/flows', json={
        'name': '坏cron', 'trigger': 'schedule', 'cron': '61 * * * *',
    })
    assert r.status_code == 422, r.text


def test_create_flow_accepts_valid_cron_and_blank(client):
    r = client.post('/automation/flows', json={
        'name': '好cron', 'trigger': 'schedule', 'cron': '0 7 * * *',
    })
    assert r.status_code == 201, r.text
    assert r.json()['cron'] == '0 7 * * *'
    r = client.post('/automation/flows', json={'name': '空cron', 'cron': '  '})
    assert r.status_code == 201, r.text
    assert r.json()['cron'] is None


def test_update_flow_rejects_invalid_cron(client):
    flow = _create_flow(client)
    r = client.put(f"/automation/flows/{flow['id']}", json={'cron': 'not-a-cron'})
    assert r.status_code == 422, r.text
    r = client.put(f"/automation/flows/{flow['id']}", json={'cron': '*/10 * * * *'})
    assert r.status_code == 200, r.text
    assert r.json()['cron'] == '*/10 * * * *'


# ---------------------------------------------------------------------------
# 5. 05-#18 _next_cron_run 时区 aware
# ---------------------------------------------------------------------------

def test_next_cron_run_is_aware_local():
    nxt, approximate = automation._next_cron_run('0 7 * * *')
    assert nxt is not None and approximate is False
    dt = datetime.fromisoformat(nxt)
    assert dt.tzinfo is not None
    assert dt.utcoffset() == datetime.now().astimezone().utcoffset()


def test_next_cron_run_naive_input_treated_as_local():
    naive = datetime(2026, 7, 18, 12, 0, 30)
    nxt, _ = automation._next_cron_run('30 12 * * *', now=naive)
    dt = datetime.fromisoformat(nxt)
    assert dt.tzinfo is not None
    assert (dt.hour, dt.minute) == (12, 30)
    assert dt.date() == naive.date()  # naive 按本地时间解释，不当 UTC 顺延


def test_next_cron_run_approximate_and_invalid():
    _, approximate = automation._next_cron_run('0 7 1 * 1')  # dom+dow 同时受限
    assert approximate is True
    nxt, approximate = automation._next_cron_run('bad cron')
    assert nxt is None and approximate is True


# ---------------------------------------------------------------------------
# 6. 05-#19 分句正则误伤修复
# ---------------------------------------------------------------------------

def test_clause_split_preserves_compound_words():
    steps, _ = automation._parse_steps('每天9点合并报表并发送邮件')
    names = [s['name'] for s in steps]
    assert '合并报表' in names and '发送邮件' in names
    steps, _ = automation._parse_steps('每天8点并发抓取三个接口然后汇总')
    names = [s['name'] for s in steps]
    assert any('并发抓取' in n for n in names), names
    steps, _ = automation._parse_steps('每天8点并行处理订单，再备份数据库')
    names = [s['name'] for s in steps]
    assert any('并行处理' in n for n in names), names


def test_clause_split_keeps_conjunction_behavior():
    steps, _ = automation._parse_steps('先抓取网页，并保存到记忆')
    names = [s['name'] for s in steps]
    assert '抓取网页' in names and '保存到记忆' in names
    steps, _ = automation._parse_steps('抓取数据并且写入记忆')
    names = [s['name'] for s in steps]
    assert '抓取数据' in names and '写入记忆' in names


def test_clause_split_zai_sequential_connector():
    steps, _ = automation._parse_steps('先备份再清理')
    names = [s['name'] for s in steps]
    assert '备份' in names and '清理' in names
    steps, _ = automation._parse_steps('每天8点处理订单，再备份数据库')
    names = [s['name'] for s in steps]
    assert any('处理订单' in n for n in names), names
    assert any('备份数据库' in n for n in names), names


# ---------------------------------------------------------------------------
# 2. 05-#8 _simulate_run 兜底 + 僵尸回收
# ---------------------------------------------------------------------------

def test_simulate_run_exception_marks_failed(store_dir, monkeypatch):
    flow = {'id': 'flow_x', 'name': '异常流程', 'enabled': True, 'steps': _steps(2)}
    run = automation._try_create_run(flow, triggered_by='manual')
    assert run is not None

    def _boom(step, index):
        raise RuntimeError('模拟内部爆炸')

    monkeypatch.setattr(automation, '_simulate_step', _boom)
    asyncio.run(automation._simulate_run(run['id'], flow))
    final = automation._runs.get(run['id'])
    assert final['status'] == 'failed'
    assert final['done'] is True
    assert '模拟内部爆炸' in final['error']
    assert final['finished_at']


def test_simulate_run_success_sets_done(store_dir):
    flow = {'id': 'flow_ok', 'name': '正常流程', 'enabled': True, 'steps': _steps(2)}
    run = automation._try_create_run(flow, triggered_by='manual')
    asyncio.run(automation._simulate_run(run['id'], flow))
    final = automation._runs.get(run['id'])
    assert final['status'] == 'done'
    assert final['done'] is True
    assert len(final['step_results']) == 2


def test_recover_interrupted_runs(store_dir):
    automation._runs.set('run_zombie', {
        'id': 'run_zombie', 'flow_id': 'flow_gone', 'status': 'running',
        'done': False, 'step_results': [], 'started_at': '2026-01-01T00:00:00+08:00',
        'finished_at': None, 'simulated': True,
    })
    assert automation._recover_interrupted_runs() == 1
    run = automation._runs.get('run_zombie')
    assert run['status'] == 'failed' and run['done'] is True
    assert '中断' in run['error']
    assert automation._recover_interrupted_runs() == 0  # 幂等


def test_router_lifespan_recovers_zombie_on_startup(store_dir):
    """router lifespan 真实生效：进入 TestClient 上下文即回收僵尸 running。"""
    automation._runs.set('run_zombie2', {
        'id': 'run_zombie2', 'flow_id': 'flow_gone', 'status': 'running',
        'done': False, 'step_results': [], 'started_at': '2026-01-01T00:00:00+08:00',
        'finished_at': None, 'simulated': True,
    })
    app = FastAPI()
    app.include_router(automation.router)
    with TestClient(app, raise_server_exceptions=False):
        run = automation._runs.get('run_zombie2')
        assert run['status'] == 'failed' and run['done'] is True


# ---------------------------------------------------------------------------
# 1. 05-#5 调度循环 tick
# ---------------------------------------------------------------------------

def _aware(y, mo, d, h, mi, s=0):
    return datetime(y, mo, d, h, mi, s).astimezone()


def test_scheduler_tick_fires_due_flow(client):
    flow = _create_flow(client, trigger='schedule', cron='* * * * *', steps=_steps(1))
    stored = automation._flows.get(flow['id'])
    t0 = _aware(2026, 7, 18, 12, 0, 30)
    assert automation._scheduler_tick(t0) == []  # 首次只见档，下一次才到期
    t1 = _aware(2026, 7, 18, 12, 1, 5)
    fired = automation._scheduler_tick(t1)
    assert len(fired) == 1
    final = _wait_done(fired[0])
    assert final['triggered_by'] == 'schedule'
    assert final['simulated'] is True
    assert final['done'] is True and final['status'] == 'done'
    assert stored['id'] == flow['id']


def test_scheduler_tick_skips_when_running_and_disabled(client):
    flow = _create_flow(client, trigger='schedule', cron='* * * * *', steps=_steps(30))
    stored = automation._flows.get(flow['id'])
    # 手动制造一个进行中的运行（约 1.5s），tick 到期应跳过而非并发
    running = automation._try_create_run(stored, triggered_by='manual')
    assert running is not None
    automation._launch_run(running['id'], stored)
    t0 = _aware(2026, 7, 18, 12, 0, 30)
    automation._scheduler_tick(t0)
    t1 = _aware(2026, 7, 18, 12, 1, 5)
    assert automation._scheduler_tick(t1) == []  # 已有 running → 跳过
    _wait_done(running['id'], timeout=30)
    # 停用后 tick 不再调度
    r = client.put(f"/automation/flows/{flow['id']}", json={'enabled': False})
    assert r.status_code == 200
    assert automation._scheduler_tick(_aware(2026, 7, 18, 12, 3, 5)) == []


def test_scheduler_tick_ignores_invalid_cron(store_dir):
    automation._flows.set('flow_bad', {
        'id': 'flow_bad', 'name': '坏', 'trigger': 'schedule', 'cron': 'not-cron',
        'steps': [], 'enabled': True, 'updated_at': '2026-01-01T00:00:00+08:00',
    })
    assert automation._scheduler_tick(_aware(2026, 7, 18, 12, 0, 30)) == []
    assert automation._scheduler_tick(_aware(2026, 7, 18, 12, 1, 30)) == []


# ---------------------------------------------------------------------------
# 3. 05-#7 ai-edit 诚实化
# ---------------------------------------------------------------------------

def test_ai_edit_declares_full_rebuild(client):
    r = client.post('/automation/flows/ai-edit', json={'instruction': '每天7点抓取科技新闻并写入记忆'})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['engine'] == 'mock'
    assert body['edit_mode'] == 'full_rebuild'
    flow = _create_flow(client, steps=_steps(1))
    r = client.post('/automation/flows/ai-edit', json={
        'flow_id': flow['id'], 'instruction': '每天7点抓取科技新闻',
    })
    assert r.status_code == 200, r.text
    assert '全量重建' in r.json()['understood']


# ---------------------------------------------------------------------------
# 7. 05-#20 delete_flow 级联清理 runs
# ---------------------------------------------------------------------------

def test_delete_flow_cascades_runs(client):
    flow = _create_flow(client, steps=_steps(1))
    r = client.post(f"/automation/flows/{flow['id']}/run")
    assert r.status_code == 202, r.text
    _wait_done(r.json()['id'])
    r = client.delete(f"/automation/flows/{flow['id']}")
    assert r.status_code == 200, r.text
    assert r.json()['runs_deleted'] >= 1
    r = client.get('/automation/runs', params={'flow_id': flow['id']})
    assert r.status_code == 200 and r.json() == []


# ---------------------------------------------------------------------------
# 8. 05-#21 ai-apply 静默创建修复
# ---------------------------------------------------------------------------

def test_ai_apply_404_unless_create_true(client):
    proposed = {'name': '新流程', 'trigger': 'manual', 'steps': _steps(1)}
    r = client.post('/automation/flows/flow_nope/ai-apply', json={'proposed_flow': proposed})
    assert r.status_code == 404, r.text
    r = client.post('/automation/flows/flow_nope/ai-apply?create=true',
                    json={'proposed_flow': proposed})
    assert r.status_code == 201, r.text
    assert r.json()['id'] == 'flow_nope'
    # 已存在后无需 create 也可应用
    r = client.post('/automation/flows/flow_nope/ai-apply',
                    json={'proposed_flow': {**proposed, 'desc': '更新'}})
    assert r.status_code == 200, r.text
    assert r.json()['desc'] == '更新'


def test_ai_apply_rejects_invalid_cron(client):
    flow = _create_flow(client)
    r = client.post(f"/automation/flows/{flow['id']}/ai-apply", json={
        'proposed_flow': {'name': 'x', 'trigger': 'schedule', 'cron': '99 * * * *'},
    })
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# 9. 05-#22 运行重入限制
# ---------------------------------------------------------------------------

def test_run_conflict_when_already_running(client):
    flow = _create_flow(client, steps=_steps(30))  # 约 1.5s 运行窗口
    r = client.post(f"/automation/flows/{flow['id']}/run")
    assert r.status_code == 202, r.text
    run = r.json()
    assert run['done'] is False and run['simulated'] is True
    assert run['triggered_by'] == 'manual'
    r2 = client.post(f"/automation/flows/{flow['id']}/run")
    assert r2.status_code == 409, r2.text
    final = _wait_done(run['id'], timeout=30)
    assert final['done'] is True
    # 终结后可再次运行
    r3 = client.post(f"/automation/flows/{flow['id']}/run")
    assert r3.status_code == 202, r3.text
    _wait_done(r3.json()['id'], timeout=30)


# ---------------------------------------------------------------------------
# 10. 05-#25 steps 语义 + flow/run 契约字段
# ---------------------------------------------------------------------------

def test_steps_null_keeps_and_empty_list_clears(client):
    flow = _create_flow(client, steps=_steps(2))
    assert len(flow['steps']) == 2
    r = client.put(f"/automation/flows/{flow['id']}", json={'steps': None})
    assert r.status_code == 200, r.text
    assert len(r.json()['steps']) == 2  # None = 保持原值
    r = client.put(f"/automation/flows/{flow['id']}", json={'steps': []})
    assert r.status_code == 200, r.text
    assert r.json()['steps'] == []  # [] = 显式清空


def test_flow_next_run_contract(client):
    flow = _create_flow(client, trigger='schedule', cron='0 7 * * *', steps=_steps(1))
    assert flow['next_run'] is not None
    assert datetime.fromisoformat(flow['next_run']).tzinfo is not None
    r = client.get(f"/automation/flows/{flow['id']}")
    assert r.json()['next_run'] == flow['next_run']
    r = client.put(f"/automation/flows/{flow['id']}", json={'enabled': False})
    assert r.json()['next_run'] is None  # 停用 → null
    manual = _create_flow(client)
    assert manual['next_run'] is None
    r = client.get('/automation/flows')
    by_id = {f['id']: f for f in r.json()}
    assert 'next_run' in by_id[flow['id']] and 'next_run' in by_id[manual['id']]


def test_run_view_backfills_done_and_simulated(client, store_dir):
    # 修复前的旧记录：无 done/simulated 字段
    automation._runs.set('run_legacy_done', {
        'id': 'run_legacy_done', 'flow_id': 'f', 'status': 'done',
        'step_results': [], 'started_at': '2026-01-01T00:00:00+08:00',
    })
    automation._runs.set('run_legacy_running', {
        'id': 'run_legacy_running', 'flow_id': 'f', 'status': 'running',
        'step_results': [], 'started_at': '2026-01-01T00:01:00+08:00',
    })
    r = client.get('/automation/runs/run_legacy_done')
    assert r.json()['done'] is True and r.json()['simulated'] is True
    r = client.get('/automation/runs/run_legacy_running')
    assert r.json()['done'] is False
    r = client.get('/automation/runs')
    by_id = {x['id']: x for x in r.json()}
    assert by_id['run_legacy_done']['done'] is True
    assert by_id['run_legacy_running']['done'] is False
