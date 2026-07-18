"""platform_api 子模块：智能体舱（多智能体编排核心）。

职责：
- 智能体 CRUD（角色定位 / 人格 / 思考深度 / 工作档位 / 权限面 / 绑定模型）
- 团队 CRUD（sequential / parallel / review_loop 三种编排）
- 编排运行 run：asyncio.create_task 后台逐步推进 plan/act/review/reflect，
  gear=human_review 时关键步骤进入 awaiting_review 等待人工放行；
  结果生成优先尝试 model_gateway（配置就绪才真实调用），失败回退模拟，
  并以 engine:'mock'|'gateway' 诚实标注。
- 对话 / 浮动工作区（子代理）/ 上下文大小估算。

持久化：JsonStore('agents')（agents + teams + floating 三个命名空间）、
JsonStore('agent_runs')（run 记录）。前端契约字段一律顶层平铺。

路由顺序约定：所有固定路径（teams/run/runs/chat/subagent/workspace/
context-size）必须先于参数路径 /{aid} 声明，避免被 aid 吞掉。
"""
from __future__ import annotations

import asyncio
import random
import uuid
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from app.platform_api.deps import THINK_DEPTHS, THINK_DEPTH_LABELS, WORK_GEARS
from app.platform_api.store import JsonStore

router = APIRouter(prefix='/agents', tags=['智能体舱'])

_agents = JsonStore('agents')
_runs = JsonStore('agent_runs')

_TEAMS_KEY = '_teams'      # agents 库内团队命名空间
_FLOATING_KEY = '_floating'  # agents 库内浮动会话命名空间

RUN_STATUSES = ('queued', 'running', 'awaiting_review', 'done', 'failed', 'cancelled')
CONTEXT_LIMIT = 128000
# 工作档位为「人工审查」时，以下步骤类型需人工放行
REVIEW_STEP_KINDS = ('act', 'review')


# ---------------------------------------------------------------- 工具

def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec='seconds')


def _new_id(prefix: str) -> str:
    return f'{prefix}_{uuid.uuid4().hex[:10]}'


def _est_tokens(text: str) -> int:
    """粗略 token 估算：约 2 字符 1 token。"""
    return max(1, len(text) // 2) if text else 0


def _valid_depth(value: str | None, default: str = 'medium') -> str:
    return value if value in THINK_DEPTHS else default


def _valid_gear(value: str | None, default: str = 'sandbox') -> str:
    return value if value in WORK_GEARS else default


def _depth_steps(depth: str) -> int:
    """思考深度 → 模拟推理要点条数。"""
    return {
        'low': 1, 'medium': 2, 'high': 3, 'xhigh': 3, 'max': 4, 'ultracode': 4,
    }.get(depth, 2)


# asyncio.create_task 返回值仅被事件 loop 弱引用持有；
# 不显式留强引用，后台任务可能被 GC 中途回收（run 永久卡 running）。
_BG_TASKS: set[asyncio.Task] = set()


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)


# ---------------------------------------------------------------- 模型

class Permissions(BaseModel):
    fs_read: bool = True
    fs_write: bool = False
    shell: bool = False
    network: bool = False
    git: bool = False


class AgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    role: str = ''
    persona: str = ''
    depth: str = 'medium'
    gear: str = 'sandbox'
    permissions: Permissions = Field(default_factory=Permissions)
    provider_pid: str = ''
    model: str = ''
    goal: str = ''

    @field_validator('depth')
    @classmethod
    def _check_depth(cls, v: str) -> str:
        if v not in THINK_DEPTHS:
            raise ValueError(f'depth 须为 {THINK_DEPTHS} 之一')
        return v

    @field_validator('gear')
    @classmethod
    def _check_gear(cls, v: str) -> str:
        if v not in WORK_GEARS:
            raise ValueError(f'gear 须为 {list(WORK_GEARS)} 之一')
        return v


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    role: str | None = None
    persona: str | None = None
    depth: str | None = None
    gear: str | None = None
    permissions: Permissions | None = None
    provider_pid: str | None = None
    model: str | None = None
    goal: str | None = None

    @field_validator('depth')
    @classmethod
    def _check_depth(cls, v: str | None) -> str | None:
        if v is not None and v not in THINK_DEPTHS:
            raise ValueError(f'depth 须为 {THINK_DEPTHS} 之一')
        return v

    @field_validator('gear')
    @classmethod
    def _check_gear(cls, v: str | None) -> str | None:
        if v is not None and v not in WORK_GEARS:
            raise ValueError(f'gear 须为 {list(WORK_GEARS)} 之一')
        return v


class TeamIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    member_ids: list[str] = Field(default_factory=list)
    orchestration: Literal['sequential', 'parallel', 'review_loop'] = 'sequential'
    description: str = ''


class TeamUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    member_ids: list[str] | None = None
    orchestration: Literal['sequential', 'parallel', 'review_loop'] | None = None
    description: str | None = None


class RunIn(BaseModel):
    agent_id: str | None = None
    team_id: str | None = None
    task: str = Field(min_length=1)
    goal: str | None = None
    depth: str | None = None
    gear: str | None = None
    context: dict[str, Any] | str | None = None


class Attachment(BaseModel):
    name: str = ''
    mime: str = ''
    size: int = 0


class ChatIn(BaseModel):
    message: str = Field(min_length=1)
    agent_id: str | None = None
    depth: str | None = None
    gear: str | None = None
    goal: str | None = None
    attachments: list[Attachment] = Field(default_factory=list)


class SubagentIn(BaseModel):
    parent_run_id: str | None = None
    task: str = Field(min_length=1)


class ApproveIn(BaseModel):
    note: str = ''


# ---------------------------------------------------------------- 读写辅助

def _agents_map() -> dict[str, Any]:
    return {k: v for k, v in _agents.all().items() if not k.startswith('_')}


def _teams_map() -> dict[str, Any]:
    data = _agents.get(_TEAMS_KEY, {})
    return data if isinstance(data, dict) else {}


def _save_team(tid: str, team: dict | None) -> None:
    teams = _teams_map()
    if team is None:
        teams.pop(tid, None)
    else:
        teams[tid] = team
    _agents.set(_TEAMS_KEY, teams)


def _floating_map() -> dict[str, Any]:
    data = _agents.get(_FLOATING_KEY, {})
    return data if isinstance(data, dict) else {}


def _touch_floating(rid: str, status: str) -> None:
    sessions = _floating_map()
    for sid, sess in sessions.items():
        if sess.get('run_id') == rid:
            sess['status'] = status
            sess['last_active_at'] = _now()
            sessions[sid] = sess
            _agents.set(_FLOATING_KEY, sessions)
            return


def _register_floating(run: dict) -> dict:
    sessions = _floating_map()
    sid = _new_id('fl')
    sess = {
        'id': sid,
        'run_id': run['id'],
        'task': run['task'],
        'parent_run_id': run.get('parent_run_id'),
        'status': run['status'],
        'created_at': run['created_at'],
        'last_active_at': _now(),
    }
    sessions[sid] = sess
    _agents.set(_FLOATING_KEY, sessions)
    return sess


def _get_agent_or_404(aid: str) -> dict:
    agent = _agents.get(aid)
    if not isinstance(agent, dict) or aid.startswith('_'):
        raise HTTPException(status_code=404, detail=f'智能体 {aid} 不存在')
    return agent


# ---------------------------------------------------------------- 模拟引擎

