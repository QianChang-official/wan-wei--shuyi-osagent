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

"""万枢编程框架 —— HTTP API（platform_api 自动发现子模块）。

本模块顶层暴露 ``router``，被 ``platform_api.__init__`` 自动挂载到
``/platform`` 前缀下，故实际路径形如 ``/platform/coding/sessions``。

设计口径：
- **owner 隔离**：所有读写经 ``actor_id_for_request`` 绑定当前操作者，
  与他人会话互不可见；
- **工作区越界 fail-closed**：建会话即校验工作区（``open_workspace``），
  越界/敏感目录直接 403；
- **长任务不阻塞**：``run`` 丢后台线程执行，接口立即返回，进度走事件流；
- **事件流**：``/events`` 轮询增量 + ``/stream`` SSE 推送，二者同源。
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ..soul.ownership import actor_id_for_request
from . import constants, llm, memory_bridge, orchestrator, skills, store, subagent, tools, workflow
from .plan import Plan, PlanError, make_todos, set_todo_state
from .sandbox import SandboxViolation, open_workspace
from .schemas import (
    ApprovalResolveIn,
    MemoryWriteIn,
    PlanConfirmIn,
    PlanGenerateIn,
    SessionCreateIn,
    SubagentRunIn,
    TodoAddIn,
    TodoUpdateIn,
    ToolInvokeIn,
    WorkflowRunIn,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/coding', tags=['编程框架'])

# 正在运行的会话集合（进程内互斥，防同一会话并发 run 互相踩状态）
_running: set[str] = set()
_running_lock = threading.Lock()


def _owner(request: Request) -> str:
    return actor_id_for_request(request)


def _require_session(session_id: str, owner_id: str) -> dict[str, Any]:
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail='会话不存在')
    if session.get('owner_id') and session['owner_id'] != owner_id:
        raise HTTPException(status_code=404, detail='会话不存在')
    return session


def _open_workspace_or_403(path: str):
    try:
        return open_workspace(path)
    except (SandboxViolation, ValueError) as exc:
        # 异常文本可能带解析后的真实路径等内部布局信息，不外泄到响应体。
        logger.warning('[coding.api] 工作区打开被拒：%r', exc)
        raise HTTPException(status_code=403, detail='工作区不可用或不在允许范围内') from exc


# ---------------------------------------------------------------------------
# 框架元信息
# ---------------------------------------------------------------------------


@router.get('/overview')
def overview(request: Request) -> dict[str, Any]:
    """框架总览：能力清单与当前可用性（供工作台首屏渲染）。"""
    owner = _owner(request)
    return {
        'name': '万枢编程框架',
        'codename': 'wanshu-coding',
        'version': '1.0.0',
        'positioning': '以万枢的智能体/记忆/模型网关为内核的 AI 编程框架',
        'capabilities': [
            {'id': 'tools', 'label': '工具系统 + 权限沙箱', 'status': 'implemented'},
            {'id': 'plan', 'label': '计划模式 + 待办', 'status': 'implemented'},
            {'id': 'subagent', 'label': '子智能体 + 技能编排', 'status': 'implemented'},
            {'id': 'memory', 'label': '可审计编程记忆', 'status': 'implemented'},
            {'id': 'workflow', 'label': '工作流受控并发', 'status': 'implemented'},
            {'id': 'guard', 'label': '循环护栏', 'status': 'implemented'},
        ],
        'counts': {
            'tools': len(tools.catalog()),
            'skills': len(skills.load_all()),
            'subagent_roles': len(subagent.catalog()),
        },
        'policy_modes': [
            {'id': mode, 'label': constants.POLICY_MODE_LABELS[mode]} for mode in constants.POLICY_MODES
        ],
        'llm': {'available': llm.available(owner)},
    }


@router.get('/tools')
def list_tools() -> dict[str, Any]:
    return {'items': tools.catalog()}


@router.get('/skills')
def list_skills(session_id: str | None = Query(default=None), request: Request = None) -> dict[str, Any]:
    session = None
    if session_id:
        session = _require_session(session_id, _owner(request))
    return {'items': orchestrator.list_skills(session)}


@router.get('/subagents')
def list_subagents() -> dict[str, Any]:
    return {'items': subagent.catalog()}


@router.get('/policy')
def policy_matrix() -> dict[str, Any]:
    return {
        'modes': [{'id': m, 'label': constants.POLICY_MODE_LABELS[m]} for m in constants.POLICY_MODES],
        'risks': [{'id': r, 'label': constants.RISK_LEVEL_LABELS[r]} for r in constants.RISK_LEVELS],
        'matrix': {
            mode: {risk: constants.decide_risk(mode, risk) for risk in constants.RISK_LEVELS}
            for mode in constants.POLICY_MODES
        },
        'session_states': [
            {'id': s, 'label': constants.SESSION_STATE_LABELS[s]} for s in constants.SESSION_STATES
        ],
    }


# ---------------------------------------------------------------------------
# 会话
# ---------------------------------------------------------------------------


@router.post('/sessions')
def create_session(payload: SessionCreateIn, request: Request) -> dict[str, Any]:
    owner = _owner(request)
    workspace = _open_workspace_or_403(payload.workspace)
    session_id = store.new_id('cs')
    record = {
        'id': session_id,
        'owner_id': owner,
        'title': payload.title or payload.task[:40],
        'task': payload.task,
        'workspace': workspace.root_text,
        'policy_mode': payload.policy_mode,
        'provider_pid': payload.provider_pid,
        'state': 'drafting',
        'plan': Plan().public(),
        'todos': [],
        'subagents': [],
        'approvals': [],
        'guard': {},
        'last_run': None,
        'created_at': store.now(),
        'updated_at': store.now(),
    }
    store.create_session(record)
    store.append_event(session_id, 'session_created', {'task': record['task'], 'workspace': record['workspace']})
    return _session_detail(record)


@router.get('/sessions')
def list_sessions(request: Request, limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    owner = _owner(request)
    items = store.list_sessions(owner_id=owner, limit=limit)
    return {'items': [_session_brief(r) for r in items], 'total': len(items)}


@router.get('/sessions/{session_id}')
def get_session(session_id: str, request: Request) -> dict[str, Any]:
    session = _require_session(session_id, _owner(request))
    return _session_detail(session)


@router.delete('/sessions/{session_id}')
def delete_session(session_id: str, request: Request) -> dict[str, Any]:
    _require_session(session_id, _owner(request))
    removed = store.delete_session(session_id)
    return {'ok': removed, 'id': session_id}


def _session_brief(session: dict[str, Any]) -> dict[str, Any]:
    plan = session.get('plan') or {}
    return {
        'id': session['id'],
        'title': session.get('title', ''),
        'task': session.get('task', ''),
        'workspace': session.get('workspace', ''),
        'policy_mode': session.get('policy_mode', 'supervised'),
        'policy_label': constants.POLICY_MODE_LABELS.get(session.get('policy_mode', ''), ''),
        'state': session.get('state', 'drafting'),
        'state_label': constants.SESSION_STATE_LABELS.get(session.get('state', ''), ''),
        'plan_total': plan.get('total', 0),
        'plan_done': plan.get('done', 0),
        'pending_approvals': sum(1 for a in (session.get('approvals') or []) if a.get('status') == 'pending'),
        'created_at': session.get('created_at'),
        'updated_at': session.get('updated_at'),
    }


def _session_detail(session: dict[str, Any]) -> dict[str, Any]:
    detail = _session_brief(session)
    detail.update({
        'plan': session.get('plan') or {},
        'todos': session.get('todos') or [],
        'subagents': session.get('subagents') or [],
        'approvals': session.get('approvals') or [],
        'guard': session.get('guard') or {},
        'last_run': session.get('last_run'),
        'events': store.list_events(session['id'], limit=300),
        'running': session['id'] in _running,
    })
    return detail


# ---------------------------------------------------------------------------
# 计划
# ---------------------------------------------------------------------------


@router.post('/sessions/{session_id}/plan')
def generate_plan(session_id: str, payload: PlanGenerateIn, request: Request) -> dict[str, Any]:
    session = _require_session(session_id, _owner(request))
    if session.get('state') in ('running',):
        raise HTTPException(status_code=409, detail='会话执行中，无法重新规划')
    plan = orchestrator.build_plan_for(session)
    plan.steps = plan.steps[:payload.max_steps]
    if payload.use_llm and llm.available(_owner(request)):
        _enrich_plan_with_llm(plan, session, _owner(request))
    session['plan'] = plan.public()
    if session.get('state') in ('drafting', 'failed'):
        session['state'] = 'planning'
    if session.get('state') == 'planning':
        session['state'] = 'awaiting'
    store.update_session(session_id, {'plan': session['plan'], 'state': session['state']})
    store.append_event(session_id, 'plan_proposed', {'plan': session['plan']})
    return {'plan': session['plan'], 'state': session['state']}


def _enrich_plan_with_llm(plan: Plan, session: dict[str, Any], owner_id: str) -> None:
    """用 LLM 覆盖步骤标题/细节；失败则保持启发式，不阻断。"""
    titles = '\n'.join(f'{i + 1}. {s.title}' for i, s in enumerate(plan.steps))
    prompt = (
        f'任务：{session.get("task", "")}\n现有步骤骨架：\n{titles}\n'
        '请为每一步给出一句更具体、贴合该任务的说明，逐行输出「序号. 说明」，不要多余解释。'
    )
    res = llm.complete(prompt, owner_id=owner_id, max_tokens=600)
    if not res.get('ok'):
        return
    lines = [ln.strip() for ln in res['text'].splitlines() if ln.strip()]
    for idx, step in enumerate(plan.steps):
        if idx < len(lines):
            detail = lines[idx].split('.', 1)[-1].strip()
            if detail:
                step.detail = detail
    plan.source = 'llm'


@router.post('/sessions/{session_id}/plan/confirm')
def confirm_plan_endpoint(session_id: str, payload: PlanConfirmIn, request: Request) -> dict[str, Any]:
    session = _require_session(session_id, _owner(request))
    if session.get('state') not in ('awaiting', 'planning', 'drafting'):
        raise HTTPException(status_code=409, detail=f'当前状态 {session.get("state")} 无法确认计划')
    try:
        result = orchestrator.confirm(session, approved=payload.approved)
    except orchestrator.OrchestratorError as exc:
        logger.warning('[coding.api] 确认计划被拒：%r', exc)
        raise HTTPException(status_code=409, detail='plan_confirm_rejected') from exc
    return result


# ---------------------------------------------------------------------------
# 执行
# ---------------------------------------------------------------------------


@router.post('/sessions/{session_id}/run')
async def run_session(session_id: str, request: Request) -> dict[str, Any]:
    session = _require_session(session_id, _owner(request))
    if session.get('state') == 'paused':
        raise HTTPException(status_code=409, detail='会话因审批暂停，请先处理审批再续跑')
    if session.get('state') in {'done', 'failed', 'cancelled'}:
        raise HTTPException(status_code=409, detail=f"会话已终结（{session['state']}），不能再次执行")
    if not (session.get('plan') or {}).get('confirmed'):
        raise HTTPException(status_code=409, detail='计划未经确认，拒绝执行')
    with _running_lock:
        if session_id in _running:
            raise HTTPException(status_code=409, detail='会话正在执行中')
        _running.add(session_id)

    async def _worker() -> None:
        try:
            fresh = store.get_session(session_id) or session
            await asyncio.to_thread(orchestrator.run_session, fresh, owner_id=_owner(request))
        except Exception:  # noqa: BLE001 —— 后台任务异常不外泄，落事件
            logger.exception('[coding.api] run 失败 session=%s', session_id)
            store.append_event(session_id, 'error', {'message': 'run 异常终止'})
        finally:
            with _running_lock:
                _running.discard(session_id)

    asyncio.create_task(_worker())
    return {'ok': True, 'session_id': session_id, 'status': 'started'}


@router.post('/sessions/{session_id}/resume')
async def resume_session(session_id: str, request: Request) -> dict[str, Any]:
    session = _require_session(session_id, _owner(request))
    if session.get('state') != 'paused':
        raise HTTPException(status_code=409, detail='仅暂停中的会话可续跑')
    pending = [a for a in (session.get('approvals') or []) if a.get('status') == 'pending']
    if pending:
        raise HTTPException(status_code=409, detail=f'仍有 {len(pending)} 条审批待处理')
    with _running_lock:
        if session_id in _running:
            raise HTTPException(status_code=409, detail='会话正在执行中')
        _running.add(session_id)

    async def _worker() -> None:
        try:
            fresh = store.get_session(session_id) or session
            await asyncio.to_thread(orchestrator.run_session, fresh, owner_id=_owner(request))
        except Exception:  # noqa: BLE001
            logger.exception('[coding.api] resume 失败 session=%s', session_id)
            store.append_event(session_id, 'error', {'message': 'resume 异常终止'})
        finally:
            with _running_lock:
                _running.discard(session_id)

    asyncio.create_task(_worker())
    return {'ok': True, 'session_id': session_id, 'status': 'resumed'}


# ---------------------------------------------------------------------------
# 工具 / 审批
# ---------------------------------------------------------------------------


@router.post('/sessions/{session_id}/tool')
def invoke_tool(session_id: str, payload: ToolInvokeIn, request: Request) -> dict[str, Any]:
    session = _require_session(session_id, _owner(request))
    try:
        return orchestrator.run_tool_direct(session, payload.tool_id, payload.params, owner_id=_owner(request))
    except (SandboxViolation, ValueError) as exc:
        logger.warning('[coding.api] 工具调用被拒：%r', exc)
        raise HTTPException(status_code=422, detail='tool_invoke_rejected') from exc


@router.post('/sessions/{session_id}/approvals/{approval_id}')
def resolve_approval(session_id: str, approval_id: str, payload: ApprovalResolveIn, request: Request) -> dict[str, Any]:
    session = _require_session(session_id, _owner(request))
    try:
        return orchestrator.resolve_approval(session, approval_id, approved=payload.approved,
                                             note=payload.note, owner_id=_owner(request))
    except orchestrator.OrchestratorError as exc:
        logger.warning('[coding.api] 审批处理被拒：%r', exc)
        raise HTTPException(status_code=409, detail='approval_resolve_rejected') from exc
    except SandboxViolation as exc:
        logger.warning('[coding.api] 审批执行越界：%r', exc)
        raise HTTPException(status_code=422, detail='approval_execution_rejected') from exc


# ---------------------------------------------------------------------------
# 待办
# ---------------------------------------------------------------------------


@router.post('/sessions/{session_id}/todos')
def add_todos(session_id: str, payload: TodoAddIn, request: Request) -> dict[str, Any]:
    session = _require_session(session_id, _owner(request))
    todos = [t.public() for t in make_todos(payload.items)]
    existing = session.get('todos') or []
    merged = existing + todos
    store.update_session(session_id, {'todos': merged})
    return {'todos': merged}


@router.post('/sessions/{session_id}/todos/{todo_id}')
def update_todo(session_id: str, todo_id: str, payload: TodoUpdateIn, request: Request) -> dict[str, Any]:
    from .plan import Todo

    session = _require_session(session_id, _owner(request))
    todos = [Todo(**{k: t.get(k, '') for k in ('id', 'text', 'state', 'note')}) for t in (session.get('todos') or [])]
    try:
        set_todo_state(todos, todo_id, payload.state, note=payload.note)
    except PlanError as exc:
        logger.warning('[coding.api] 待办状态转移非法：%r', exc)
        raise HTTPException(status_code=422, detail='todo_transition_rejected') from exc
    merged = [t.public() for t in todos]
    store.update_session(session_id, {'todos': merged})
    return {'todos': merged}


# ---------------------------------------------------------------------------
# 子智能体
# ---------------------------------------------------------------------------


@router.post('/sessions/{session_id}/subagents')
def run_subagent(session_id: str, payload: SubagentRunIn, request: Request) -> dict[str, Any]:
    session = _require_session(session_id, _owner(request))
    try:
        spec = subagent.spawn(role=payload.role, task=payload.task, parent_depth=0)
    except subagent.SubagentError as exc:
        logger.warning('[coding.api] 子智能体委派被拒：%r', exc)
        raise HTTPException(status_code=422, detail='subagent_spawn_rejected') from exc
    workspace = _open_workspace_or_403(session.get('workspace', ''))
    ctx = tools.ToolContext(workspace=workspace, policy_mode='readonly')
    store.append_event(session_id, 'subagent_spawned', {'subagent': spec.public()})
    subagent.run(spec, ctx)
    store.append_event(session_id, 'subagent_finished', {'subagent': spec.public()})
    bucket = session.setdefault('subagents', [])
    bucket.append(spec.public())
    store.update_session(session_id, {'subagents': bucket[-20:]})
    return {'subagent': spec.public()}


# ---------------------------------------------------------------------------
# 记忆（可审计）
# ---------------------------------------------------------------------------


@router.get('/sessions/{session_id}/memory')
def list_memory(session_id: str, request: Request) -> dict[str, Any]:
    _require_session(session_id, _owner(request))
    result = memory_bridge.list_memories(session_id=session_id, owner_id=_owner(request))
    result['summary'] = memory_bridge.summarize(result.get('items') or [])
    return result


@router.post('/sessions/{session_id}/memory')
def write_memory(session_id: str, payload: MemoryWriteIn, request: Request) -> dict[str, Any]:
    session = _require_session(session_id, _owner(request))
    result = memory_bridge.remember(
        session_id=session_id,
        workspace=session.get('workspace', ''),
        kind=payload.kind, title=payload.title, text=payload.text, owner_id=_owner(request),
    )
    if result.get('ok'):
        store.append_event(session_id, 'memory_written',
                           {'capsule_id': result.get('capsule_id'), 'kind': payload.kind, 'title': payload.title})
    return result


@router.post('/sessions/{session_id}/memory/{capsule_id}/forget')
def forget_memory(session_id: str, capsule_id: str, request: Request) -> dict[str, Any]:
    _require_session(session_id, _owner(request))
    result = memory_bridge.forget(capsule_id=capsule_id, owner_id=_owner(request))
    if result.get('ok'):
        store.append_event(session_id, 'memory_forgotten',
                           {'capsule_id': capsule_id, 'verification': result.get('deletion_verification')})
    return result


# ---------------------------------------------------------------------------
# 工作流
# ---------------------------------------------------------------------------


@router.post('/sessions/{session_id}/workflow')
def run_workflow(session_id: str, payload: WorkflowRunIn, request: Request) -> dict[str, Any]:
    session = _require_session(session_id, _owner(request))
    workspace = _open_workspace_or_403(session.get('workspace', ''))
    ctx = tools.ToolContext(workspace=workspace, policy_mode=session.get('policy_mode', 'supervised'))
    nodes = [workflow.WorkflowNode(id=n.id, title=n.title or n.id, kind=n.kind,
                                   payload=n.payload, depends_on=n.depends_on) for n in payload.nodes]

    def _executor(node: workflow.WorkflowNode) -> dict[str, Any]:
        if node.kind == 'tool':
            tool_id = str(node.payload.get('tool_id', ''))
            result = tools.invoke(tool_id, node.payload.get('params') or {}, ctx)
            return {'status': result.status, 'summary': result.summary, 'result': result.public()}
        if node.kind == 'subagent':
            spec = subagent.spawn(role=str(node.payload.get('role', 'explorer')),
                                  task=str(node.payload.get('task', session.get('task', ''))), parent_depth=0)
            subagent.run(spec, ctx)
            return {'status': 'ok' if spec.status == 'done' else 'failed', 'subagent': spec.public()}
        return {'status': 'ok', 'summary': 'noop'}

    store.append_event(session_id, 'workflow_started', {'nodes': [n.public() for n in nodes]})
    try:
        outcome = workflow.run(nodes, executor=_executor, concurrency=payload.concurrency)
    except workflow.WorkflowError as exc:
        logger.warning('[coding.api] 工作流定义非法：%r', exc)
        raise HTTPException(status_code=422, detail='workflow_definition_invalid') from exc
    store.append_event(session_id, 'workflow_finished',
                       {'ok': outcome['ok'], 'succeeded': outcome['succeeded'],
                        'failed': outcome['failed'], 'blocked': outcome['blocked']})
    return outcome


# ---------------------------------------------------------------------------
# 工作区树 & 事件流
# ---------------------------------------------------------------------------


@router.get('/sessions/{session_id}/tree')
def workspace_tree(session_id: str, request: Request, depth: int = Query(default=2, ge=1, le=4)) -> dict[str, Any]:
    session = _require_session(session_id, _owner(request))
    workspace = _open_workspace_or_403(session.get('workspace', ''))
    return {'tree': _build_tree(workspace.root, workspace.root, depth=depth)}


def _build_tree(root, current, *, depth: int) -> list[dict[str, Any]]:
    if depth <= 0:
        return []
    entries: list[dict[str, Any]] = []
    try:
        children = sorted(current.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except OSError:
        return []
    for child in children[:120]:
        if child.name in {'.git', 'node_modules', '__pycache__', '.venv'}:
            continue
        node = {
            'name': child.name,
            'path': child.relative_to(root).as_posix(),
            'type': 'dir' if child.is_dir() else 'file',
        }
        if child.is_dir():
            node['children'] = _build_tree(root, child, depth=depth - 1)
        entries.append(node)
    return entries


@router.get('/sessions/{session_id}/events')
def get_events(session_id: str, request: Request,
               after: int = Query(default=0, ge=0), limit: int = Query(default=500, ge=1, le=2000)) -> dict[str, Any]:
    _require_session(session_id, _owner(request))
    events = store.list_events(session_id, after_seq=after, limit=limit)
    return {'items': events, 'count': len(events),
            'last_seq': events[-1]['seq'] if events else after}


@router.get('/sessions/{session_id}/stream')
async def stream_events(session_id: str, request: Request, after: int = Query(default=0, ge=0)):
    """SSE 事件流：增量推送会话事件，供工作台时间线实时刷新。"""
    _require_session(session_id, _owner(request))

    async def _gen():
        cursor = after
        idle = 0
        while True:
            if await request.is_disconnected():
                break
            events = store.list_events(session_id, after_seq=cursor, limit=200)
            if events:
                idle = 0
                for event in events:
                    cursor = event['seq']
                    yield f'data: {json.dumps(event, ensure_ascii=False)}\n\n'
            else:
                idle += 1
                if idle % 15 == 0:
                    yield ': keep-alive\n\n'
                if idle > 600:  # ~10 分钟无事件则结束，避免连接泄漏
                    break
            await asyncio.sleep(1)

    return StreamingResponse(_gen(), media_type='text/event-stream')
