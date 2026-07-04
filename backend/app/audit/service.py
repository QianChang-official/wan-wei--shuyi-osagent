import uuid,json,datetime
from ..db import get_conn
def record(event_type:str,payload:dict)->str:
    audit_id='audit_'+uuid.uuid4().hex[:12]
    conn=get_conn(); conn.execute('INSERT INTO audit_logs VALUES (?,?,?,?)',(audit_id,event_type,json.dumps(payload,ensure_ascii=False),datetime.datetime.utcnow().isoformat())); conn.commit(); return audit_id