def _mock_step_detail(run: dict, step: dict) -> str:
    task = run.get('task', '')
    depth = run.get('depth', 'medium')
    n = _depth_steps(depth)
    kind = step.get('kind')
    label = THINK_DEPTH_LABELS.get(depth, depth)
    if kind == 'plan':
        points = [
            f'拆解目标「{task[:40]}」的关键约束与交付物',
            '确定信息收集范围与优先级',
            '评估可用权限面，划定执行边界',
            '预设验收标准与回退方案',
        ][:n]
        body = '；'.join(f'{i + 1}) {p}' for i, p in enumerate(points))
        return f'【规划·{label}】{body}。'
    if kind == 'act':
        perm = run.get('permissions') or {}
        granted = [k for k, v in perm.items() if v] or ['（无显式授权）']
        return (
            f'【执行·{label}】按规划推进「{task[:40]}」：完成核心动作（模拟），'
            f'声明权限面 {granted}，未真实触达文件/网络/Shell。'
        )
    if kind == 'review':
        return (
            f'【审查】关键动作待人工确认：任务「{task[:40]}」的执行产物与权限使用'
            f'是否符合预期；通过后继续后续步骤。'
        )
    # reflect
    return (
        f'【复盘·{label}】任务「{task[:40]}」按预期收敛；'
        f'可改进点：补充真实数据校验、缩短规划-执行回路。'
    )


def _mock_result(run: dict) -> str:
    steps = run.get('steps', [])
    done = [s for s in steps if s.get('status') == 'done']
    names = '、'.join(s.get('name', '') for s in done) or '（无）'
    gear_label = WORK_GEARS.get(run.get('gear', ''), run.get('gear', ''))
    depth_label = THINK_DEPTH_LABELS.get(run.get('depth', ''), run.get('depth', ''))
    return (
        f'【任务结论】「{run.get("task", "")[:60]}」已完成（模拟引擎）。\n'
        f'【编排】{run.get("kind", "solo")} ｜ 档位 {gear_label} ｜ 深度 {depth_label}\n'
        f'【过程摘要】已执行步骤：{names}，共 {len(done)} 步。\n'
        f'【结果】目标达成度评估为良好；产物为结构化中文结论（本段文本）。\n'
        f'【后续建议】1) 接入真实模型网关后可复跑对比；2) 人工审查链路保持开启。'
    )


def _mock_chat_reply(
    message: str,
    agent: dict | None,
    depth: str,
    gear: str,
    goal: str,
    attachments: list[Attachment],
) -> str:
    name = (agent or {}).get('name', '通用智能体')
    role = (agent or {}).get('role', '通用协作角色')
    depth_label = THINK_DEPTH_LABELS.get(depth, depth)
    gear_label = WORK_GEARS.get(gear, gear)
    n = _depth_steps(depth)
    ideas = [
        f'先厘清「{message[:30]}」的真实诉求与约束，再给出可执行路径',
        '将问题拆为信息收集、方案设计、落地验证三段推进',
        '对关键不确定点先行假设并标注置信度，后续用证据修正',
        '对齐当前目标与权限面，避免越权操作与范围蔓延',
    ][:n]
    idea_lines = '\n'.join(f'{i + 1}. {idea}' for i, idea in enumerate(ideas))
    attach_line = ''
    if attachments:
        listing = '、'.join(f'{a.name or "附件"}({a.mime or "unknown"})' for a in attachments)
        attach_line = f'\n【附件】已收到 {len(attachments)} 个附件：{listing}（当前仅登记元信息，未读取内容）。'
    goal_line = f'\n【目标对齐】{goal}' if goal else ''
    return (
        f'【{name}｜{role}】已收到你的消息。\n'
        f'【任务理解】{message[:80]}{"……" if len(message) > 80 else ""}\n'
        f'【思考深度】{depth_label} ｜ 【工作档位】{gear_label}\n'
        f'【执行思路】\n{idea_lines}\n'
        f'【下一步】确认方向后，可发起编排运行（run）进入 plan/act/reflect 流程；'
        f'关键步骤将按档位{("提交人工审查" if gear == "human_review" else "自动推进")}。'
        f'{goal_line}{attach_line}'
    )


# ---------------------------------------------------------------- 网关尝试（配置就绪才真实调用）

