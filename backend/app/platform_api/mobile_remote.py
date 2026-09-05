"""手机端远程控制补充 API：实时事件流 / 工具调用实时查询 / 文件上传。

为宛委枢忆手机端 APP（meoo-app）提供 orca/mobile 风格的远程控制能力：

实际挂载前缀：/platform/mobile（platform_api 自动发现，app_runtime 统一 prefix='/platform'）
1. GET  /platform/mobile/events              SSE 实时事件流（健康/任务/工具调用/审计）
2. GET  /platform/mobile/tool-calls          最近工具调用（轮询，支持 since）
3. POST /platform/mobile/upload              上传文件到后端存储（AI 可读取）
4. GET  /platform/mobile/list                已上传文件列表
5. GET  /platform/mobile/{file_id}/content   读取文件内容（AI 视角）
6. DELETE /platform/mobile/{file_id}         删除文件
"""
import json
import logging
import re
import sqlite3
import threading
import time
import uuid
from itertools import count
from pathlib import Path
from typing import Optional

import asyncio
from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse

from ..audit.service import list_logs, record
from ..db import get_conn
from ..security.auth import _lan_session_identity
from ..security.input_limits import MOBILE_UPLOAD_MAX_FILE_BYTES
from ..soul.ownership import actor_id_for_request, configured_actor_id

router = APIRouter(prefix='/mobile', tags=['mobile-remote'])

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 实时事件流（SSE）
# ---------------------------------------------------------------------------

# 事件总线：最近 N 条事件环形缓冲 + 订阅者集合（asyncio 版本）
_EVENT_BUFFER: list[dict] = []
_EVENT_BUFFER_MAX = 200
_SUBSCRIBERS: set[asyncio.Event] = set()
_SUBSCRIBER_OWNERS: dict[asyncio.Event, str] = {}
_SUBSCRIBERS_MAX = 100
_BUS_LOCK = asyncio.Lock()
_EVENT_SEQUENCE = count(1)
_SESSION_CHECK_INTERVAL = 1.0


async def _append_event(event: dict) -> None:
    """把事件写进环形缓冲并唤醒所有 SSE 订阅者。"""
    event = dict(event)
    event.setdefault('ts', time.time())
    async with _BUS_LOCK:
        event['_sequence'] = next(_EVENT_SEQUENCE)
        _EVENT_BUFFER.append(event)
        if len(_EVENT_BUFFER) > _EVENT_BUFFER_MAX:
            _EVENT_BUFFER[:] = _EVENT_BUFFER[-_EVENT_BUFFER_MAX:]
        event_owner = event.get('owner_id')
        for ev in list(_SUBSCRIBERS):
            subscriber_owner = _SUBSCRIBER_OWNERS.get(ev)
            if (
                (event_owner is None and subscriber_owner == configured_actor_id())
                or (event_owner is not None and str(event_owner) == subscriber_owner)
            ):
                ev.set()


def _event_visible(event: dict, owner_id: str) -> bool:
    event_owner = event.get('owner_id')
    if event_owner is None:
        return owner_id == configured_actor_id()
    return str(event_owner) == owner_id


def _public_event(event: dict) -> dict:
    public = dict(event)
    public.pop('owner_id', None)
    public.pop('_sequence', None)
    return public


def _public_audit_row(row: dict) -> dict:
    public = dict(row)
    public.pop('owner_id', None)
    return public


