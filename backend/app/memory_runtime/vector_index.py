"""Kylin-native vector index lifecycle for MemoryCapsule records.

Only policy-approved active capsules are sent to the native SDK.  The FTS
index remains the safe fallback whenever the optional bridge is absent or the
vendor service cannot complete an operation.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from typing import Any

from ..audit.service import record
from ..db import get_conn
from ..kylin_sdk.native import MAX_BRIDGE_TIMEOUT_SECONDS, KylinNativeSdkError, get_native_sdk
from ..utils.datetime_utils import utc_now_iso_compact


PROVIDER = "kylin_native_sdk"
ELIGIBLE_POLICY_RESULTS = ("allow", "redact")
DEFAULT_REINDEX_BATCH_SIZE = 10
MAX_REINDEX_BATCH_SIZE = 25
_reindex_state_lock = threading.Lock()
_reindex_active = False
_delete_sweep_lock = threading.Lock()
DELETE_VERIFICATION_DELAY_SECONDS = int(MAX_BRIDGE_TIMEOUT_SECONDS) + 1
DELETE_CLAIM_LEASE_SECONDS = int(MAX_BRIDGE_TIMEOUT_SECONDS) + 1
DELETE_CLAIM_POLL_SECONDS = 0.02


def init_vector_schema() -> None:
    conn = get_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_vector_refs(
            vector_id INTEGER PRIMARY KEY AUTOINCREMENT,
            capsule_id TEXT NOT NULL UNIQUE,
            provider TEXT NOT NULL,
            collection_name TEXT NOT NULL,
            model_name TEXT,
            dimension INTEGER,
            status TEXT NOT NULL,
            attempt_generation INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_vector_id_allocations(
            vector_id INTEGER PRIMARY KEY AUTOINCREMENT,
            allocated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_vector_tombstones(
            provider TEXT NOT NULL,
            collection_name TEXT NOT NULL,
            vector_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            checked_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(provider, collection_name, vector_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_vector_delete_claims(
            provider TEXT NOT NULL,
            collection_name TEXT NOT NULL,
            vector_id INTEGER NOT NULL,
            claim_token TEXT NOT NULL,
            claimed_at TEXT NOT NULL,
            PRIMARY KEY(provider, collection_name, vector_id)
        )
        """
    )
    conn.commit()
    from ..init_db import migrate_legacy_vector_refs

    migrate_legacy_vector_refs(conn)
    conn.commit()


def index_capsule(*, capsule_id: str, content: dict[str, Any], index_refs: dict[str, Any]) -> dict[str, Any]:
    """Write one approved capsule to the native vector index when available."""
    adapter = get_native_sdk()
    availability = adapter.availability()
    if not availability["available"]:
        return {"backend": "fts_fallback", "indexed": False, "reason": availability["reason"]}

    init_vector_schema()
    return _index_capsule_with_adapter(
        adapter=adapter,
        capsule_id=capsule_id,
        content=content,
        index_refs=index_refs,
    )


def _index_capsule_with_adapter(
    *, adapter: Any, capsule_id: str, content: dict[str, Any], index_refs: dict[str, Any]
) -> dict[str, Any]:
    """Index one Capsule through an already-selected native adapter."""
    try:
        _get_or_create_vector_ref(capsule_id, adapter.collection)
    except KylinNativeSdkError:
        record("kylin_sdk_vector_index", {"capsule_id": capsule_id, "status": "collection_mismatch"})
        return {"backend": "fts_fallback", "indexed": False, "reason": "native_collection_mismatch"}
    text = json.dumps(content, ensure_ascii=False, sort_keys=True)
    attempt = _claim_vector_indexing(capsule_id)
    if attempt is None:
        return {"backend": "fts_fallback", "indexed": False, "reason": "capsule_not_indexable"}
    vector_id, attempt_generation = attempt
    try:
        response = adapter.upsert(vector_id=vector_id, capsule_id=capsule_id, text=text)
    except Exception:
        _set_status_if_current(
            vector_id,
            "index_failed",
            expected_status="indexing",
            attempt_generation=attempt_generation,
        )
        record("kylin_sdk_vector_index", {"capsule_id": capsule_id, "vector_id": vector_id, "status": "fallback"})
        return {"backend": "fts_fallback", "indexed": False, "reason": "native_upsert_failed"}

    published = _publish_indexed_if_active(
        vector_id,
        capsule_id,
        attempt_generation=attempt_generation,
        model_name=response.get("model"),
        dimension=response.get("dimension"),
    )
    if not published:
        if _attempt_is_published(vector_id, capsule_id, attempt_generation):
            published = True
        else:
            _record_vector_tombstone(vector_id, adapter.collection)
    if not published:
        native_vector = _delete_vector_with_adapter(adapter, vector_id)
        active = _capsule_is_active(capsule_id)
        record(
            "kylin_sdk_vector_index",
            {
                "capsule_id": capsule_id,
                "vector_id": vector_id,
                "status": "discarded_after_lease_loss" if active else "discarded_after_forget",
                "native_vector": native_vector,
            },
        )
        return {
            "backend": "fts_fallback",
            "indexed": False,
            "reason": "native_index_lease_lost" if active else "capsule_forgotten_during_index",
        }
    index_refs["vector_ref"] = f"kylin-native:{vector_id}"
    index_refs["vector_backend"] = {
        "provider": PROVIDER,
        "collection": adapter.collection,
        "model": response.get("model"),
        "dimension": response.get("dimension"),
    }
    conn = get_conn()
    conn.execute(
        """
        UPDATE memory_capsules_v2 SET index_refs=?, updated_at=?
        WHERE capsule_id=? AND json_extract(state,'$.lifecycle')='active'
        """,
        (json.dumps(index_refs, ensure_ascii=False, sort_keys=True), utc_now_iso_compact(), capsule_id),
    )
    conn.commit()
    record("kylin_sdk_vector_index", {"capsule_id": capsule_id, "vector_id": vector_id, "status": "indexed"})
    return {"backend": "kylin_native", "indexed": True, "vector_id": vector_id, "collection": adapter.collection}


