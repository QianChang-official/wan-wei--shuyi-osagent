"""platform_api.automation —— 自动化舱：AI 可编辑工作流与自动化。

职责：
- 工作流 CRUD（JsonStore('flows')）；
- AI 编辑：规则式中文解析器把自然语言指令转成完整流程定义 diff
  （engine='rule'，非模型生成，issue #45 P0-4；响应显式声明规则解析）。
  语义为「全量重建」：proposed_flow 每次都是按整段指令重建的完整流程定义，
  步骤序列整体替换，不是对现有步骤的增量调整（edit_mode='full_rebuild'）；
- 运行执行（JsonStore('flow_runs')）：asyncio 后台逐步执行，按流程档位
  （flow.gear）分两种模式，run 记录以 mode='real'|'dry_run' 如实标注：
  - dry_run（gear=human_review 默认档 / 显式 /flows/{fid}/simulate 入口）：
    shell/http/agent/memory 步骤一律不真实执行，仅返回 would_run 说明；
    run 记录 simulated 默认 False（P0-5），模拟态只能由显式模拟入口写入；
  - real（gear=sandbox/device 且经 /flows/{fid}/run 或定时触发）：真实
    执行。每步先过 _enforce_real_execution_gear 单一权限边界；shell 复用
    _system_svc_runtime 沙盒同一套白名单常量（cwd 监禁 data/platform/
    sandbox/、最小环境变量、5s 超时、stdout/stderr 截断 4KB）；http 仅
    GET/POST，经 resolve_external_url SSRF 校验后 pinned-IP 直连（10s
    超时、响应体截断 4KB）；memory 经 memory_runtime 真实读写（写入前过
    policy_gate）；condition 仅支持字面量比较表达式的 ast 安全求值；agent
    复用 agents._try_gateway 回退链真实补全。非白名单命令 / SSRF 拦截 /
    非 2xx / 策略拦截 / 不支持的语法 / 网关不可用一律步骤 failed 并在
    detail 写明原因，绝不静默放行或回退假文本；真实执行起止各落一条
    审计事件；
- 定时调度：router lifespan 内启 asyncio 后台任务，周期扫描 enabled 且
  trigger='schedule' 的流程，按 cron 五段式（本地时区 aware datetime）
  判到期触发，运行语义复用 _simulate_run（模拟执行，run 记录如实标注
  simulated/triggered_by）。进程宕机期间错过的触发不补跑；
- 定时总览：标准库解析 cron 五段式粗算下次触发时间，算不准的标注
  approximate=true。

路由顺序：固定路径（/flows/ai-edit、/flows/schedule/overview）定义在
参数路径（/flows/{fid} 一族）之前，避免被参数路径吞掉。
"""
from __future__ import annotations

import ast
import asyncio
from bisect import bisect_left
import json
import operator
import os
import re
import shlex
import subprocess
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any, Literal, Optional
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ..memory_runtime.policy_gate import evaluate_policy
from . import _system_svc_runtime as _sysrt
from .deps import WORK_GEARS
from .guards import audit_safe, require_gear
from .store import JsonStore
from ..security.ssrf import SSRFError, resolve_external_url
from ..soul.ownership import actor_id_for_request, configured_actor_id

router = APIRouter(prefix='/automation', tags=['platform-automation'])

_flows = JsonStore('flows')
_runs = JsonStore('flow_runs')


# ---------------------------------------------------------------------------
# owner 隔离（C3）：flow/run 记录绑定 owner_id，跨属主一律 404；
# 对外视图经 _flow_view/_run_view 剔除 owner_id，绝不外泄属主信息。
# ---------------------------------------------------------------------------

def _actor_id(request: Request | None = None) -> str:
    return actor_id_for_request(request)


def _legacy_owner_allowed(owner_id: str) -> bool:
    return owner_id == 'anonymous' or owner_id == configured_actor_id()


def _record_visible(record: dict[str, Any], owner_id: str) -> bool:
    owner = record.get('owner_id')
    if owner:
        return str(owner) == owner_id
    return _legacy_owner_allowed(owner_id)


def _materialize_owner(store: JsonStore, key: str, record: dict[str, Any], owner_id: str) -> str | None:
    """把无主旧记录绑定到其兼容属主（legacy 只允许 configured actor 认领）。"""
    if record.get('owner_id'):
        return str(record['owner_id'])
    if not _legacy_owner_allowed(owner_id):
        return None
    record['owner_id'] = owner_id
    store.set(key, record)
    return owner_id


def _flow_owner(flow: dict, preferred_owner: str | None = None) -> str | None:
    owner = flow.get('owner_id')
    if owner:
        return str(owner)
    candidate = preferred_owner or configured_actor_id() or 'anonymous'
    return candidate if _legacy_owner_allowed(candidate) else None


def _get_flow_or_404(fid: str, owner_id: str, *, materialize: bool = True) -> dict:
    flow = _flows.get(fid)
    if not isinstance(flow, dict) or not _record_visible(flow, owner_id):
        raise HTTPException(status_code=404, detail=f'流程不存在：{fid}')
    if materialize and not flow.get('owner_id'):
        _materialize_owner(_flows, fid, flow, owner_id)
    return flow


def _owned_flow_snapshot(owner_id: str) -> list[dict]:
    """按属主过滤可见流程，并顺带把兼容的旧记录打上 owner 标。"""
    def _snapshot(data: dict) -> list[dict]:
        visible: list[dict] = []
        for fid, value in data.items():
            if not isinstance(value, dict) or not _record_visible(value, owner_id):
                continue
            if not value.get('owner_id'):
                value['owner_id'] = owner_id
                data[fid] = value
            visible.append(dict(value))
        return visible

    return _flows.mutate(_snapshot)


def _run_owner(run: dict, preferred_owner: str | None = None) -> str | None:
    owner = run.get('owner_id')
    if owner:
        return str(owner)
    # 旧 run 无 owner 标：优先继承所属 flow 的 owner（flow 同样只认领 legacy 兼容属主）
    flow_id = run.get('flow_id')
    if flow_id:
        flow = _flows.get(str(flow_id))
        if isinstance(flow, dict):
            flow_owner = _flow_owner(flow, preferred_owner)
            if flow_owner:
                return flow_owner
    candidate = preferred_owner or configured_actor_id() or 'anonymous'
    return candidate if _legacy_owner_allowed(candidate) else None


def _run_visible(run: dict, owner_id: str) -> bool:
    owner = _run_owner(run, owner_id)
    return bool(owner) and owner == owner_id


def _materialize_run_owner(run: dict, preferred_owner: str | None = None) -> str | None:
    if run.get('owner_id'):
        return str(run['owner_id'])
    owner = _run_owner(run, preferred_owner)
    if not owner or (not _legacy_owner_allowed(owner) and not run.get('flow_id')):
        return None
    rid = str(run.get('id') or '')
    if not rid:
        return None
    def _claim(data: dict) -> dict:
        current = data.get(rid)
        if isinstance(current, dict):
            current = dict(current)
            current['owner_id'] = owner
            data[rid] = current
            return current
        data[rid] = run
        return run
    _runs.mutate(_claim)
    run['owner_id'] = owner
    return owner


def _public_record(record: dict) -> dict:
    public = dict(record)
    public.pop('owner_id', None)
    return public


TRIGGERS = ('manual', 'schedule', 'event')
TRIGGER_LABELS = {'manual': '手动触发', 'schedule': '定时触发', 'event': '事件触发'}

# 工作流执行档位（与 deps.WORK_GEARS 三档一致）。human_review 为默认档，
# 仅表示人工审查语义，绝不可被当作真实执行授权（README 口径）；只有
# 显式选择 sandbox/device 的流程才进入真实执行模式。
Gear = Literal['human_review', 'sandbox', 'device']
GEARS = ('human_review', 'sandbox', 'device')

# 真实执行边界：HTTP 超时 10s、响应体截断 4KB。shell 的超时/截断/白名单/
# cwd 监禁目录/最小环境变量全部复用 _system_svc_runtime 沙盒常量（单一来源，
# 防两处漂移）。
_REAL_HTTP_TIMEOUT_S = 10
_REAL_BODY_TRUNCATE_BYTES = 4096
STEP_TYPES = ('agent', 'shell', 'http', 'memory', 'condition')
STEP_TYPE_LABELS = {
    'agent': '智能体',
    'shell': '命令',
    'http': 'HTTP 请求',
    'memory': '记忆',
    'condition': '条件判断',
}

MAX_FLOW_COUNT = 200
MAX_STEPS_PER_FLOW = 64
MAX_FLOW_NAME_LENGTH = 120
MAX_FLOW_DESCRIPTION_LENGTH = 2000
MAX_STEP_ID_LENGTH = 64
MAX_STEP_NAME_LENGTH = 120
MAX_STEP_TEXT_LENGTH = 2000
MAX_CRON_EXPRESSION_LENGTH = 128
_MAX_CRON_FIELD_SEGMENTS = 32
_MAX_CRON_SEARCH_DAYS = 400


class _StepConfigBase(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    simulate_failure: bool = False


class _AgentStepConfig(_StepConfigBase):
    task: str = Field(default='', max_length=MAX_STEP_TEXT_LENGTH)


class _ShellStepConfig(_StepConfigBase):
    command: str = Field(default='', max_length=MAX_STEP_TEXT_LENGTH)


class _HttpStepConfig(_StepConfigBase):
    method: str = 'GET'
    url: str = Field(default='', max_length=2048)
    desc: str = Field(default='', max_length=MAX_STEP_TEXT_LENGTH)

    @field_validator('method')
    @classmethod
    def _method_valid(cls, value: str) -> str:
        method = value.upper()
        if method not in {'GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'}:
            raise ValueError('method 须为受支持的 HTTP 方法')
        return method


class _MemoryStepConfig(_StepConfigBase):
    op: str = 'read'
    key: str = Field(default='', max_length=256)
    desc: str = Field(default='', max_length=MAX_STEP_TEXT_LENGTH)

    @field_validator('op')
    @classmethod
    def _operation_valid(cls, value: str) -> str:
        operation = value.lower()
        if operation not in {'read', 'write'}:
            raise ValueError("op 须为 'read' 或 'write'")
        return operation


class _ConditionStepConfig(_StepConfigBase):
    expr: str = Field(default='', max_length=MAX_STEP_TEXT_LENGTH)
    desc: str = Field(default='', max_length=MAX_STEP_TEXT_LENGTH)


_STEP_CONFIG_MODELS: dict[str, type[_StepConfigBase]] = {
    'agent': _AgentStepConfig,
    'shell': _ShellStepConfig,
    'http': _HttpStepConfig,
    'memory': _MemoryStepConfig,
    'condition': _ConditionStepConfig,
}


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec='seconds')


