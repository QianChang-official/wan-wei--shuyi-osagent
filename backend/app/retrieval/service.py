from ..db import get_conn


def search(q:str, scene:str='general', top_k:int=5):
    conn=get_conn()
    try:
        rows=conn.execute(
            'SELECT e.event_id,e.source_type,e.scene,e.content,e.trust_score FROM memory_fts f JOIN memory_events e ON f.event_id=e.event_id WHERE memory_fts MATCH ? LIMIT ?',
            (q,top_k),
        ).fetchall()
    except Exception:
        return []
    return [dict(r) for r in rows]
