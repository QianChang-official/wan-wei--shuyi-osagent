from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any

from ..db import get_conn
from .capsule_store import get_capsules_batch, allowed_for_context, bump_usage_batch, now
from .vector_index import PROVIDER, native_candidates

logger = logging.getLogger(__name__)

# 03-#15 搜索读路径写放大降频：
# usage_count / last_accessed_at 是统计性元数据。此前每次 search 都对全部命中
# 批量 UPDATE 一次并写一条聚合审计行，前端轮询/重试同一查询会造成 O(搜索次数)
# 的写放大与审计噪音。现按 capsule 做时间窗合并：同一 capsule 在窗口内的重复
# 命中只在首次落库，窗口外的命中再次落库。语义注释：
#   - 使用统计「最终一致」——窗口内被合并的访问不重复计数（这本身是期望语义：
#     短时间反复读到同一条记忆，按一次使用计）。
#   - _recent_usage_bumps 只保存「最近落库时间」的内存标记，不含未落盘数据，
#     进程退出不会有缓冲丢失；重启后窗口自然失效，下一次命中照常落库。
_USAGE_BUMP_MIN_INTERVAL_SECONDS = 60.0
_USAGE_BUMP_CACHE_MAX = 10000
_recent_usage_bumps: dict[str, float] = {}
_recent_usage_bumps_lock = threading.Lock()


def _usage_bump_due(capsule_id: str) -> bool:
    """判断并标记该 capsule 的 usage 落库是否到达时间窗（线程安全）。"""
    now_mono = time.monotonic()
    with _recent_usage_bumps_lock:
        if len(_recent_usage_bumps) >= _USAGE_BUMP_CACHE_MAX:
            _recent_usage_bumps.clear()
        last = _recent_usage_bumps.get(capsule_id)
        if last is not None and now_mono - last < _USAGE_BUMP_MIN_INTERVAL_SECONDS:
            return False
        _recent_usage_bumps[capsule_id] = now_mono
        return True


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
    return " OR ".join(f'"{part}"' for part in parts) if parts else q


def _fts_rows(conn, q: str, limit: int, *, failed_collection: str | None = None):
    try:
        failed_join = ""
        params: list[Any] = []
        if failed_collection is not None:
            failed_join = """
                JOIN memory_vector_refs AS ref
                  ON ref.capsule_id=memory_capsules_v2_fts.capsule_id
                 AND ref.provider=? AND ref.collection_name=? AND ref.status='index_failed'
            """
            params.extend((PROVIDER, failed_collection))
        params.extend((_match_query(q), limit))
        return conn.execute(
            f"""
            SELECT memory_capsules_v2_fts.capsule_id
            FROM memory_capsules_v2_fts
            JOIN memory_capsules_v2 AS capsule
              ON capsule.capsule_id=memory_capsules_v2_fts.capsule_id
            {failed_join}
            WHERE memory_capsules_v2_fts MATCH ?
              AND json_extract(capsule.state,'$.lifecycle') IN ('active','reinforced','conflicted')
              AND json_extract(capsule.governance,'$.policy_result') IN ('allow','redact')
            LIMIT ?
            """,
            params,
        ).fetchall()
    except Exception as exc:
        # 03-#16: 降级但不静默——FTS 出错（如 MATCH 语法/缺表）记 warning，
        # 返回空后由 substring/原生通道兜底。
        logger.warning("FTS 检索失败，降级为空结果（substring/native 通道仍可命中）: %s", exc)
        return []


def _substring_rows(conn, q: str, limit: int, *, failed_collection: str | None = None):
    terms = _zh_terms(q)
    if not terms:
        return []
    clauses = " OR ".join(["content LIKE ?" for _ in terms])
    failed_join = ""
    params: list[Any] = []
    if failed_collection is not None:
        failed_join = """
            JOIN memory_vector_refs AS ref
              ON ref.capsule_id=capsule.capsule_id
             AND ref.provider=? AND ref.collection_name=? AND ref.status='index_failed'
        """
        params.extend((PROVIDER, failed_collection))
    params.extend(f"%{term}%" for term in terms)
    params.append(limit)
    return conn.execute(
        f"""
        SELECT capsule.capsule_id FROM memory_capsules_v2 AS capsule
        {failed_join}
        WHERE ({clauses})
          AND json_extract(capsule.state,'$.lifecycle') IN ('active','reinforced','conflicted')
          AND json_extract(capsule.governance,'$.policy_result') IN ('allow','redact')
        ORDER BY capsule.updated_at DESC LIMIT ?
        """,
        params,
    ).fetchall()


