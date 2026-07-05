import uuid,json,datetime
from ..db import get_conn
from ..security.redaction import redact_audit_payload


def _ensure_audit_table(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS audit_logs(audit_id TEXT PRIMARY KEY, event_type TEXT, payload TEXT, created_at TEXT)')
    conn.commit()


def record(event_type:str,payload:dict)->str:
    """Record audit event with sensitive data redaction."""
    audit_id='audit_'+uuid.uuid4().hex[:12]
    conn=get_conn(); _ensure_audit_table(conn)
    # Redact sensitive data before storing
    safe_payload = redact_audit_payload(payload)
    conn.execute('INSERT INTO audit_logs VALUES (?,?,?,?)',(audit_id,event_type,json.dumps(safe_payload,ensure_ascii=False),datetime.datetime.utcnow().isoformat())); conn.commit(); return audit_id


def list_logs(limit:int=50,trace_id:str|None=None)->list[dict]:
    capped=max(1,min(limit,200))
    conn=get_conn(); _ensure_audit_table(conn)
    if trace_id:
        rows=conn.execute(
            'SELECT * FROM audit_logs WHERE payload LIKE ? ORDER BY created_at DESC LIMIT ?',
            (f'%"trace_id": "{trace_id}"%',capped),
        ).fetchall()
    else:
        rows=conn.execute('SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT ?',(capped,)).fetchall()
    return [dict(r) for r in rows]
