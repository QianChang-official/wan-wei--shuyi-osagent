"""Kylin-native vector index lifecycle for MemoryCapsule records.

Only policy-approved active capsules are sent to the native SDK.  The FTS
index remains the safe fallback whenever the optional bridge is absent or the
vendor service cannot complete an operation.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any

from ..audit.service import record
from ..db import get_conn
from ..kylin_sdk.native import KylinNativeSdkError, get_native_sdk
from ..utils.datetime_utils import utc_now_iso_compact


PROVIDER = "kylin_native_sdk"
ELIGIBLE_POLICY_RESULTS = ("allow", "redact")
DEFAULT_REINDEX_BATCH_SIZE = 10
MAX_REINDEX_BATCH_SIZE = 25
_reindex_state_lock = threading.Lock()
_reindex_active = False


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
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
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
    vector_id = _get_or_create_vector_ref(capsule_id, adapter.collection)
    text = json.dumps(content, ensure_ascii=False, sort_keys=True)
    try:
        response = adapter.upsert(vector_id=vector_id, capsule_id=capsule_id, text=text)
    except KylinNativeSdkError:
        _set_status(vector_id, "index_failed")
        record("kylin_sdk_vector_index", {"capsule_id": capsule_id, "vector_id": vector_id, "status": "fallback"})
        return {"backend": "fts_fallback", "indexed": False, "reason": "native_upsert_failed"}

    _set_status(
        vector_id,
        "indexed",
        model_name=response.get("model"),
        dimension=response.get("dimension"),
    )
    index_refs["vector_ref"] = f"kylin-native:{vector_id}"
    index_refs["vector_backend"] = {
        "provider": PROVIDER,
        "collection": adapter.collection,
        "model": response.get("model"),
        "dimension": response.get("dimension"),
    }
    conn = get_conn()
    conn.execute(
        "UPDATE memory_capsules_v2 SET index_refs=?, updated_at=? WHERE capsule_id=?",
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
        return {"eligible": 0, "indexed": 0, "failed": 0, "pending": 0}
    eligible = int(row["eligible"] or 0)
    indexed = int(row["indexed"] or 0)
    failed = int(row["failed"] or 0)
    return {
        "eligible": eligible,
        "indexed": indexed,
        "failed": failed,
        "pending": max(0, eligible - indexed - failed),
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
            vector_id = _get_or_create_vector_ref(capsule_id, adapter.collection)
            _set_status(vector_id, "index_failed")
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
        metadata["_failed_capsule_ids"] = failed_vector_capsule_ids(adapter.collection)
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
    refs = _vector_refs_for_capsules(capsule_ids)
    if not refs:
        return {"backend": "not_indexed", "deleted_vector_ids": [], "pending_vector_ids": []}

    adapter = get_native_sdk()
    availability = adapter.availability()
    if not availability["available"]:
        for ref in refs:
            _set_status(ref["vector_id"], "delete_pending")
        record("kylin_sdk_vector_delete", {"count": len(refs), "status": "pending"})
        return {
            "backend": "fts_fallback",
            "deleted_vector_ids": [],
            "pending_vector_ids": [ref["vector_id"] for ref in refs],
        }

    deleted: list[int] = []
    pending: list[int] = []
    for ref in refs:
        try:
            adapter.delete(vector_id=ref["vector_id"])
        except KylinNativeSdkError:
            _set_status(ref["vector_id"], "delete_pending")
            pending.append(ref["vector_id"])
        else:
            _set_status(ref["vector_id"], "deleted")
            deleted.append(ref["vector_id"])
    record("kylin_sdk_vector_delete", {"deleted": deleted, "pending": pending})
    return {"backend": "kylin_native", "deleted_vector_ids": deleted, "pending_vector_ids": pending}


def _get_or_create_vector_ref(capsule_id: str, collection_name: str) -> int:
    conn = get_conn()
    row = conn.execute(
        "SELECT vector_id,provider,collection_name FROM memory_vector_refs WHERE capsule_id=?",
        (capsule_id,),
    ).fetchone()
    if row:
        if row["provider"] != PROVIDER or row["collection_name"] != collection_name:
            conn.execute(
                """
                UPDATE memory_vector_refs
                SET provider=?, collection_name=?, model_name=NULL, dimension=NULL,
                    status='allocated', updated_at=?
                WHERE vector_id=?
                """,
                (PROVIDER, collection_name, utc_now_iso_compact(), row["vector_id"]),
            )
            conn.commit()
        return int(row["vector_id"])
    timestamp = utc_now_iso_compact()
    cursor = conn.execute(
        """
        INSERT INTO memory_vector_refs(capsule_id,provider,collection_name,status,created_at,updated_at)
        VALUES (?,?,?,?,?,?)
        """,
        (capsule_id, PROVIDER, collection_name, "allocated", timestamp, timestamp),
    )
    conn.commit()
    return int(cursor.lastrowid)


def _pending_capsules(collection_name: str, limit: int, *, retry_failed: bool) -> list[Any]:
    status_clause = "ref.status!='indexed'" if retry_failed else "ref.status NOT IN ('indexed','index_failed')"
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
          AND (ref.vector_id IS NULL OR {status_clause})
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


def _vector_refs_for_capsules(capsule_ids: list[str]) -> list[dict[str, Any]]:
    if not capsule_ids:
        return []
    placeholders = ",".join("?" for _ in capsule_ids)
    rows = get_conn().execute(
        f"""
        SELECT vector_id,capsule_id FROM memory_vector_refs
        WHERE provider=? AND status='indexed' AND capsule_id IN ({placeholders})
        """,
        (PROVIDER, *capsule_ids),
    ).fetchall()
    return [dict(row) for row in rows]
