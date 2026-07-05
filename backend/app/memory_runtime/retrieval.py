from __future__ import annotations

import re
from typing import Any

from ..db import get_conn
from .capsule_store import get_capsules_batch, allowed_for_context, bump_usage_batch, now


def _has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def _zh_terms(q: str) -> list[str]:
    q = q.strip().replace('"', ' ')
    if not q:
        return []
    parts = [p for p in re.split(r"\s+", q) if p]
    terms: list[str] = []
    for part in parts:
        terms.append(part)
        if _has_cjk(part) and len(part) >= 3:
            terms.extend(part[i:i+2] for i in range(len(part)-1))
    seen = []
    for term in terms:
        if term and term not in seen:
            seen.append(term)
    return seen


def _match_query(q: str) -> str:
    parts = [p for p in q.replace('"', ' ').split() if p]
    return " OR ".join(parts) if parts else q


def _fts_rows(conn, q: str, limit: int):
    try:
        return conn.execute(
            "SELECT capsule_id FROM memory_capsules_v2_fts WHERE memory_capsules_v2_fts MATCH ? LIMIT ?",
            (_match_query(q), limit),
        ).fetchall()
    except Exception:
        return []


def _substring_rows(conn, q: str, limit: int):
    terms = _zh_terms(q)
    if not terms:
        return []
    clauses = " OR ".join(["content LIKE ?" for _ in terms])
    params: list[Any] = [f"%{term}%" for term in terms]
    params.append(limit)
    return conn.execute(
        f"""
        SELECT capsule_id FROM memory_capsules_v2
        WHERE ({clauses})
          AND json_extract(state,'$.lifecycle') NOT IN ('forgotten','deleted','rejected','quarantined')
        ORDER BY updated_at DESC LIMIT ?
        """,
        params,
    ).fetchall()


def search_capsules(q: str, *, top_k: int = 5, high_risk: bool = False) -> list[dict[str, Any]]:
    conn = get_conn()
    rows = _fts_rows(conn, q, top_k * 4)
    if _has_cjk(q):
        seen = {r["capsule_id"] for r in rows}
        for row in _substring_rows(conn, q, top_k * 4):
            if row["capsule_id"] not in seen:
                rows.append(row)
                seen.add(row["capsule_id"])
    # Batch-fetch all candidates in a single query (avoids N+1).
    candidate_ids = [r["capsule_id"] for r in rows]
    by_id = get_capsules_batch(candidate_ids)
    accessed_at = now()
    out = []
    updates: list[tuple[str, dict[str, Any]]] = []
    for capsule_id in candidate_ids:
        cap = by_id.get(capsule_id)
        if not cap or not allowed_for_context(cap, high_risk=high_risk):
            continue
        gov = cap["governance"]; state = cap["state"]
        score = 0.35 + 0.25 * float(gov.get("trust_score", 0)) + 0.20 * float(gov.get("confidence", 0)) + 0.05 * float(state.get("retention_score", 0))
        cap["retrieval_score"] = round(score, 4)
        state["usage_count"] = int(state.get("usage_count") or 0) + 1
        state["last_accessed_at"] = accessed_at
        updates.append((capsule_id, state))
        out.append(cap)
        if len(out) >= top_k:
            break
    # Batch-update usage counts in a single executemany + one aggregated audit.
    bump_usage_batch(updates)
    return out
