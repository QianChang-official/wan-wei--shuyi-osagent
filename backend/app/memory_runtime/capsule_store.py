import json
import threading
import uuid
from typing import Any

from ..db import get_conn, database_path, transaction
from ..audit.service import record, record_in_transaction
from ..utils.datetime_utils import utc_now_iso_compact
from .policy_gate import evaluate_policy

RETRIEVABLE_POLICY = {"allow", "redact"}
RETRIEVABLE_LIFECYCLE = {"active", "reinforced", "conflicted"}

# B2: 模块级 once 标记，按 db_path 缓存。避免每次 write_capsule 都跑完整
# init_db（~30 条 DDL + 迁移扫描 + print）。测试切换 WANWEI_MEMORY_DB 时
# 新路径不在缓存中，会重新 init。
_runtime_schema_done: set[str] = set()
_runtime_schema_lock = threading.Lock()


def now() -> str:
    return utc_now_iso_compact()


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def loads(text: str, default: Any = None) -> Any:
    if text is None:
        return default
    return json.loads(text)


def _content_text(content: dict[str, Any]) -> str:
    return dumps(content)


def _lifecycle_for_policy(policy_result: str) -> str:
    if policy_result == "quarantine":
        return "quarantined"
    if policy_result == "reject":
        return "rejected"
    if policy_result == "require_confirmation":
        return "candidate"
    return "active"


def init_runtime_schema() -> None:
    """初始化 runtime schema，每个 db_path 只跑一次（线程安全）。"""
    path = str(database_path())
    if path in _runtime_schema_done:
        return
    with _runtime_schema_lock:
        if path in _runtime_schema_done:
            return
        from ..init_db import main
        main()
        _runtime_schema_done.add(path)


def write_capsule(
    *,
    memory_class: str,
    content: dict[str, Any],
    source_type: str = "user_input",
    scene: str = "general",
    task_type: str = "planning",
    risk_class: str = "low",
    write_intent: str = "explicit",
    affects_future_behavior: bool = False,
    source_trust: str = "normal",
    provenance: dict[str, Any] | None = None,
    production_context: dict[str, Any] | None = None,
    alignment_metadata: dict[str, Any] | None = None,
    relation_edges: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    init_runtime_schema()
    text = _content_text(content)
    governance = evaluate_policy(
        text=text,
        source_type=source_type,
        write_intent=write_intent,
        affects_future_behavior=affects_future_behavior,
        source_trust=source_trust,
        memory_class=memory_class,
    )
    capsule_id = "cap_" + uuid.uuid4().hex[:12]
    created = now()
    provenance = provenance or {
        "origin": "human" if source_type in {"user_input", "user"} else source_type,
        "writer_identity": "runtime",
        "source_type": source_type,
        "source_ids": [],
        "evidence_ids": [],
        "verified": source_type in {"user_input", "eval", "file"},
        "verification_method": "manual" if source_type == "user_input" else "unknown",
    }
    production_context = production_context or {
        "scene": scene, "task_type": task_type, "risk_class": risk_class,
        "tenant_scope": "local", "validity_scope": "project",
    }
    state = {
        "lifecycle": _lifecycle_for_policy(governance["policy_result"]),
        "version": 1,
        "importance_score": 0.5,
        "retention_score": 0.5,
        "usage_count": 0,
        "last_accessed_at": None,
        "supersedes": [],
        "superseded_by": [],
    }
    alignment_metadata = alignment_metadata or {
        "human_preference_links": [], "policy_links": [], "constraint_links": [],
        "oversight_required": governance.get("requires_confirmation", False),
        "confirmation_status": "pending" if governance.get("requires_confirmation") else "not_required",
        "last_human_feedback": "unknown",
    }
    relation_edges = relation_edges or []
    index_refs = {"fts_ref": capsule_id, "vector_ref": None, "graph_node_id": capsule_id}
    native_index = {"backend": "fts_fallback", "indexed": False, "reason": "policy_not_indexable"}

    if governance["policy_result"] == "reject":
        audit_id = record(
            "capsule_write",
            {
                "capsule_id": capsule_id,
                "policy_result": governance["policy_result"],
                "memory_class": memory_class,
            },
        )
        return {
            "capsule_id": capsule_id,
            "memory_class": memory_class,
            "governance": governance,
            "state": state,
            "audit_id": audit_id,
            "native_index": native_index,
        }

    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO memory_capsules_v2 (
                capsule_id, memory_class, content, source_events, provenance, governance,
                state, production_context, alignment_metadata, affective_metadata,
                relation_edges, index_refs, created_at, updated_at,
                memory_tier, emotional_weight, created_in_dream
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                capsule_id, memory_class, dumps(content), dumps([]), dumps(provenance), dumps(governance),
                dumps(state), dumps(production_context), dumps(alignment_metadata), dumps({}),
                dumps(relation_edges), dumps(index_refs), created, created,
                'working', 0.0, 0,
            ),
        )
        if governance["policy_result"] in RETRIEVABLE_POLICY and state["lifecycle"] == "active":
            conn.execute("INSERT INTO memory_capsules_v2_fts(capsule_id,text) VALUES (?,?)", (capsule_id, text))
    audit_id = record("capsule_write", {"capsule_id": capsule_id, "policy_result": governance["policy_result"], "memory_class": memory_class})
    # The vector copy is optional and is never created for rejected,
    # quarantined, or confirmation-pending memories.
    if state["lifecycle"] == "active":
        try:
            from .vector_index import index_capsule

            native_index = index_capsule(capsule_id=capsule_id, content=content, index_refs=index_refs)
        except Exception:
            record("kylin_sdk_vector_index", {"capsule_id": capsule_id, "status": "fallback"})
            native_index = {"backend": "fts_fallback", "indexed": False, "reason": "native_index_exception"}
    return {
        "capsule_id": capsule_id,
        "memory_class": memory_class,
        "governance": governance,
        "state": state,
        "audit_id": audit_id,
        "native_index": native_index,
    }