def native_index_coverage(collection_name: str) -> dict[str, int]:
    """Report whether every eligible active Capsule is represented natively."""
    init_vector_schema()
    try:
        row = get_conn().execute(
            """
            SELECT
                COUNT(*) AS eligible,
            COALESCE(SUM(CASE
                WHEN ref.provider=? AND ref.collection_name=? AND ref.status='indexed' THEN 1
                ELSE 0
            END), 0) AS indexed,
            COALESCE(SUM(CASE
                WHEN ref.provider=? AND ref.collection_name=? AND ref.status='index_failed' THEN 1
                ELSE 0
            END), 0) AS failed
            FROM memory_capsules_v2 AS capsule
            LEFT JOIN memory_vector_refs AS ref ON ref.capsule_id=capsule.capsule_id
            WHERE json_extract(capsule.state,'$.lifecycle')='active'
              AND json_extract(capsule.governance,'$.policy_result') IN (?, ?)
            """,
            (PROVIDER, collection_name, PROVIDER, collection_name, *ELIGIBLE_POLICY_RESULTS),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc).lower():
            raise
        # The status endpoint is also used by lightweight health test clients
        # that do not enter the FastAPI lifespan.  Treat an uninitialized
        # runtime as an empty index; the application lifespan creates it before
        # normal request handling.
        return {"eligible": 0, "indexed": 0, "failed": 0, "pending": 0, "delete_pending": 0}
    eligible = int(row["eligible"] or 0)
    indexed = int(row["indexed"] or 0)
    failed = int(row["failed"] or 0)
    delete_pending = int(get_conn().execute(
        """
        SELECT COUNT(*) FROM (
            SELECT collection_name,vector_id FROM memory_vector_refs
            WHERE provider=? AND status='delete_pending'
            UNION
            SELECT collection_name,vector_id FROM memory_vector_tombstones
            WHERE provider=? AND status='delete_pending'
        )
        """,
        (PROVIDER, PROVIDER),
    ).fetchone()[0])
    return {
        "eligible": eligible,
        "indexed": indexed,
        "failed": failed,
        "pending": max(0, eligible - indexed - failed),
        "delete_pending": delete_pending,
    }


def failed_vector_capsule_ids(collection_name: str) -> list[str]:
    """Return IDs whose vector write failed but whose FTS fallback remains safe."""
    init_vector_schema()
    rows = get_conn().execute(
        """
        SELECT capsule_id FROM memory_vector_refs
        WHERE provider=? AND collection_name=? AND status='index_failed'
        ORDER BY updated_at ASC
        """,
        (PROVIDER, collection_name),
    ).fetchall()
    return [row["capsule_id"] for row in rows]


def sync_pending_vectors(*, limit: int = DEFAULT_REINDEX_BATCH_SIZE, retry_failed: bool = False) -> dict[str, Any]:
    """Index one bounded batch of eligible Capsules that predate native setup."""
    limit = max(1, min(int(limit), MAX_REINDEX_BATCH_SIZE))
    adapter = get_native_sdk()
    availability = adapter.availability()
    if not availability["available"]:
        return {
            "backend": "fts_fallback",
            "attempted": 0,
            "indexed": 0,
            "failed": 0,
            "reason": availability["reason"],
            "index": native_index_coverage(adapter.collection),
        }

    init_vector_schema()
    delete_sweep = sweep_pending_vector_deletes(limit=limit, adapter=adapter)
    rows = _pending_capsules(adapter.collection, limit, retry_failed=retry_failed)
    indexed = 0
    failed = 0
    for row in rows:
        capsule_id = row["capsule_id"]
        try:
            content = json.loads(row["content"])
            index_refs = json.loads(row["index_refs"])
            if not isinstance(content, dict) or not isinstance(index_refs, dict):
                raise ValueError("invalid_capsule_json")
            result = _index_capsule_with_adapter(
                adapter=adapter,
                capsule_id=capsule_id,
                content=content,
                index_refs=index_refs,
            )
        except Exception:
            vector_id = _vector_id_for_capsule(capsule_id, adapter.collection)
            record("kylin_sdk_vector_index", {"capsule_id": capsule_id, "vector_id": vector_id, "status": "fallback"})
            failed += 1
        else:
            if result["indexed"]:
                indexed += 1
            else:
                failed += 1

    coverage = native_index_coverage(adapter.collection)
    if rows:
        record(
            "kylin_sdk_vector_reindex",
            {
                "collection": adapter.collection,
                "attempted": len(rows),
                "indexed": indexed,
                "failed": failed,
                "pending": coverage["pending"],
            },
        )
    result: dict[str, Any] = {
        "backend": "kylin_native" if failed == 0 else "fts_fallback",
        "attempted": len(rows),
        "indexed": indexed,
        "failed": failed,
        "index": coverage,
        "delete_sweep": delete_sweep,
    }
    if failed:
        result["reason"] = "native_reindex_failed"
    return result


