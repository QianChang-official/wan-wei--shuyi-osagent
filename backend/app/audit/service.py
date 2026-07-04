import uuid,json,datetime
from ..db import get_conn
def record(event_type:str,payload:dict)->str:
    audit_id='audit_'+uuid.uuid4().hex[:12]
    conn=get_conn(); conn.execute('INSERT INTO audit_logs VALUES (?,?,?,?)',(audit_id,event_type,json.dumps(payload,ensure_ascii=False),datetime.datetime.utcnow().isoformat())); conn.commit(); return audit_id

def list_logs(limit:int=50,trace_id:str|None=None)->list[dict]:
    capped=max(1,min(limit,200))
    conn=get_conn()
    if trace_id:
        rows=conn.execute(
            'SELECT * FROM audit_logs WHERE payload LIKE ? ORDER BY created_at DESC LIMIT ?',
            (f'%"trace_id": "{trace_id}"%',capped),
        ).fetchall()
    else:
        rows=conn.execute('SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT ?',(capped,)).fetchall()
    return [dict(r) for r in rows]