_JSON_COLUMNS = [
    "content", "source_events", "provenance", "governance", "state",
    "production_context", "alignment_metadata", "affective_metadata",
    "relation_edges", "index_refs",
]


def _row_to_capsule(row: Any) -> dict[str, Any]:
    """Deserialize a memory_capsules_v2 row into a capsule dict."""
    d = dict(row)
    for key in _JSON_COLUMNS:
        d[key] = loads(d[key], {} if key != "relation_edges" else [])
    return d


def get_capsule(capsule_id: str) -> dict[str, Any] | None:
    row = get_conn().execute("SELECT * FROM memory_capsules_v2 WHERE capsule_id=?", (capsule_id,)).fetchone()
    if not row:
        return None
    return _row_to_capsule(row)


def get_capsules_batch(capsule_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch multiple capsules in a single query (avoids N+1).

    Returns a mapping of capsule_id -> capsule dict. Missing ids are omitted.
    Preserves no particular order; callers should order via capsule_ids.
    """
    if not capsule_ids:
        return {}
    placeholders = ",".join("?" for _ in capsule_ids)
    rows = get_conn().execute(
        f"SELECT * FROM memory_capsules_v2 WHERE capsule_id IN ({placeholders})",
        tuple(capsule_ids),
    ).fetchall()
    return {row["capsule_id"]: _row_to_capsule(row) for row in rows}


def list_capsules(limit: int = 50) -> list[dict[str, Any]]:
    rows = get_conn().execute(
        """
        SELECT capsule_id FROM memory_capsules_v2
        WHERE json_extract(state,'$.lifecycle') NOT IN ('forgotten','deleted','rejected')
        ORDER BY created_at DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    ids = [r["capsule_id"] for r in rows]
    by_id = get_capsules_batch(ids)
    return [by_id[i] for i in ids if i in by_id]


def update_capsule(capsule_id: str, *, state: dict[str, Any] | None = None, relation_edges: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    cap = get_capsule(capsule_id)
    if not cap:
        raise KeyError(capsule_id)
    new_state = state or cap["state"]
    new_edges = relation_edges if relation_edges is not None else cap["relation_edges"]
    with transaction() as conn:
        conn.execute(
            "UPDATE memory_capsules_v2 SET state=?, relation_edges=?, updated_at=? WHERE capsule_id=?",
            (dumps(new_state), dumps(new_edges), now(), capsule_id),
        )
    record("capsule_update", {"capsule_id": capsule_id, "state": new_state})
    return get_capsule(capsule_id)


def bump_usage_batch(updates: list[tuple[str, dict[str, Any]]]) -> None:
    """Persist usage-count/state updates for many capsules in one round-trip.

    ``updates`` is a list of (capsule_id, new_state) pairs. Uses a single
    ``executemany`` plus one aggregated audit record, replacing the per-capsule
    get+update+audit+get chain that caused N+1 query amplification in the
    retrieval hot path.
    """
    if not updates:
        return
    ts = now()
    with transaction() as conn:
        conn.executemany(
            """
            UPDATE memory_capsules_v2
            SET state=json_set(
                    state,
                    '$.usage_count', COALESCE(CAST(json_extract(state,'$.usage_count') AS INTEGER), 0) + 1,
                    '$.last_accessed_at', ?
                ),
                updated_at=?
            WHERE capsule_id=?
              AND json_extract(state,'$.lifecycle') IN ('active','reinforced','conflicted')
              AND json_extract(governance,'$.policy_result') IN ('allow','redact')
            """,
            [(state.get("last_accessed_at") or ts, ts, cid) for cid, state in updates],
        )
    record("capsule_usage_batch", {"capsule_ids": [cid for cid, _ in updates], "count": len(updates)})


def forget_capsules_in_transaction(conn, capsule_ids: list[str], *, mode: str = "soft_delete") -> dict[str, Any]:
    """Apply local forget state using the caller's transaction."""
    from .vector_index import mark_vectors_delete_pending_in_transaction

    deleted: list[str] = []
    unique_ids = list(dict.fromkeys(capsule_ids))
    if unique_ids:
        placeholders = ",".join("?" for _ in unique_ids)
        rows = conn.execute(
            f"SELECT capsule_id,state FROM memory_capsules_v2 WHERE capsule_id IN ({placeholders})",
            unique_ids,
        ).fetchall()
    else:
        rows = []
    by_id = {row["capsule_id"]: row for row in rows}
    timestamp = now()
    for capsule_id in unique_ids:
        row = by_id.get(capsule_id)
        if not row:
            continue
        state = loads(row["state"], {})
        state["lifecycle"] = "forgotten" if mode != "hard_delete" else "deleted"
        state["forgotten_at"] = timestamp
        if mode == "hard_delete":
            conn.execute("DELETE FROM memory_capsules_v2 WHERE capsule_id=?", (capsule_id,))
        else:
            conn.execute(
                "UPDATE memory_capsules_v2 SET state=?, updated_at=? WHERE capsule_id=?",
                (dumps(state), timestamp, capsule_id),
            )
        conn.execute("DELETE FROM memory_capsules_v2_fts WHERE capsule_id=?", (capsule_id,))
        deleted.append(capsule_id)
    native_vector = mark_vectors_delete_pending_in_transaction(conn, deleted)
    return {
        "status": "forgotten",
        "deleted_capsule_ids": deleted,
        "native_vector": native_vector,
    }


def forget_capsules(capsule_ids: list[str], *, mode: str = "soft_delete") -> dict[str, Any]:
    init_runtime_schema()
    conn = get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        result = forget_capsules_in_transaction(conn, capsule_ids, mode=mode)
        audit_id = record_in_transaction(
            conn,
            "forget_confirm",
            {"deleted_capsule_ids": result["deleted_capsule_ids"], "mode": mode},
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    try:
        from .vector_index import remove_vectors

        native_vector = remove_vectors(result["deleted_capsule_ids"])
    except Exception:
        native_vector = {
            "backend": "fts_fallback",
            "deleted_vector_ids": [],
            "pending_vector_ids": result["native_vector"]["pending_vector_ids"],
            "reason": "native_delete_status_unknown",
        }
    return {
        "status": "forgotten",
        "deleted_capsule_ids": result["deleted_capsule_ids"],
        "audit_id": audit_id,
        "native_vector": native_vector,
    }


def allowed_for_context(cap: dict[str, Any], *, high_risk: bool = False) -> bool:
    gov = cap["governance"]
    state = cap["state"]
    if gov.get("policy_result") not in RETRIEVABLE_POLICY:
        return False
    if gov.get("sensitivity_level") == "S3":
        return False
    if state.get("lifecycle") not in RETRIEVABLE_LIFECYCLE:
        return False
    if high_risk and state.get("lifecycle") == "conflicted":
        return False
    return True
