# Copyright (c) 2026 QianChang-official
#
# 宛委·枢忆 is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
# http://license.coscl.org.cn/MulanPSL2
#
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

"""编排执行引擎的真实性测试。

为什么需要单独一组：`_drive_run` 此前是模拟的（sleep + 模板产物），而既有的
API 层测试**同样全绿**——它们断言的是接口形状，不验证真的干活。所以这里绕过
HTTP 层，直接对执行器断言四件事：

1. plan / act / reflect 真的调用了模型或工具循环（而不是 sleep）
2. parallel 编排是**真并发**，不是串行假装
3. 一个 run 复用同一个执行上下文（重复创建会泄漏工作目录）
4. 能力不可用时**如实说未执行**，不产出看起来成功的模板文本

第 4 条是安全相关的：一个声称完成但什么都没做的步骤，会让用户以为事情已经
办妥，比明说失败有害得多。
"""

from __future__ import annotations

import asyncio

import pytest

from backend.app.platform_api import agents as ag


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """把 JsonStore 重定向到临时目录，避免污染真实平台数据。"""
    monkeypatch.setenv('WANWEI_PLATFORM_DIR', str(tmp_path))
    # 清掉跨用例残留的运行上下文映射，避免互相干扰
    monkeypatch.setattr(ag, '_RUN_CONTEXTS', {}, raising=False)
    yield tmp_path


class _Ctx:
    """最小执行上下文替身。真实 ctx 需要 workdir 等资源，这里只关心调度语义。"""

    def __init__(self):
        self.pending_flag = False

    def pending(self):
        return self.pending_flag


def _step(kind: str, title: str = '', *, needs_review: bool = False, index: int = 0) -> dict:
    return {
        'id': f'st-{index}', 'index': index, 'name': kind, 'kind': kind,
        'title': title or kind, 'status': 'pending', 'needs_review': needs_review,
        'detail': '', 'started_at': None, 'finished_at': None,
    }


def _run(steps: list[dict], *, orchestration: str = '', kind: str = 'solo') -> dict:
    return {
        'id': 'run-test', 'kind': kind, 'owner_id': 'owner-1',
        'agent_id': None, 'agent_name': '', 'team_id': None, 'team_name': '',
        'orchestration': orchestration,
        'task': '写一个测试', 'goal': '', 'depth': 'low', 'gear': 'sandbox',
        'context': None, 'permissions': {}, 'provider_pid': '', 'model': '',
        'status': 'queued', 'engine': 'pending',
        'steps': steps, 'cursor': 0, 'result': '', 'error': '',
        'created_at': '2026-01-01T00:00:00Z', 'updated_at': '2026-01-01T00:00:00Z',
        'finished_at': None,
    }


def _drive(run: dict) -> dict:
    ag._runs.set(run['id'], run)
    asyncio.run(ag._drive_run(run['id']))
    return ag._runs.get(run['id'])


def _fake_gateway(text: str = '1) 拆解任务\n2) 实施并验证'):
    """替身网关。记录调用以便断言「真的调了模型」。"""
    calls: list[str] = []

    async def gw(prompt, run=None, owner_id=None):
        calls.append(prompt)
        return text, 'test-provider'

    return gw, calls


def _stub_act(monkeypatch, reply='已完成动作'):
    """让 act 步骤走「工具可用」路径，并记录调用。"""
    from backend.app.platform_api import agent_bridge as bridge
    seen: list[str] = []

    async def fake_chat(system_prompt, message, target, *, context, history=None):
        seen.append(message)
        return reply

    monkeypatch.setattr(bridge, 'run_agent_chat', fake_chat, raising=False)
    monkeypatch.setattr(bridge, 'bridge_capabilities',
                        lambda *a, **k: {'tools_available': True}, raising=False)
    monkeypatch.setattr(ag, '_resolve_gateway_target',
                        lambda run, owner_id=None: ('http://gw/v1', 'k', 'm', 'p'), raising=False)
    monkeypatch.setattr(ag, '_context_for_run', lambda rid, run: _Ctx(), raising=False)
    return seen


# ---------------------------------------------------------------------------
# 1. 三种步骤真的干活
# ---------------------------------------------------------------------------

def test_plan_step_calls_model(monkeypatch):
    gw, calls = _fake_gateway()
    monkeypatch.setattr(ag, '_try_gateway', gw)

    run = _drive(_run([_step('plan')]))
    assert calls, 'plan 步骤必须真的调用模型'
    detail = run['steps'][0]['detail']
    assert '拆解任务' in detail, f'规划产物应来自模型，实际：{detail!r}'
    assert '模拟' not in detail, '不应再出现模拟字样'