def reserve_vector_sync() -> bool:
    """Reserve the one in-process background reindex slot."""
    global _reindex_active
    with _reindex_state_lock:
        if _reindex_active:
            return False
        _reindex_active = True
        return True


def run_reserved_vector_sync(*, limit: int, retry_failed: bool = False) -> None:
    """Run a reserved reindex task and always release its scheduler slot."""
    global _reindex_active
    try:
        sync_pending_vectors(limit=limit, retry_failed=retry_failed)
    finally:
        with _reindex_state_lock:
            _reindex_active = False


def vector_sync_active() -> bool:
    with _reindex_state_lock:
        return _reindex_active


def native_candidates(query: str, *, top_k: int) -> tuple[list[tuple[str, float]] | None, dict[str, Any]]:
    """Return native candidates, or ``None`` when FTS must handle the request."""
    adapter = get_native_sdk()
    availability = adapter.availability()
    if not availability["available"]:
        return None, {"backend": "fts_fallback", "fallback_reason": availability["reason"]}

    init_vector_schema()
    coverage = native_index_coverage(adapter.collection)
    if coverage["pending"]:
        # Native search cannot safely stand alone until all existing eligible
        # Capsules have a vector.  Keep FTS observable until the operator runs
        # the bounded reindex endpoint, rather than silently dropping history.
        return None, {
            "backend": "fts_fallback",
            "fallback_reason": "native_index_backfill_pending",
            "native_index": coverage,
        }
    try:
        response = adapter.search(text=query, top_k=top_k)
    except KylinNativeSdkError:
        return None, {"backend": "fts_fallback", "fallback_reason": "native_search_failed"}

    hits = response.get("hits")
    if not isinstance(hits, list):
        return None, {"backend": "fts_fallback", "fallback_reason": "native_search_invalid_response"}
    metadata: dict[str, Any] = {
        "backend": "kylin_native",
        "model": response.get("model"),
        "collection": adapter.collection,
        "native_index": coverage,
    }
    if coverage["failed"]:
        metadata["fallback_reason"] = "native_index_failed_capsules"
    vector_ids = [hit.get("vector_id") for hit in hits if isinstance(hit, dict) and isinstance(hit.get("vector_id"), int)]
    if not vector_ids:
        return [], metadata

    by_vector_id = _capsules_for_vector_ids(vector_ids, adapter.collection)
    candidates: list[tuple[str, float]] = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        vector_id = hit.get("vector_id")
        capsule_id = by_vector_id.get(vector_id)
        if capsule_id is None:
            continue
        score = hit.get("score", 0.0)
        candidates.append((capsule_id, float(score) if isinstance(score, (int, float)) else 0.0))
    return candidates, metadata


def remove_vectors(capsule_ids: list[str]) -> dict[str, Any]:
    """Best-effort native deletion; failed removals remain auditable as pending."""
    init_vector_schema()
    refs = _vector_refs_for_capsules(capsule_ids, include_deleted=True)
    if not refs:
        return {"backend": "not_indexed", "deleted_vector_ids": [], "pending_vector_ids": []}

    adapter = get_native_sdk()
    availability = adapter.availability()
    if not availability["available"]:
        deleted: list[int] = []
        pending: list[int] = []
        for ref in refs:
            vector_id = int(ref["vector_id"])
            if _native_delete_is_confirmed(vector_id, ref["collection_name"]):
                deleted.append(vector_id)
            else:
                if ref["status"] != "deleted":
                    _set_status_if_current(
                        vector_id,
                        "delete_pending",
                        expected_status=ref["status"],
                    )
                if _native_delete_is_confirmed(vector_id, ref["collection_name"]):
                    deleted.append(vector_id)
                else:
                    pending.append(vector_id)
        record("kylin_sdk_vector_delete", {"count": len(pending), "status": "pending"})
        return {
            "backend": "fts_fallback",
            "deleted_vector_ids": deleted,
            "pending_vector_ids": pending,
        }

    deleted: list[int] = []
    pending: list[int] = []
    for ref in refs:
        vector_id = int(ref["vector_id"])
        if _native_delete_is_confirmed(vector_id, ref["collection_name"]):
            deleted.append(vector_id)
            continue
        if ref["collection_name"] != adapter.collection:
            if ref["status"] != "deleted":
                _set_status_if_current(
                    vector_id,
                    "delete_pending",
                    expected_status=ref["status"],
                )
            if _native_delete_is_confirmed(vector_id, ref["collection_name"]):
                deleted.append(vector_id)
            else:
                pending.append(vector_id)
            continue
        result = _delete_vector_with_adapter(adapter, vector_id)
        if result["deleted"]:
            deleted.append(vector_id)
        else:
            pending.append(vector_id)
    record("kylin_sdk_vector_delete", {"deleted": deleted, "pending": pending})
    return {"backend": "kylin_native", "deleted_vector_ids": deleted, "pending_vector_ids": pending}