async def _try_gateway(prompt: str) -> str | None:
    """尝试经 model_gateway 真实补全；任何不满足/失败均返回 None（回退模拟）。"""
    def _call() -> str | None:
        try:
            from app.model_gateway import service as mgw  # 延迟导入，故障隔离
            cfg = mgw._provider_config('openai_compatible')  # noqa: SLF001
            if not cfg or not cfg.get('enabled'):
                return None
            api_base = (cfg.get('api_base') or '').strip()
            model = (cfg.get('model') or '').strip()
            if not api_base or not model:
                return None
            status, _ms, text = mgw._openai_compatible_smoke(  # noqa: SLF001
                api_base, cfg.get('api_key') or '', model, prompt[:800], 384,
            )
            text = (text or '').strip()
            return text if status == 'ok' and text else None
        except Exception:  # noqa: BLE001 —— 网关故障不得拖垮编排
            return None

    try:
        return await asyncio.wait_for(asyncio.to_thread(_call), timeout=15)
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------- 编排驱动

def _build_steps(kind: str, orchestration: str, members: list[dict], gear: str) -> list[dict]:
    def mk(idx: int, name: str, skind: str, title: str) -> dict:
        return {
            'id': _new_id('st'),
            'index': idx,
            'name': name,
            'kind': skind,
            'title': title,
            'status': 'pending',
            'needs_review': gear == 'human_review' and skind in REVIEW_STEP_KINDS,
            'detail': '',
            'started_at': None,
            'finished_at': None,
        }

    steps: list[dict] = []
    if kind == 'team' and orchestration == 'sequential':
        i = 0
        for m in members:
            steps.append(mk(i, f'plan:{m["name"]}', 'plan', f'{m["name"]} 规划'))
            i += 1
            steps.append(mk(i, f'act:{m["name"]}', 'act', f'{m["name"]} 执行'))
            i += 1
        steps.append(mk(i, 'reflect:汇总', 'reflect', '团队汇总复盘'))
    elif kind == 'team' and orchestration == 'parallel':
        steps.append(mk(0, 'plan:分工', 'plan', 'orchestrator 任务分工'))
        for j, m in enumerate(members, start=1):
            steps.append(mk(j, f'act:{m["name"]}', 'act', f'{m["name"]} 并行执行'))
        steps.append(mk(len(members) + 1, 'reflect:汇总', 'reflect', '团队汇总复盘'))
    elif kind == 'team' and orchestration == 'review_loop':
        steps.append(mk(0, 'plan', 'plan', '初稿规划'))
        steps.append(mk(1, 'act:初稿', 'act', '产出初稿'))
        steps.append(mk(2, 'review:一审', 'review', '审查初稿'))
        steps.append(mk(3, 'act:修订', 'act', '按审查意见修订'))
        steps.append(mk(4, 'reflect', 'reflect', '复盘定稿'))
    else:  # solo / subagent / chat 基础三段式
        steps.append(mk(0, 'plan', 'plan', '规划'))
        steps.append(mk(1, 'act', 'act', '执行'))
        steps.append(mk(2, 'reflect', 'reflect', '复盘'))
    return steps


