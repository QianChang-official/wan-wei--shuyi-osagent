"""记忆中枢：记忆指令、梦境归档、常用语与会话管理。

挂载前缀 ``/platform``（由 platform_api 包自动发现挂载），本模块路由均以
``/memory`` 开头：

- 记忆指令（「记住」）：``/memory/instructions*``、``/memory/remember``
- 梦境记忆：``/memory/dreams*``（每夜整理为手动触发，当前无后台调度，
  调度状态以 ``/memory/dreams/schedule`` 如实返回为准）
- 常用语：``/memory/phrases*``
- 会话管理：``/memory/sessions*``

持久化全部走共享 ``JsonStore``（JSON 落盘，模块级共享锁 + ``mutate`` 原子原语）：
``memory_instructions`` / ``phrases`` / ``sessions`` / ``dream_archive``。

路由顺序注意：``/memory/instructions/prompt`` 等固定路径必须先于
``/memory/instructions/{index}`` 这类参数路径定义，避免被参数路径吞掉。

双轨现状（审计 06-#11 诚实标注，不做合并重构）：
本模块是 platform 版记忆体系（JSON 影子存储），与老 ``app.memory_runtime``
体系（sqlite 胶囊 / FTS 检索 / evolution）双轨并行、零数据互通。
唯一复用点是写入前的 ``memory_runtime.policy_gate.evaluate_policy`` 安全闸门；
记忆指令、常用语、梦境归档均不进入老体系的胶囊/检索链路，反之亦然。
- sessions：``JsonStore('sessions')`` 无真实生产者（无创建接口、未对接
  sqlite ``conversation_turns`` 表），列表接口已在响应中如实标注来源；
- dream_archive：与 ``app/dream/scheduler.py``（sqlite ``dream_lock``
  占位引擎）无关；无真实会话数据时归档走示例会话并标注 ``source='sample'``。

时间基准（审计 06-#12 统一）：全模块 UTC aware datetime，
ISO8601 秒级带 ``Z`` 序列化（与 knowledge.py 同一口径）。
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.platform_api.guards import audit_safe
from app.platform_api.store import JsonStore
from app.memory_runtime.policy_gate import evaluate_policy
from app.utils.datetime_utils import utc_now, utc_now_iso_compact

router = APIRouter(prefix='/memory', tags=['memory-center'])


def _enforce_memory_policy(text: str) -> None:
    """写入前 Policy Gate 校验：reject/quarantine → 422。

    remember / instructions / phrases 三个写入入口统一调用，防止密码、
    密钥、身份证号、记忆投毒等敏感内容被持久化为指令/常用语。
    """
    guard = evaluate_policy(
        text=text,
        source_type="user_input",
        write_intent="explicit",
        affects_future_behavior=True,
    )
    policy = guard.get("policy_result")
    if policy in ("reject", "quarantine"):
        audit_safe('policy_blocked', {
            'endpoint': 'memory_write',
            'policy_result': policy,
            'risk_tags': guard.get('risk_tags', []),
            'sensitivity_level': guard.get('sensitivity_level'),
        })
        raise HTTPException(
            status_code=422,
            detail={
                "message": "记忆内容触发安全策略拦截",
                "policy_result": policy,
                "risk_tags": guard.get("risk_tags", []),
                "sensitivity_level": guard.get("sensitivity_level"),
            },
        )

# ---------------------------------------------------------------------------
# 存储与常量
# ---------------------------------------------------------------------------

_instructions_store = JsonStore('memory_instructions')
_phrases_store = JsonStore('phrases')
_sessions_store = JsonStore('sessions')
_dream_store = JsonStore('dream_archive')

MAX_INSTRUCTION_LINES = 200
MAX_INSTRUCTION_LINE_CHARS = 500
MAX_PHRASE_CHARS = 200

PROMPT_HEADER = '用户长期记忆指令，须始终遵循'

# 梦境归档在没有真实会话数据时使用的示例会话（诚实标注 simulated 边界）
_SAMPLE_SESSIONS: list[dict[str, Any]] = [
    {
        'id': 'sample-001',
        'title': '示例：麒麟桌面兼容性排查',
        'agent': '系统助手',
        'turns': 18,
    },
    {
        'id': 'sample-002',
        'title': '示例：模型网关接入与密钥配置',
        'agent': '平台助手',
        'turns': 12,
    },
    {
        'id': 'sample-003',
        'title': '示例：国风控制台主题打磨',
        'agent': '设计助手',
        'turns': 9,
    },
]


def _now_iso() -> str:
    """UTC aware 当前时间 → ISO8601 秒级带 Z（与 knowledge.py 统一基准）。"""
    return utc_now_iso_compact()


def _today() -> str:
    """当前 UTC 日期：梦境「夜」的切分基准，与全模块 UTC 口径一致。"""
    return utc_now().strftime('%Y-%m-%d')


def _short_id(prefix: str) -> str:
    return f'{prefix}-{uuid.uuid4().hex[:12]}'


# ---------------------------------------------------------------------------
# 记忆指令（「记住」）
# ---------------------------------------------------------------------------


def _read_lines() -> list[str]:
    lines = _instructions_store.get('lines', [])
    if not isinstance(lines, list):
        return []
    return [str(line) for line in lines]


def _write_lines(lines: list[str]) -> str:
    updated_at = _now_iso()
    _instructions_store.update({'lines': lines, 'updated_at': updated_at})
    return updated_at


def _mutate_lines(fn: Any) -> Any:
    """锁内「读-改-写」指令行：fn(lines) 原地修改，返回值透传（06-#9）。

    基于 ``JsonStore.mutate`` 原子原语：读取、修改、落盘在同一把模块级
    共享锁内一次完成，杜绝并发 /remember 相互覆盖丢更新。fn 抛异常时
    不落盘。仅当 lines 真有变更时才刷新 ``updated_at``（保持去重等
    无操作路径不触碰时间戳的旧行为）。
    """
    def _apply(data: dict) -> Any:
        raw = data.get('lines')
        lines = [str(line) for line in raw] if isinstance(raw, list) else []
        before = list(lines)
        result = fn(lines)
        if lines != before:
            data['lines'] = lines
            data['updated_at'] = _now_iso()
        return result
    return _instructions_store.mutate(_apply)


def _validate_lines(lines: Any) -> list[str]:
    """校验指令行列表：≤200 行、每行为字符串且 ≤500 字。不合规抛 400。"""
    if not isinstance(lines, list):
        raise HTTPException(status_code=400, detail='lines 必须是字符串数组')
    if len(lines) > MAX_INSTRUCTION_LINES:
        raise HTTPException(
            status_code=400,
            detail=f'记忆指令最多 {MAX_INSTRUCTION_LINES} 行，当前 {len(lines)} 行',
        )
    cleaned: list[str] = []
    for i, line in enumerate(lines):
        if not isinstance(line, str):
            raise HTTPException(status_code=400, detail=f'第 {i + 1} 行不是字符串')
        text = line.strip()
        if len(text) > MAX_INSTRUCTION_LINE_CHARS:
            raise HTTPException(
                status_code=400,
                detail=f'第 {i + 1} 行超过 {MAX_INSTRUCTION_LINE_CHARS} 字上限',
            )
        if text:
            cleaned.append(text)
    return cleaned


class InstructionsPut(BaseModel):
    lines: list[str] = Field(default_factory=list)


class RememberPost(BaseModel):
    text: str = Field(..., min_length=1)


@router.get('/instructions')
def get_instructions() -> dict:
    lines = _read_lines()
    return {
        'lines': lines,
        'count': len(lines),
        'max': MAX_INSTRUCTION_LINES,
        'updated_at': _instructions_store.get('updated_at', ''),
    }


@router.put('/instructions')
def put_instructions(body: InstructionsPut) -> dict:
    lines = _validate_lines(body.lines)
    for line in lines:
        _enforce_memory_policy(line)
    updated_at = _write_lines(lines)
    return {
        'ok': True,
        'lines': lines,
        'count': len(lines),
        'max': MAX_INSTRUCTION_LINES,
        'updated_at': updated_at,
    }


# 固定路径 /instructions/prompt 必须先于参数路径 /instructions/{index} 定义
@router.get('/instructions/prompt')
def get_instructions_prompt() -> dict:
    """拼成始终注入系统提示的文本块；无指令时 text 为空串，调用方跳过注入。"""
    lines = _read_lines()
    if not lines:
        return {'text': '', 'header': PROMPT_HEADER, 'count': 0}
    body = '\n'.join(f'{i + 1}. {line}' for i, line in enumerate(lines))
    return {
        'text': f'【{PROMPT_HEADER}】\n{body}',
        'header': PROMPT_HEADER,
        'count': len(lines),
    }


@router.delete('/instructions/{index}')
def delete_instruction(index: int) -> dict:
    def _apply(lines: list[str]) -> tuple[str, int]:
        if index < 0 or index >= len(lines):
            raise HTTPException(status_code=404, detail=f'指令行 {index} 不存在')
        removed = lines.pop(index)
        return removed, len(lines)

    removed, count = _mutate_lines(_apply)
    return {'ok': True, 'removed': removed, 'count': count}


@router.post('/remember')
def remember(body: RememberPost) -> dict:
    """把一句「记住xxx」追加为指令行：自动去重，超 200 行淘汰最旧。"""
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail='记忆内容不能为空')
    if len(text) > MAX_INSTRUCTION_LINE_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f'单条记忆最多 {MAX_INSTRUCTION_LINE_CHARS} 字',
        )
    _enforce_memory_policy(text)

    def _apply(lines: list[str]) -> dict[str, Any]:
        if text in lines:
            # 自动去重：已存在的指令不重复追加（无变更，不刷新 updated_at）
            return {'deduped': True, 'lines_count': len(lines), 'evicted': None}
        lines.append(text)
        evicted = lines.pop(0) if len(lines) > MAX_INSTRUCTION_LINES else None
        return {'deduped': False, 'lines_count': len(lines), 'evicted': evicted}

    outcome = _mutate_lines(_apply)
    if outcome['deduped']:
        return {'ok': True, 'lines_count': outcome['lines_count'], 'deduped': True}
    audit_safe('memory_remember', {'lines_count': outcome['lines_count'], 'text': text})
    resp: dict[str, Any] = {'ok': True, 'lines_count': outcome['lines_count']}
    if outcome['evicted'] is not None:
        resp['evicted'] = outcome['evicted']
    return resp


# ---------------------------------------------------------------------------
# 梦境记忆（每夜整理）
# ---------------------------------------------------------------------------


def _read_sessions_raw() -> list[dict[str, Any]]:
    """读取会话列表，容忍多种落盘形态；无数据返回 []。"""
    data = _sessions_store.all()
    items = data.get('items')
    if isinstance(items, list):
        return [s for s in items if isinstance(s, dict)]
    # 容错：整店若是 {sid: session} 映射也接受
    sessions = [v for v in data.values() if isinstance(v, dict) and 'id' in v]
    return sessions


def _normalize_session(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        'id': str(raw.get('id', '')),
        'title': str(raw.get('title', '') or '未命名会话'),
        'agent': raw.get('agent'),
        'turns': int(raw.get('turns', 0) or 0),
        'archived': bool(raw.get('archived', False)),
        'pinned': bool(raw.get('pinned', False)),
        'updated_at': str(raw.get('updated_at', '')),
        'auto_expand_refs': bool(raw.get('auto_expand_refs', False)),
    }


def _mutate_items(store: JsonStore, fn: Any) -> Any:
    """锁内「读 items 列表 → fn(items) 原地修改 → 一次落盘」（06-#9）。

    基于 ``JsonStore.mutate`` 原子原语，杜绝 use_phrase / archive 等
    读改写路径的并发覆盖。fn 返回值透传给调用方；fn 抛异常时不落盘。
    读取兼容 sessions 旧落盘形态（整店为 ``{sid: session}`` 映射），
    写回统一收口为 ``{'items': [...]}``。
    """
    def _apply(data: dict) -> Any:
        raw = data.get('items')
        if isinstance(raw, list):
            items = [x for x in raw if isinstance(x, dict)]
        else:
            items = [v for v in data.values() if isinstance(v, dict) and 'id' in v]
        result = fn(items)
        data.clear()
        data['items'] = items
        return result
    return store.mutate(_apply)


def _read_dreams() -> list[dict[str, Any]]:
    items = _dream_store.get('items', [])
    if not isinstance(items, list):
        return []
    return [d for d in items if isinstance(d, dict)]


@router.get('/dreams')
def list_dreams() -> dict:
    """梦境归档时间线，按创建时间倒序。"""
    items = _read_dreams()
    items.sort(key=lambda d: str(d.get('created_at', '')), reverse=True)
    return {'items': items, 'count': len(items)}


# 固定路径先于任何可能的参数路径定义
@router.get('/dreams/schedule')
def dream_schedule() -> dict:
    """梦境调度状态：如实返回，当前版本无后台调度任务。"""
    return {
        'enabled': False,
        'mode': 'manual',
        'note': '当前版本无后台调度任务；可手动调用 /dreams/archive-now 触发整理',
    }


@router.post('/dreams/archive-now')
def dream_archive_now() -> dict:
    """模拟「每夜整理」：汇总近期会话生成一条梦境归档。

    无真实会话数据时使用示例会话（source=sample，诚实标注模拟边界）。
    同一夜晚重复执行会覆盖旧条目，保证每夜至多一条归档。
    """
    sessions = [_normalize_session(s) for s in _read_sessions_raw()]
    source = 'sessions'
    if not sessions:
        sessions = [_normalize_session(s) for s in _SAMPLE_SESSIONS]
        source = 'sample'

    # 取最近 10 个会话参与整理
    recent = sorted(
        sessions, key=lambda s: str(s.get('updated_at', '')), reverse=True
    )[:10]

    topics: list[str] = []
    for s in recent:
        title = str(s.get('title', '')).strip()
        if title and title not in topics:
            topics.append(title)
    topics = topics[:6]

    total_turns = sum(int(s.get('turns', 0)) for s in recent)
    capsule_refs = [str(s.get('id', '')) for s in recent if s.get('id')]

    night = _today()
    topics_str = '、'.join(topics) if topics else '（无明确主题）'
    summary = (
        f'本夜整理近期会话 {len(recent)} 个，累计 {total_turns} 轮对话；'
        f'关键主题：{topics_str}。'
    )
    if source == 'sample':
        summary += '（当前无真实会话数据，本条基于示例会话生成）'

    entry = {
        'id': _short_id(f'dream-{night.replace("-", "")}'),
        'night': night,
        'summary': summary,
        'key_topics': topics,
        'capsule_refs': capsule_refs,
        'created_at': _now_iso(),
        'source': source,
    }

    def _apply(items: list[dict[str, Any]]) -> bool:
        for i, old in enumerate(items):
            if old.get('night') == night:
                items[i] = entry  # 每夜至多一条：覆盖同夜旧归档
                return True
        items.append(entry)
        return False

    replaced = _mutate_items(_dream_store, _apply)

    return {'ok': True, 'entry': entry, 'replaced': replaced, 'source': source}


# ---------------------------------------------------------------------------
# 常用语
# ---------------------------------------------------------------------------


def _read_phrases() -> list[dict[str, Any]]:
    items = _phrases_store.get('items', [])
    if not isinstance(items, list):
        return []
    return [p for p in items if isinstance(p, dict)]


def _sorted_phrases(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda p: (-int(p.get('usage_count', 0) or 0), str(p.get('created_at', ''))),
    )


class PhrasePost(BaseModel):
    text: str = Field(..., min_length=1)


@router.get('/phrases')
def list_phrases() -> dict:
    items = _sorted_phrases(_read_phrases())
    return {'items': items, 'count': len(items)}


@router.post('/phrases')
def create_phrase(body: PhrasePost) -> dict:
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail='常用语不能为空')
    if len(text) > MAX_PHRASE_CHARS:
        raise HTTPException(
            status_code=400, detail=f'常用语最多 {MAX_PHRASE_CHARS} 字'
        )
    _enforce_memory_policy(text)

    def _apply(items: list[dict[str, Any]]) -> dict[str, Any]:
        for p in items:
            if p.get('text') == text:
                return {'item': p, 'deduped': True}
        item = {
            'id': _short_id('ph'),
            'text': text,
            'usage_count': 0,
            'created_at': _now_iso(),
        }
        items.append(item)
        return {'item': item, 'deduped': False}

    outcome = _mutate_items(_phrases_store, _apply)
    if outcome['deduped']:
        return {'ok': True, 'item': outcome['item'], 'deduped': True}
    audit_safe('phrase_created', {'phrase_id': outcome['item']['id'], 'text': text})
    return {'ok': True, 'item': outcome['item']}


@router.delete('/phrases/{pid}')
def delete_phrase(pid: str) -> dict:
    def _apply(items: list[dict[str, Any]]) -> tuple[dict[str, Any], int]:
        for i, p in enumerate(items):
            if p.get('id') == pid:
                removed = items.pop(i)
                return removed, len(items)
        raise HTTPException(status_code=404, detail=f'常用语 {pid} 不存在')

    removed, count = _mutate_items(_phrases_store, _apply)
    return {'ok': True, 'removed': removed, 'count': count}


@router.post('/phrases/{pid}/use')
def use_phrase(pid: str) -> dict:
    def _apply(items: list[dict[str, Any]]) -> dict[str, Any]:
        for p in items:
            if p.get('id') == pid:
                p['usage_count'] = int(p.get('usage_count', 0) or 0) + 1
                return p
        raise HTTPException(status_code=404, detail=f'常用语 {pid} 不存在')

    item = _mutate_items(_phrases_store, _apply)
    return {'ok': True, 'item': item}


# ---------------------------------------------------------------------------
# 会话管理
# ---------------------------------------------------------------------------


@router.get('/sessions')
def list_sessions() -> dict[str, Any]:
    """会话列表。

    返回 ``sessions`` 数组；``source`` 与 ``note`` 诚实标注当前数据来自独立
    JsonStore('sessions')，未与真实 conversation_turns 表对接，避免文档/接口
    暗示存在不存在的会话数据源。
    """
    sessions = [_normalize_session(s) for s in _read_sessions_raw()]
    # pinned 优先 + updated_at 倒序：先按 updated_at 倒序，再稳定排序 pinned
    sessions.sort(key=lambda s: str(s.get('updated_at', '')), reverse=True)
    sessions.sort(key=lambda s: not s['pinned'])
    return {
        'sessions': sessions,
        'count': len(sessions),
        'source': "JsonStore('sessions')",
        'note': '当前会话数据为独立 JSON 存储，未对接真实 conversation_turns 表；空列表表示尚无记录。',
    }


def _find_session(items: list[dict[str, Any]], sid: str) -> dict[str, Any] | None:
    for s in items:
        if str(s.get('id', '')) == sid:
            return s
    return None


class SessionPut(BaseModel):
    # archived 为后补的可选字段（06-#6 对齐）：与 archive/unarchive 专用端点
    # 行为一致，避免前端 PUT {archived: false} 被静默丢弃造成假成功。
    title: str | None = None
    pinned: bool | None = None
    archived: bool | None = None
    auto_expand_refs: bool | None = None


@router.post('/sessions/{sid}/archive')
def archive_session(sid: str) -> dict:
    def _apply(items: list[dict[str, Any]]) -> dict[str, Any]:
        target = _find_session(items, sid)
        if target is None:
            raise HTTPException(status_code=404, detail=f'会话 {sid} 不存在')
        target['archived'] = True
        return target

    target = _mutate_items(_sessions_store, _apply)
    return {'ok': True, 'session': _normalize_session(target)}


@router.post('/sessions/{sid}/unarchive')
def unarchive_session(sid: str) -> dict:
    def _apply(items: list[dict[str, Any]]) -> dict[str, Any]:
        target = _find_session(items, sid)
        if target is None:
            raise HTTPException(status_code=404, detail=f'会话 {sid} 不存在')
        target['archived'] = False
        return target

    target = _mutate_items(_sessions_store, _apply)
    return {'ok': True, 'session': _normalize_session(target)}


@router.put('/sessions/{sid}')
def update_session(sid: str, body: SessionPut) -> dict:
    def _apply(items: list[dict[str, Any]]) -> dict[str, Any]:
        target = _find_session(items, sid)
        if target is None:
            raise HTTPException(status_code=404, detail=f'会话 {sid} 不存在')
        changed = False
        if body.title is not None:
            title = body.title.strip()
            if not title:
                raise HTTPException(status_code=400, detail='会话标题不能为空')
            target['title'] = title
            changed = True
        if body.pinned is not None:
            target['pinned'] = bool(body.pinned)
            changed = True
        if body.archived is not None:
            target['archived'] = bool(body.archived)
            changed = True
        if body.auto_expand_refs is not None:
            target['auto_expand_refs'] = bool(body.auto_expand_refs)
            changed = True
        if changed:
            target['updated_at'] = _now_iso()
        return target

    target = _mutate_items(_sessions_store, _apply)
    return {'ok': True, 'session': _normalize_session(target)}
