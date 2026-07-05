import uuid,json,datetime
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from .security.auth import APIKeyMiddleware
from .schemas import MemoryEventIn,ForgetPreviewIn,ForgetConfirmIn,CapsuleWriteIn,CommandLoopIn,ReflectionIn
from .db import get_conn
from .memory_runtime.policy_gate import evaluate_policy
from .audit.service import list_logs, record
from .retrieval.service import search as do_search
from .memory_runtime.capsule_store import write_capsule, list_capsules, get_capsule, forget_capsules
from .memory_runtime.retrieval import search_capsules
from .memory_runtime.command_loop import run_command_loop
from .memory_runtime.evolution import reflect_task
from .platform.service import list_modules, module_summary
from .model_gateway.schemas import ModelGatewayTestIn
from .model_gateway.service import list_providers, run_provider_test
from .tool_registry.service import list_skills, list_tools
from .tuning.service import get_defaults, list_policy_modes
from .export_center.service import list_packages
from .research_adoption.service import list_routes as list_adoption_routes, list_technologies, version_map
from .workflow.service import (
    VERSION as WORKFLOW_VERSION,
    WorkflowRunIn,
    competition_mapping as workflow_competition_mapping,
    create_run as workflow_create_run,
    get_artifacts as workflow_get_artifacts,
    get_run as workflow_get_run,
    get_trace as workflow_get_trace,
    run_dry_run as workflow_run_dry_run,
    workflow_design,
)
from .deepening.service import (
    InterrogationAnswerIn,
    ReasoningDepthSimulateIn,
    RedQueenEvaluateIn,
    VisualChecklistIn,
    answer_dry_run as deepening_answer_dry_run,
    drift_check as deepening_drift_check,
    evaluator_design as deepening_evaluator_design,
    pathways as deepening_pathways,
    questions as deepening_questions,
    reasoning_depth_design as deepening_reasoning_depth_design,
    reasoning_depth_simulate as deepening_reasoning_depth_simulate,
    redqueen_evaluate_dry_run as deepening_redqueen_evaluate_dry_run,
    session_core_demo_trace as deepening_session_core_demo_trace,
    session_core_design as deepening_session_core_design,
    source_of_truth as deepening_source_of_truth,
    visual_checklist_dry_run as deepening_visual_checklist_dry_run,
    visual_protocol as deepening_visual_protocol,
)
from .reproduction.service import (
    HippoRecallIn,
    MemoryToolDryRunIn,
    ReflexionEvaluateIn,
    RetentionSimulateIn,
    evaluator as reproduction_reflexion_evaluator,
    generative_template,
    hippo_graph,
    hippo_recall,
    list_systems as list_reproduction_systems,
    list_tools as list_memory_tools,
    locomo_template,
    memcube_schema,
    memory_tiers,
    memory_tool_dry_run,
    retention_simulate,
    retention_state,
    reflexion_evaluate,
    workbench as reproduction_workbench,
)

_prod_mode = __import__('os').getenv('WANWEI_PRODUCTION', '').lower() in {'1','true','yes'}
app=FastAPI(
    title='宛委·枢忆 MemoryOps Autopilot Platform',
    docs_url=None if _prod_mode else '/docs',
    redoc_url=None if _prod_mode else '/redoc',
    openapi_url=None if _prod_mode else '/openapi.json',
)
app.add_middleware(APIKeyMiddleware)

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
def health(): return {'status':'ok','name':'wanwei-shuyi-memoryops-autopilot','version':WORKFLOW_VERSION}

@app.get('/arena/metrics')
def arena_metrics():
    metrics_path = Path(__file__).resolve().parents[2] / 'reports' / 'production_memory_eval_metrics.json'
    if not metrics_path.exists():
        return {'error': 'metrics_not_found', 'hint': 'run ./scripts/run_eval.sh'}
    return json.loads(metrics_path.read_text(encoding='utf-8'))

# v0.7 platform cockpit endpoints
@app.get('/platform/modules')
def platform_modules(status: str | None = None):
    return {'items': list_modules(status), 'summary': module_summary()}

@app.get('/model-gateway/providers')
def model_gateway_providers():
    return list_providers()

@app.post('/model-gateway/test')
def model_gateway_test(req: ModelGatewayTestIn):
    return run_provider_test(req)

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

# v0.9.3 competition workflow run endpoints
@app.get('/workflow/design')
def workflow_design_view():
    return workflow_design()

@app.get('/workflow/competition-mapping')
def workflow_competition_mapping_view():
    return workflow_competition_mapping()

@app.post('/workflow/run-dry-run')
def workflow_run_dry_run_view(req: WorkflowRunIn):
    return workflow_run_dry_run(req)

@app.post('/workflow/runs')
def workflow_runs_create(req: WorkflowRunIn):
    return workflow_create_run(req)

@app.get('/workflow/runs/{run_id}')
def workflow_runs_get(run_id: str):
    return workflow_get_run(run_id)

@app.get('/workflow/runs/{run_id}/trace')
def workflow_runs_trace(run_id: str):
    return workflow_get_trace(run_id)

@app.get('/workflow/runs/{run_id}/artifacts')
def workflow_runs_artifacts(run_id: str):
    return workflow_get_artifacts(run_id)

# v0.9 lightweight research system reproduction endpoints
@app.get('/reproduction/systems')
def reproduction_systems():
    return list_reproduction_systems()

@app.get('/reproduction/memoryarena/workbench')
def reproduction_memoryarena_workbench():
    return reproduction_workbench()

