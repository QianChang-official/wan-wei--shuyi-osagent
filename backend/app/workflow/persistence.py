"""SQLite persistence for owner-scoped workflow runs."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from ..db import get_conn, transaction
from ..utils.datetime_utils import utc_now, utc_now_iso


DEFAULT_TTL_DAYS = 7


class WorkflowOwnershipError(PermissionError):
    """A run identifier is already owned by another principal."""


def _effective_owner(owner_id: str | None) -> str:
    if owner_id:
        return owner_id
    from ..soul.ownership import configured_actor_id

    return configured_actor_id()


def _legacy_owner_allowed(owner_id: str) -> bool:
    try:
        from ..soul.ownership import configured_actor_id

        return owner_id == configured_actor_id()
    except Exception:
        return False


def init_workflow_persistence() -> None:
    """Create or migrate the workflow run table and indexes."""
    conn = get_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_runs (
            run_id TEXT PRIMARY KEY,
            trace_id TEXT NOT NULL,
            scenario TEXT NOT NULL,
            user_goal TEXT NOT NULL,
            status TEXT NOT NULL,
            dry_run INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            run_data TEXT NOT NULL,
            version TEXT NOT NULL,
            total_stages INTEGER,
            completed_stages INTEGER,
            skipped_stages INTEGER,
            latency_ms INTEGER,
            risk_level TEXT,
            owner_id TEXT
        )
        """
    )
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(workflow_runs)")}
    if "owner_id" not in columns:
        conn.execute("ALTER TABLE workflow_runs ADD COLUMN owner_id TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_runs_owner_created "
        "ON workflow_runs(owner_id, created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_runs_owner_status "
        "ON workflow_runs(owner_id, status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_runs_owner_scenario "
        "ON workflow_runs(owner_id, scenario)"
    )
    conn.commit()


def _claim_legacy_rows(owner_id: str, run_id: str | None = None) -> None:
    """Atomically bind ownerless historical rows to the compatibility actor."""
    if not _legacy_owner_allowed(owner_id):
        return
    where = "(owner_id IS NULL OR owner_id='')"
    params: list[Any] = [owner_id]
    if run_id is not None:
        where += " AND run_id=?"
        params.append(run_id)
    with transaction(immediate=True) as conn:
        conn.execute(f"UPDATE workflow_runs SET owner_id=? WHERE {where}", params)


def _serialized_run(run_data: dict[str, Any]) -> str:
    public_data = dict(run_data)
    public_data.pop("owner_id", None)
    return json.dumps(public_data, ensure_ascii=False)