@router.get('/events')
async def realtime_events(
    request: Request = None,
    since: float = Query(0, description='只推送 ts > since 的事件（秒时间戳）'),
    max_idle: float = Query(
        300,
        ge=0,
        le=300,
        description='空闲多少秒后主动收流（默认 300 秒）',
    ),
):
    """SSE 实时事件流。

    用法（手机端 EventSource / Taro.request enableChunked）：
        curl -N -H 'X-API-Key: <key>' http://host:8080/realtime/events

    事件格式：
        event: <type>
        data: {"ts": ..., "event_type": "workflow_run", "payload": {...}}
    """
    owner_id = actor_id_for_request(request)
    state = getattr(request, 'state', None)
    credential = (
        request.headers.get('x-api-key', '')
        if getattr(state, 'is_lan_session', False) else None
    )
    sub = asyncio.Event()
    async with _BUS_LOCK:
        if len(_SUBSCRIBERS) >= _SUBSCRIBERS_MAX:
            raise HTTPException(429, 'SSE subscriber limit reached')

    async def session_valid() -> bool:
        if credential is None:
            return True
        try:
            return await asyncio.to_thread(_lan_session_identity, credential) == owner_id
        except sqlite3.Error:
            # A failed registry lookup must not leave a privileged stream open.
            return False

    async def gen():
        cursor = 0
        idle = 0.0
        heartbeat = 0.0
        registered = False
        try:
            # Registration belongs to the generator so an unstarted response
            # cannot reserve a subscriber slot indefinitely.
            async with _BUS_LOCK:
                if len(_SUBSCRIBERS) >= _SUBSCRIBERS_MAX:
                    yield_limit = True
                else:
                    yield_limit = False
                    _SUBSCRIBERS.add(sub)
                    _SUBSCRIBER_OWNERS[sub] = owner_id
                    registered = True
            if yield_limit:
                yield 'event: stream_end\ndata: {"reason": "subscriber_limit"}\n\n'
                return
            while True:
                if not await session_valid():
                    yield 'event: stream_end\ndata: {"reason": "session_expired_or_revoked"}\n\n'
                    return
                # Snapshot and reset the wake-up under the producer's lock.
                # Events arriving while frames are yielded remain in the next snapshot.
                async with _BUS_LOCK:
                    sub.clear()
                    latest = [e for e in _EVENT_BUFFER if e['_sequence'] > cursor]
                    if latest:
                        cursor = latest[-1]['_sequence']
                    pending = [
                        e for e in latest
                        if e['ts'] > since and _event_visible(e, owner_id)
                    ]
                for e in pending:
                    if not await session_valid():
                        yield 'event: stream_end\ndata: {"reason": "session_expired_or_revoked"}\n\n'
                        return
                    yield f"event: {e.get('event_type', 'event')}\ndata: {json.dumps(_public_event(e), ensure_ascii=False)}\n\n"
                if pending:
                    idle = heartbeat = 0.0
                    continue
                timeout = min(25.0, _SESSION_CHECK_INTERVAL) if credential is not None else 25.0
                if max_idle:
                    timeout = min(timeout, max_idle - idle)
                try:
                    await asyncio.wait_for(sub.wait(), timeout=timeout)
                except asyncio.TimeoutError:
                    idle += timeout
                    heartbeat += timeout
                    if not await session_valid():
                        yield 'event: stream_end\ndata: {"reason": "session_expired_or_revoked"}\n\n'
                        return
                    if max_idle and idle >= max_idle:
                        yield 'event: stream_end\ndata: {"reason": "idle_timeout"}\n\n'
                        return
                    if heartbeat >= 25:
                        heartbeat = 0.0
                        yield ': keepalive\n\n'
        finally:
            if registered:
                async with _BUS_LOCK:
                    _SUBSCRIBERS.discard(sub)
                    _SUBSCRIBER_OWNERS.pop(sub, None)

    return StreamingResponse(
        gen(),
        media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@router.get('/tool-calls')
def recent_tool_calls(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    since: Optional[float] = Query(None, description='只返回 ts > since 的记录'),
):
    """最近工具调用记录（轮询用，手机端可每 5s 拉一次）。"""
    # 从审计日志里筛 mcp_tool_call / tool_call 事件
    items = []
    for row in list_logs(limit=200, owner_id=actor_id_for_request(request)):
        if row.get('event_type') in ('mcp_tool_call', 'tool_call'):
            ts = _ts_of(row)
            if since is not None and ts <= since:
                continue
            items.append(_public_audit_row(row))
    return {'items': items[:limit]}


def _ts_of(row: dict) -> float:
    """从审计行里尽力解析时间戳（created_at 是 ISO 字符串）。"""
    created = row.get('created_at', '')
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
        return dt.timestamp()
    except Exception:
        return time.time()


# ---------------------------------------------------------------------------
# 文件上传 / 列表 / 读取（AI 可读取）
# ---------------------------------------------------------------------------

_UPLOAD_DIR = Path(__file__).resolve().parent.parent / 'uploads'
# 合法 file_id 形态：上传时由服务端生成的 file_<12位小写hex>
_FILE_ID_RE = re.compile(r'^file_[0-9a-f]{12}$')
MAX_FILES = 1000
MAX_TOTAL_BYTES = 1024 * 1024 * 1024


def _ensure_upload_dir() -> Path:
    """惰性创建上传目录。

    导入期不要碰文件系统：只读根文件系统的加固容器里 mkdir 会抛
    OSError，导致 platform_api 自动发现把本模块记为失败模块，
    /health/ready 直接 not_ready（503）。改为首次真正上传时才建。
    """
    try:
        _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise HTTPException(503, 'upload directory unavailable') from None
    return _UPLOAD_DIR


def _file_meta_table(conn):
    conn.execute(
        'CREATE TABLE IF NOT EXISTS mobile_files('
        ' file_id TEXT PRIMARY KEY,'
        ' filename TEXT,'
        ' size_bytes INTEGER,'
        ' content_type TEXT,'
        ' created_at TEXT,'
        ' owner_id TEXT)'
    )
    columns = {row[1] for row in conn.execute('PRAGMA table_info(mobile_files)')}
    if 'owner_id' not in columns:
        # Legacy rows remain ownerless until the configured actor accesses them.
        conn.execute('ALTER TABLE mobile_files ADD COLUMN owner_id TEXT')
    conn.execute(
        'CREATE INDEX IF NOT EXISTS idx_mobile_files_owner_created '
        'ON mobile_files(owner_id, created_at)'
    )
    conn.commit()


def _legacy_owner_allowed(owner_id: str) -> bool:
    return owner_id == configured_actor_id()


def _file_visible(row, owner_id: str) -> bool:
    owner = row['owner_id']
    if owner:
        return str(owner) == owner_id
    return _legacy_owner_allowed(owner_id)


def _claim_legacy_file(conn, row, owner_id: str) -> None:
    if row['owner_id'] or not _legacy_owner_allowed(owner_id):
        return
    conn.execute(
        "UPDATE mobile_files SET owner_id=? WHERE file_id=? AND (owner_id IS NULL OR owner_id='')",
        (owner_id, row['file_id']),
    )
    conn.commit()


@router.post('/upload')
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    note: str = Query('', description='备注（可选）'),
):
    """上传文件到后端存储，AI 可通过 canonical content URL 读取。"""
    owner_id = actor_id_for_request(request)
    file_id = 'file_' + uuid.uuid4().hex[:12]
    MAX_BYTES = MOBILE_UPLOAD_MAX_FILE_BYTES

    # 预检：优先用 file.size，回退 Content-Length 头；超限直接 413 不落盘
    declared = getattr(file, 'size', None) or 0
    if declared <= 0:
        try:
            declared = int(file.headers.get('content-length', 0))
        except (ValueError, TypeError):
            declared = 0
    if declared > MAX_BYTES:
        raise HTTPException(413, '文件超过 50MB 限制')

    dest = _ensure_upload_dir() / file_id
    total = 0
    CHUNK = 256 * 1024  # 256KB chunks

    with dest.open('wb') as fh:
        while True:
            chunk = await file.read(CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_BYTES:
                dest.unlink(missing_ok=True)
                raise HTTPException(413, '文件超过 50MB 限制')
            fh.write(chunk)

    conn = get_conn()
    _file_meta_table(conn)
    quota_clause = "owner_id=?"
    quota_params = [owner_id]
    if _legacy_owner_allowed(owner_id):
        quota_clause += " OR owner_id IS NULL OR owner_id=''"
    quota = conn.execute(
        f'SELECT COUNT(*), COALESCE(SUM(size_bytes),0) FROM mobile_files WHERE {quota_clause}',
        quota_params,
    ).fetchone()
    if quota[0] >= MAX_FILES or quota[1] + total > MAX_TOTAL_BYTES:
        dest.unlink(missing_ok=True)
        raise HTTPException(413, 'upload quota exceeded')
    from ..utils.datetime_utils import utc_now_iso
    conn.execute(
        'INSERT INTO mobile_files(file_id,filename,size_bytes,content_type,created_at,owner_id) '
        'VALUES (?,?,?,?,?,?)',
        (file_id, file.filename or 'unnamed', total, file.content_type or '', utc_now_iso(), owner_id),
    )
    conn.commit()

    record(
        'file_upload',
        {'file_id': file_id, 'filename': file.filename, 'size': total, 'note': note},
        owner_id=owner_id,
    )
    await _append_event({
        'event_type': 'file_upload',
        'file_id': file_id,
        'filename': file.filename,
        'owner_id': owner_id,
    })

    return {
        'file_id': file_id,
        'filename': file.filename,
        'size_bytes': total,
        'content_type': file.content_type,
        'url': f'/platform/mobile/{file_id}/content',
        'note': note,
    }


@router.get('/list')
def list_files(request: Request, limit: int = Query(50, ge=1, le=200)):
    """已上传文件列表（元数据，不含内容）。"""
    owner_id = actor_id_for_request(request)
    conn = get_conn()
    _file_meta_table(conn)
    legacy_clause = " OR owner_id IS NULL OR owner_id=''" if _legacy_owner_allowed(owner_id) else ''
    rows = conn.execute(
        'SELECT file_id,filename,size_bytes,content_type,created_at,owner_id '
        f'FROM mobile_files WHERE owner_id=?{legacy_clause} '
        'ORDER BY created_at DESC LIMIT ?',
        (owner_id, limit),
    ).fetchall()
    for row in rows:
        _claim_legacy_file(conn, row, owner_id)
    return {
        'items': [
            {
                'file_id': r[0],
                'filename': r[1],
                'size_bytes': r[2],
                'content_type': r[3],
                'created_at': r[4],
            }
            for r in rows
        ]
    }


def _file_path_from_db(file_id: str, owner_id: str) -> Path:
    """从 DB 元数据取当前 actor 可见的文件路径（白名单模式）。

    路径完全由服务端生成（_UPLOAD_DIR / file_id），file_id 是上传时生成的
    file_<hex> 格式——不存在或不属于当前 actor 的 ID 直接 404。
    """
    # 第一道：格式白名单——只接受上传时生成的 file_<12位小写hex>
    if not file_id or not _FILE_ID_RE.fullmatch(file_id):
        raise HTTPException(400, '非法文件 ID')

    # 第二道：DB 元数据白名单——把服务端存储的 file_id 取回来用于拼路径，
    # 请求里的字符串只作为查询参数，绝不参与路径构造（taint 在此断链）。
    conn = get_conn()
    _file_meta_table(conn)
    row = conn.execute(
        'SELECT file_id, owner_id FROM mobile_files WHERE file_id=?', (file_id,)
    ).fetchone()
    if row is None or not _file_visible(row, owner_id):
        raise HTTPException(404, '文件不存在')
    _claim_legacy_file(conn, row, owner_id)
    stored_id = str(row['file_id'])

    # 第三道：对服务端取回的值再确认形态，并做前缀归属校验
    if not _FILE_ID_RE.fullmatch(stored_id):
        raise HTTPException(400, '非法文件 ID')
    base = _UPLOAD_DIR.resolve()
    dest = (base / stored_id).resolve()
    if dest.parent != base:
        raise HTTPException(400, '非法文件 ID')
    return dest


@router.get('/{file_id}/content')
def read_file_content(file_id: str, request: Request):
    """读取文件内容（AI 读取入口；文本直接返回，二进制返回 base64）。"""
    dest = _file_path_from_db(file_id, actor_id_for_request(request))
    if not dest.exists():
        raise HTTPException(404, '文件不存在')
    data = dest.read_bytes()
    try:
        text = data.decode('utf-8')
        return {'file_id': file_id, 'content': text, 'encoding': 'utf-8'}
    except UnicodeDecodeError:
        import base64
        return {
            'file_id': file_id,
            'content_b64': base64.b64encode(data).decode(),
            'encoding': 'base64',
            'size_bytes': len(data),
        }


@router.delete('/{file_id}')
async def delete_file(file_id: str, request: Request):
    """删除文件。

    删除语义是"逻辑删除"：无论物理文件是否删除成功，元数据记录都会移除，
    审计与 SSE 事件照常写入。物理删除失败（如部分环境禁用了回收站/安全删除
    通道）只记录警告，不再让整个接口退化为 500 —— 否则客户端会误以为删除
    从未发生，元数据与磁盘事实将更难收敛。
    """
    owner_id = actor_id_for_request(request)
    dest = _file_path_from_db(file_id, owner_id)
    try:
        dest.unlink(missing_ok=True)
    except OSError as exc:
        # 仓库既有模式（如 memory_runtime/capsule_store.py）：物理清理失败
        # 不可让成功的业务操作失败 —— 记录并继续，由运维据此补清理。
        logger.warning(
            'mobile file physical delete failed for %s (logical delete proceeds): %s',
            dest,
            exc,
        )
    conn = get_conn()
    _file_meta_table(conn)
    conn.execute(
        'DELETE FROM mobile_files WHERE file_id=? AND owner_id=?', (file_id, owner_id)
    )
    conn.commit()
    record('file_delete', {'file_id': file_id}, owner_id=owner_id)
    await _append_event({'event_type': 'file_delete', 'file_id': file_id, 'owner_id': owner_id})
    return {'deleted': file_id}