def _new_run(
    *,
    kind: str,
    task: str,
    agent: dict | None = None,
    team: dict | None = None,
    parent_run_id: str | None = None,
    goal: str | None = None,
    depth: str | None = None,
    gear: str | None = None,
    context: dict[str, Any] | str | None = None,
) -> dict:
    agent = agent or {}
    resolved_depth = _valid_depth(depth or agent.get('depth'), 'medium')
    resolved_gear = _valid_gear(gear or agent.get('gear'), 'sandbox')
    members: list[dict] = []
    orchestration = ''
    if team:
        orchestration = team.get('orchestration', 'sequential')
        amap = _agents_map()
        members = [amap[mid] for mid in team.get('member_ids', []) if mid in amap]
    now = _now()
    run = {
        'id': _new_id('run'),
        'kind': kind,
        'agent_id': agent.get('id'),
        'agent_name': agent.get('name', ''),
        'team_id': (team or {}).get('id'),
        'team_name': (team or {}).get('name', ''),
        'orchestration': orchestration,
        'parent_run_id': parent_run_id,
        'task': task,
        'goal': goal if goal is not None else agent.get('goal', ''),
        'depth': resolved_depth,
        'gear': resolved_gear,
        'context': context,
        'permissions': agent.get('permissions', {}),
        'provider_pid': agent.get('provider_pid', ''),
        'model': agent.get('model', ''),
        'status': 'queued',
        'engine': 'mock',
        'steps': _build_steps(kind, orchestration, members, resolved_gear),
        'cursor': 0,
        'result': '',
        'error': '',
        'created_at': now,
        'updated_at': now,
        'finished_at': None,
    }
    _runs.set(run['id'], run)
    return run


async def _finalize_run(rid: str) -> None:
    run = _runs.get(rid)
    if not run or run.get('status') in ('done', 'failed', 'cancelled'):
        return
    prompt = (
        f'任务：{run.get("task", "")}\n目标：{run.get("goal", "")}\n'
        f'请给出简洁的中文执行结论。'
    )
    gateway_text = await _try_gateway(prompt)
    run = _runs.get(rid)  # 重新读取，避免覆盖并发改动
    if not run or run.get('status') in ('done', 'failed', 'cancelled'):
        return
    if gateway_text:
        run['engine'] = 'gateway'
        run['result'] = f'{gateway_text}\n\n—— 以上由模型网关真实生成（engine=gateway）。'
    else:
        run['engine'] = 'mock'
        run['result'] = _mock_result(run)
    run['status'] = 'done'
    run['updated_at'] = _now()
    run['finished_at'] = _now()
    _runs.set(rid, run)
    _touch_floating(rid, 'done')


async def _drive_run(rid: str) -> None:
    """后台推进 run：逐步 running→done；人工审查档位在关键步骤挂起。"""
    try:
        while True:
            run = _runs.get(rid)
            if not run or run.get('status') in ('done', 'failed', 'cancelled', 'awaiting_review'):
                return
            idx = run.get('cursor', 0)
            steps = run.get('steps', [])
            if idx >= len(steps):
                await _finalize_run(rid)
                return
            if run.get('status') == 'queued':
                run['status'] = 'running'
            step = steps[idx]
            step['status'] = 'running'
            step['started_at'] = _now()
            run['updated_at'] = _now()
            _runs.set(rid, run)
            _touch_floating(rid, 'running')

            await asyncio.sleep(random.uniform(0.5, 1.0))

            run = _runs.get(rid)  # sleep 期间可能被取消
            if not run or run.get('status') == 'cancelled':
                return
            step = run['steps'][idx]
            if step.get('needs_review'):
                step['status'] = 'awaiting_review'
                if not step.get('detail'):
                    step['detail'] = _mock_step_detail(run, step)
                run['status'] = 'awaiting_review'
                run['cursor'] = idx
                run['updated_at'] = _now()
                _runs.set(rid, run)
                _touch_floating(rid, 'awaiting_review')
                return  # 等待 approve 重新唤起
            step['status'] = 'done'
            step['detail'] = _mock_step_detail(run, step)
            step['finished_at'] = _now()
            run['cursor'] = idx + 1
            run['updated_at'] = _now()
            _runs.set(rid, run)
    except Exception as exc:  # noqa: BLE001 —— 任何异常都落账为 failed
        run = _runs.get(rid)
        if run:
            run['status'] = 'failed'
            run['error'] = f'{type(exc).__name__}: {exc}'
            run['updated_at'] = _now()
            _runs.set(rid, run)
            _touch_floating(rid, 'failed')


# ---------------------------------------------------------------- 智能体 CRUD

