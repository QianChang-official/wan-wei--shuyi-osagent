from ..db import get_conn


def _match_query(q: str) -> str:
    parts = [p for p in q.replace('"', ' ').split() if p]
    return ' OR '.join(f'"{part}"' for part in parts) if parts else '""'


def search(q: str, top_k: int = 5):
    if not q or not q.strip():
        return []
    conn = get_conn()
    try:
        rows = conn.execute(
            'SELECT e.event_id,e.source_type,e.scene,e.content,e.trust_score FROM memory_fts f JOIN memory_events e ON f.event_id=e.event_id WHERE memory_fts MATCH ? LIMIT ?',
            (_match_query(q), top_k),
        ).fetchall()
    except Exception:
        return []
    return [dict(r) for r in rows]