@app.get('/reproduction/hippo-lite/graph')
def reproduction_hippo_graph():
    return hippo_graph()

@app.post('/reproduction/hippo-lite/recall')
def reproduction_hippo_recall(req: HippoRecallIn):
    return hippo_recall(req)

@app.get('/reproduction/retention/state')
def reproduction_retention_state():
    return retention_state()

@app.post('/reproduction/retention/simulate')
def reproduction_retention_simulate(req: RetentionSimulateIn):
    return retention_simulate(req)

@app.get('/reproduction/reflexion/evaluator')
def reproduction_reflexion_evaluator_view():
    return reproduction_reflexion_evaluator()

@app.post('/reproduction/reflexion/evaluate')
def reproduction_reflexion_evaluate(req: ReflexionEvaluateIn):
    return reflexion_evaluate(req)

@app.get('/reproduction/memory-tools')
def reproduction_memory_tools():
    return list_memory_tools()

@app.post('/reproduction/memory-tools/dry-run')
def reproduction_memory_tool_dry_run(req: MemoryToolDryRunIn):
    return memory_tool_dry_run(req)

@app.get('/reproduction/memcube/schema')
def reproduction_memcube_schema():
    return memcube_schema()

@app.get('/reproduction/memory-tiers')
def reproduction_memory_tiers():
    return memory_tiers()

@app.get('/reproduction/locomo/template')
def reproduction_locomo_template():
    return locomo_template()

@app.get('/reproduction/generative-stream/template')
def reproduction_generative_template():
    return generative_template()

# v0.9.1 deep expansion and visual verification endpoints
@app.get('/deepening/session-core/design')
def deepening_session_core_design_view():
    return deepening_session_core_design()

@app.get('/deepening/session-core/demo-trace')
def deepening_session_core_demo_trace_view():
    return deepening_session_core_demo_trace()

@app.get('/deepening/reasoning-depth/design')
def deepening_reasoning_depth_design_view():
    return deepening_reasoning_depth_design()

@app.post('/deepening/reasoning-depth/simulate')
def deepening_reasoning_depth_simulate_view(req: ReasoningDepthSimulateIn):
    return deepening_reasoning_depth_simulate(req)

@app.get('/deepening/redqueen/evaluator-design')
def deepening_redqueen_evaluator_design_view():
    return deepening_evaluator_design()

@app.post('/deepening/redqueen/evaluate-dry-run')
def deepening_redqueen_evaluate_dry_run_view(req: RedQueenEvaluateIn):
    return deepening_redqueen_evaluate_dry_run(req)

@app.get('/deepening/contracts/source-of-truth')
def deepening_source_of_truth_view():
    return deepening_source_of_truth()

@app.get('/deepening/contracts/drift-check')
def deepening_drift_check_view():
    return deepening_drift_check()

@app.get('/deepening/agi-asi/pathways')
def deepening_agi_asi_pathways_view():
    return deepening_pathways()

@app.get('/deepening/interrogation/questions')
def deepening_interrogation_questions_view():
    return deepening_questions()

@app.post('/deepening/interrogation/answer-dry-run')
def deepening_interrogation_answer_dry_run_view(req: InterrogationAnswerIn):
    return deepening_answer_dry_run(req)

@app.get('/deepening/visual-verification/protocol')
def deepening_visual_verification_protocol_view():
    return deepening_visual_protocol()

@app.post('/deepening/visual-verification/checklist-dry-run')
def deepening_visual_verification_checklist_dry_run_view(req: VisualChecklistIn):
    return deepening_visual_checklist_dry_run(req)

# legacy v0.2/v0.3 endpoint kept for compatibility
@app.post('/memory/events')
def add_event(event:MemoryEventIn):
    event_id='evt_'+uuid.uuid4().hex[:12]; text=json.dumps(event.content,ensure_ascii=False); guard=evaluate_policy(text=text); quality=0.9 if len(text)>8 else 0.5
    if guard['policy_result'] == 'reject':
        audit_id=record('memory_rejected',{'event_id':event_id,'guard':guard,'event':event.dict()})
        return {'event_id':event_id,'status':'rejected','guard':guard,'audit_id':audit_id}
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
    if not req.confirm:
        audit_id=record('forget_confirm_cancelled',req.dict()); return {'status':'cancelled','audit_id':audit_id}
    conn=get_conn()
    preview=conn.execute("SELECT payload FROM audit_logs WHERE event_type='forget_preview' AND payload LIKE ? ORDER BY created_at DESC LIMIT 1",(f'%{req.forget_request_id}%',)).fetchone()
    capsule_ids=[]
    event_ids=[]
    if preview:
        payload=json.loads(preview['payload'])
        for item in payload.get('candidates',[]):
            if item.get('capsule_id'): capsule_ids.append(item['capsule_id'])
            if item.get('event_id'): event_ids.append(item['event_id'])
    for event_id in event_ids:
        conn.execute('DELETE FROM memory_fts WHERE event_id=?',(event_id,))
        conn.execute('DELETE FROM memory_events WHERE event_id=?',(event_id,))
    conn.commit()
    result=forget_capsules(capsule_ids, mode=req.mode)
    audit_id=record('forget_confirm',{'request':req.dict(),'deleted_capsule_ids':result['deleted_capsule_ids'],'deleted_event_ids':event_ids})
    return {'status':'forgotten','audit_id':audit_id,'deleted_capsule_ids':result['deleted_capsule_ids'],'deleted_event_ids':event_ids}

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
def audit_logs(limit:int=50,trace_id:str|None=None):
    return {'items':list_logs(limit,trace_id)}
