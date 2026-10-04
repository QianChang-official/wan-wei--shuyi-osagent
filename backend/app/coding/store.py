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

"""万枢编程框架 —— 会话与事件持久化。

复用 ``platform_api.store.JsonStore``（原子写 + 模块级共享锁 + 损坏隔离），
不新造存储层。两个命名空间：

- ``coding_sessions``：``{session_id: session_record}``；
- ``coding_events``：``{session_id: [event, ...]}``（追加式事件流，供前端时间线）。

事件流采用**单调递增 seq**，前端据此做增量拉取与去重。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from . import constants

# 注意：``JsonStore`` 惰性导入以断开与 ``platform_api`` 的导入环
# （详见 ``platform_api/coding.py`` 的模块说明）。JsonStore 的存储路径
# 按环境变量惰性解析，故单例缓存不会跨环境串味。
_sessions: Any = None
_events: Any = None


def _stores() -> tuple[Any, Any]:
    global _sessions, _events
    if _sessions is None:
        from ..platform_api.store import JsonStore  # 惰性导入，断开导入环

        _sessions = JsonStore('coding_sessions')
        _events = JsonStore('coding_events')
    return _sessions, _events


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec='seconds')


def new_id(prefix: str) -> str:
    return f'{prefix}_{uuid.uuid4().hex[:10]}'


# ---------------------------------------------------------------------------
# 会话
# ---------------------------------------------------------------------------


def create_session(record: dict[str, Any]) -> dict[str, Any]:
    def _mutate(data: dict) -> dict:
        data[record['id']] = record
        # 保留上限：按 updated_at 倒序裁剪，避免无限膨胀
        if len(data) > constants.SESSION_RETENTION:
            ordered = sorted(data.values(), key=lambda r: r.get('updated_at', ''), reverse=True)
            keep = {r['id']: r for r in ordered[:constants.SESSION_RETENTION]}
            data.clear()
            data.update(keep)
        return record

    sessions, _ = _stores()
    return sessions.mutate(_mutate)


def get_session(session_id: str) -> dict[str, Any] | None:
    sessions, _ = _stores()
    return sessions.get(session_id)


def update_session(session_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    def _mutate(data: dict) -> dict | None:
        record = data.get(session_id)
        if record is None:
            return None
        record.update(patch)
        record['updated_at'] = now()
        return record

    sessions, _ = _stores()
    return sessions.mutate(_mutate)


def list_sessions(*, owner_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    sessions, _ = _stores()
    records = list(sessions.all().values())
    if owner_id:
        records = [r for r in records if r.get('owner_id') == owner_id]
    records.sort(key=lambda r: r.get('updated_at', ''), reverse=True)
    return records[:limit]


def delete_session(session_id: str) -> bool:
    def _mutate(data: dict) -> bool:
        existed = session_id in data
        data.pop(session_id, None)
        return existed

    sessions, events = _stores()
    removed = sessions.mutate(_mutate)
    if removed:
        events.mutate(lambda d: d.pop(session_id, None))
    return bool(removed)


# ---------------------------------------------------------------------------
# 事件流
# ---------------------------------------------------------------------------


def append_event(session_id: str, event_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """追加一条事件，返回写入后的事件记录（含单调 seq）。"""
    def _mutate(data: dict) -> dict:
        bucket: list[dict[str, Any]] = data.get(session_id) or []
        seq = (bucket[-1]['seq'] + 1) if bucket else 1
        event = {
            'seq': seq,
            'id': new_id('ev'),
            'session_id': session_id,
            'type': event_type,
            'payload': payload or {},
            'at': now(),
        }
        bucket.append(event)
        if len(bucket) > constants.EVENT_RETENTION:
            bucket = bucket[-constants.EVENT_RETENTION:]
        data[session_id] = bucket
        return event

    _, events = _stores()
    return events.mutate(_mutate)


def list_events(session_id: str, *, after_seq: int = 0, limit: int = 500) -> list[dict[str, Any]]:
    _, events = _stores()
    bucket: list[dict[str, Any]] = events.get(session_id) or []
    return [e for e in bucket if e.get('seq', 0) > after_seq][:limit]


def clear_events(session_id: str) -> None:
    _, events = _stores()
    events.mutate(lambda d: d.pop(session_id, None))