def _new_id(prefix: str) -> str:
    return f'{prefix}_{uuid.uuid4().hex[:12]}'


def _store_delete(store: JsonStore, key: str) -> bool:
    """JsonStore 公开 API 没有 delete，此处加锁整文件重写以实现删除。"""
    with store._lock:  # noqa: SLF001 —— 共享工具缺 delete 的务实兜底
        data = store._read()  # noqa: SLF001
        if key not in data:
            return False
        data.pop(key)
        store._write(data)  # noqa: SLF001
        return True


def _bounded_text(value: Any, *, field: str, max_length: int, default: str = '') -> str:
    text = str(value if value is not None else default)
    if len(text) > max_length:
        raise ValueError(f'{field} 最长 {max_length} 个字符')
    return text


def _normalize_step(raw_step: dict, index: int) -> dict:
    if not isinstance(raw_step, dict):
        raise ValueError(f'steps[{index}] 须为对象')
    step_type = raw_step.get('type', 'agent')
    if step_type not in STEP_TYPES:
        raise ValueError(f'steps[{index}].type 须为 {list(STEP_TYPES)} 之一')
    raw_config = raw_step.get('config', {})
    if not isinstance(raw_config, dict):
        raise ValueError(f'steps[{index}].config 须为对象')
    try:
        config = _STEP_CONFIG_MODELS[step_type].model_validate(raw_config)
    except ValidationError as exc:
        raise ValueError(f'steps[{index}].config 与 {step_type} schema 不匹配：{exc}') from exc
    return {
        'id': _bounded_text(
            raw_step.get('id') or f'st{index + 1}',
            field=f'steps[{index}].id',
            max_length=MAX_STEP_ID_LENGTH,
        ),
        'type': step_type,
        'name': _bounded_text(
            raw_step.get('name') or f'步骤{index + 1}',
            field=f'steps[{index}].name',
            max_length=MAX_STEP_NAME_LENGTH,
        ),
        'config': config.model_dump(exclude_unset=True),
        'on_error': 'continue' if raw_step.get('on_error') == 'continue' else 'stop',
    }


def _normalize_steps(raw_steps: list) -> list[dict]:
    if len(raw_steps) > MAX_STEPS_PER_FLOW:
        raise ValueError(f'每个流程最多 {MAX_STEPS_PER_FLOW} 个步骤')
    return [_normalize_step(step, index) for index, step in enumerate(raw_steps)]


def _enforce_real_execution_gear(step_type: str, gear: str | None) -> None:
    """真实步骤执行前必须通过的单一权限边界（_exec_step_real 逐步调用）。

    只有显式传入 sandbox/device 才可能放行；human_review 仅表示等待人工，
    不得被当作执行授权。device 档继续复用全局默认拒绝闸门（require_gear：
    WANWEI_DEVICE_GEAR_ENABLED），避免接入真实 shell/HTTP 后绕过。
    """
    if step_type not in STEP_TYPES:
        raise ValueError(f'未知步骤类型：{step_type}')
    if gear not in {'sandbox', 'device'}:
        audit_safe('gear_denied', {
            'action': 'automation_step_execute',
            'step_type': step_type,
            'gear': gear,
            'reason': 'explicit_execution_gear_required',
        })
        raise PermissionError('真实自动化步骤必须显式选择 sandbox 或 device 档')
    denied = require_gear(
        gear,
        action='automation_step_execute',
        context={'step_type': step_type},
    )
    if denied:
        raise PermissionError(f'{WORK_GEARS[gear]}档未获授权')


def _store_new_flow(flow_id: str, flow: dict) -> None:
    """在同一锁内完成数量门禁与创建，避免并发请求同时越过上限。"""
    with _flows._lock:  # noqa: SLF001 - JsonStore 尚无 create-if-capacity API
        data = _flows._read()  # noqa: SLF001
        flow_count = sum(isinstance(item, dict) for item in data.values())
        if flow_count >= MAX_FLOW_COUNT:
            raise HTTPException(409, f'流程数量已达上限（{MAX_FLOW_COUNT}）')
        data[flow_id] = flow
        _flows._write(data)  # noqa: SLF001


def _normalize_flow(
    pf: dict,
    fid: str,
    existing: Optional[dict],
    *,
    preserve_existing_steps: bool = False,
) -> dict:
    """把任意来源（POST/PUT/ai-apply）的流程载荷归一成契约定义的完整结构。

    ``preserve_existing_steps`` 只用于未显式修改 steps 的 PUT。历史版本允许
    宽松的 config 别名；对这些流程修改名称或启用状态时必须逐字保留步骤，
    但任何新建、AI apply 或显式 steps 更新仍须通过当前严格 schema。
    """
    pf = pf if isinstance(pf, dict) else {}
    existing = existing or {}
    now = _now_iso()
    trigger = pf.get('trigger') if pf.get('trigger') in TRIGGERS else existing.get('trigger', 'manual')
    cron = pf.get('cron')
    cron = cron.strip() if isinstance(cron, str) and cron.strip() else None
    # gear 归一：显式非法值拒绝；缺失/旧记录回退 human_review（默认档，
    # 仅人工审查语义，绝不当作执行授权）。
    raw_gear = pf.get('gear')
    if raw_gear is not None and raw_gear not in GEARS:
        raise ValueError(f'gear 须为 {list(GEARS)} 之一')
    legacy_gear = existing.get('gear')
    gear = raw_gear or (legacy_gear if legacy_gear in GEARS else 'human_review')
    # 非定时流同样允许保留 cron 草稿，前端自行忽略。
    # steps 语义：list（含 []）→ 按载荷归一（[] 即显式清空）；
    # None / 缺失 → 保持 existing 原值（新建时为空列表）；其他类型拒绝。
    if preserve_existing_steps:
        existing_steps = existing.get('steps')
        steps = existing_steps if isinstance(existing_steps, list) else []
    else:
        raw_steps = pf.get('steps')
        if raw_steps is not None and not isinstance(raw_steps, list):
            raise ValueError('steps 须为数组或 null')
        if raw_steps is None:
            raw_steps = existing.get('steps') if isinstance(existing.get('steps'), list) else []
        steps = _normalize_steps(raw_steps)
    return {
        'id': fid,
        'name': _bounded_text(
            pf.get('name') or existing.get('name') or '未命名流程',
            field='name',
            max_length=MAX_FLOW_NAME_LENGTH,
        ),
        'desc': _bounded_text(
            pf.get('desc') if pf.get('desc') is not None else existing.get('desc', ''),
            field='desc',
            max_length=MAX_FLOW_DESCRIPTION_LENGTH,
        ),
        'trigger': trigger,
        'gear': gear,
        'cron': cron,
        'steps': steps,
        'enabled': bool(pf.get('enabled', existing.get('enabled', True))),
        'created_at': existing.get('created_at') or pf.get('created_at') or now,
        'updated_at': now,
        'ai_editable': True,
    }


# ---------------------------------------------------------------------------
# cron 五段式：标准库粗算下次触发
# ---------------------------------------------------------------------------

def _parse_cron_field(field: str, lo: int, hi: int) -> set[int]:
    field = field.strip()
    if field in ('*', '?', ''):
        return set(range(lo, hi + 1))
    values: set[int] = set()
    segments = field.split(',')
    if len(segments) > _MAX_CRON_FIELD_SEGMENTS:
        raise ValueError(f'cron 单字段最多 {_MAX_CRON_FIELD_SEGMENTS} 个片段')
    for part in segments:
        part = part.strip()
        if not part:
            raise ValueError('cron 字段含空片段')
        step = 1
        base = part
        if '/' in part:
            base, step_s = part.split('/', 1)
            step = int(step_s)
            if step < 1:
                raise ValueError('cron 步长必须为正')
        if base in ('*', '?', ''):
            start, end = lo, hi
        elif '-' in base:
            a, b = base.split('-', 1)
            start, end = int(a), int(b)
        else:
            start = int(base)
            end = hi if '/' in part else start
        if start < lo or end > hi or start > end:
            raise ValueError(f'cron 字段越界：{part}')
        values.update(range(start, end + 1, step))
    if not values:
        raise ValueError('cron 字段为空')
    return values


def _validate_cron_expr(cron: str) -> None:
    """校验 5 段 cron（分 时 日 月 周）的格式与取值范围，非法抛 ValueError。"""
    if len(cron) > MAX_CRON_EXPRESSION_LENGTH:
        raise ValueError(f'cron 最长 {MAX_CRON_EXPRESSION_LENGTH} 个字符')
    parts = cron.split()
    if len(parts) != 5:
        raise ValueError('cron 须为 5 段：分 时 日 月 周（如 "0 7 * * *"）')
    for part, (lo, hi) in zip(parts, ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))):
        try:
            _parse_cron_field(part, lo, hi)
        except (ValueError, AttributeError) as exc:
            raise ValueError(f'cron 字段非法：{part!r}（{exc}）') from exc


@lru_cache(maxsize=256)
def _parsed_cron(
    cron: str,
) -> tuple[tuple[int, ...], frozenset[int], frozenset[int], bool, bool, frozenset[int]]:
    """解析并缓存 cron 的有界执行计划。

    minute-of-day 至多 1440 项，日期扫描由 _MAX_CRON_SEARCH_DAYS 封顶；
    缓存避免列表/总览接口反复为同一表达式展开字段集合。
    """
    _validate_cron_expr(cron)
    parts = cron.split()
    minutes = _parse_cron_field(parts[0], 0, 59)
    hours = _parse_cron_field(parts[1], 0, 23)
    minute_offsets = tuple(hour * 60 + minute for hour in sorted(hours) for minute in sorted(minutes))
    doms = frozenset(_parse_cron_field(parts[2], 1, 31))
    months = frozenset(_parse_cron_field(parts[3], 1, 12))
    dows_raw = _parse_cron_field(parts[4], 0, 7)
    dows = frozenset(0 if day == 7 else day for day in dows_raw)
    return minute_offsets, doms, months, parts[2] in ('*', '?'), parts[4] in ('*', '?'), dows


