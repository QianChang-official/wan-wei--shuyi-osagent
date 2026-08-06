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
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

import asyncio
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

from ..audit.service import list_logs, record
from ..db import get_conn

router = APIRouter(prefix='/mobile', tags=['mobile-remote'])

# ---------------------------------------------------------------------------
# 实时事件流（SSE）
# ---------------------------------------------------------------------------

# 事件总线：最近 N 条事件环形缓冲 + 订阅者集合（asyncio 版本）
_EVENT_BUFFER: list[dict] = []
_EVENT_BUFFER_MAX = 200
_SUBSCRIBERS: set[asyncio.Event] = set()
_BUS_LOCK = asyncio.Lock()


async def _append_event(event: dict) -> None:
    """把事件写进环形缓冲并唤醒所有 SSE 订阅者。"""
    event.setdefault('ts', time.time())
    async with _BUS_LOCK:
        _EVENT_BUFFER.append(event)
        if len(_EVENT_BUFFER) > _EVENT_BUFFER_MAX:
            _EVENT_BUFFER[:] = _EVENT_BUFFER[-_EVENT_BUFFER_MAX:]
        for ev in list(_SUBSCRIBERS):
            ev.set()


@router.get('/events')
async def realtime_events(
    since: float = Query(0, description='只推送 ts > since 的事件（秒时间戳）'),
    max_idle: float = Query(
        0,
        ge=0,
        le=300,
        description='空闲多少秒后主动收流（0=永久保持长连接；测试或短轮询客户端可设小值）',
    ),
):
    """SSE 实时事件流。

    用法（手机端 EventSource / Taro.request enableChunked）：
        curl -N -H 'X-API-Key: <key>' http://host:8080/realtime/events

    事件格式：
        event: <type>
        data: {"ts": ..., "event_type": "workflow_run", "payload": {...}}
    """
    async def gen():
        # 先补发 since 之后的缓冲事件（断线重连不丢）
        async with _BUS_LOCK:
            backlog = [e for e in _EVENT_BUFFER if e['ts'] > since]
        for e in backlog:
            yield f"event: {e.get('event_type', 'event')}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n"
        # 长连接等待新事件
        sub = asyncio.Event()
        async with _BUS_LOCK:
            _SUBSCRIBERS.add(sub)
        idle = 0.0
        try:
            while True:
                sub.clear()
                try:
                    await asyncio.wait_for(sub.wait(), timeout=25)
                    async with _BUS_LOCK:
                        latest = list(_EVENT_BUFFER)
                    for e in latest[-5:]:
                        yield f"event: {e.get('event_type', 'event')}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    idle += 25
                    # max_idle > 0 时（测试/短轮询客户端）空闲到点就正常收流，
                    # 避免调用方阻塞在永不结束的长连接上；默认 0 = 永久保持。
                    if max_idle and idle >= max_idle:
                        yield "event: stream_end\ndata: {\"reason\": \"idle_timeout\"}\n\n"
                        return
                    yield ": keepalive\n\n"  # 心跳，防代理断连
        finally:
            async with _BUS_LOCK:
                _SUBSCRIBERS.discard(sub)

    return StreamingResponse(
        gen(),
        media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@router.get('/tool-calls')
def recent_tool_calls(
    limit: int = Query(20, ge=1, le=100),
    since: Optional[float] = Query(None, description='只返回 ts > since 的记录'),
):
    """最近工具调用记录（轮询用，手机端可每 5s 拉一次）。"""
    # 从审计日志里筛 mcp_tool_call / tool_call 事件
    items = []
    for row in list_logs(limit=200):
        if row.get('event_type') in ('mcp_tool_call', 'tool_call'):
            ts = _ts_of(row)
            if since is not None and ts <= since:
                continue
            items.append(row)
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


def _ensure_upload_dir() -> Path:
    """惰性创建上传目录。

    导入期不要碰文件系统：只读根文件系统的加固容器里 mkdir 会抛
    OSError，导致 platform_api 自动发现把本模块记为失败模块，
    /health/ready 直接 not_ready（503）。改为首次真正上传时才建。
    """
    try:
        _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(503, f'上传目录不可写：{type(exc).__name__}') from exc
    return _UPLOAD_DIR


def _file_meta_table(conn):
    conn.execute(
        'CREATE TABLE IF NOT EXISTS mobile_files('
        ' file_id TEXT PRIMARY KEY,'
        ' filename TEXT,'
        ' size_bytes INTEGER,'
        ' content_type TEXT,'
        ' created_at TEXT)'
    )
    conn.commit()


@router.post('/upload')
async def upload_file(
    file: UploadFile = File(...),
    note: str = Query('', description='备注（可选）'),
):
    """上传文件到后端存储，AI 可通过 /files/{file_id}/content 读取。"""
    file_id = 'file_' + uuid.uuid4().hex[:12]
    data = await file.read()
    if len(data) > 50 * 1024 * 1024:
        raise HTTPException(413, '文件超过 50MB 限制')

    dest = _ensure_upload_dir() / file_id
    dest.write_bytes(data)

    conn = get_conn()
    _file_meta_table(conn)
    from ..utils.datetime_utils import utc_now_iso
    conn.execute(
        'INSERT INTO mobile_files VALUES (?,?,?,?,?)',
        (file_id, file.filename or 'unnamed', len(data), file.content_type or '', utc_now_iso()),
    )
    conn.commit()

    record('file_upload', {'file_id': file_id, 'filename': file.filename, 'size': len(data), 'note': note})
    await _append_event({'event_type': 'file_upload', 'file_id': file_id, 'filename': file.filename})

    return {
        'file_id': file_id,
        'filename': file.filename,
        'size_bytes': len(data),
        'content_type': file.content_type,
        'url': f'/files/{file_id}/content',
        'note': note,
    }


@router.get('/list')
def list_files(limit: int = Query(50, ge=1, le=200)):
    """已上传文件列表（元数据，不含内容）。"""
    conn = get_conn()
    _file_meta_table(conn)
    rows = conn.execute('SELECT * FROM mobile_files ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
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


def _file_path_from_db(file_id: str) -> Path:
    """从 DB 元数据取文件路径（白名单模式）：file_id 必须在 mobile_files 表里存在。

    路径完全由服务端生成（_UPLOAD_DIR / file_id），file_id 是上传时生成的
    file_<hex> 格式——不存在的 ID 直接 404，从根上杜绝路径穿越。
    """
    # 第一道：格式白名单——只接受上传时生成的 file_<12位小写hex>
    if not file_id or not _FILE_ID_RE.fullmatch(file_id):
        raise HTTPException(400, '非法文件 ID')

    # 第二道：DB 元数据白名单——把服务端存储的 file_id 取回来用于拼路径，
    # 请求里的字符串只作为查询参数，绝不参与路径构造（taint 在此断链）。
    conn = get_conn()
    _file_meta_table(conn)
    row = conn.execute('SELECT file_id FROM mobile_files WHERE file_id=?', (file_id,)).fetchone()
    if row is None:
        raise HTTPException(404, '文件不存在')
    stored_id = str(row[0])

    # 第三道：对服务端取回的值再确认形态，并做前缀归属校验
    if not _FILE_ID_RE.fullmatch(stored_id):
        raise HTTPException(400, '非法文件 ID')
    base = _UPLOAD_DIR.resolve()
    dest = (base / stored_id).resolve()
    if dest.parent != base:
        raise HTTPException(400, '非法文件 ID')
    return dest


@router.get('/{file_id}/content')
def read_file_content(file_id: str):
    """读取文件内容（AI 读取入口；文本直接返回，二进制返回 base64）。"""
    dest = _file_path_from_db(file_id)
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
async def delete_file(file_id: str):
    """删除文件。"""
    dest = _file_path_from_db(file_id)
    if not dest.exists():
        raise HTTPException(404, '文件不存在')
    dest.unlink()
    conn = get_conn()
    _file_meta_table(conn)
    conn.execute('DELETE FROM mobile_files WHERE file_id=?', (file_id,))
    conn.commit()
    record('file_delete', {'file_id': file_id})
    await _append_event({'event_type': 'file_delete', 'file_id': file_id})
    return {'deleted': file_id}


