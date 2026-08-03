import logging

from ..db import get_conn

logger = logging.getLogger(__name__)


def _match_query(q: str) -> str:
    parts = [p for p in q.replace('"', ' ').split() if p]
    return ' OR '.join(f'"{part}"' for part in parts) if parts else '""'


def search(
    q: str,
    top_k: int = 5,
    *,
    owner_id: str | None = None,
    soul_id: str | None = None,
):
    if not q or not q.strip():
        return []
    conn = get_conn()
    clauses = ["memory_fts MATCH ?"]
    params: list[object] = [_match_query(q)]
    if owner_id is not None:
        clauses.append("e.owner_id=?")
        params.append(owner_id)
    if soul_id is not None:
        clauses.append("(e.soul_id=? OR e.soul_id IS NULL)")
        params.append(soul_id)
    params.append(top_k)
    try:
        rows = conn.execute(
            "SELECT e.event_id,e.source_type,e.scene,e.content,e.trust_score "
            "FROM memory_fts f JOIN memory_events e ON f.event_id=e.event_id "
            f"WHERE {' AND '.join(clauses)} LIMIT ?",
            params,
        ).fetchall()
    except Exception as exc:
        # SQLite/驱动异常文本可能回显 MATCH 输入，因此只记异常类型；这既让
        # 降级可观测，又不会把潜在敏感查询写入日志。
        logger.warning('legacy FTS 检索失败，降级为空结果（%s）', type(exc).__name__)
        return []
    return [dict(r) for r in rows]