def sweep_pending_vector_deletes(*, limit: int = DEFAULT_REINDEX_BATCH_SIZE, adapter: Any | None = None) -> dict[str, Any]:
    """Reconcile a bounded delete outbox and permanent vector tombstones."""
    limit = max(1, min(int(limit), MAX_REINDEX_BATCH_SIZE))
    if not _delete_sweep_lock.acquire(blocking=False):
        return {"attempted": 0, "deleted_vector_ids": [], "pending_vector_ids": [], "reason": "sweep_in_progress"}
    try:
        init_vector_schema()
        native_adapter = adapter or get_native_sdk()
        availability = native_adapter.availability()
        rows = get_conn().execute(
            """
            WITH delete_candidates AS (
                SELECT vector_id,collection_name,status,updated_at AS checked_at,
                       julianday(updated_at) AS due_at
                FROM memory_vector_refs
                WHERE provider=? AND collection_name=? AND status='delete_pending'
                UNION ALL
                SELECT vector_id,collection_name,status,COALESCE(checked_at,updated_at),
                       CASE
                           WHEN status='deleted' THEN
                               julianday(COALESCE(checked_at,updated_at), ?)
                           ELSE julianday(updated_at)
                       END AS due_at
                FROM memory_vector_tombstones
                WHERE provider=? AND collection_name=?
                  AND (
                      status='delete_pending'
                      OR (
                          status='deleted'
                          AND julianday(COALESCE(checked_at,updated_at))
                              <= julianday('now', ?)
                      )
                  )
            ), ranked_candidates AS (
                SELECT vector_id,collection_name,status,checked_at,due_at,
                       ROW_NUMBER() OVER (
                           PARTITION BY collection_name,vector_id
                           ORDER BY CASE status WHEN 'delete_pending' THEN 0 ELSE 1 END,
                                    checked_at ASC
                       ) AS candidate_rank
                FROM delete_candidates
            )
            SELECT vector_id,collection_name,status,checked_at,due_at FROM ranked_candidates
            WHERE candidate_rank=1
            ORDER BY due_at ASC, vector_id ASC
            LIMIT ?
            """,
            (
                PROVIDER,
                native_adapter.collection,
                f"+{DELETE_VERIFICATION_DELAY_SECONDS} seconds",
                PROVIDER,
                native_adapter.collection,
                f"-{DELETE_VERIFICATION_DELAY_SECONDS} seconds",
                limit,
            ),
        ).fetchall()
        if not rows:
            return {"attempted": 0, "deleted_vector_ids": [], "pending_vector_ids": []}
        if not availability["available"]:
            return {
                "attempted": len(rows),
                "deleted_vector_ids": [],
                "pending_vector_ids": [int(row["vector_id"]) for row in rows],
                "reason": availability["reason"],
            }
        deleted: list[int] = []
        pending: list[int] = []
        attempted = 0
        for row in rows:
            vector_id = int(row["vector_id"])
            if row["collection_name"] != native_adapter.collection:
                pending.append(vector_id)
                continue
            if row["status"] == "deleted" and not _claim_deleted_tombstone_verification(
                vector_id,
                native_adapter.collection,
                row["checked_at"],
            ):
                continue
            attempted += 1
            result = _delete_vector_with_adapter(
                native_adapter,
                vector_id,
                verify_deleted=row["status"] == "deleted",
            )
            if result["deleted"]:
                deleted.append(vector_id)
                if row["status"] == "deleted":
                    _set_tombstone_status(
                        vector_id,
                        native_adapter.collection,
                        "verified_deleted",
                    )
            else:
                pending.append(vector_id)
        record("kylin_sdk_vector_delete_sweep", {"deleted": deleted, "pending": pending})
        return {
            "attempted": attempted,
            "deleted_vector_ids": deleted,
            "pending_vector_ids": pending,
        }
    finally:
        _delete_sweep_lock.release()


def run_vector_delete_sweeper(
    stop_event: threading.Event,
    *,
    interval_seconds: float = 60.0,
    limit: int = DEFAULT_REINDEX_BATCH_SIZE,
) -> None:
    """Continuously drain the bounded delete outbox until shutdown."""
    while not stop_event.is_set():
        try:
            sweep_pending_vector_deletes(limit=limit)
        except Exception:
            pass
        stop_event.wait(max(1.0, interval_seconds))