def _next_cron_dt(cron: Optional[str], now: Optional[datetime] = None) -> tuple[Optional[datetime], bool]:
    """返回 (下次触发的本地 aware datetime, approximate)。

    显式本地时区（datetime.now().astimezone() 的固定偏移），与全模块
    _now_iso 的本地 aware 口径一致；naive 入参按本地时间解释并显式化。
    解析失败 / 400 天内无触发 → (None, True)。固定偏移不处理 DST 跳变，
    与 approximate 语义一致（部署目标时区无夏令时）。
    """
    try:
        minute_offsets, doms, months, dom_any, dow_any, dows = _parsed_cron(cron or '')
    except (ValueError, AttributeError):
        return None, True
    # dom 与 dow 同时受限时 cron 语义为「或」，粗算结果标注 approximate
    approximate = not dom_any and not dow_any
    now = now or datetime.now().astimezone()
    if now.tzinfo is None:
        now = now.astimezone()  # naive 按本地时间解释，输出始终 aware
    start = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    start_minute = start.hour * 60 + start.minute
    for offset in range(_MAX_CRON_SEARCH_DAYS):
        day = (start + timedelta(days=offset)).date()
        if day.month not in months:
            continue
        cron_dow = (day.weekday() + 1) % 7  # Python 周一=0 → cron 周日=0
        if dom_any and dow_any:
            day_ok = True
        elif dom_any:
            day_ok = cron_dow in dows
        elif dow_any:
            day_ok = day.day in doms
        else:
            day_ok = day.day in doms or cron_dow in dows
        if not day_ok:
            continue
        first_candidate = bisect_left(minute_offsets, start_minute) if offset == 0 else 0
        if first_candidate >= len(minute_offsets):
            continue
        minute_of_day = minute_offsets[first_candidate]
        hour, minute = divmod(minute_of_day, 60)
        return datetime(day.year, day.month, day.day, hour, minute, tzinfo=start.tzinfo), approximate
    return None, True


def _next_cron_run(cron: Optional[str], now: Optional[datetime] = None) -> tuple[Optional[str], bool]:
    """返回 (下次触发本地时间 ISO8601 带时区偏移, approximate)。"""
    nxt, approximate = _next_cron_dt(cron, now)
    return (nxt.isoformat(timespec='seconds') if nxt is not None else None), approximate


# ---------------------------------------------------------------------------
# AI 编辑：规则式中文指令解析器（engine='rule'，非模型生成，P0-4）
# ---------------------------------------------------------------------------

_WEEKDAY_MAP = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '日': 0, '天': 0}

# 裸「并」可作连词分句，但须排除复合词：「合并/归并」等 X+并 用后顾排除，
# 「并发/并行/并入」等 并+X 用前瞻排除；「并发送」仍按连词切分（发(?!送)
# 区分「并发」与「并+发送」）。
_CLAUSE_SPLIT_RE = re.compile(
    r'[，。；;！!？?\n]'
    r'|(?:然后|接着|接下来|随后|之后|最后'
    r'|(?<!合)(?<!归)(?<!裁)(?<!吞)并且'
    r'|(?<!合)(?<!归)(?<!裁)(?<!吞)并(?!行|入|购|排|联|存|举|重|网|肩|茂|轨|发(?!送))'
    r'|(?<!不|一|再)再(?!次|也|见|来|者|三))'
)
# 句首连接词剥离：裸「并」同样须避开「并发/并行」等复合词（与分句正则同策）。
_CONNECTOR_RE = re.compile(
    r'^(?:首先|先|再|且|第[一二三四五六七八九十\d]+步'
    r'|并(?!发(?!送)|行|入|购|排|联|存|举|重|网|肩|茂|轨))[，,：:、\s]*'
)
_SCHED_PREFIX_RE = re.compile(
    r'^\s*每(?:天|日|\d+\s*个?\s*小时|\d+\s*分钟|小时|分钟'
    r'|(?:周|星期)\s*[一二三四五六日天\d]|月\s*\d{1,2}\s*[号日])\s*'
)
_TIME_PREFIX_RE = re.compile(
    r'^\s*(?:凌晨|早上|上午|中午|下午|晚上|傍晚)?\s*\d{1,2}\s*[点:：]\s*\d{0,2}\s*分?\s*(?:左右|整)?\s*'
)
_META_RE = re.compile(r'(?:创建|新建|建立|帮我|我想|我要|需要|设计|生成)\s*.{0,12}?(?:工作流|流程|自动化|任务流)')
_ON_ERROR_RE = re.compile(r'(?:如果|若|当)?[^，。；;、]{0,8}?(?:失败|出错|异常)(?:则|时)?(?:继续|跳过)')
_URL_RE = re.compile(r'https?://[^\s，。；;、]+')

_STEP_KEYWORDS = [
    ('condition', re.compile(r'如果|倘若|若|当.{1,20}时|是否|判断')),
    ('memory', re.compile(r'记忆|记住|存档|存入知识|检索|读取记忆|写入记忆')),
    ('http', re.compile(r'抓取|爬取|请求|调用接口|接口|API|api|http|HTTP|webhook|Webhook|推送|拉取|访问网页|获取网页|下载')),
    ('shell', re.compile(r'执行命令|运行命令|shell|Shell|脚本|备份|清理|打包|压缩|重启|命令行')),
]


def _extract_time(text: str) -> tuple[int, int, bool]:
    """从文本提取小时/分钟，缺省 09:00。返回 (hour, minute, 是否显式给出)。"""
    m = re.search(r'(\d{1,2})\s*[点:：]\s*(\d{1,2})?\s*分?', text)
    if not m:
        return 9, 0, False
    hour = min(int(m.group(1)), 23)
    minute = min(int(m.group(2)), 59) if m.group(2) else 0
    if re.search(r'下午|晚上|傍晚|夜里', text) and hour < 12:
        hour += 12
    elif '中午' in text and hour not in (12,) and hour + 12 <= 23:
        hour += 12
    return hour, minute, True


def _parse_trigger(text: str) -> tuple[str, Optional[str], str]:
    """识别触发方式，返回 (trigger, cron, 中文说明)。"""
    hour, minute, has_time = _extract_time(text)
    m = re.search(r'每\s*(\d+)\s*分钟', text)
    if m:
        n = max(1, min(59, int(m.group(1))))
        return 'schedule', f'*/{n} * * * *', f'每 {n} 分钟'
    m = re.search(r'每\s*(\d+)\s*个?\s*小时', text)
    if m:
        n = max(1, min(23, int(m.group(1))))
        return 'schedule', f'0 */{n} * * *', f'每 {n} 小时'
    if '每小时' in text:
        return 'schedule', '0 * * * *', '每小时整点'
    if '每分钟' in text:
        return 'schedule', '* * * * *', '每分钟'
    m = re.search(r'每\s*(?:周|星期)\s*([一二三四五六日天\d])', text)
    if m:
        token = m.group(1)
        dow = _WEEKDAY_MAP.get(token)
        if dow is None:
            dow = int(token) if token.isdigit() else 1
        if dow == 7:
            dow = 0
        t = f' {hour:02d}:{minute:02d}' if has_time else '（未指明时间，默认 09:00）'
        return 'schedule', f'{minute} {hour} * * {dow}', f'每周{token}{t}'
    m = re.search(r'每月\s*(\d{1,2})\s*[号日]', text)
    if m:
        dom = max(1, min(31, int(m.group(1))))
        t = f' {hour:02d}:{minute:02d}' if has_time else '（未指明时间，默认 09:00）'
        return 'schedule', f'{minute} {hour} {dom} * *', f'每月 {dom} 号{t}'
    if '每天' in text or '每日' in text or '天天' in text:
        t = f'{hour:02d}:{minute:02d}' if has_time else '09:00（未指明时间，默认）'
        return 'schedule', f'{minute} {hour} * * *', f'每天 {t}'
    if re.search(r'(当.{1,30}时|事件|收到.{0,12}(?:后|时))(自动)?(触发|执行|运行|启动)', text):
        return 'event', None, '事件触发'
    return 'manual', None, '手动触发'


def _extract_name(text: str) -> Optional[str]:
    m = re.search(r'(?:改名为|命名为|名为|叫做|名称是?|名字叫?)\s*[「\'"]?([^，。；;「」\'"]{2,20})', text)
    if m:
        return m.group(1).strip()
    m = re.search(r'「([^」]{2,20})」', text)
    if m:
        return m.group(1).strip()
    return None


def _expand_condition(clause: str) -> list[str]:
    """「如果A就B」拆成条件步骤 + 动作步骤。"""
    m = re.match(r'^(?:如果|若|倘若)(.+?)(?:就|则)(.+)$', clause)
    if m and m.group(1).strip() and m.group(2).strip():
        return [f'如果{m.group(1).strip()}', m.group(2).strip()]
    return [clause]


def _infer_step(clause: str, index: int, on_error: str) -> dict:
    stype = 'agent'
    for t, pat in _STEP_KEYWORDS:
        if pat.search(clause):
            stype = t
            break
    config: dict[str, Any]
    if stype == 'shell':
        q = re.search(r'["\'“”‘’`「](.+?)["\'“”‘’`」]', clause)
        if q:
            cmd = q.group(1)
        else:
            mm = re.search(r'(?:执行|运行)\s*(.+)', clause)
            cmd = mm.group(1) if mm else clause
        config = {'command': cmd.strip()}
    elif stype == 'http':
        u = _URL_RE.search(clause)
        config = {'method': 'GET', 'url': u.group(0) if u else '', 'desc': clause}
    elif stype == 'memory':
        op = 'write' if re.search(r'写入|存入|记住|存档|保存', clause) else 'read'
        config = {'op': op, 'key': '', 'desc': clause}
    elif stype == 'condition':
        config = {'expr': clause, 'desc': clause}
    else:
        config = {'task': clause}
    name = _URL_RE.sub('', clause).strip('，。；;、 ')
    name = re.sub(r'\s+', ' ', name)[:14]
    return {
        'id': f'st{index}',
        'type': stype,
        'name': name or f'步骤{index}',
        'config': config,
        'on_error': on_error,
    }