def test_act_step_uses_tool_loop(monkeypatch):
    gw, _ = _fake_gateway()
    monkeypatch.setattr(ag, '_try_gateway', gw)
    seen = _stub_act(monkeypatch, reply='读取了文件并汇报')

    run = _drive(_run([_step('act', '执行第一步')]))
    assert seen, 'act 步骤必须走真实工具循环'
    assert '读取了文件并汇报' in run['steps'][0]['detail']


def test_reflect_step_calls_model(monkeypatch):
    gw, calls = _fake_gateway('复盘：完成了 X，未完成 Y')
    monkeypatch.setattr(ag, '_try_gateway', gw)

    plan = _step('plan', index=0)
    plan['status'] = 'done'
    plan['detail'] = '【规划】步骤一二三'
    run = _drive(_run([plan, _step('reflect', index=1)]))

    detail = run['steps'][1]['detail']
    assert '复盘' in detail
    assert any('复盘' in c or '已完成' in c for c in calls), '复盘提示词应带上实际产物'


# ---------------------------------------------------------------------------
# 2. parallel 是真并发
# ---------------------------------------------------------------------------

def test_parallel_group_runs_concurrently(monkeypatch):
    """核心断言：并发峰值必须 > 1。

    串行实现同样能让所有步骤变成 done——所以「结果都对」不足以证明并行。
    只有观察到重叠执行才算数。
    """
    from backend.app.platform_api import agent_bridge as bridge
    state = {'now': 0, 'peak': 0}

    async def slow_chat(system_prompt, message, target, *, context, history=None):
        state['now'] += 1
        state['peak'] = max(state['peak'], state['now'])
        await asyncio.sleep(0.05)
        state['now'] -= 1
        return f'done:{message}'

    gw, _ = _fake_gateway()
    monkeypatch.setattr(ag, '_try_gateway', gw)
    monkeypatch.setattr(bridge, 'run_agent_chat', slow_chat, raising=False)
    monkeypatch.setattr(bridge, 'bridge_capabilities',
                        lambda *a, **k: {'tools_available': True}, raising=False)
    monkeypatch.setattr(ag, '_resolve_gateway_target',
                        lambda run, owner_id=None: ('http://gw/v1', 'k', 'm', 'p'), raising=False)
    monkeypatch.setattr(ag, '_context_for_run', lambda rid, run: _Ctx(), raising=False)

    steps = [_step('plan', index=0)] + [_step('act', f'分支{i}', index=i + 1) for i in range(3)]
    run = _drive(_run(steps, orchestration='parallel', kind='team'))

    assert state['peak'] > 1, f'parallel 必须并发执行，实际并发峰值 {state["peak"]}'
    assert all(s['status'] == 'done' for s in run['steps']), '所有分支都应完成'


def test_sequential_orchestration_does_not_parallelize(monkeypatch):
    """对照：sequential 编排下不应出现并发重叠。"""
    from backend.app.platform_api import agent_bridge as bridge
    state = {'now': 0, 'peak': 0}

    async def slow_chat(system_prompt, message, target, *, context, history=None):
        state['now'] += 1
        state['peak'] = max(state['peak'], state['now'])
        await asyncio.sleep(0.02)
        state['now'] -= 1
        return 'ok'

    gw, _ = _fake_gateway()
    monkeypatch.setattr(ag, '_try_gateway', gw)
    monkeypatch.setattr(bridge, 'run_agent_chat', slow_chat, raising=False)
    monkeypatch.setattr(bridge, 'bridge_capabilities',
                        lambda *a, **k: {'tools_available': True}, raising=False)
    monkeypatch.setattr(ag, '_resolve_gateway_target',
                        lambda run, owner_id=None: ('http://gw/v1', 'k', 'm', 'p'), raising=False)
    monkeypatch.setattr(ag, '_context_for_run', lambda rid, run: _Ctx(), raising=False)

    steps = [_step('act', f'步骤{i}', index=i) for i in range(3)]
    _drive(_run(steps, orchestration='sequential', kind='team'))

    assert state['peak'] == 1, f'sequential 不应并发，实际峰值 {state["peak"]}'


# ---------------------------------------------------------------------------
# 3. 上下文复用（泄漏防护）
# ---------------------------------------------------------------------------

def test_context_is_reused_within_one_run(monkeypatch):
    """同一 run 必须复用 ctx。

    create_context 每次都 mkdtemp 一个新工作目录并以 run_id 为键注册；重复创建
    会覆盖旧 ctx 并**泄漏**上一个工作目录。这条测试守住那个不变式。
    """
    from backend.app.platform_api import agent_bridge as bridge
    created: list[str] = []
    real_create = bridge.create_context

    def spy(run, **kwargs):
        created.append(run['id'])
        return real_create(run, **kwargs)

    monkeypatch.setattr(bridge, 'create_context', spy, raising=False)

    run = _run([_step('plan')])
    first = ag._context_for_run('run-test', run)
    second = ag._context_for_run('run-test', run)

    assert first is second, '两次取用必须是同一 ctx 实例'
    assert len(created) == 1, f'create_context 只应调用一次，实际 {len(created)} 次'
    ag._release_run_context('run-test')