@router.get('')
def list_agents():
    items = sorted(_agents_map().values(), key=lambda a: a.get('created_at', ''), reverse=True)
    return {'items': items, 'total': len(items)}


@router.post('', status_code=201)
def create_agent(body: AgentIn):
    agent = {
        'id': _new_id('ag'),
        **body.model_dump(),
        'created_at': _now(),
    }
    _agents.set(agent['id'], agent)
    return agent


@router.get('/teams')
def list_teams():
    items = sorted(_teams_map().values(), key=lambda t: t.get('created_at', ''), reverse=True)
    amap = _agents_map()
    for t in items:
        t['members'] = [amap[mid] for mid in t.get('member_ids', []) if mid in amap]
    return {'items': items, 'total': len(items)}


@router.post('/teams', status_code=201)
def create_team(body: TeamIn):
    amap = _agents_map()
    missing = [mid for mid in body.member_ids if mid not in amap]
    if missing:
        raise HTTPException(status_code=422, detail=f'成员不存在：{missing}')
    team = {
        'id': _new_id('tm'),
        **body.model_dump(),
        'created_at': _now(),
    }
    _save_team(team['id'], team)
    return team


@router.get('/teams/{tid}')
def get_team(tid: str):
    team = _teams_map().get(tid)
    if not team:
        raise HTTPException(status_code=404, detail=f'团队 {tid} 不存在')
    amap = _agents_map()
    team = dict(team)
    team['members'] = [amap[mid] for mid in team.get('member_ids', []) if mid in amap]
    return team


@router.put('/teams/{tid}')
def update_team(tid: str, body: TeamUpdate):
    team = _teams_map().get(tid)
    if not team:
        raise HTTPException(status_code=404, detail=f'团队 {tid} 不存在')
    patch = body.model_dump(exclude_none=True)
    if 'member_ids' in patch:
        amap = _agents_map()
        missing = [mid for mid in patch['member_ids'] if mid not in amap]
        if missing:
            raise HTTPException(status_code=422, detail=f'成员不存在：{missing}')
    team.update(patch)
    _save_team(tid, team)
    return team


@router.delete('/teams/{tid}')
def delete_team(tid: str):
    if tid not in _teams_map():
        raise HTTPException(status_code=404, detail=f'团队 {tid} 不存在')
    _save_team(tid, None)
    return {'ok': True, 'id': tid}


# ---------------------------------------------------------------- 编排运行

@router.post('/run', status_code=201)
async def start_run(body: RunIn):
    if bool(body.agent_id) == bool(body.team_id):
        raise HTTPException(status_code=422, detail='agent_id 与 team_id 须且仅须提供一个')
    agent = team = None
    if body.agent_id:
        agent = _get_agent_or_404(body.agent_id)
        kind = 'solo'
    else:
        team = _teams_map().get(body.team_id)
        if not team:
            raise HTTPException(status_code=404, detail=f'团队 {body.team_id} 不存在')
        kind = 'team'
    run = _new_run(
        kind=kind, task=body.task, agent=agent, team=team,
        goal=body.goal, depth=body.depth, gear=body.gear, context=body.context,
    )
    _spawn(_drive_run(run['id']))
    return run


@router.get('/runs')
def list_runs(status: str | None = Query(default=None)):
    items = sorted(_runs.all().values(), key=lambda r: r.get('created_at', ''), reverse=True)
    if status:
        items = [r for r in items if r.get('status') == status]
    return {'items': items, 'total': len(items)}


@router.get('/runs/{rid}')
def get_run(rid: str):
    run = _runs.get(rid)
    if not run:
        raise HTTPException(status_code=404, detail=f'运行 {rid} 不存在')
    return run