def _fts_candidate_ids(q: str, *, limit: int, failed_collection: str | None = None) -> list[str]:
    conn = get_conn()
    rows = _fts_rows(conn, q, limit, failed_collection=failed_collection)
    if _has_cjk(q):
        seen = {r["capsule_id"] for r in rows}
        for row in _substring_rows(conn, q, limit, failed_collection=failed_collection):
            if row["capsule_id"] not in seen:
                rows.append(row)
                seen.add(row["capsule_id"])
    return [r["capsule_id"] for r in rows]


def _normalized_native_score(score: float) -> float:
    # The official default metric is cosine, which can range from -1 to 1.
    return min(1.0, max(0.0, (score + 1.0) / 2.0))


def search_capsules_with_status(q: str, *, top_k: int = 5, high_risk: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    native_rows, status = native_candidates(q, top_k=top_k * 4)
    native_scores: dict[str, float] = {}
    fts_fallback_ids: set[str] = set()
    if native_rows is None:
        candidate_ids = _fts_candidate_ids(q, limit=top_k * 4)
    else:
        candidate_ids = []
        for capsule_id, raw_score in native_rows:
            if capsule_id not in native_scores:
                candidate_ids.append(capsule_id)
                native_scores[capsule_id] = raw_score
        # An isolated permanently-unindexable Capsule must not disable native
        # retrieval for every other Capsule.  Preserve it through a narrow,
        # observable FTS fallback instead of a whole-index fallback.
        failed_collection = None
        if status.get("native_index", {}).get("failed"):
            failed_collection = status.get("collection")
        for capsule_id in _fts_candidate_ids(q, limit=top_k * 4, failed_collection=failed_collection):
            if capsule_id not in native_scores:
                candidate_ids.append(capsule_id)
                fts_fallback_ids.add(capsule_id)

    # Batch-fetch all candidates in a single query (avoids N+1).
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
        if capsule_id in native_scores:
            semantic_score = _normalized_native_score(native_scores[capsule_id])
            score = 0.15 + 0.20 * semantic_score + 0.25 * float(gov.get("trust_score", 0)) + 0.20 * float(gov.get("confidence", 0)) + 0.05 * float(state.get("retention_score", 0))
            cap["vector_score"] = round(native_scores[capsule_id], 4)
        cap["retrieval_score"] = round(score, 4)
        cap["retrieval_backend"] = "fts_fallback" if capsule_id in fts_fallback_ids else status["backend"]
        if capsule_id in fts_fallback_ids:
            cap["retrieval_fallback_reason"] = "native_index_failed_capsule"
        elif status.get("fallback_reason") and status["backend"] == "fts_fallback":
            cap["retrieval_fallback_reason"] = status["fallback_reason"]
        # 03-#15: 时间窗内重复命中的 capsule 跳过落库（内存计数同步跳过，
        # 保持响应与库内一致）；窗口外命中照常累计并批量落库。
        if _usage_bump_due(capsule_id):
            state["usage_count"] = int(state.get("usage_count") or 0) + 1
            state["last_accessed_at"] = accessed_at
            updates.append((capsule_id, state))
        out.append(cap)
        if len(out) >= top_k:
            break
    # Batch-update usage counts in a single executemany + one aggregated audit.
    bump_usage_batch(updates)
    return out, status


def search_capsules(q: str, *, top_k: int = 5, high_risk: bool = False) -> list[dict[str, Any]]:
    """Compatibility wrapper for internal callers that expect only result rows."""
    results, _ = search_capsules_with_status(q, top_k=top_k, high_risk=high_risk)
    return results
