"""platform_api.automation —— 自动化舱：AI 可编辑工作流与自动化。

职责：
- 工作流 CRUD（JsonStore('flows')）；
- AI 编辑：规则式中文解析器把自然语言指令转成完整流程定义 diff
  （engine='mock'，未接入真实大模型，诚实标注为模拟引擎）；
- 运行模拟（JsonStore('flow_runs')）：asyncio 后台逐步执行；shell/http/
  agent/memory 步骤一律不真实执行，仅返回 would_run 说明；
- 定时总览：标准库解析 cron 五段式粗算下次触发时间，算不准的标注
  approximate=true。

路由顺序：固定路径（/flows/ai-edit、/flows/schedule/overview）定义在
参数路径（/flows/{fid} 一族）之前，避免被参数路径吞掉。
"""
from __future__ import annotations

import asyncio
import re
import threading
import uuid
from datetime import datetime, timedelta
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.platform_api.store import JsonStore

router = APIRouter(prefix='/automation', tags=['platform-automation'])

_flows = JsonStore('flows')
_runs = JsonStore('flow_runs')

TRIGGERS = ('manual', 'schedule', 'event')
TRIGGER_LABELS = {'manual': '手动触发', 'schedule': '定时触发', 'event': '事件触发'}
STEP_TYPES = ('agent', 'shell', 'http', 'memory', 'condition')
STEP_TYPE_LABELS = {
    'agent': '智能体',
    'shell': '命令',
    'http': 'HTTP 请求',
    'memory': '记忆',
    'condition': '条件判断',
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


def _normalize_flow(pf: dict, fid: str, existing: Optional[dict]) -> dict:
    """把任意来源（POST/PUT/ai-apply）的流程载荷归一成契约定义的完整结构。"""
    pf = pf if isinstance(pf, dict) else {}
    existing = existing or {}
    now = _now_iso()
    trigger = pf.get('trigger') if pf.get('trigger') in TRIGGERS else existing.get('trigger', 'manual')
    cron = pf.get('cron')
    cron = cron.strip() if isinstance(cron, str) and cron.strip() else None
    if trigger != 'schedule':
        cron = cron  # 非定时流也允许保留 cron 草稿，前端自行忽略
    steps_in = pf.get('steps') if isinstance(pf.get('steps'), list) else []
    steps: list[dict] = []
    for i, s in enumerate(steps_in, 1):
        if not isinstance(s, dict):
            continue
        stype = s.get('type') if s.get('type') in STEP_TYPES else 'agent'
        cfg = s.get('config') if isinstance(s.get('config'), dict) else {}
        steps.append({
            'id': str(s.get('id') or f'st{i}'),
            'type': stype,
            'name': str(s.get('name') or f'步骤{i}'),
            'config': cfg,
            'on_error': 'continue' if s.get('on_error') == 'continue' else 'stop',
        })
    return {
        'id': fid,
        'name': str(pf.get('name') or existing.get('name') or '未命名流程'),
        'desc': str(pf.get('desc') if pf.get('desc') is not None else existing.get('desc', '')),
        'trigger': trigger,
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
    for part in field.split(','):
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


def _next_cron_run(cron: Optional[str], now: Optional[datetime] = None) -> tuple[Optional[str], bool]:
    """返回 (下次触发本地时间 ISO, approximate)。解析失败/400 天内无触发 → (None, True)。"""
    parts = (cron or '').split()
    if len(parts) != 5:
        return None, True
    try:
        minutes = _parse_cron_field(parts[0], 0, 59)
        hours = _parse_cron_field(parts[1], 0, 23)
        doms = _parse_cron_field(parts[2], 1, 31)
        months = _parse_cron_field(parts[3], 1, 12)
        dows_raw = _parse_cron_field(parts[4], 0, 7)
    except (ValueError, AttributeError):
        return None, True
    dows = {0 if d == 7 else d for d in dows_raw}
    dom_any = parts[2] in ('*', '?')
    dow_any = parts[4] in ('*', '?')
    # dom 与 dow 同时受限时 cron 语义为「或」，粗算结果标注 approximate
    approximate = not dom_any and not dow_any
    now = now or datetime.now()
    start = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    sorted_hours = sorted(hours)
    sorted_minutes = sorted(minutes)
    for offset in range(0, 400):
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
        for h in sorted_hours:
            for m in sorted_minutes:
                cand = datetime(day.year, day.month, day.day, h, m)
                if cand >= start:
                    return cand.isoformat(timespec='seconds'), approximate
    return None, True


# ---------------------------------------------------------------------------
# AI 编辑：规则式中文指令解析器（engine='mock'）
# ---------------------------------------------------------------------------

_WEEKDAY_MAP = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '日': 0, '天': 0}

_CLAUSE_SPLIT_RE = re.compile(r'[，。；;！!？?\n]|(?:然后|接着|接下来|随后|之后|最后|并且?)')
_CONNECTOR_RE = re.compile(r'^(?:首先|先|再|并|且|第[一二三四五六七八九十\d]+步)[，,：:、\s]*')
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
    who = f'在现有流程「{base["name"]}」基础上调整' if base else '创建新流程'
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


async def _simulate_run(run_id: str, flow: dict) -> None:
    run = _runs.get(run_id) or {}
    steps = flow.get('steps') or []
    results: list[dict] = []
    status = 'done'
    for i, step in enumerate(steps):
        st = _simulate_step(step, i)
        await asyncio.sleep(0.05)  # 模拟耗时，让运行过程可观察
        st['finished_at'] = _now_iso()
        results.append(st)
        run['step_results'] = results
        _runs.set(run_id, run)
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
            _runs.set(run_id, run)
            break
    run['status'] = status
    run['finished_at'] = _now_iso()
    _runs.set(run_id, run)


# ---------------------------------------------------------------------------
# 路由 —— 固定路径先于参数路径
# ---------------------------------------------------------------------------

class FlowIn(BaseModel):
    name: str = Field(min_length=1)
    desc: str = ''
    trigger: Literal['manual', 'schedule', 'event'] = 'manual'
    cron: Optional[str] = None
    steps: list[dict] = Field(default_factory=list)
    enabled: bool = True


class FlowPatch(BaseModel):
    name: Optional[str] = None
    desc: Optional[str] = None
    trigger: Optional[Literal['manual', 'schedule', 'event']] = None
    cron: Optional[str] = None
    steps: Optional[list[dict]] = None
    enabled: Optional[bool] = None


class AiEditIn(BaseModel):
    flow_id: Optional[str] = None
    instruction: str = Field(min_length=1)


class AiApplyIn(BaseModel):
    proposed_flow: dict


@router.get('/flows')
def list_flows() -> list[dict]:
    items = [f for f in _flows.all().values() if isinstance(f, dict)]
    items.sort(key=lambda f: str(f.get('updated_at') or ''), reverse=True)
    return items


@router.post('/flows', status_code=201)
def create_flow(payload: FlowIn) -> dict:
    fid = _new_id('flow')
    flow = _normalize_flow(payload.model_dump(), fid=fid, existing=None)
    _flows.set(fid, flow)
    return flow


@router.post('/flows/ai-edit')
def ai_edit_flow(payload: AiEditIn) -> dict:
    instruction = payload.instruction.strip()
    if not instruction:
        raise HTTPException(400, 'instruction 不能为空')
    base: Optional[dict] = None
    if payload.flow_id:
        base = _flows.get(payload.flow_id)
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
        'engine': 'mock',
    }