def _parse_steps(text: str) -> tuple[list[dict], list[str]]:
    """把指令切成顺序步骤。返回 (steps, 解析备注)。"""
    steps: list[dict] = []
    notes: list[str] = []
    default_on_error = 'stop'
    idx = 1
    for raw in _CLAUSE_SPLIT_RE.split(text):
        c = raw.strip()
        if not c:
            continue
        # 依次剥离：连接词 → 调度前缀 → 时间前缀 → 连接词（处理「每天8点先…」）
        c = _CONNECTOR_RE.sub('', c)
        c = _SCHED_PREFIX_RE.sub('', c)
        c = _TIME_PREFIX_RE.sub('', c)
        c = _CONNECTOR_RE.sub('', c).strip('，。；;、 ')
        if not c:
            continue
        if _META_RE.fullmatch(c):
            continue
        on_error = default_on_error
        m = _ON_ERROR_RE.search(c)
        if m:
            remainder = (c[:m.start()] + c[m.end():]).strip('，。；;、 ')
            if remainder:
                c = remainder
                on_error = 'continue'
            else:
                # 整句都是「失败则继续」：作用于上一步，并成为后续默认值
                if steps:
                    steps[-1]['on_error'] = 'continue'
                default_on_error = 'continue'
                continue
        for part in _expand_condition(c):
            if len(steps) >= MAX_STEPS_PER_FLOW:
                notes.append(f'步骤已截断为上限 {MAX_STEPS_PER_FLOW} 条')
                return steps, notes
            steps.append(_infer_step(part, idx, on_error))
            idx += 1
    if not steps:
        steps.append({
            'id': 'st1',
            'type': 'agent',
            'name': '智能体处理',
            'config': {'task': text.strip()[:200]},
            'on_error': 'stop',
        })
        notes.append('未识别出明确步骤，已按整段指令生成一个智能体步骤')
    return steps, notes


def _step_label(st: dict) -> str:
    label = STEP_TYPE_LABELS.get(st.get('type'), str(st.get('type')))
    if st.get('on_error') == 'continue':
        label += '·失败继续'
    return label


def _ai_diff(base: Optional[dict], proposed: dict) -> list[str]:
    changes: list[str] = []
    if base is None:
        changes.append(f'新建工作流「{proposed["name"]}」')
    else:
        if base.get('name') != proposed.get('name'):
            changes.append(f'重命名：「{base.get("name")}」→「{proposed.get("name")}」')
        if (base.get('desc') or '') != (proposed.get('desc') or ''):
            changes.append('更新流程描述')
    if base is None or base.get('trigger') != proposed.get('trigger') \
            or (base.get('cron') or '') != (proposed.get('cron') or ''):
        trig = proposed.get('trigger')
        label = TRIGGER_LABELS.get(trig, str(trig))
        if trig == 'schedule' and proposed.get('cron'):
            label += f'（cron: {proposed["cron"]}）'
        changes.append(f'触发方式设为：{label}')
    old_steps = (base or {}).get('steps') or []
    new_steps = proposed.get('steps') or []
    for i, st in enumerate(new_steps):
        if i >= len(old_steps):
            changes.append(f'新增步骤「{st.get("name")}」（{_step_label(st)}）')
        else:
            old = old_steps[i]
            if old.get('type') != st.get('type') or old.get('name') != st.get('name') \
                    or (old.get('config') or {}) != (st.get('config') or {}) \
                    or old.get('on_error') != st.get('on_error'):
                changes.append(f'修改步骤「{st.get("name")}」（{_step_label(st)}）')
    for j in range(len(new_steps), len(old_steps)):
        changes.append(f'移除步骤「{old_steps[j].get("name")}」')
    if not changes:
        changes.append('指令未产生实质变更')
    return changes


def _understood(base: Optional[dict], trigger: str, cron: Optional[str], steps: list[dict]) -> str:
    seq = ' → '.join(s['name'] for s in steps)
    t = TRIGGER_LABELS.get(trigger, trigger)
    if trigger == 'schedule' and cron:
        t += f'（cron {cron}）'
    who = (
        f'按指令全量重建流程定义（将整体替换现有流程「{base["name"]}」的步骤与触发方式）'
        if base else '创建新流程'
    )
    return f'{who}：{t}，共 {len(steps)} 个步骤，顺序为 {seq}。'


# ---------------------------------------------------------------------------
# 运行模拟
# ---------------------------------------------------------------------------

def _simulate_step(step: dict, index: int) -> dict:
    stype = step.get('type') if step.get('type') in STEP_TYPES else 'agent'
    cfg = step.get('config') if isinstance(step.get('config'), dict) else {}
    st = {
        'step_id': str(step.get('id') or f'st{index + 1}'),
        'name': str(step.get('name') or f'步骤{index + 1}'),
        'type': stype,
        'status': 'done',
        'detail': '',
        'would_run': '',
        'started_at': _now_iso(),
        'finished_at': None,
    }
    if stype == 'shell':
        cmd = str(cfg.get('command') or cfg.get('cmd') or '')
        st['would_run'] = cmd
        st['detail'] = '模拟执行：shell 命令未真正运行'
    elif stype == 'http':
        method = str(cfg.get('method') or 'GET').upper()
        url = str(cfg.get('url') or '')
        st['would_run'] = f'{method} {url}'.strip()
        st['detail'] = '模拟执行：HTTP 请求未真正发起'
    elif stype == 'memory':
        op = str(cfg.get('op') or 'read')
        key = str(cfg.get('key') or '')
        st['would_run'] = f'memory.{op}({key})' if key else f'memory.{op}'
        st['detail'] = '模拟执行：记忆读写未真正访问记忆库'
    elif stype == 'condition':
        expr = str(cfg.get('expr') or cfg.get('description') or '')
        st['would_run'] = expr
        st['detail'] = '条件检查（模拟，按通过处理）'
    else:
        task = str(cfg.get('task') or cfg.get('prompt') or st['name'])
        st['would_run'] = task
        st['detail'] = '模拟执行：智能体任务未真正调用模型'
    if cfg.get('simulate_failure'):
        st['status'] = 'failed'
        st['detail'] += '；按 config.simulate_failure 模拟失败'
    return st


def _persist_run(run_id: str, run: dict) -> bool:
    """写回运行记录。记录已被清理（如流程删除级联清理 runs）时返回
    False，调用方据此静默终止，避免把孤儿记录重新写回。"""
    with _runs._lock:  # noqa: SLF001 —— 「存在才写」需与删除互斥
        data = _runs._read()  # noqa: SLF001
        if run_id not in data:
            return False
        data[run_id] = run
        _runs._write(data)  # noqa: SLF001
    return True


async def _simulate_run(run_id: str, flow: dict) -> None:
    """逐步模拟执行。全程兜底：任何异常都把运行终结为 failed + error
    字段，绝不留 running 假死；done 在终态一律置 True。"""
    run = _runs.get(run_id)
    if run is None:
        return
    steps = flow.get('steps') or []
    results: list[dict] = []
    status = 'done'
    try:
        for i, step in enumerate(steps):
            st = _simulate_step(step, i)
            await asyncio.sleep(0.05)  # 模拟耗时，让运行过程可观察
            st['finished_at'] = _now_iso()
            results.append(st)
            run['step_results'] = results
            if not _persist_run(run_id, run):
                return
            if st['status'] == 'failed' and (step.get('on_error') or 'stop') == 'stop':
                status = 'failed'
                for j, rest in enumerate(steps[i + 1:], i + 1):
                    results.append({
                        'step_id': str(rest.get('id') or f'st{j + 1}'),
                        'name': str(rest.get('name') or f'步骤{j + 1}'),
                        'type': rest.get('type') or 'agent',
                        'status': 'skipped',
                        'detail': '前序步骤失败，on_error=stop，本步骤跳过',
                        'would_run': '',
                        'started_at': None,
                        'finished_at': None,
                    })
                run['step_results'] = results
                if not _persist_run(run_id, run):
                    return
                break
    except Exception as exc:  # noqa: BLE001 —— 兜底：运行绝不留 running 假死
        status = 'failed'
        run['error'] = f'运行模拟内部异常：{exc!r}'
    run['status'] = status
    run['done'] = True
    run['finished_at'] = _now_iso()
    _persist_run(run_id, run)


def _try_create_run(flow: dict, *, triggered_by: str, mode: str = 'dry_run', owner_id: Optional[str] = None) -> Optional[dict]:
    """创建 running 记录；同流程已有 running 时返回 None（重入拒绝）。

    重入检查与创建写入在同一 store 锁内完成，避免并发双开。
    mode 记录本次运行是真实执行（real）还是 dry-run 模拟（dry_run）。
    owner_id 记录运行属主：优先继承 flow 的 owner 标，缺省回落 configured actor。
    """
    fid = str(flow.get('id') or '')
    rid = _new_id('run')
    run = {
        'id': rid,
        'flow_id': fid,
        'flow_name': flow.get('name') or '',
        'status': 'running',
        'done': False,
        'step_results': [],
        'started_at': _now_iso(),
        'finished_at': None,
        'simulated': False,
        'mode': mode,
        'triggered_by': triggered_by,
        'owner_id': str(flow.get('owner_id') or owner_id or configured_actor_id() or 'anonymous'),
    }
    if not flow.get('enabled', True):
        run['note'] = '流程处于停用状态，本次为手动强制执行'
    with _runs._lock:  # noqa: SLF001 —— 重入检查与创建需原子
        data = _runs._read()  # noqa: SLF001
        for existing in data.values():
            if isinstance(existing, dict) and existing.get('flow_id') == fid \
                    and existing.get('status') == 'running':
                return None
        data[rid] = run
        _runs._write(data)  # noqa: SLF001
    return run