def mark_vectors_delete_pending_in_transaction(conn: sqlite3.Connection, capsule_ids: list[str]) -> dict[str, Any]:
    """Stage native deletions on an existing SQLite transaction."""
    if not capsule_ids:
        return {"backend": "not_indexed", "deleted_vector_ids": [], "pending_vector_ids": []}
    placeholders = ",".join("?" for _ in capsule_ids)
    rows = conn.execute(
        f"""
        SELECT vector_id,collection_name,status FROM memory_vector_refs
        WHERE provider=? AND status!='deleted'
          AND capsule_id IN ({placeholders})
        """,
        (PROVIDER, *capsule_ids),
    ).fetchall()
    vector_ids = [int(row["vector_id"]) for row in rows]
    if not vector_ids:
        return {"backend": "not_indexed", "deleted_vector_ids": [], "pending_vector_ids": []}
    vector_placeholders = ",".join("?" for _ in vector_ids)
    conn.execute(
        f"UPDATE memory_vector_refs SET status='delete_pending', updated_at=? "
        f"WHERE vector_id IN ({vector_placeholders})",
        (utc_now_iso_compact(), *vector_ids),
    )
    timestamp = utc_now_iso_compact()
    for row in rows:
        if row["status"] in {"indexing", "index_failed"}:
            _record_vector_tombstone_in_transaction(
                conn,
                int(row["vector_id"]),
                row["collection_name"],
                timestamp,
            )
    return {
        "backend": "kylin_native",
        "deleted_vector_ids": [],
        "pending_vector_ids": vector_ids,
    }


def _get_or_create_vector_ref(capsule_id: str, collection_name: str) -> int:
    conn = get_conn()
    row = conn.execute(
        "SELECT vector_id,provider,collection_name,status FROM memory_vector_refs WHERE capsule_id=?",
        (capsule_id,),
    ).fetchone()
    if row:
        if row["provider"] != PROVIDER or row["collection_name"] != collection_name:
            raise KylinNativeSdkError("native_collection_mismatch")
        if row["status"] in {"delete_pending", "deleted"}:
            raise KylinNativeSdkError("native_vector_delete_in_progress")
        return int(row["vector_id"])
    timestamp = utc_now_iso_compact()
    vector_id = _allocate_vector_id_in_transaction(conn, timestamp)
    conn.execute(
        """
        INSERT INTO memory_vector_refs(
            vector_id,capsule_id,provider,collection_name,status,
            attempt_generation,created_at,updated_at
        ) VALUES (?,?,?,?,?,?,?,?)
        """,
        (vector_id, capsule_id, PROVIDER, collection_name, "allocated", 0, timestamp, timestamp),
    )
    conn.commit()
    return vector_id


def _pending_capsules(collection_name: str, limit: int, *, retry_failed: bool) -> list[Any]:
    retry_clause = " OR ref.status='index_failed'" if retry_failed else ""
    return get_conn().execute(
        f"""
        SELECT capsule.capsule_id,capsule.content,capsule.index_refs
        FROM memory_capsules_v2 AS capsule
        LEFT JOIN memory_vector_refs AS ref
          ON ref.capsule_id=capsule.capsule_id
         AND ref.provider=?
         AND ref.collection_name=?
        WHERE json_extract(capsule.state,'$.lifecycle')='active'
          AND json_extract(capsule.governance,'$.policy_result') IN (?, ?)
          AND (
              ref.vector_id IS NULL OR ref.status='allocated'{retry_clause}
              OR (ref.status='indexing' AND julianday(ref.updated_at)<=julianday('now','-1 hour'))
          )
        ORDER BY capsule.updated_at ASC
        LIMIT ?
        """,
        (PROVIDER, collection_name, *ELIGIBLE_POLICY_RESULTS, limit),
    ).fetchall()


def _set_status(vector_id: int, status: str, *, model_name: Any = None, dimension: Any = None) -> None:
    conn = get_conn()
    conn.execute(
        """
        UPDATE memory_vector_refs
        SET status=?, model_name=COALESCE(?, model_name), dimension=COALESCE(?, dimension), updated_at=?
        WHERE vector_id=?
        """,
        (status, model_name if isinstance(model_name, str) else None, dimension if isinstance(dimension, int) else None,
         utc_now_iso_compact(), vector_id),
    )
    conn.commit()


def _set_status_if_current(
    vector_id: int,
    status: str,
    *,
    expected_status: str,
    attempt_generation: int | None = None,
) -> bool:
    conn = get_conn()
    generation_clause = " AND attempt_generation=?" if attempt_generation is not None else ""
    parameters: tuple[Any, ...] = (status, utc_now_iso_compact(), vector_id, expected_status)
    if attempt_generation is not None:
        parameters += (attempt_generation,)
    updated = conn.execute(
        "UPDATE memory_vector_refs SET status=?, updated_at=? "
        f"WHERE vector_id=? AND status=?{generation_clause}",
        parameters,
    )
    conn.commit()
    return updated.rowcount == 1