def test_context_released_after_run(monkeypatch):
    """run 结束后必须释放 ctx，否则 _MAX_CONTEXTS(128) 会被耗尽。"""
    gw, _ = _fake_gateway()
    monkeypatch.setattr(ag, '_try_gateway', gw)
    monkeypatch.setattr(ag, '_context_for_run', lambda rid, run: _Ctx(), raising=False)

    run = _run([_step('plan')])
    _drive(run)
    assert 'run-test' not in ag._RUN_CONTEXTS, 'run 结束后应清理上下文映射'


# ---------------------------------------------------------------------------
# 4. 降级必须如实
# ---------------------------------------------------------------------------

def test_act_reports_not_executed_when_tools_unavailable(monkeypatch):
    """工具循环不可用时不得假装执行过。

    这是安全相关断言：产出「已完成」的文本会让用户以为动作真的发生了。
    """
    from backend.app.platform_api import agent_bridge as bridge
    monkeypatch.setattr(bridge, 'bridge_capabilities',
                        lambda *a, **k: {'tools_available': False}, raising=False)

    async def dead_gateway(prompt, run=None, owner_id=None):
        return None, None

    monkeypatch.setattr(ag, '_try_gateway', dead_gateway)
    monkeypatch.setattr(ag, '_context_for_run', lambda rid, run: _Ctx(), raising=False)

    run = _drive(_run([_step('act', '执行第一步')]))
    detail = run['steps'][0]['detail']
    assert '未真实执行' in detail, f'必须如实说明未执行，实际：{detail!r}'


def test_plan_reports_when_gateway_unavailable(monkeypatch):
    async def dead_gateway(prompt, run=None, owner_id=None):
        return None, None

    monkeypatch.setattr(ag, '_try_gateway', dead_gateway)
    run = _drive(_run([_step('plan')]))
    assert '未获得规划结果' in run['steps'][0]['detail']


def test_act_surfaces_pending_approval(monkeypatch):
    """有操作等审批时必须停下来，不能静默继续往下跑。"""
    gw, _ = _fake_gateway()
    monkeypatch.setattr(ag, '_try_gateway', gw)

    from backend.app.platform_api import agent_bridge as bridge
    ctx = _Ctx()

    async def chat_with_pending(system_prompt, message, target, *, context, history=None):
        ctx.pending_flag = True
        return '已提交写入请求，等待批准'

    monkeypatch.setattr(bridge, 'run_agent_chat', chat_with_pending, raising=False)
    monkeypatch.setattr(bridge, 'bridge_capabilities',
                        lambda *a, **k: {'tools_available': True}, raising=False)
    monkeypatch.setattr(ag, '_resolve_gateway_target',
                        lambda run, owner_id=None: ('http://gw/v1', 'k', 'm', 'p'), raising=False)
    monkeypatch.setattr(ag, '_context_for_run', lambda rid, run: ctx, raising=False)

    run = _drive(_run([_step('act', '执行')]))
    assert run['status'] == 'awaiting_review', '有待批操作时应挂起等待用户'
    assert '尚未执行' in run['steps'][0]['detail']


# ---------------------------------------------------------------------------
# 5. needs_review 语义（审查发生在执行前）
# ---------------------------------------------------------------------------

def test_needs_review_suspends_before_execution(monkeypatch):
    """审查在执行前：挂起时不得已经调用模型产生「产物」。"""
    from backend.app.platform_api import agent_bridge as bridge
    called: list[str] = []

    async def spy_chat(*a, **k):
        called.append('x')
        return '不该被调用'

    monkeypatch.setattr(bridge, 'run_agent_chat', spy_chat, raising=False)
    monkeypatch.setattr(bridge, 'bridge_capabilities',
                        lambda *a, **k: {'tools_available': True}, raising=False)
    monkeypatch.setattr(ag, '_resolve_gateway_target',
                        lambda run, owner_id=None: ('http://gw/v1', 'k', 'm', 'p'), raising=False)
    monkeypatch.setattr(ag, '_context_for_run', lambda rid, run: _Ctx(), raising=False)

    run = _drive(_run([_step('act', '待审步骤', needs_review=True)]))
    assert run['status'] == 'awaiting_review'
    assert called == [], '审查前的挂起不应已经执行该步骤'
    detail = run['steps'][0]['detail']
    assert '待审查' in detail
    assert '批准后继续执行' in detail