@router.post('/runs/{rid}/approve')
async def approve_run(rid: str, body: ApproveIn | None = None):
    run = _runs.get(rid)
    if not run:
        raise HTTPException(status_code=404, detail=f'运行 {rid} 不存在')
    if run.get('status') != 'awaiting_review':
        raise HTTPException(status_code=409, detail=f'当前状态 {run.get("status")} 不可审批')
    idx = run.get('cursor', 0)
    note = (body.note if body else '') or ''
    if idx < len(run.get('steps', [])):
        step = run['steps'][idx]
        step['status'] = 'done'
        suffix = f'\n【人工审查】通过。{("备注：" + note) if note else ""}'.rstrip()
        step['detail'] = (step.get('detail') or '') + suffix
        step['finished_at'] = _now()
    run['cursor'] = idx + 1
    run['status'] = 'running'
    run['updated_at'] = _now()
    _runs.set(rid, run)
    _spawn(_drive_run(rid))
    return run


@router.post('/runs/{rid}/cancel')
def cancel_run(rid: str):
    run = _runs.get(rid)
    if not run:
        raise HTTPException(status_code=404, detail=f'运行 {rid} 不存在')
    if run.get('status') in ('done', 'failed', 'cancelled'):
        raise HTTPException(status_code=409, detail=f'当前状态 {run.get("status")} 不可取消')
    for step in run.get('steps', []):
        if step.get('status') in ('pending', 'running', 'awaiting_review'):
            step['status'] = 'skipped'
    run['status'] = 'cancelled'
    run['error'] = '人工取消'
    run['updated_at'] = _now()
    run['finished_at'] = _now()
    _runs.set(rid, run)
    _touch_floating(rid, 'cancelled')
    return run


# ---------------------------------------------------------------- 对话

@router.post('/chat')
async def chat(body: ChatIn):
    agent = _agents.get(body.agent_id) if body.agent_id else None
    if body.agent_id and not isinstance(agent, dict):
        raise HTTPException(status_code=404, detail=f'智能体 {body.agent_id} 不存在')
    depth = _valid_depth(body.depth or (agent or {}).get('depth'), 'medium')
    gear = _valid_gear(body.gear or (agent or {}).get('gear'), 'sandbox')
    goal = body.goal if body.goal is not None else (agent or {}).get('goal', '')
    reply = _mock_chat_reply(body.message, agent, depth, gear, goal, body.attachments)
    context_chars = (
        len(body.message) + len(goal or '')
        + sum(len(a.name) + len(a.mime) + 8 for a in body.attachments)
    )
    run = _new_run(
        kind='chat', task=body.message[:120], agent=agent,
        goal=goal, depth=depth, gear=gear,
        context={'attachments': [a.model_dump() for a in body.attachments]},
    )
    # 对话即问即答：步骤同步完成，不走后台推进
    now = _now()
    for step in run['steps']:
        step['status'] = 'done'
        step['detail'] = _mock_step_detail(run, step)
        step['started_at'] = now
        step['finished_at'] = now
        step['needs_review'] = False
    run.update({
        'status': 'done', 'cursor': len(run['steps']), 'result': reply,
        'engine': 'mock', 'updated_at': now, 'finished_at': now,
    })
    _runs.set(run['id'], run)
    return {
        'reply': reply,
        'context_tokens': context_chars // 2,
        'run_id': run['id'],
        'depth': depth,
        'gear': gear,
        'engine': 'mock',
        'agent_id': body.agent_id,
    }


# ---------------------------------------------------------------- 浮动工作区 / 子代理

@router.post('/subagent', status_code=201)
async def spawn_subagent(body: SubagentIn):
    parent = None
    if body.parent_run_id:
        parent = _runs.get(body.parent_run_id)
        if not parent:
            raise HTTPException(status_code=404, detail=f'父运行 {body.parent_run_id} 不存在')
    run = _new_run(
        kind='subagent', task=body.task, parent_run_id=body.parent_run_id,
        depth=(parent or {}).get('depth'), gear=(parent or {}).get('gear'),
        context={'spawned_by': body.parent_run_id or 'manual'},
    )
    sess = _register_floating(run)
    _spawn(_drive_run(run['id']))
    return {'run': run, 'session': sess}