def _claim_vector_indexing(capsule_id: str) -> tuple[int, int] | None:
    conn = get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT ref.vector_id,ref.collection_name,ref.status,
                   ref.attempt_generation,ref.updated_at
            FROM memory_vector_refs AS ref
            JOIN memory_capsules_v2 AS capsule ON capsule.capsule_id=ref.capsule_id
            WHERE ref.capsule_id=?
              AND json_extract(capsule.state,'$.lifecycle')='active'
            """,
            (capsule_id,),
        ).fetchone()
        if row is None or row["status"] in {"delete_pending", "deleted"}:
            conn.rollback()
            return None
        claimable = row["status"] in {"allocated", "index_failed", "indexed"}
        if row["status"] == "indexing":
            claimable = bool(conn.execute(
                "SELECT julianday(?)<=julianday('now','-1 hour')",
                (row["updated_at"],),
            ).fetchone()[0])
        if not claimable:
            conn.rollback()
            return None

        timestamp = utc_now_iso_compact()
        old_vector_id = int(row["vector_id"])
        generation = int(row["attempt_generation"] or 0) + 1
        if row["status"] == "allocated" and int(row["attempt_generation"] or 0) == 0:
            vector_id = old_vector_id
        else:
            vector_id = _allocate_vector_id_in_transaction(conn, timestamp)
            _record_vector_tombstone_in_transaction(
                conn,
                old_vector_id,
                row["collection_name"],
                timestamp,
            )
        updated = conn.execute(
            """
            UPDATE memory_vector_refs
            SET vector_id=?,status='indexing',attempt_generation=?,
                model_name=NULL,dimension=NULL,updated_at=?
            WHERE capsule_id=? AND vector_id=? AND attempt_generation=?
            """,
            (
                vector_id,
                generation,
                timestamp,
                capsule_id,
                old_vector_id,
                int(row["attempt_generation"] or 0),
            ),
        )
        if updated.rowcount != 1:
            conn.rollback()
            return None
        conn.commit()
        return vector_id, generation
    except Exception:
        conn.rollback()
        raise


def _vector_id_for_capsule(capsule_id: str, collection_name: str) -> int | None:
    row = get_conn().execute(
        """
        SELECT vector_id FROM memory_vector_refs
        WHERE capsule_id=? AND provider=? AND collection_name=?
        """,
        (capsule_id, PROVIDER, collection_name),
    ).fetchone()
    return int(row["vector_id"]) if row else None


def _publish_indexed_if_active(
    vector_id: int,
    capsule_id: str,
    *,
    attempt_generation: int,
    model_name: Any = None,
    dimension: Any = None,
) -> bool:
    conn = get_conn()
    published = conn.execute(
        """
        UPDATE memory_vector_refs
        SET status='indexed', model_name=COALESCE(?, model_name),
            dimension=COALESCE(?, dimension), updated_at=?
        WHERE vector_id=? AND status='indexing' AND attempt_generation=?
          AND EXISTS (
              SELECT 1 FROM memory_capsules_v2
              WHERE capsule_id=? AND json_extract(state,'$.lifecycle')='active'
          )
        """,
        (
            model_name if isinstance(model_name, str) else None,
            dimension if isinstance(dimension, int) else None,
            utc_now_iso_compact(),
            vector_id,
            attempt_generation,
            capsule_id,
        ),
    )
    conn.commit()
    return published.rowcount == 1


def _attempt_is_published(vector_id: int, capsule_id: str, attempt_generation: int) -> bool:
    row = get_conn().execute(
        """
        SELECT 1 FROM memory_vector_refs
        WHERE vector_id=? AND capsule_id=? AND attempt_generation=? AND status='indexed'
        """,
        (vector_id, capsule_id, attempt_generation),
    ).fetchone()
    return row is not None


def _capsule_is_active(capsule_id: str) -> bool:
    row = get_conn().execute(
        """
        SELECT 1 FROM memory_capsules_v2
        WHERE capsule_id=? AND json_extract(state,'$.lifecycle')='active'
        """,
        (capsule_id,),
    ).fetchone()
    return row is not None


def _allocate_vector_id_in_transaction(conn: sqlite3.Connection, timestamp: str) -> int:
    cursor = conn.execute(
        "INSERT INTO memory_vector_id_allocations(allocated_at) VALUES (?)",
        (timestamp,),
    )
    return int(cursor.lastrowid)


def _record_vector_tombstone(vector_id: int, collection_name: str) -> None:
    conn = get_conn()
    timestamp = utc_now_iso_compact()
    _record_vector_tombstone_in_transaction(conn, vector_id, collection_name, timestamp)
    conn.commit()


def _record_vector_tombstone_in_transaction(
    conn: sqlite3.Connection,
    vector_id: int,
    collection_name: str,
    timestamp: str,
) -> None:
    conn.execute(
        """
        INSERT INTO memory_vector_tombstones(
            provider,collection_name,vector_id,status,checked_at,created_at,updated_at
        ) VALUES (?,?,?,'delete_pending',NULL,?,?)
        ON CONFLICT(provider,collection_name,vector_id) DO UPDATE SET
            status='delete_pending',updated_at=excluded.updated_at
        """,
        (PROVIDER, collection_name, vector_id, timestamp, timestamp),
    )


def _delete_vector_with_adapter(
    adapter: Any,
    vector_id: int,
    *,
    verify_deleted: bool = False,
) -> dict[str, bool]:
    """Run one native delete while serializing duplicate callers through SQLite."""
    if not verify_deleted and _native_delete_is_confirmed(vector_id, adapter.collection):
        return {"deleted": True}

    claim_token = _claim_vector_delete(vector_id, adapter.collection)
    if claim_token is None:
        return _wait_for_vector_delete_claim(vector_id, adapter.collection)
    if not verify_deleted and _native_delete_is_confirmed(vector_id, adapter.collection):
        _release_vector_delete_claim(vector_id, adapter.collection, claim_token)
        return {"deleted": True}

    claim_settled = False
    try:
        try:
            response = adapter.delete(vector_id=vector_id)
            status = "deleted" if response.get("deleted") is True else "delete_pending"
        except Exception:
            status = "delete_pending"
        _set_delete_status(
            vector_id,
            adapter.collection,
            status,
            claim_token=claim_token,
        )
        claim_settled = True
        return {"deleted": _native_delete_is_confirmed(vector_id, adapter.collection)}
    finally:
        if not claim_settled:
            _release_vector_delete_claim(vector_id, adapter.collection, claim_token)


def _claim_vector_delete(vector_id: int, collection_name: str) -> str | None:
    """Claim a delete across request workers, allowing recovery after a crash."""
    conn = get_conn()
    claim_token = uuid.uuid4().hex
    timestamp = utc_now_iso_compact()
    try:
        conn.execute("BEGIN IMMEDIATE")
        claimed = conn.execute(
            """
            INSERT INTO memory_vector_delete_claims(
                provider,collection_name,vector_id,claim_token,claimed_at
            ) VALUES (?,?,?,?,?)
            ON CONFLICT(provider,collection_name,vector_id) DO UPDATE SET
                claim_token=excluded.claim_token,
                claimed_at=excluded.claimed_at
            WHERE julianday(memory_vector_delete_claims.claimed_at)
                  <= julianday('now', ?)
            """,
            (
                PROVIDER,
                collection_name,
                vector_id,
                claim_token,
                timestamp,
                f"-{DELETE_CLAIM_LEASE_SECONDS} seconds",
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return claim_token if claimed.rowcount == 1 else None


def _wait_for_vector_delete_claim(vector_id: int, collection_name: str) -> dict[str, bool]:
    """Return the current owner's result without issuing another native delete."""
    deadline = time.monotonic() + DELETE_CLAIM_LEASE_SECONDS
    conn = get_conn()
    while True:
        if _native_delete_is_confirmed(vector_id, collection_name):
            return {"deleted": True}
        claimed = conn.execute(
            """
            SELECT 1 FROM memory_vector_delete_claims
            WHERE provider=? AND collection_name=? AND vector_id=?
            """,
            (PROVIDER, collection_name, vector_id),
        ).fetchone()
        if claimed is None or time.monotonic() >= deadline:
            return {"deleted": False}
        time.sleep(DELETE_CLAIM_POLL_SECONDS)


