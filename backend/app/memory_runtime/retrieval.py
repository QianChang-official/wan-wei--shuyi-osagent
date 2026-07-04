from typing import Any
from ..db import get_conn
from .capsule_store import get_capsule, allowed_for_context, update_capsule, now


def _match_query(q: str) -> str:
    # FTS5 is strict; use OR for plain multi-word queries.
    parts = [p for p in q.replace('"', ' ').split() if p]
    return " OR ".join(parts) if parts else q


def search_capsules(q: str, *, top_k: int = 5, high_risk: bool = False) -> list[dict[str, Any]]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT capsule_id FROM memory_capsules_v2_fts WHERE memory_capsules_v2_fts MATCH ? LIMIT ?",
            (_match_query(q), top_k * 4),
        ).fetchall()
    except Exception:
        rows = []
    if not rows:
        # Chinese production goals may not tokenize into FTS terms predictably.
        # For the Lite runtime, fall back to latest eligible capsules so the
        # command loop can still demonstrate governance + evidence cards.
        rows = conn.execute("SELECT capsule_id FROM memory_capsules_v2 ORDER BY updated_at DESC LIMIT ?", (top_k * 4,)).fetchall()
    out = []
    for r in rows:
        cap = get_capsule(r["capsule_id"])
        if not cap or not allowed_for_context(cap, high_risk=high_risk):
            continue
        gov = cap["governance"]; state = cap["state"]
        score = 0.35 + 0.25 * float(gov.get("trust_score", 0)) + 0.20 * float(gov.get("confidence", 0)) + 0.05 * float(state.get("retention_score", 0))
        cap["retrieval_score"] = round(score, 4)
        state["usage_count"] = int(state.get("usage_count") or 0) + 1
        state["last_accessed_at"] = now()
        update_capsule(cap["capsule_id"], state=state)
        out.append(cap)
        if len(out) >= top_k:
            break
    return out