def _launch_run(run_id: str, flow: dict, mode: str = 'dry_run') -> None:
    """独立线程里跑 asyncio 事件循环执行运行：不依赖请求处理所在 loop 的
    生命周期（TestClient/部分中间件下 create_task 的任务可能不再推进），
    对 uvicorn 等常驻 loop 同样安全；JsonStore 自带线程锁。
    mode='real' 走真实执行器，否则一律 dry-run 模拟。"""
    threading.Thread(
        target=lambda: asyncio.run(_dispatch_run(run_id, flow, mode)),
        name=f'flow-run-{run_id}',
        daemon=True,
    ).start()


async def _dispatch_run(run_id: str, flow: dict, mode: str) -> None:
    if mode == 'real':
        await _execute_run_real(run_id, flow)
    else:
        await _simulate_run(run_id, flow)


# ---------------------------------------------------------------------------
# 真实执行（gear=sandbox/device 且非模拟入口时启用）
# ---------------------------------------------------------------------------

def _flow_mode(flow: dict) -> str:
    """流程档位 → 运行模式：human_review（默认档，含旧记录缺省）一律
    dry-run 模拟；sandbox/device 显式档走真实执行（每步仍过
    _enforce_real_execution_gear 门禁，device 未显式授权时如实 failed）。"""
    return 'real' if flow.get('gear') in ('sandbox', 'device') else 'dry_run'


def _truncate_utf8(text: str, limit: int) -> tuple[str, bool]:
    raw = text.encode('utf-8')
    if len(raw) <= limit:
        return text, False
    return raw[:limit].decode('utf-8', errors='ignore'), True


def _check_sandbox_command(command: str) -> tuple[list[str], str]:
    """把 shell 步骤命令按 system_svc 沙盒同一套规则校验。

    白名单表/元字符正则/监禁目录判断全部复用 _system_svc_runtime 的常量与
    函数（单一来源）；校验失败返回 ([], 失败原因)，原因可直接放进 step
    detail —— 非白名单命令绝不静默放行。
    """
    if not command.strip():
        return [], 'shell 步骤未配置命令'
    if _sysrt._SHELL_META_RE.search(command):  # noqa: SLF001 —— 白名单单一来源
        return [], '命令包含 shell 元字符（;&|<>`$ 或换行），已拒绝'
    try:
        argv = shlex.split(command)
    except ValueError:
        return [], '命令解析失败：引号未闭合'
    if not argv:
        return [], 'shell 步骤未配置命令'
    name, args = argv[0], argv[1:]
    spec = _sysrt._SANDBOX_COMMANDS.get(name)  # noqa: SLF001 —— 白名单单一来源
    whitelist = '、'.join(sorted(_sysrt._SANDBOX_COMMANDS))  # noqa: SLF001
    if spec is None:
        return [], f'命令不在沙盒白名单内：{name}（白名单：{whitelist}）'
    if spec == 'none' and args:
        return [], f'沙盒内 {name} 不允许携带参数'
    if isinstance(spec, list) and args != spec:
        return [], f'沙盒内 {name} 仅允许参数：{" ".join(spec)}'
    if spec == 'any':
        for arg in args:
            if arg.startswith('-'):
                if arg.startswith('--'):
                    opt_value = arg.partition('=')[2] if '=' in arg else ''
                    if opt_value and not _sysrt._within_sandbox(opt_value):  # noqa: SLF001
                        return [], f'选项参数越出沙盒监禁目录：{arg}'
                elif not _sysrt._SHORT_FLAGS_RE.fullmatch(arg):  # noqa: SLF001
                    return [], f'不允许的选项参数（疑似内嵌路径或赋值）：{arg}'
                continue
            if not _sysrt._within_sandbox(arg):  # noqa: SLF001
                return [], f'路径越出沙盒监禁目录：{arg}'
    return argv, ''


def _fill_shell_result(st: dict, cfg: dict) -> None:
    """真实执行白名单 shell 命令：cwd 监禁 data/platform/sandbox/、最小环境
    变量、5s 超时、stdout/stderr 截断 4KB（全部同 system_svc 沙盒口径）。"""
    command = str(cfg.get('command') or cfg.get('cmd') or '').strip()
    st['would_run'] = command
    argv, err = _check_sandbox_command(command)
    if err:
        st['status'] = 'failed'
        st['detail'] = f'已拒绝执行：{err}'
        return
    sandbox = _sysrt._sandbox_dir()  # noqa: SLF001 —— 与 JsonStore 同一数据目录语义
    sandbox.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            argv,
            cwd=sandbox,
            capture_output=True,
            text=True,
            errors='replace',
            timeout=_sysrt._SANDBOX_TIMEOUT_S,  # noqa: SLF001
            shell=False,
            env=_sysrt._SANDBOX_ENV,  # noqa: SLF001 —— 最小环境，不继承 WANWEI_*
        )
    except FileNotFoundError:
        st['status'] = 'failed'
        st['detail'] = f'真实执行失败：命令在当前平台不可执行（未找到可执行文件 {argv[0]}）'
        return
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b'').decode('utf-8', 'replace')
        err_text = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b'').decode('utf-8', 'replace')
        stdout, out_trunc = _sysrt._truncate(out)  # noqa: SLF001
        stderr, err_trunc = _sysrt._truncate(err_text)  # noqa: SLF001
        st.update({'exit_code': None, 'stdout': stdout, 'stderr': stderr, 'truncated': out_trunc or err_trunc})
        st['status'] = 'failed'
        st['detail'] = f'真实执行失败：超过 {_sysrt._SANDBOX_TIMEOUT_S}s 超时已终止'  # noqa: SLF001
        return
    stdout, out_trunc = _sysrt._truncate(proc.stdout or '')  # noqa: SLF001
    stderr, err_trunc = _sysrt._truncate(proc.stderr or '')  # noqa: SLF001
    st.update({
        'exit_code': proc.returncode,
        'stdout': stdout,
        'stderr': stderr,
        'truncated': out_trunc or err_trunc,
    })
    if proc.returncode == 0:
        st['detail'] = (
            f'真实执行完成：退出码 0（cwd 监禁 {_sysrt._rel_to_root(sandbox)}，'  # noqa: SLF001
            f'超时 {_sysrt._SANDBOX_TIMEOUT_S}s）'  # noqa: SLF001
        )
    else:
        st['status'] = 'failed'
        head = stderr.strip().splitlines()[0][:200] if stderr.strip() else ''
        st['detail'] = f'真实执行失败：退出码 {proc.returncode}' + (f'；stderr 首行：{head}' if head else '')


def _pinned_http_request(method: str, url: str) -> httpx.Response:
    """经 SSRF 校验后 pinned-IP 发起真实请求。

    与 providers._probe_pinned_url 同模式：连接解析出的 IP、保留原始
    HTTP/TLS 主机头（sni_hostname），trust_env=False 防代理替换目标，
    不跟随重定向（3xx 按「未跟随的重定向」处理，避免重定向绕过 SSRF 校验）。
    合并全局显式信任主机白名单（WANWEI_SSRF_EXTRA_ALLOWED_HOSTS），与其它
    外呼路径同口径：fake-ip 代理环境下用户显式配置的公网 URL 才跑得动。
    """
    from ..security.ssrf import extra_allowed_hosts

    normalized, pinned_ip = resolve_external_url(
        url, allowlist=extra_allowed_hosts() or None,
    )
    parsed = urlsplit(normalized)
    hostname = parsed.hostname or ''
    hostname_ascii = hostname.encode('idna').decode('ascii')
    pinned_host = f'[{pinned_ip}]' if ':' in pinned_ip else pinned_ip
    original_host = f'[{hostname_ascii}]' if ':' in hostname_ascii else hostname_ascii
    if parsed.port is not None:
        pinned_host = f'{pinned_host}:{parsed.port}'
        original_host = f'{original_host}:{parsed.port}'
    pinned_url = urlunsplit((parsed.scheme, pinned_host, parsed.path, parsed.query, ''))
    extensions = {'sni_hostname': hostname_ascii} if parsed.scheme == 'https' else None
    with httpx.Client(timeout=_REAL_HTTP_TIMEOUT_S, follow_redirects=False, trust_env=False) as client:
        return client.request(method, pinned_url, headers={'Host': original_host}, extensions=extensions)


def _fill_http_result(st: dict, cfg: dict) -> None:
    """真实发起 HTTP 请求：仅 GET/POST；SSRF 拦截与非 2xx 都算步骤失败，
    detail 写明状态码/原因；响应体截断 4KB。"""
    method = str(cfg.get('method') or 'GET').upper()
    url = str(cfg.get('url') or '').strip()
    st['would_run'] = f'{method} {url}'.strip()
    if method not in ('GET', 'POST'):
        st['status'] = 'failed'
        st['detail'] = f'真实执行仅支持 GET/POST，当前 method={method}，已拒绝'
        return
    if not url:
        st['status'] = 'failed'
        st['detail'] = 'http 步骤未配置 URL'
        return
    try:
        resp = _pinned_http_request(method, url)
    except SSRFError as exc:
        st['status'] = 'failed'
        st['detail'] = f'SSRF 校验拦截，未发起请求：{exc}'
        return
    except httpx.HTTPError as exc:
        st['status'] = 'failed'
        st['detail'] = f'真实请求失败：{type(exc).__name__}: {exc}'
        return
    body, truncated = _truncate_utf8(resp.text, _REAL_BODY_TRUNCATE_BYTES)
    st['status_code'] = resp.status_code
    st['response_body'] = body
    st['truncated'] = truncated
    if 200 <= resp.status_code < 300:
        st['detail'] = (
            f'真实 HTTP {method} 完成：状态码 {resp.status_code}，'
            f'响应体截断至 {_REAL_BODY_TRUNCATE_BYTES} 字节'
            + ('（已发生截断）' if truncated else '')
        )
    else:
        st['status'] = 'failed'
        st['detail'] = (
            f'真实请求失败：非 2xx 状态码 {resp.status_code}'
            + ('（重定向不自动跟随）' if 300 <= resp.status_code < 400 else '')
        )


def _memory_content_text(cap: dict) -> str:
    content = cap.get('content')
    if isinstance(content, dict):
        text = content.get('text')
        if isinstance(text, str) and text:
            return text
        return json.dumps(content, ensure_ascii=False)
    return str(content or '')


