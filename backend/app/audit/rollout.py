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

"""执行轨迹（rollout journal）—— 哈希链 append-only。

借鉴 openai/codex（Apache-2.0, Copyright 2025 OpenAI）的 rollout 持久化
与 resume 思路：把「谁在什么时候用什么能力做了什么」从散落的日志文件
变成一条**可校验、不可事后改写**的链，自研实现，未复制其源码。

与既有 ``audit_logs`` / ``memory_ledger`` 的分工：

- ``audit_logs``：平铺事件，供面板检索（无完整性保证）
- ``memory_ledger``：记忆的生命周期账本（append-only + 触发器强制）
- **本模块**：Agent/感知**执行动作**的结构化轨迹，带哈希链

每条 entry 的 ``entry_sha256 = H(prev_sha256 ‖ thread_id ‖ turn_index ‖
item_type ‖ item_json ‖ created_at)``，篡改任一条即导致其后整条链的
校验失败，``verify_chain`` 会精确指出第一处断裂位置——与项目「怎么证明
它删干净了」同一套方法论：不给信任，给证据。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..db import get_conn
from ..memory_runtime.capsule_store import now

TABLE = "agent_rollouts"
GENESIS_HASH = "0" * 64

#: 单条 item 的 JSON 上限（防止轨迹表被大 payload 撑爆）。
MAX_ITEM_BYTES = 64 * 1024


class RolloutError(ValueError):
    """轨迹写入/校验失败（超限或链断裂）。"""


def _entry_hash(
    prev_sha256: str, thread_id: str, turn_index: int,
    item_type: str, item_json: str, created_at: str,
) -> str:
    digest = hashlib.sha256()
    for part in (
        prev_sha256, thread_id, str(turn_index), item_type, item_json, created_at,
    ):
        digest.update(part.encode("utf-8"))
        digest.update(b"\x1f")  # 分隔符，避免拼接歧义
    return digest.hexdigest()


def init_schema(*, conn=None) -> None:
    target = conn if conn is not None else get_conn()
    target.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE}(
            entry_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id   TEXT NOT NULL,
            turn_index  INTEGER NOT NULL,
            item_type   TEXT NOT NULL,
            item        TEXT NOT NULL,
            prev_sha256 TEXT NOT NULL,
            entry_sha256 TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            owner_id    TEXT
        )
        """
    )
    target.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{TABLE}_thread ON {TABLE}(thread_id, entry_id)"
    )
    if conn is None:
        target.commit()


def append_rollout(
    *,
    thread_id: str,
    item_type: str,
    item: dict[str, Any],
    turn_index: int | None = None,
    owner_id: str | None = None,
    conn=None,
) -> dict[str, Any]:
    """追加一条轨迹。``turn_index`` 省略时接续该线程的下一轮。

    事务规则与 local_embedding 一致：传入 ``conn`` 时不 commit，提交权
    归调用方事务。
    """
    if not thread_id or not item_type:
        raise RolloutError("rollout needs thread_id and item_type")
    item_json = json.dumps(item, ensure_ascii=False, sort_keys=True)
    if len(item_json.encode("utf-8")) > MAX_ITEM_BYTES:
        raise RolloutError(f"rollout item exceeds {MAX_ITEM_BYTES} bytes")
    target = conn if conn is not None else get_conn()
    init_schema(conn=target)

    row = target.execute(
        f"SELECT entry_id, turn_index, entry_sha256 FROM {TABLE} "
        f"WHERE thread_id=? ORDER BY entry_id DESC LIMIT 1",
        (thread_id,),
    ).fetchone()
    prev_sha256 = row["entry_sha256"] if row else GENESIS_HASH
    if turn_index is None:
        turn_index = (row["turn_index"] + 1) if row else 0
    created_at = now()
    entry_sha256 = _entry_hash(
        prev_sha256, thread_id, turn_index, item_type, item_json, created_at
    )
    target.execute(
        f"INSERT INTO {TABLE}(thread_id, turn_index, item_type, item, "
        f"prev_sha256, entry_sha256, created_at, owner_id) VALUES(?,?,?,?,?,?,?,?)",
        (thread_id, turn_index, item_type, item_json, prev_sha256,
         entry_sha256, created_at, owner_id),
    )
    if conn is None:
        target.commit()
    return {
        "entry_id": target.execute("SELECT last_insert_rowid()").fetchone()[0],
        "thread_id": thread_id,
        "turn_index": turn_index,
        "item_type": item_type,
        "prev_sha256": prev_sha256,
        "entry_sha256": entry_sha256,
        "created_at": created_at,
    }


def list_rollout(
    thread_id: str,
    *,
    owner_id: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """按 entry_id 升序返回轨迹条目（含哈希链字段）。"""
    init_schema()
    clauses = ["thread_id=?"]
    params: list[Any] = [thread_id]
    if owner_id is not None:
        clauses.append("owner_id=?")
        params.append(owner_id)
    params.append(limit)
    rows = get_conn().execute(
        f"SELECT * FROM {TABLE} WHERE {' AND '.join(clauses)} ORDER BY entry_id LIMIT ?",
        params,
    ).fetchall()
    return [
        {**dict(row), "item": json.loads(row["item"])} for row in rows
    ]


def verify_chain(
    thread_id: str, *, owner_id: str | None = None
) -> dict[str, Any]:
    """逐条重算哈希链，返回是否完整与第一处断裂位置。"""
    entries = list_rollout(thread_id, owner_id=owner_id, limit=100000)
    prev = GENESIS_HASH
    for index, entry in enumerate(entries):
        item_json = json.dumps(entry["item"], ensure_ascii=False, sort_keys=True)
        expected = _entry_hash(
            prev, entry["thread_id"], entry["turn_index"],
            entry["item_type"], item_json, entry["created_at"],
        )
        if entry["prev_sha256"] != prev or entry["entry_sha256"] != expected:
            return {
                "thread_id": thread_id,
                "complete": False,
                "checked": index,
                "broken_at": entry["entry_id"],
                "reason": "hash_mismatch" if entry["entry_sha256"] != expected
                else "broken_link",
            }
        prev = entry["entry_sha256"]
    return {
        "thread_id": thread_id,
        "complete": True,
        "checked": len(entries),
        "broken_at": None,
        "head_sha256": prev,
    }


def resume_point(
    thread_id: str, *, owner_id: str | None = None
) -> dict[str, Any] | None:
    """Codex 式 resume：返回最后一轮的条目，供续跑时重建上下文。"""
    entries = list_rollout(thread_id, owner_id=owner_id)
    if not entries:
        return None
    last_turn = entries[-1]["turn_index"]
    return {
        "thread_id": thread_id,
        "turn_index": last_turn,
        "entries": [e for e in entries if e["turn_index"] == last_turn],
    }


__all__ = [
    "GENESIS_HASH",
    "TABLE",
    "RolloutError",
    "append_rollout",
    "init_schema",
    "list_rollout",
    "resume_point",
    "verify_chain",
]
