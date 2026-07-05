import json
import uuid
from typing import Any

from ..db import get_conn
from ..audit.service import record
from ..utils.datetime_utils import utc_now_iso_compact
from .policy_gate import evaluate_policy

BLOCKED_POLICY = {"reject", "quarantine"}
BLOCKED_LIFECYCLE = {"quarantined", "forgotten", "rolled_back", "deprecated"}


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
    from ..init_db import main
    main()


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

    conn = get_conn()
    conn.execute(
        """INSERT INTO memory_capsules_v2 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            capsule_id, memory_class, dumps(content), dumps([]), dumps(provenance), dumps(governance),
            dumps(state), dumps(production_context), dumps(alignment_metadata), dumps({}),
            dumps(relation_edges), dumps(index_refs), created, created,
        ),
    )
    if governance["policy_result"] not in {"reject"}:
        conn.execute("INSERT INTO memory_capsules_v2_fts(capsule_id,text) VALUES (?,?)", (capsule_id, text))
    conn.commit()
    audit_id = record("capsule_write", {"capsule_id": capsule_id, "policy_result": governance["policy_result"], "memory_class": memory_class})
    return {"capsule_id": capsule_id, "memory_class": memory_class, "governance": governance, "state": state, "audit_id": audit_id}


def get_capsule(capsule_id: str) -> dict[str, Any] | None:
    row = get_conn().execute("SELECT * FROM memory_capsules_v2 WHERE capsule_id=?", (capsule_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    for key in ["content", "source_events", "provenance", "governance", "state", "production_context", "alignment_metadata", "affective_metadata", "relation_edges", "index_refs"]:
        d[key] = loads(d[key], {} if key != "relation_edges" else [])
    return d


def list_capsules(limit: int = 50) -> list[dict[str, Any]]:
    rows = get_conn().execute(
        """
        SELECT capsule_id FROM memory_capsules_v2
        WHERE json_extract(state,'$.lifecycle') NOT IN ('forgotten','deleted','rejected')
        ORDER BY created_at DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [get_capsule(r["capsule_id"]) for r in rows]


def update_capsule(capsule_id: str, *, state: dict[str, Any] | None = None, relation_edges: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    cap = get_capsule(capsule_id)
    if not cap:
        raise KeyError(capsule_id)
    new_state = state or cap["state"]
    new_edges = relation_edges if relation_edges is not None else cap["relation_edges"]
    get_conn().execute(
        "UPDATE memory_capsules_v2 SET state=?, relation_edges=?, updated_at=? WHERE capsule_id=?",
        (dumps(new_state), dumps(new_edges), now(), capsule_id),
    ).connection.commit()
    record("capsule_update", {"capsule_id": capsule_id, "state": new_state})
    return get_capsule(capsule_id)


def forget_capsules(capsule_ids: list[str], *, mode: str = "soft_delete") -> dict[str, Any]:
    init_runtime_schema()
    deleted: list[str] = []
    conn = get_conn()
    for capsule_id in capsule_ids:
        cap = get_capsule(capsule_id)
        if not cap:
            continue
        state = cap["state"]
        state["lifecycle"] = "forgotten" if mode != "hard_delete" else "deleted"
        state["forgotten_at"] = now()
        conn.execute(
            "UPDATE memory_capsules_v2 SET state=?, updated_at=? WHERE capsule_id=?",
            (dumps(state), now(), capsule_id),
        )
        conn.execute("DELETE FROM memory_capsules_v2_fts WHERE capsule_id=?", (capsule_id,))
        deleted.append(capsule_id)
    conn.commit()
    audit_id = record("forget_confirm", {"deleted_capsule_ids": deleted, "mode": mode})
    return {"status": "forgotten", "deleted_capsule_ids": deleted, "audit_id": audit_id}


def allowed_for_context(cap: dict[str, Any], *, high_risk: bool = False) -> bool:
    gov = cap["governance"]
    state = cap["state"]
    if gov.get("policy_result") in BLOCKED_POLICY:
        return False
    if gov.get("sensitivity_level") == "S3":
        return False
    if state.get("lifecycle") in BLOCKED_LIFECYCLE:
        return False
    if high_risk and state.get("lifecycle") == "conflicted":
        return False
    return True