def _release_vector_delete_claim(vector_id: int, collection_name: str, claim_token: str) -> None:
    conn = get_conn()
    try:
        conn.execute(
            """
            DELETE FROM memory_vector_delete_claims
            WHERE provider=? AND collection_name=? AND vector_id=? AND claim_token=?
            """,
            (PROVIDER, collection_name, vector_id, claim_token),
        )
        conn.commit()
    except Exception:
        conn.rollback()


def _delete_statuses(vector_id: int, collection_name: str) -> tuple[str | None, str | None]:
    row = get_conn().execute(
        """
        SELECT ref.status AS ref_status,tombstone.status AS tombstone_status
        FROM memory_vector_refs AS ref
        LEFT JOIN memory_vector_tombstones AS tombstone
          ON tombstone.provider=ref.provider
         AND tombstone.collection_name=ref.collection_name
         AND tombstone.vector_id=ref.vector_id
        WHERE ref.provider=? AND ref.collection_name=? AND ref.vector_id=?
        """,
        (PROVIDER, collection_name, vector_id),
    ).fetchone()
    if row:
        return row["ref_status"], row["tombstone_status"]
    tombstone = get_conn().execute(
        """
        SELECT status FROM memory_vector_tombstones
        WHERE provider=? AND collection_name=? AND vector_id=?
        """,
        (PROVIDER, collection_name, vector_id),
    ).fetchone()
    return None, tombstone["status"] if tombstone else None


def _native_delete_is_confirmed(vector_id: int, collection_name: str) -> bool:
    ref_status, tombstone_status = _delete_statuses(vector_id, collection_name)
    if ref_status == "deleted":
        return tombstone_status != "delete_pending"
    return ref_status is None and tombstone_status in {"deleted", "verified_deleted"}