def save_run(
    run_id: str,
    run_data: dict[str, Any],
    owner_id: str | None = None,
) -> None:
    """Insert or update a run without allowing cross-owner ID replacement."""
    init_workflow_persistence()
    owner = _effective_owner(owner_id)
    summary = run_data.get("summary", {})
    can_claim_legacy = _legacy_owner_allowed(owner)
    values = (
        run_id,
        run_data.get("trace_id", ""),
        run_data.get("scenario", ""),
        run_data.get("user_goal", ""),
        run_data.get("status", "unknown"),
        1 if run_data.get("dry_run", True) else 0,
        run_data.get("created_at", utc_now_iso()),
        run_data.get("completed_at"),
        _serialized_run(run_data),
        run_data.get("version", ""),
        summary.get("total_stages", 0),
        summary.get("completed_stages", 0),
        summary.get("skipped_stages", 0),
        summary.get("latency_ms", 0),
        summary.get("risk_level", "unknown"),
        owner,
    )
    with transaction(immediate=True) as conn:
        existing = conn.execute(
            "SELECT owner_id FROM workflow_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if existing is not None:
            existing_owner = existing["owner_id"]
            is_legacy = existing_owner is None or str(existing_owner) == ""
            if str(existing_owner or "") != owner and not (
                is_legacy and can_claim_legacy
            ):
                raise WorkflowOwnershipError(run_id)
        conn.execute(
            """
            INSERT INTO workflow_runs (
                run_id, trace_id, scenario, user_goal, status, dry_run,
                created_at, completed_at, run_data, version,
                total_stages, completed_stages, skipped_stages,
                latency_ms, risk_level, owner_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                trace_id=excluded.trace_id,
                scenario=excluded.scenario,
                user_goal=excluded.user_goal,
                status=excluded.status,
                dry_run=excluded.dry_run,
                created_at=excluded.created_at,
                completed_at=excluded.completed_at,
                run_data=excluded.run_data,
                version=excluded.version,
                total_stages=excluded.total_stages,
                completed_stages=excluded.completed_stages,
                skipped_stages=excluded.skipped_stages,
                latency_ms=excluded.latency_ms,
                risk_level=excluded.risk_level,
                owner_id=excluded.owner_id
            """,
            values,
        )


def _safe_load_run_data(raw: str | bytes | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    data.pop("owner_id", None)
    return data


def get_run(run_id: str, owner_id: str | None = None) -> dict[str, Any] | None:
    """Read one run in the requested owner scope."""
    init_workflow_persistence()
    owner = _effective_owner(owner_id)
    _claim_legacy_rows(owner, run_id)
    row = get_conn().execute(
        "SELECT run_data FROM workflow_runs WHERE run_id=? AND owner_id=?",
        (run_id, owner),
    ).fetchone()
    return _safe_load_run_data(row[0]) if row else None


def list_runs(
    limit: int = 100,
    offset: int = 0,
    scenario: str | None = None,
    status: str | None = None,
    owner_id: str | None = None,
) -> list[dict[str, Any]]:
    """List runs in one owner scope with pagination and optional filters."""
    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")
    if offset < 0:
        raise ValueError("offset must be non-negative")
    init_workflow_persistence()
    owner = _effective_owner(owner_id)
    _claim_legacy_rows(owner)
    query = "SELECT run_data FROM workflow_runs WHERE owner_id=?"
    params: list[Any] = [owner]
    if scenario:
        query += " AND scenario=?"
        params.append(scenario)
    if status:
        query += " AND status=?"
        params.append(status)
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = get_conn().execute(query, params).fetchall()
    runs: list[dict[str, Any]] = []
    for row in rows:
        data = _safe_load_run_data(row[0])
        if data is not None:
            runs.append(data)
    return runs


def cleanup_old_runs(
    ttl_days: int = DEFAULT_TTL_DAYS,
    owner_id: str | None = None,
) -> int:
    """Delete expired runs belonging to one owner."""
    if not 1 <= ttl_days <= 3650:
        raise ValueError("ttl_days must be between 1 and 3650")
    init_workflow_persistence()
    owner = _effective_owner(owner_id)
    _claim_legacy_rows(owner)
    cutoff_iso = (utc_now() - timedelta(days=ttl_days)).isoformat()
    with transaction() as conn:
        deleted = conn.execute(
            "DELETE FROM workflow_runs WHERE owner_id=? AND created_at<?",
            (owner, cutoff_iso),
        )
    return deleted.rowcount


def get_run_count(owner_id: str | None = None) -> int:
    """Count runs belonging to one owner."""
    init_workflow_persistence()
    owner = _effective_owner(owner_id)
    _claim_legacy_rows(owner)
    row = get_conn().execute(
        "SELECT COUNT(*) FROM workflow_runs WHERE owner_id=?", (owner,)
    ).fetchone()
    return int(row[0])


def get_storage_stats(owner_id: str | None = None) -> dict[str, Any]:
    """Return storage statistics for one owner without leaking other tenants."""
    init_workflow_persistence()
    owner = _effective_owner(owner_id)
    _claim_legacy_rows(owner)
    conn = get_conn()
    total = conn.execute(
        "SELECT COUNT(*) FROM workflow_runs WHERE owner_id=?", (owner,)
    ).fetchone()[0]
    status_distribution = dict(
        conn.execute(
            "SELECT status, COUNT(*) FROM workflow_runs "
            "WHERE owner_id=? GROUP BY status",
            (owner,),
        ).fetchall()
    )
    oldest, newest = conn.execute(
        "SELECT MIN(created_at), MAX(created_at) FROM workflow_runs WHERE owner_id=?",
        (owner,),
    ).fetchone()
    scenario_distribution = dict(
        conn.execute(
            "SELECT scenario, COUNT(*) FROM workflow_runs "
            "WHERE owner_id=? GROUP BY scenario",
            (owner,),
        ).fetchall()
    )
    return {
        "total_runs": total,
        "status_distribution": status_distribution,
        "scenario_distribution": scenario_distribution,
        "oldest_run": oldest,
        "newest_run": newest,
    }
