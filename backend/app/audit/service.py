from __future__ import annotations

import contextvars
import json
import secrets
import sqlite3
from contextlib import contextmanager
from typing import Iterator

from ..db import get_conn
from ..security.redaction import redact_audit_payload
from ..utils.datetime_utils import utc_now_iso


_AUDIT_OWNER: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "wanwei_audit_owner", default=None
)


@contextmanager
def audit_owner_context(owner_id: str | None) -> Iterator[None]:
    """Bind an owner to audit writes and reads for the current request/task."""
    token = _AUDIT_OWNER.set(owner_id)
    try:
        yield
    finally:
        _AUDIT_OWNER.reset(token)


def current_audit_owner() -> str | None:
    return _AUDIT_OWNER.get()


def _configured_owner() -> str | None:
    try:
        from ..security.auth import actor_id_from_api_key, get_api_key

        return actor_id_from_api_key(get_api_key())
    except Exception:
        return None


def _effective_owner(owner_id: str | None) -> str | None:
    if owner_id is not None:
        return owner_id
    return current_audit_owner() or _configured_owner()


def _read_owner(owner_id: str | None) -> str | None:
    if owner_id is not None:
        return owner_id
    return current_audit_owner() or _configured_owner()


def _legacy_owner_allowed(owner_id: str | None) -> bool:
    """Expose ownerless historical rows only to the configured actor."""
    return owner_id is not None and owner_id == _configured_owner()


def _ensure_audit_schema(conn) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS audit_logs("
        "audit_id TEXT PRIMARY KEY, event_type TEXT, payload TEXT, "
        "created_at TEXT, owner_id TEXT)"
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info(audit_logs)")}
    if "owner_id" not in columns:
        conn.execute("ALTER TABLE audit_logs ADD COLUMN owner_id TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_logs_owner_created "
        "ON audit_logs(owner_id, created_at)"
    )


def _ensure_audit_table(conn) -> None:
    _ensure_audit_schema(conn)
    conn.commit()


def record_in_transaction(
    conn,
    event_type: str,
    payload: dict,
    *,
    owner_id: str | None = None,
) -> str:
    """Insert an audit row without committing the caller's transaction."""
    _ensure_audit_schema(conn)
    audit_id = "audit_" + secrets.token_hex(6)
    safe_payload = redact_audit_payload(payload)
    conn.execute(
        "INSERT INTO audit_logs(audit_id,event_type,payload,created_at,owner_id) "
        "VALUES (?,?,?,?,?)",
        (
            audit_id,
            event_type,
            json.dumps(safe_payload, ensure_ascii=False),
            utc_now_iso(),
            _effective_owner(owner_id),
        ),
    )
    return audit_id


def record(event_type: str, payload: dict, *, owner_id: str | None = None) -> str:
    """Record an audit event with sensitive data redaction and owner scope."""
    conn = get_conn()
    _ensure_audit_table(conn)
    audit_id = record_in_transaction(conn, event_type, payload, owner_id=owner_id)
    conn.commit()
    return audit_id


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_logs(
    limit: int = 50,
    trace_id: str | None = None,
    *,
    owner_id: str | None = None,
) -> list[dict]:
    capped = max(1, min(limit, 200))
    conn = get_conn()
    _ensure_audit_table(conn)
    read_owner = _read_owner(owner_id)
    clauses: list[str] = []
    params: list[object] = []
    if read_owner is not None:
        if _legacy_owner_allowed(read_owner):
            clauses.append("(owner_id=? OR owner_id IS NULL OR owner_id='')")
        else:
            clauses.append("owner_id=?")
        params.append(read_owner)
    if trace_id:
        try:
            clauses.append("json_extract(payload,'$.trace_id')=?")
            params.append(trace_id)
            query = (
                "SELECT * FROM audit_logs WHERE "
                + " AND ".join(clauses)
                + " ORDER BY created_at DESC LIMIT ?"
            )
            rows = conn.execute(query, [*params, capped]).fetchall()
        except sqlite3.OperationalError:
            # JSON1 不可用时保留精确 trace_id 的兼容查询。
            clauses = [c for c in clauses if not c.startswith("json_extract")]
            params = params[:1] if read_owner is not None else []
            clauses.append("payload LIKE ? ESCAPE '\\'")
            params.append(f'%"trace_id": "{_escape_like(trace_id)}"%')
            query = (
                "SELECT * FROM audit_logs WHERE "
                + " AND ".join(clauses)
                + " ORDER BY created_at DESC LIMIT ?"
            )
            rows = conn.execute(query, [*params, capped]).fetchall()
    else:
        if clauses:
            query = (
                "SELECT * FROM audit_logs WHERE "
                + " AND ".join(clauses)
                + " ORDER BY created_at DESC LIMIT ?"
            )
            rows = conn.execute(query, [*params, capped]).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT ?", (capped,)
            ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item.pop("owner_id", None)
        items.append(item)
    return items