def _set_delete_status(
    vector_id: int,
    collection_name: str,
    status: str,
    *,
    claim_token: str | None = None,
) -> str | None:
    conn = get_conn()
    timestamp = utc_now_iso_compact()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if claim_token is not None:
            claim = conn.execute(
                """
                SELECT 1 FROM memory_vector_delete_claims
                WHERE provider=? AND collection_name=? AND vector_id=? AND claim_token=?
                """,
                (PROVIDER, collection_name, vector_id, claim_token),
            ).fetchone()
            if claim is None:
                conn.rollback()
                return _current_delete_status(vector_id, collection_name)
        conn.execute(
            """
            UPDATE memory_vector_refs SET status=?, updated_at=?
            WHERE provider=? AND collection_name=? AND vector_id=?
            """,
            (status, timestamp, PROVIDER, collection_name, vector_id),
        )
        conn.execute(
            """
            UPDATE memory_vector_tombstones
            SET status=?,checked_at=?,updated_at=?
            WHERE provider=? AND collection_name=? AND vector_id=?
            """,
            (status, timestamp, timestamp, PROVIDER, collection_name, vector_id),
        )
        if claim_token is not None:
            conn.execute(
                """
                DELETE FROM memory_vector_delete_claims
                WHERE provider=? AND collection_name=? AND vector_id=? AND claim_token=?
                """,
                (PROVIDER, collection_name, vector_id, claim_token),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return _current_delete_status(vector_id, collection_name)


def _current_delete_status(vector_id: int, collection_name: str) -> str | None:
    ref_status, tombstone_status = _delete_statuses(vector_id, collection_name)
    return ref_status or tombstone_status


def _set_tombstone_status(vector_id: int, collection_name: str, status: str) -> None:
    conn = get_conn()
    timestamp = utc_now_iso_compact()
    conn.execute(
        """
        UPDATE memory_vector_tombstones
        SET status=?,checked_at=?,updated_at=?
        WHERE provider=? AND collection_name=? AND vector_id=?
        """,
        (status, timestamp, timestamp, PROVIDER, collection_name, vector_id),
    )
    conn.commit()


def _claim_deleted_tombstone_verification(
    vector_id: int,
    collection_name: str,
    expected_checked_at: str,
) -> bool:
    """Claim one delayed verification across worker processes."""
    conn = get_conn()
    timestamp = utc_now_iso_compact()
    claimed = conn.execute(
        """
        UPDATE memory_vector_tombstones
        SET checked_at=?,updated_at=?
        WHERE provider=? AND collection_name=? AND vector_id=? AND status='deleted'
          AND COALESCE(checked_at,updated_at)=?
          AND julianday(COALESCE(checked_at,updated_at))<=julianday('now', ?)
        """,
        (
            timestamp,
            timestamp,
            PROVIDER,
            collection_name,
            vector_id,
            expected_checked_at,
            f"-{DELETE_VERIFICATION_DELAY_SECONDS} seconds",
        ),
    )
    conn.commit()
    return claimed.rowcount == 1


def _capsules_for_vector_ids(vector_ids: list[int], collection_name: str) -> dict[int, str]:
    placeholders = ",".join("?" for _ in vector_ids)
    rows = get_conn().execute(
        f"""
        SELECT vector_id,capsule_id FROM memory_vector_refs
        WHERE provider=? AND collection_name=? AND status='indexed' AND vector_id IN ({placeholders})
        """,
        (PROVIDER, collection_name, *vector_ids),
    ).fetchall()
    return {int(row["vector_id"]): row["capsule_id"] for row in rows}


def _vector_refs_for_capsules(capsule_ids: list[str], *, include_deleted: bool = False) -> list[dict[str, Any]]:
    if not capsule_ids:
        return []
    placeholders = ",".join("?" for _ in capsule_ids)
    status_clause = "status!='deleted'" if not include_deleted else "status IN ('allocated','indexing','indexed','index_failed','delete_pending','deleted')"
    rows = get_conn().execute(
        f"""
        SELECT ref.vector_id,ref.capsule_id,ref.collection_name,ref.status,
               tombstone.status AS tombstone_status
        FROM memory_vector_refs AS ref
        LEFT JOIN memory_vector_tombstones AS tombstone
          ON tombstone.provider=ref.provider
         AND tombstone.collection_name=ref.collection_name
         AND tombstone.vector_id=ref.vector_id
        WHERE ref.provider=? AND ref.{status_clause} AND ref.capsule_id IN ({placeholders})
        ORDER BY ref.vector_id ASC
        """,
        (PROVIDER, *capsule_ids),
    ).fetchall()
    return [dict(row) for row in rows]


def pending_delete_vector_ids(
    capsule_ids: list[str],
    *,
    conn: sqlite3.Connection | None = None,
) -> set[int]:
    """Return vectors whose durable ref or tombstone state still needs deletion."""
    if not capsule_ids:
        return set()
    connection = conn if conn is not None else get_conn()
    if conn is None:
        init_vector_schema()
        connection = get_conn()
    placeholders = ",".join("?" for _ in capsule_ids)
    rows = connection.execute(
        f"""
        SELECT ref.vector_id,ref.status AS ref_status,tombstone.status AS tombstone_status
        FROM memory_vector_refs AS ref
        LEFT JOIN memory_vector_tombstones AS tombstone
          ON tombstone.provider=ref.provider
         AND tombstone.collection_name=ref.collection_name
         AND tombstone.vector_id=ref.vector_id
        WHERE ref.provider=? AND ref.capsule_id IN ({placeholders})
        """,
        (PROVIDER, *capsule_ids),
    ).fetchall()
    return {
        int(row["vector_id"])
        for row in rows
        if row["ref_status"] == "delete_pending" or row["tombstone_status"] == "delete_pending"
    }