def _fill_memory_result(st: dict, cfg: dict, owner_id: str) -> None:
    """通过 memory_runtime 真实读写记忆胶囊。

    写入前先过 policy_gate.evaluate_policy：reject/quarantine → 步骤失败
    并落 policy_blocked 审计，内容不落库；读取按 config.key 提供的胶囊 id
    精确读取，不存在则如实 failed。
    """
    op = str(cfg.get('op') or 'read').lower()
    key = str(cfg.get('key') or '').strip()
    desc = str(cfg.get('desc') or '').strip()
    st['would_run'] = f'memory.{op}({key})' if key else f'memory.{op}'
    from ..memory_runtime import capsule_store  # 延迟导入：故障隔离，同 agents 对 mgw 的处理
    capsule_store.init_runtime_schema()
    if op == 'write':
        text = desc or str(st.get('name') or '').strip()
        if not text:
            st['status'] = 'failed'
            st['detail'] = 'memory.write 缺少写入内容（config.desc 为空）'
            return
        guard = evaluate_policy(
            text=text,
            source_type='tool_result',
            write_intent='autonomous',
            affects_future_behavior=False,
        )
        policy = guard.get('policy_result')
        if policy in ('reject', 'quarantine'):
            audit_safe('policy_blocked', {
                'endpoint': 'automation_memory_write',
                'policy_result': policy,
                'risk_tags': guard.get('risk_tags', []),
                'sensitivity_level': guard.get('sensitivity_level'),
            })
            st['status'] = 'failed'
            st['detail'] = (
                f'写入被 Policy Gate 拦截（policy_result={policy}，'
                f"risk_tags={guard.get('risk_tags')}），内容未落库"
            )
            return
        res = capsule_store.write_capsule(
            memory_class='knowledge',
            content={'text': text, **({'key': key} if key else {})},
            source_type='tool_result',
            write_intent='autonomous',
            source_trust='normal',
            provenance={
                'origin': 'tool',
                'writer_identity': 'automation_flow',
                'source_type': 'workflow_step',
                'source_ids': [key] if key else [],
                'evidence_ids': [],
                'verified': False,
                'verification_method': 'unknown',
            },
            owner_id=owner_id,
        )
        governance = res.get('governance') or {}
        state = res.get('state') or {}
        if governance.get('policy_result') in ('reject', 'quarantine'):
            # 双保险：预检放行但落库治理仍拦截时如实失败，不报假成功
            st['status'] = 'failed'
            st['detail'] = (
                f"写入未生效：治理结果 {governance.get('policy_result')}"
                f"（lifecycle={state.get('lifecycle')}），内容未入库"
            )
            return
        capsule_id = str(res.get('capsule_id') or '')
        st['output'] = capsule_id
        st['capsule_id'] = capsule_id
        st['detail'] = (
            f'真实写入记忆胶囊 {capsule_id}'
            f"（lifecycle={state.get('lifecycle')}，policy={governance.get('policy_result')}）"
        )
    else:  # read
        if not key:
            st['status'] = 'failed'
            st['detail'] = 'memory.read 需要在 config.key 提供胶囊 id（cap_…）；留空不支持'
            return
        cap = capsule_store.get_capsule(key, owner_id=owner_id)
        if cap is None:
            st['status'] = 'failed'
            st['detail'] = f'记忆不存在或当前作用域不可读：{key}'
            return
        text_out, truncated = _truncate_utf8(_memory_content_text(cap), _REAL_BODY_TRUNCATE_BYTES)
        lifecycle = (cap.get('state') or {}).get('lifecycle')
        st['output'] = text_out
        st['truncated'] = truncated
        st['detail'] = f'真实读取记忆胶囊 {key}（lifecycle={lifecycle}）'


# 条件步骤允许的比较算子（与 ast.Compare 节点一一对应）；链式比较按成对短路求值
_CONDITION_COMPARE_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}


def _eval_condition_node(node: ast.AST):
    """只允许「字面量 + 比较 + and/or」的安全求值；其余语法一律拒绝。"""
    if isinstance(node, ast.Constant) and (
        node.value is None or isinstance(node.value, (bool, int, float, str))
    ):
        return node.value
    if isinstance(node, ast.BoolOp):
        values = [_eval_condition_node(v) for v in node.values]
        return all(values) if isinstance(node.op, ast.And) else any(values)
    if isinstance(node, ast.Compare):
        left = _eval_condition_node(node.left)
        result = True
        for op, comparator in zip(node.ops, node.comparators):
            fn = _CONDITION_COMPARE_OPS.get(type(op))
            if fn is None:
                raise ValueError(f'不支持的比较运算符：{type(op).__name__}')
            right = _eval_condition_node(comparator)
            if not fn(left, right):
                result = False
                break
            left = right
        return result
    raise ValueError(f'不支持的表达式元素：{type(node).__name__}')


def _eval_condition(expr: str):
    try:
        tree = ast.parse(expr, mode='eval')
    except (SyntaxError, ValueError) as exc:
        raise ValueError(f'表达式语法错误：{getattr(exc, "msg", exc)}') from exc
    return _eval_condition_node(tree.body)


def _fill_condition_result(st: dict, cfg: dict) -> None:
    """条件步骤：仅支持 ast.literal_eval 同源安全子集（字面量比较表达式），
    不支持的语法如实 failed，绝不按「通过」处理。"""
    expr = str(cfg.get('expr') or cfg.get('description') or '').strip()
    st['would_run'] = expr
    if not expr:
        st['status'] = 'failed'
        st['detail'] = 'condition 步骤未配置表达式（config.expr 为空）'
        return
    try:
        value = _eval_condition(expr)
    except ValueError as exc:
        st['status'] = 'failed'
        st['detail'] = f'条件表达式不支持安全求值：{exc}'
        return
    st['condition_result'] = bool(value)
    st['detail'] = (
        f'条件求值完成：{value!r}（{"成立" if value else "不成立"}；'
        '引擎为顺序执行，条件结果不影响后续步骤是否运行）'
    )


async def _agent_complete(
    task: str, owner_id: str | None = None,
) -> tuple[str, str]:
    """调用模型网关真实补全（复用 agents._try_gateway 回退链，含
    get_active_provider 兜底）。网关不可用/未配置/调用失败 → 抛
    RuntimeError 由步骤统一标 failed，绝不回退假文本。"""
    from .agents import _try_gateway  # noqa: SLF001 —— 复用既有回退链
    text, provider_used = await _try_gateway(task[:800], owner_id=owner_id)
    if not text:
        raise RuntimeError(
            '模型网关不可用（未配置可用 provider 或本次调用失败），agent 步骤不回退模拟文本'
        )
    return text, (provider_used or 'unknown')


async def _exec_step_real(
    step: dict, index: int, gear: Optional[str], owner_id: str,
) -> dict:
    """单个步骤的真实执行器。门禁前置（PermissionError → failed）；
    其余任何异常都终结为 failed + 原因，绝不静默成功。"""
    stype = step.get('type') if step.get('type') in STEP_TYPES else 'agent'
    cfg = step.get('config') if isinstance(step.get('config'), dict) else {}
    st = {
        'step_id': str(step.get('id') or f'st{index + 1}'),
        'name': str(step.get('name') or f'步骤{index + 1}'),
        'type': stype,
        'status': 'done',
        'detail': '',
        'would_run': '',
        'started_at': _now_iso(),
        'finished_at': None,
    }
    try:
        _enforce_real_execution_gear(stype, gear)
        if stype == 'shell':
            await asyncio.to_thread(_fill_shell_result, st, cfg)
        elif stype == 'http':
            await asyncio.to_thread(_fill_http_result, st, cfg)
        elif stype == 'memory':
            await asyncio.to_thread(_fill_memory_result, st, cfg, owner_id)
        elif stype == 'condition':
            _fill_condition_result(st, cfg)
        else:  # agent
            task = str(cfg.get('task') or cfg.get('prompt') or st['name'])
            st['would_run'] = task
            text, provider_used = await _agent_complete(task, owner_id=owner_id)
            st['output'] = text
            st['provider'] = provider_used
            st['detail'] = f'真实调用模型网关完成（provider={provider_used}）'
    except PermissionError as exc:
        st['status'] = 'failed'
        st['detail'] = f'gear 门禁拒绝真实执行：{exc}'
    except Exception as exc:  # noqa: BLE001 —— 单步失败如实落账，绝不静默成功
        st['status'] = 'failed'
        st['detail'] = f'真实执行异常：{type(exc).__name__}: {exc}'
    return st


async def _execute_run_real(run_id: str, flow: dict) -> None:
    """真实逐步执行。与 _simulate_run 相同的兜底契约：任何路径都把运行
    终结为 done/failed + done=True + finished_at，绝不留 running 假死；
    on_error=stop 时后续步骤 skipped。真实执行起止各落一条审计事件
    （started 由入口路由/调度器记录并带 mode=real）。"""
    run = _runs.get(run_id)
    if run is None:
        return
    fid = str(flow.get('id') or '')
    owner_id = str(run.get('owner_id') or configured_actor_id())
    gear = flow.get('gear')
    steps = flow.get('steps') or []
    results: list[dict] = []
    status = 'done'
    stopped_at: Optional[int] = None
    try:
        for i, step in enumerate(steps):
            st = await _exec_step_real(step, i, gear, owner_id)
            st['finished_at'] = _now_iso()
            results.append(st)
            run['step_results'] = results
            if not _persist_run(run_id, run):
                return
            if st['status'] == 'failed' and (step.get('on_error') or 'stop') == 'stop':
                status = 'failed'
                stopped_at = i
                break
        if stopped_at is not None:
            for j, rest in enumerate(steps[stopped_at + 1:], stopped_at + 1):
                results.append({
                    'step_id': str(rest.get('id') or f'st{j + 1}'),
                    'name': str(rest.get('name') or f'步骤{j + 1}'),
                    'type': rest.get('type') or 'agent',
                    'status': 'skipped',
                    'detail': '前序步骤失败，on_error=stop，本步骤跳过',
                    'would_run': '',
                    'started_at': None,
                    'finished_at': None,
                })
            run['step_results'] = results
            if not _persist_run(run_id, run):
                return
    except Exception as exc:  # noqa: BLE001 —— 兕底：运行绝不留 running 假死
        status = 'failed'
        run['error'] = f'真实运行内部异常：{exc!r}'
    run['status'] = status
    run['done'] = True
    run['finished_at'] = _now_iso()
    persisted = _persist_run(run_id, run)
    audit_safe('flow_run_finished', {
        'run_id': run_id,
        'flow_id': fid,
        'mode': 'real',
        'gear': gear,
        'status': status,
        'record_persisted': persisted,
    })