@router.get('/flows/schedule/overview')
def schedule_overview() -> list[dict]:
    items: list[dict] = []
    for f in _flows.all().values():
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
def get_flow(fid: str) -> dict:
    flow = _flows.get(fid)
    if flow is None:
        raise HTTPException(404, f'流程不存在：{fid}')
    return flow


@router.put('/flows/{fid}')
def update_flow(fid: str, payload: FlowPatch) -> dict:
    existing = _flows.get(fid)
    if existing is None:
        raise HTTPException(404, f'流程不存在：{fid}')
    merged = dict(existing)
    merged.update(payload.model_dump(exclude_unset=True))
    flow = _normalize_flow(merged, fid=fid, existing=existing)
    _flows.set(fid, flow)
    return flow


@router.delete('/flows/{fid}')
def delete_flow(fid: str) -> dict:
    if not _store_delete(_flows, fid):
        raise HTTPException(404, f'流程不存在：{fid}')
    return {'deleted': True, 'id': fid}


@router.post('/flows/{fid}/ai-apply')
def ai_apply_flow(fid: str, payload: AiApplyIn) -> dict:
    existing = _flows.get(fid)
    flow = _normalize_flow(payload.proposed_flow, fid=fid, existing=existing)
    _flows.set(fid, flow)
    return flow


@router.post('/flows/{fid}/run', status_code=202)
async def run_flow(fid: str) -> dict:
    flow = _flows.get(fid)
    if flow is None:
        raise HTTPException(404, f'流程不存在：{fid}')
    rid = _new_id('run')
    run = {
        'id': rid,
        'flow_id': fid,
        'flow_name': flow.get('name') or '',
        'status': 'running',
        'step_results': [],
        'started_at': _now_iso(),
        'finished_at': None,
        'simulated': True,
    }
    if not flow.get('enabled', True):
        run['note'] = '流程处于停用状态，本次为手动强制执行'
    _runs.set(rid, run)
    # 独立线程里跑 asyncio 事件循环执行模拟：不依赖请求处理所在 loop 的
    # 生命周期（TestClient/部分中间件下 create_task 的任务可能不再推进），
    # 对 uvicorn 等常驻 loop 同样安全；JsonStore 自带线程锁。
    threading.Thread(
        target=lambda: asyncio.run(_simulate_run(rid, flow)),
        name=f'flow-run-{rid}',
        daemon=True,
    ).start()
    return run


@router.get('/runs')
def list_runs(flow_id: Optional[str] = None, limit: int = 200) -> list[dict]:
    limit = max(1, min(limit, 500))
    items = [r for r in _runs.all().values() if isinstance(r, dict)]
    if flow_id:
        items = [r for r in items if r.get('flow_id') == flow_id]
    items.sort(key=lambda r: str(r.get('started_at') or ''), reverse=True)
    return items[:limit]


@router.get('/runs/{rid}')
def get_run(rid: str) -> dict:
    run = _runs.get(rid)
    if run is None:
        raise HTTPException(404, f'运行记录不存在：{rid}')
    return run