@router.get('/workspace/floating')
def floating_workspace():
    sessions = _floating_map()
    cutoff = datetime.now().astimezone() - timedelta(minutes=30)
    items = []
    changed = False
    for sid, sess in list(sessions.items()):
        run = _runs.get(sess.get('run_id', ''))
        if run and run.get('status') != sess.get('status'):
            sess['status'] = run['status']
            sess['last_active_at'] = _now()
            sessions[sid] = sess
            changed = True
        # 终态且超过 30 分钟的会话从浮动工作区退场
        try:
            last = datetime.fromisoformat(sess.get('last_active_at', ''))
        except ValueError:
            last = cutoff - timedelta(seconds=1)
        if sess.get('status') in ('done', 'failed', 'cancelled') and last < cutoff:
            sessions.pop(sid)
            changed = True
            continue
        items.append(sess)
    if changed:
        _agents.set(_FLOATING_KEY, sessions)
    items.sort(key=lambda s: s.get('last_active_at', ''), reverse=True)
    return {'items': items, 'total': len(items)}


# ---------------------------------------------------------------- 上下文大小

@router.get('/context-size')
def context_size(agent_id: str | None = Query(default=None)):
    agent: dict = {}
    if agent_id:
        agent = _get_agent_or_404(agent_id)
    gear_label = WORK_GEARS.get(agent.get('gear', 'sandbox'), '沙盒工作')
    depth_label = THINK_DEPTH_LABELS.get(agent.get('depth', 'medium'), '常思')
    system_text = (
        f'你是「{agent.get("name", "通用智能体")}」，{agent.get("role", "通用协作角色")}。'
        f'{agent.get("persona", "")}工作档位：{gear_label}；思考深度：{depth_label}。'
    )
    memory_text = f'当前目标：{agent.get("goal", "（未设置）")}。记忆指令：保持目标对齐，关键结论落盘。'
    history_runs = [
        r for r in _runs.all().values()
        if agent_id and r.get('agent_id') == agent_id
    ]
    history_runs.sort(key=lambda r: r.get('created_at', ''), reverse=True)
    history_text = ''.join(
        f'任务：{r.get("task", "")}\n结果：{r.get("result", "")[:200]}\n'
        for r in history_runs[:10]
    )
    t_sys = _est_tokens(system_text)
    t_mem = _est_tokens(memory_text)
    t_his = _est_tokens(history_text)
    return {
        'agent_id': agent_id,
        'system_prompt': t_sys,
        'memory_instructions': t_mem,
        'history': t_his,
        'total_tokens': t_sys + t_mem + t_his,
        'limit': CONTEXT_LIMIT,
        'previews': {
            'system_prompt': system_text,
            'memory_instructions': memory_text,
            'history_runs': len(history_runs),
        },
    }


# ---------------------------------------------------------------- 参数路径（务必最后声明）

@router.get('/{aid}')
def get_agent(aid: str):
    return _get_agent_or_404(aid)


@router.put('/{aid}')
def update_agent(aid: str, body: AgentUpdate):
    agent = _get_agent_or_404(aid)
    agent.update(body.model_dump(exclude_none=True))
    _agents.set(aid, agent)
    return agent


@router.delete('/{aid}')
def delete_agent(aid: str):
    _get_agent_or_404(aid)
    # JsonStore 无单键删除 API：持锁整库回写，同事务内删 agent + 修团队
    with _agents._lock:  # noqa: SLF001
        store = _agents._read()  # noqa: SLF001
        store.pop(aid, None)
        teams = store.get(_TEAMS_KEY)
        if isinstance(teams, dict):
            for t in teams.values():
                if isinstance(t, dict) and aid in t.get('member_ids', []):
                    t['member_ids'] = [m for m in t['member_ids'] if m != aid]
        _agents._write(store)  # noqa: SLF001
    return {'ok': True, 'id': aid}
