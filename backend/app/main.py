import uuid,json,datetime
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from .schemas import MemoryEventIn,ForgetPreviewIn,ForgetConfirmIn,CapsuleWriteIn,CommandLoopIn,ReflectionIn
from .db import get_conn
from .guardrail.service import evaluate
from .audit.service import record
from .retrieval.service import search as do_search
from .memory_runtime.capsule_store import write_capsule, list_capsules, get_capsule
from .memory_runtime.retrieval import search_capsules
from .memory_runtime.command_loop import run_command_loop
from .memory_runtime.evolution import reflect_task
from .platform.service import list_modules, module_summary
from .model_gateway.schemas import ModelGatewayTestIn
from .model_gateway.service import list_providers, test_provider
from .tool_registry.service import list_skills, list_tools
from .tuning.service import get_defaults, list_policy_modes
from .export_center.service import list_packages
from .research_adoption.service import list_routes as list_adoption_routes, list_technologies, version_map

app=FastAPI(title='宛委·枢忆 MemoryOps Autopilot Platform')

# Mount frontend console at /console (same-origin, no CORS needed).
# Prefer the built Vue SPA (console-vue/dist); fall back to the single-file console.
_frontend = Path(__file__).parent.parent.parent / "frontend"
_vue_dist = _frontend / "console-vue" / "dist"
_legacy_console = _frontend / "web-console"
if _vue_dist.exists():
    app.mount("/console", StaticFiles(directory=str(_vue_dist), html=True), name="console")
if _legacy_console.exists():
    app.mount("/console-legacy", StaticFiles(directory=str(_legacy_console), html=True), name="console-legacy")

@app.on_event('startup')
def _startup():
    try:
        from .init_db import main as init_db
        init_db()
    except Exception:
        pass

@app.get('/health')
def health(): return {'status':'ok','name':'wanwei-shuyi-memoryops-autopilot','version':'v0.8-authoritative-tech-adoption'}

# v0.7 platform cockpit endpoints
@app.get('/platform/modules')
def platform_modules(status: str | None = None):
    return {'items': list_modules(status), 'summary': module_summary()}

@app.get('/model-gateway/providers')
def model_gateway_providers():
    return list_providers()

@app.post('/model-gateway/test')
def model_gateway_test(req: ModelGatewayTestIn):
    return test_provider(req)

@app.get('/tool-registry/tools')
def tool_registry_tools():
    return list_tools()

@app.get('/tool-registry/skills')
def tool_registry_skills():
    return list_skills()

@app.get('/tuning/defaults')
def tuning_defaults():
    return get_defaults()

@app.get('/tuning/policies')
def tuning_policies():
    return list_policy_modes()

@app.get('/exports/packages')
def export_packages():
    return list_packages()

# v0.8 authoritative technology adoption endpoints
@app.get('/research-adoption/technologies')
def research_adoption_technologies():
    return list_technologies()

@app.get('/research-adoption/routes')
def research_adoption_routes():
    return list_adoption_routes()

@app.get('/research-adoption/version-map')
def research_adoption_version_map():
    return version_map()

# legacy v0.2/v0.3 endpoint kept for compatibility
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

# v0.6 MemoryOps Runtime endpoints
@app.post('/memory/v2/capsules')
def v2_write_capsule(req: CapsuleWriteIn):
    return write_capsule(**req.dict())

@app.get('/memory/v2/capsules')
def v2_list_capsules(limit:int=50):
    return {'items': list_capsules(limit)}

@app.get('/memory/v2/capsules/{capsule_id}')
def v2_get_capsule(capsule_id: str):
    return get_capsule(capsule_id) or {'error':'not_found','capsule_id':capsule_id}

@app.get('/memory/v2/search')
def v2_search(q:str,top_k:int=5,high_risk:bool=False):
    from .memory_runtime.evidence import build_evidence_card
    results=search_capsules(q,top_k=top_k,high_risk=high_risk)
    return {'query':q,'results':results,'evidence_cards':[build_evidence_card(r) for r in results]}

@app.post('/memory/v2/command')
def v2_command(req: CommandLoopIn):
    return run_command_loop(goal=req.goal, scene=req.scene, top_k=req.top_k)

@app.post('/memory/v2/reflection')
def v2_reflection(req: ReflectionIn):
    return reflect_task(req.task_id, req.dict())

@app.get('/audit/logs')
def audit_logs(limit:int=20):
    rows=get_conn().execute('SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT ?',(limit,)).fetchall(); return {'items':[dict(r) for r in rows]}