# ---------------------------------------------------------------------------
# 定时调度：router lifespan 内的最小 cron 调度循环
# ---------------------------------------------------------------------------

_SCHEDULER_INTERVAL_ENV = 'WANWEI_FLOW_SCHEDULER_INTERVAL_SECONDS'
_DEFAULT_SCHEDULER_INTERVAL = 30.0

# fid -> {'updated_at': str, 'due': Optional[datetime]}；仅调度协程读写，
# 进程内存态：重启后按当前时间重算，宕机期间错过的触发不补跑。
_schedule_state: dict[str, dict] = {}


def _scheduler_interval() -> float:
    try:
        raw = os.environ.get(_SCHEDULER_INTERVAL_ENV, '').strip()
        return max(0.1, float(raw)) if raw else _DEFAULT_SCHEDULER_INTERVAL
    except ValueError:
        return _DEFAULT_SCHEDULER_INTERVAL


def _scheduler_tick(now: Optional[datetime] = None) -> list[str]:
    """扫一遍 enabled 的定时流程，到期即触发一次模拟运行。

    返回本轮触发的 run id 列表。同流程已有 running 时跳过本次触发
    （不堆积），并在 audit 如实记录。
    """
    now = now or datetime.now().astimezone()
    if now.tzinfo is None:
        now = now.astimezone()
    fired: list[str] = []
    flows = _flows.all()
    live_fids = {fid for fid, f in flows.items() if isinstance(f, dict)}
    for stale in set(_schedule_state) - live_fids:
        _schedule_state.pop(stale, None)
    for fid, flow in flows.items():
        if not isinstance(flow, dict):
            continue
        if flow.get('trigger') != 'schedule' or not flow.get('enabled', True) \
                or not flow.get('cron'):
            _schedule_state.pop(fid, None)
            continue
        state = _schedule_state.get(fid)
        if state is None or state.get('updated_at') != flow.get('updated_at'):
            due, _approx = _next_cron_dt(flow['cron'], now)
            state = {'updated_at': flow.get('updated_at'), 'due': due}
            _schedule_state[fid] = state
        due = state.get('due')
        if due is None or due > now:
            continue
        mode = _flow_mode(flow)
        owner = _flow_owner(flow)
        if owner and not flow.get('owner_id'):
            _materialize_owner(_flows, str(fid), flow, owner)
        run = _try_create_run(flow, triggered_by='schedule', mode=mode, owner_id=owner)
        if run is not None:
            _launch_run(run['id'], flow, mode)
            fired.append(run['id'])
            audit_safe('flow_run_started', {'run_id': run['id'], 'flow_id': fid, 'manual': False, 'mode': mode})
        else:
            audit_safe('flow_run_skipped', {'flow_id': fid, 'reason': '已有运行进行中，跳过本次定时触发'})
        nxt, _approx = _next_cron_dt(flow['cron'], now)
        state['due'] = nxt
        state['updated_at'] = flow.get('updated_at')
    return fired


async def _scheduler_loop(stop: asyncio.Event) -> None:
    """周期调度循环：单轮扫描失败不拖垮循环本身。"""
    while not stop.is_set():
        try:
            _scheduler_tick()
        except Exception:  # noqa: BLE001 —— 单轮失败静默，下轮继续
            pass
        try:
            await asyncio.wait_for(stop.wait(), timeout=_scheduler_interval())
        except asyncio.TimeoutError:
            pass


def _recover_interrupted_runs() -> int:
    """启动时回收僵尸 running：服务重启/崩溃导致的中断一律终结为
    failed + error 说明，避免运行记录永久假死。返回回收条数。"""
    recovered = 0
    with _runs._lock:  # noqa: SLF001
        data = _runs._read()  # noqa: SLF001
        changed = False
        for run in data.values():
            if isinstance(run, dict) and run.get('status') == 'running':
                run['status'] = 'failed'
                run['done'] = True
                run['error'] = '服务重启，本次运行被中断，已按失败终结'
                run['finished_at'] = run.get('finished_at') or _now_iso()
                changed = True
                recovered += 1
        if changed:
            _runs._write(data)  # noqa: SLF001
    return recovered


async def _automation_lifespan(_app: Any) -> Any:
    """router 级 lifespan：启动时回收僵尸 running，并启动 cron 调度协程。"""
    _recover_interrupted_runs()
    stop = asyncio.Event()
    task = asyncio.create_task(_scheduler_loop(stop), name='flow-cron-scheduler')
    try:
        yield
    finally:
        stop.set()
        try:
            await asyncio.wait_for(task, timeout=5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass


# APIRouter 构造时未传 lifespan：此处替换默认 lifespan_context，
# platform_api 聚合 include_router 时会向上合并进应用 lifespan。
router.lifespan_context = asynccontextmanager(_automation_lifespan)


# ---------------------------------------------------------------------------
# 对外视图：契约字段（flow.next_run / run.done / run.simulated）
# ---------------------------------------------------------------------------

def _flow_view(flow: dict) -> dict:
    """flow 对外视图：补 next_run（schedule 且 enabled 时的下一次触发
    ISO8601，否则 None）。读取时现算不落库，避免存储值过期。
    真实执行批次：gear 旧记录缺省回填 human_review（默认档，仅人工审查
    语义），与 _run_view 的 mode 回填同口。"""
    view = _public_record(flow)
    view['gear'] = view.get('gear') if view.get('gear') in GEARS else 'human_review'
    next_run: Optional[str] = None
    if view.get('trigger') == 'schedule' and view.get('enabled', True):
        next_run, _approx = _next_cron_run(view.get('cron'))
    view['next_run'] = next_run
    return view


def _run_view(run: dict) -> dict:
    """run 对外视图：补齐契约字段 done/simulated/mode，兼容修复前的旧记录。

    issue #45 P0-5：simulated 默认值反转为 False——真实触发默认为非模拟，
    模拟态只能由显式模拟入口写入。
    真实执行批次：mode 字段（'real'|'dry_run'）旧记录缺省按 dry_run 兼容回填
    ——历史记录全部产生于「只模拟」时期。
    """
    view = _public_record(run)
    done = view.get('done')
    view['done'] = done if isinstance(done, bool) else str(view.get('status') or '') != 'running'
    view['simulated'] = bool(view.get('simulated', False))
    view['mode'] = view.get('mode') if view.get('mode') in ('real', 'dry_run') else 'dry_run'
    return view


# ---------------------------------------------------------------------------
# 路由 —— 固定路径先于参数路径
# ---------------------------------------------------------------------------

def _check_cron_value(v: Optional[str]) -> Optional[str]:
    """cron 写入口统一校验：5 段格式 + 取值范围，非法抛 ValueError（pydantic 转 422）。"""
    if v is None:
        return None
    v = v.strip()
    if not v:
        return None
    _validate_cron_expr(v)
    return v


class FlowIn(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_FLOW_NAME_LENGTH)
    desc: str = Field(default='', max_length=MAX_FLOW_DESCRIPTION_LENGTH)
    trigger: Literal['manual', 'schedule', 'event'] = 'manual'
    gear: Gear = 'human_review'
    cron: Optional[str] = Field(default=None, max_length=MAX_CRON_EXPRESSION_LENGTH)
    steps: list[dict] = Field(default_factory=list, max_length=MAX_STEPS_PER_FLOW)
    enabled: bool = True

    @field_validator('cron')
    @classmethod
    def _cron_valid(cls, v: Optional[str]) -> Optional[str]:
        return _check_cron_value(v)

    @field_validator('steps')
    @classmethod
    def _steps_valid(cls, value: list[dict]) -> list[dict]:
        return _normalize_steps(value)


class FlowPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=MAX_FLOW_NAME_LENGTH)
    desc: Optional[str] = Field(default=None, max_length=MAX_FLOW_DESCRIPTION_LENGTH)
    trigger: Optional[Literal['manual', 'schedule', 'event']] = None
    gear: Optional[Gear] = None
    cron: Optional[str] = Field(default=None, max_length=MAX_CRON_EXPRESSION_LENGTH)
    steps: Optional[list[dict]] = Field(default=None, max_length=MAX_STEPS_PER_FLOW)
    enabled: Optional[bool] = None

    @field_validator('cron')
    @classmethod
    def _cron_valid(cls, v: Optional[str]) -> Optional[str]:
        return _check_cron_value(v)

    @field_validator('steps')
    @classmethod
    def _steps_valid(cls, value: Optional[list[dict]]) -> Optional[list[dict]]:
        return _normalize_steps(value) if value is not None else None


class AiEditIn(BaseModel):
    flow_id: Optional[str] = None
    instruction: str = Field(min_length=1, max_length=4000)


class AiApplyIn(BaseModel):
    proposed_flow: dict


@router.get('/flows')
def list_flows(request: Request = None) -> list[dict]:
    items = _owned_flow_snapshot(_actor_id(request))
    items.sort(key=lambda f: str(f.get('updated_at') or ''), reverse=True)
    return [_flow_view(f) for f in items]


@router.post('/flows', status_code=201)
def create_flow(payload: FlowIn, request: Request = None) -> dict:
    fid = _new_id('flow')
    owner_id = _actor_id(request)
    flow = _normalize_flow(payload.model_dump(), fid=fid, existing=None)
    flow['owner_id'] = owner_id
    _store_new_flow(fid, flow)
    audit_safe('flow_created', {'flow_id': fid, 'name': flow.get('name')})
    return _flow_view(flow)


