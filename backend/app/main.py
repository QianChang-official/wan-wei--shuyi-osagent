import uuid,json,datetime
from fastapi import FastAPI
from .schemas import MemoryEventIn,ForgetPreviewIn,ForgetConfirmIn
from .db import get_conn
from .guardrail.service import evaluate
from .audit.service import record
from .retrieval.service import search as do_search
app=FastAPI(title='宛委·枢忆 OSAgent')
@app.get('/health')
def health(): return {'status':'ok','name':'wanwei-shuyi-osagent'}
@app.post('/memory/events')
def add_event(event:MemoryEventIn):
    event_id='evt_'+uuid.uuid4().hex[:12]; text=json.dumps(event.content,ensure_ascii=False); guard=evaluate(text); quality=0.9 if len(text)>8 else 0.5
    conn=get_conn(); conn.execute('INSERT INTO memory_events VALUES (?,?,?,?,?,?,?,?)',(event_id,event.source_type,event.scene,text,quality,guard['sensitivity_level'],guard['trust_score'],datetime.datetime.utcnow().isoformat())); conn.execute('INSERT INTO memory_fts(event_id,content) VALUES (?,?)',(event_id,text))
    capsule_id='cap_'+uuid.uuid4().hex[:12]; lifecycle='quarantined' if guard['sensitivity_level']=='S3' else 'active'; conn.execute('INSERT INTO memory_capsules VALUES (?,?,?,?,?,?)',(capsule_id,'event',text,lifecycle,guard['trust_score'],datetime.datetime.utcnow().isoformat())); conn.commit()
    audit_id=record('memory_write',{'event_id':event_id,'capsule_id':capsule_id,'guard':guard}); return {'event_id':event_id,'capsule_id':capsule_id,'quality_score':quality,**guard,'audit_id':audit_id}
@app.get('/memory/search')
def search(q:str,scene:str='general',top_k:int=5):
    results=do_search(q,scene,top_k); evidence=[{'source_event_id':r['event_id'],'source_type':r['source_type'],'trust_score':r['trust_score'],'actions':['view_source','correct','forget']} for r in results]
    return {'query':q,'results':results,'evidence_cards':evidence}
@app.post('/memory/forget/preview')
def forget_preview(req:ForgetPreviewIn):
    candidates=do_search(req.instruction,'general',10); forget_request_id='forget_'+uuid.uuid4().hex[:12]; record('forget_preview',{'forget_request_id':forget_request_id,'instruction':req.instruction,'candidates':candidates}); return {'forget_request_id':forget_request_id,'candidates':candidates}
@app.post('/memory/forget/confirm')
def forget_confirm(req:ForgetConfirmIn):
    audit_id=record('forget_confirm',req.dict()); return {'status':'recorded','audit_id':audit_id}
@app.get('/audit/logs')
def audit_logs(limit:int=20):
    rows=get_conn().execute('SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT ?',(limit,)).fetchall(); return {'items':[dict(r) for r in rows]}