@router.post('/flows/ai-edit')
def ai_edit_flow(payload: AiEditIn, request: Request = None) -> dict:
    """规则式中文解析（engine='rule'，非模型生成，issue #45 P0-4）。

    语义为「全量重建」（edit_mode='full_rebuild'）：proposed_flow 每次都
    按整段指令重建完整流程定义，步骤序列整体替换，不是对现有步骤的增量
    调整；changes 如实列出重建后与现状的差异。响应显式声明「规则解析、
    非模型生成」，不允许与成功语义混同。跨属主一律 404。
    """
    instruction = payload.instruction.strip()
    if not instruction:
        raise HTTPException(400, 'instruction 不能为空')
    owner_id = _actor_id(request)
    base: Optional[dict] = None
    if payload.flow_id:
        candidate = _flows.get(payload.flow_id)
        if isinstance(candidate, dict) and _record_visible(candidate, owner_id):
            base = candidate
            if not base.get('owner_id'):
                _materialize_owner(_flows, str(payload.flow_id), base, owner_id)
        if base is None:
            raise HTTPException(404, f'流程不存在：{payload.flow_id}')
    trigger, cron, _trig_desc = _parse_trigger(instruction)
    steps, notes = _parse_steps(instruction)
    now = _now_iso()
    new_name = _extract_name(instruction)
    if new_name:
        name = new_name
    elif base:
        name = base.get('name') or '未命名流程'
    else:
        name = f'AI 流程 {datetime.now().strftime("%m%d%H%M")}'
    desc = base.get('desc') if base else f'由 AI 编辑指令生成：{instruction[:80]}'
    proposed = {
        'id': base.get('id') if base else '',
        'name': name,
        'desc': desc,
        'trigger': trigger,
        # gear 是执行门禁字段：规则解析不擅自改动，编辑现有流程时保留原值，
        # 新建提案归一为默认 human_review（绝不当作执行授权）。
        'gear': (base or {}).get('gear') or 'human_review',
        'cron': cron,
        'steps': steps,
        'enabled': bool(base.get('enabled', True)) if base else True,
        'created_at': base.get('created_at') if base else now,
        'updated_at': now,
        'ai_editable': True,
    }
    changes = _ai_diff(base, proposed)
    changes.extend(notes)
    return {
        'understood': _understood(base, trigger, cron, steps),
        'proposed_flow': proposed,
        'changes': changes,
        'engine': 'rule',
        'edit_mode': 'full_rebuild',
        'note': '规则解析、非模型生成（engine=rule）',
    }


@router.get('/flows/schedule/overview')
def schedule_overview(request: Request = None) -> list[dict]:
    items: list[dict] = []
    for f in _owned_flow_snapshot(_actor_id(request)):
        if not isinstance(f, dict):
            continue
        if f.get('trigger') != 'schedule' or not f.get('enabled'):
            continue
        next_run, approximate = _next_cron_run(f.get('cron'))
        items.append({
            'flow_id': f.get('id'),
            'name': f.get('name'),
            'cron': f.get('cron'),
            'enabled': True,
            'next_run': next_run,
            'approximate': approximate,
        })
    items.sort(key=lambda x: (x['next_run'] is None, x['next_run'] or ''))
    return items


@router.get('/flows/{fid}')
def get_flow(fid: str, request: Request = None) -> dict:
    flow = _get_flow_or_404(fid, _actor_id(request))
    return _flow_view(flow)


@router.put('/flows/{fid}')
def update_flow(fid: str, payload: FlowPatch, request: Request = None) -> dict:
    owner_id = _actor_id(request)
    patch = payload.model_dump(exclude_unset=True)

    def _apply(data: dict) -> dict:
        existing = data.get(fid)
        if not isinstance(existing, dict) or not _record_visible(existing, owner_id):
            raise HTTPException(404, f'流程不存在：{fid}')
        if not existing.get('owner_id'):
            _materialize_owner(_flows, fid, existing, owner_id)
        merged = dict(existing)
        merged.update(patch)
        flow = _normalize_flow(
            merged,
            fid=fid,
            existing=existing,
            preserve_existing_steps=patch.get('steps') is None,
        )
        flow['owner_id'] = str(existing.get('owner_id') or owner_id)
        data[fid] = flow
        return flow

    try:
        flow = _flows.mutate(_apply)
    except ValueError:
        raise HTTPException(422, "invalid flow definition") from None
    return _flow_view(flow)


def _delete_runs_of_flow(fid: str, owner_id: Optional[str] = None) -> int:
    """级联清理某流程的运行记录（owner_id 传值时仅清理该属主的），返回清理条数。"""
    with _runs._lock:  # noqa: SLF001 —— 共享工具缺批量删除的务实兜底
        data = _runs._read()  # noqa: SLF001
        victims = [
            k for k, r in data.items()
            if isinstance(r, dict) and r.get('flow_id') == fid
            and (owner_id is None or _run_visible(r, owner_id))
        ]
        for k in victims:
            data.pop(k, None)
        if victims:
            _runs._write(data)  # noqa: SLF001
    return len(victims)


@router.delete('/flows/{fid}')
def delete_flow(fid: str, request: Request = None) -> dict:
    owner_id = _actor_id(request)
    flow = _get_flow_or_404(fid, owner_id)
    if not _store_delete(_flows, fid):
        raise HTTPException(404, f'流程不存在：{fid}')
    runs_deleted = _delete_runs_of_flow(fid, str(flow.get('owner_id') or owner_id))
    audit_safe('flow_deleted', {'flow_id': fid, 'runs_deleted': runs_deleted})
    return {'deleted': True, 'id': fid, 'runs_deleted': runs_deleted}


@router.post('/flows/{fid}/ai-apply')
def ai_apply_flow(fid: str, payload: AiApplyIn, response: Response, create: bool = False, request: Request = None) -> dict:
    """应用 AI 提案。flow_id 不存在时 404；仅显式 create=true 才允许按
    提案新建（此前会静默创建，与写路径语义不一致）。跨属主一律 404。"""
    owner_id = _actor_id(request)
    existing = _flows.get(fid)
    if isinstance(existing, dict) and not _record_visible(existing, owner_id):
        raise HTTPException(status_code=404, detail=f'流程不存在：{fid}')
    if isinstance(existing, dict) and not existing.get('owner_id'):
        _materialize_owner(_flows, fid, existing, owner_id)
    if existing is None and not create:
        raise HTTPException(404, f'流程不存在：{fid}；如需按提案新建请显式传 create=true')
    cron = payload.proposed_flow.get('cron') if isinstance(payload.proposed_flow, dict) else None
    if isinstance(cron, str) and cron.strip():
        try:
            _validate_cron_expr(cron.strip())
        except ValueError:
            raise HTTPException(422, "invalid cron expression") from None
    target_id = fid
    if existing is None:
        target_id = _new_id('fl')
    try:
        flow = _normalize_flow(payload.proposed_flow, fid=target_id, existing=existing)
    except ValueError:
        raise HTTPException(422, "invalid flow data") from None
    flow['owner_id'] = str(existing.get('owner_id') if existing else owner_id)
    if existing is None:
        _store_new_flow(target_id, flow)
    else:
        _flows.set(target_id, flow)
    if existing is None:
        response.status_code = 201
        audit_safe('flow_created', {'flow_id': target_id, 'requested_id': fid, 'name': flow.get('name'), 'via': 'ai-apply'})
    return _flow_view(flow)


@router.post('/flows/{fid}/run', status_code=202)
async def run_flow(fid: str, request: Request = None) -> dict:
    """执行流程。模式由流程档位决定（run.mode 如实记录）：
    human_review（默认档）→ dry-run 模拟；sandbox/device → 真实执行
    （每步仍过 _enforce_real_execution_gear 门禁，未授权如实 failed）。
    显式 dry-run 预演请走 /flows/{fid}/simulate。跨属主一律 404。"""
    owner_id = _actor_id(request)
    flow = _get_flow_or_404(fid, owner_id)
    mode = _flow_mode(flow)
    run = _try_create_run(flow, triggered_by='manual', mode=mode, owner_id=owner_id)
    if run is None:
        raise HTTPException(409, '该流程已有运行进行中，拒绝并发重入')
    _launch_run(run['id'], flow, mode)
    audit_safe('flow_run_started', {'run_id': run['id'], 'flow_id': fid, 'manual': True, 'mode': mode})
    return _run_view(run)


@router.post('/flows/{fid}/simulate', status_code=202)
async def simulate_flow(fid: str, request: Request = None) -> dict:
    """显式模拟运行入口：无论流程档位一律 dry-run（不申请任何执行档位），
    sandbox/device 流程也可先预演再真实执行。真实执行入口是 /run。跨属主一律 404。"""
    owner_id = _actor_id(request)
    flow = _get_flow_or_404(fid, owner_id)
    run = _try_create_run(flow, triggered_by='manual', mode='dry_run', owner_id=owner_id)
    if run is None:
        raise HTTPException(409, '该流程已有运行进行中，拒绝并发重入')
    _launch_run(run['id'], flow, 'dry_run')
    audit_safe('flow_run_started', {'run_id': run['id'], 'flow_id': fid, 'manual': True, 'mode': 'dry_run'})
    return _run_view(run)


@router.get('/runs')
def list_runs(flow_id: Optional[str] = None, limit: int = 200, request: Request = None) -> list[dict]:
    limit = max(1, min(limit, 500))
    owner_id = _actor_id(request)
    items = []
    for run in _runs.all().values():
        if not isinstance(run, dict) or not _run_visible(run, owner_id):
            continue
        if not run.get('owner_id'):
            _materialize_run_owner(run, owner_id)
        items.append(run)
    if flow_id:
        items = [r for r in items if r.get('flow_id') == flow_id]
    items.sort(key=lambda r: str(r.get('started_at') or ''), reverse=True)
    return [_run_view(r) for r in items[:limit]]


@router.get('/runs/{rid}')
def get_run(rid: str, request: Request = None) -> dict:
    owner_id = _actor_id(request)
    run = _runs.get(rid)
    if isinstance(run, dict) and _run_visible(run, owner_id):
        if not run.get('owner_id'):
            _materialize_run_owner(run, owner_id)
    else:
        run = None
    if run is None:
        raise HTTPException(404, f'运行记录不存在：{rid}')
    return _run_view(run)
