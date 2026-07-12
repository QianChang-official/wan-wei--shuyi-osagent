import os
import uuid,json
import threading
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request, Response
from starlette.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from .security.auth import APIKeyMiddleware, get_api_key, is_production_mode
from .security.input_limits import BodySizeLimitMiddleware, validate_search_params, validate_goal_length, validate_prompt_length
from .security.headers import SecurityHeadersMiddleware
from .security.rate_limit import RateLimitMiddleware
from .operations.health import readiness_report
from .operations.observability import ObservabilityMiddleware, metrics
from .schemas import MemoryEventIn,ForgetPreviewIn,ForgetConfirmIn,CapsuleWriteIn,CommandLoopIn,ReflectionIn
from .db import close_all, get_conn
from .memory_runtime.policy_gate import evaluate_policy
from .audit.service import list_logs, record, record_in_transaction
from .retrieval.service import search as do_search
from .memory_runtime.capsule_store import (
    forget_capsules,
    forget_capsules_in_transaction,
    get_capsule,
    list_capsules,
    write_capsule,
)
from .memory_runtime.retrieval import search_capsules, search_capsules_with_status
from .kylin_sdk.native import get_native_sdk
from .memory_runtime.command_loop import run_command_loop
from .memory_runtime.evolution import reflect_task
from .platform.service import list_modules, module_summary
from .model_gateway.schemas import ModelGatewayTestIn
from .model_gateway.service import list_providers, run_provider_test
from .tool_registry.service import list_skills, list_tools
from .tuning.service import get_defaults, list_policy_modes
from .export_center.service import list_packages
from .research_adoption.service import list_routes as list_adoption_routes, list_technologies, version_map
from .utils.datetime_utils import utc_now_iso
from .workflow.service import (
    WorkflowRunIn,
    cleanup_old_runs as workflow_cleanup_old_runs,
    competition_mapping as workflow_competition_mapping,
    create_run as workflow_create_run,
    get_artifacts as workflow_get_artifacts,
    get_run as workflow_get_run,
    get_storage_stats as workflow_get_storage_stats,
    get_trace as workflow_get_trace,
    list_runs as workflow_list_runs,
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

@asynccontextmanager
async def lifespan(app: FastAPI):
    from .init_db import main as init_db
    from .memory_runtime.vector_index import run_vector_delete_sweeper
    from .workflow.persistence import init_workflow_persistence

    if is_production_mode():
        get_api_key()
    init_db()
    init_workflow_persistence()
    delete_sweeper_stop = threading.Event()
    delete_sweeper = threading.Thread(
        target=run_vector_delete_sweeper,
        args=(delete_sweeper_stop,),
        kwargs={'limit': 10},
        name='kylin-vector-delete-sweeper',
        daemon=True,
    )
    delete_sweeper.start()
    try:
        yield
    finally:
        delete_sweeper_stop.set()
        delete_sweeper.join(timeout=65)
        close_all()

_prod_mode = is_production_mode()
app=FastAPI(
    title='宛委·枢忆 MemoryOps Autopilot Platform',
    docs_url=None if _prod_mode else '/docs',
    redoc_url=None if _prod_mode else '/redoc',
    openapi_url=None if _prod_mode else '/openapi.json',
    lifespan=lifespan,
)
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(APIKeyMiddleware)
# v0.9.6 (T6): per-IP in-memory token-bucket rate limit. It wraps auth/body
# parsing so a burst is rejected before heavier request work. Single-process
# only; multi-process shared limiting is deferred to v1.0.
app.add_middleware(RateLimitMiddleware)
app.add_middleware(ObservabilityMiddleware)
# Added last so it wraps middleware-generated 401/413/429 responses too.
app.add_middleware(SecurityHeadersMiddleware)

# Mount frontend console at /console (same-origin, no CORS needed).
# Legacy console contains inline script and innerHTML rendering; keep it opt-in
# for local compatibility instead of exposing it by default.
_frontend = Path(__file__).parent.parent.parent / "frontend"
_vue_dist = _frontend / "console-vue" / "dist"
_legacy_console = _frontend / "web-console"
if _vue_dist.exists():
    app.mount("/console", StaticFiles(directory=str(_vue_dist), html=True), name="console")
if _legacy_console.exists() and os.getenv("WANWEI_ENABLE_LEGACY_CONSOLE", "").strip().lower() in {"1", "true", "yes"}:
    app.mount("/console-legacy", StaticFiles(directory=str(_legacy_console), html=True), name="console-legacy")

@app.get('/health')
def health():
    from .version import VERSION
    return {'status':'ok','name':'wanwei-shuyi-memoryops-autopilot','version':VERSION}

@app.get('/health/live')
def health_live():
    from .version import VERSION
    return {'status': 'alive', 'version': VERSION}

@app.get('/health/ready')
def health_ready():
    report = readiness_report((_vue_dist / 'index.html', _legacy_console / 'index.html'))
    return JSONResponse(report, status_code=200 if report['status'] == 'ready' else 503)

@app.get('/kylin/sdk/status')
def kylin_sdk_status():
    """Expose native SDK readiness without leaking bridge input or credentials."""
    from .memory_runtime.vector_index import native_index_coverage, vector_sync_active

    sdk = get_native_sdk()
    status = sdk.status()
    status["index"] = native_index_coverage(sdk.collection)
    status["reindex_in_progress"] = vector_sync_active()
    return status

@app.post('/kylin/sdk/reindex')
def kylin_sdk_reindex(
    background_tasks: BackgroundTasks,
    limit: int = 10,
    retry_failed: bool = False,
):
    """Queue a bounded native-index migration without holding the HTTP worker."""
    if not 1 <= limit <= 25:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 25")
    from .memory_runtime.vector_index import (
        native_index_coverage,
        reserve_vector_sync,
        run_reserved_vector_sync,
        vector_sync_active,
    )

    sdk = get_native_sdk()
    availability = sdk.availability()
    coverage = native_index_coverage(sdk.collection)
    if not availability["available"]:
        return {
            "backend": "fts_fallback",
            "scheduled": False,
            "reason": availability["reason"],
            "index": coverage,
        }
    if not reserve_vector_sync():
        return JSONResponse(
            {
                "backend": "kylin_native",
                "scheduled": False,
                "reason": "reindex_already_in_progress",
                "index": coverage,
                "reindex_in_progress": vector_sync_active(),
            },
            status_code=409,
        )
    background_tasks.add_task(run_reserved_vector_sync, limit=limit, retry_failed=retry_failed)
    return JSONResponse(
        {
            "backend": "kylin_native",
            "scheduled": True,
            "limit": limit,
            "retry_failed": retry_failed,
            "index": coverage,
            "reindex_in_progress": True,
        },
        status_code=202,
    )

@app.get('/metrics')
def prometheus_metrics():
    from .version import VERSION
    return Response(metrics.render(VERSION), media_type='text/plain; version=0.0.4')

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

# v0.9.5: New workflow persistence management endpoints
@app.get('/workflow/runs')
def workflow_runs_list(
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    scenario: str | None = None,
):
    return workflow_list_runs(limit=limit, offset=offset, scenario=scenario)

@app.post('/workflow/cleanup')
def workflow_cleanup(ttl_days: int = Query(default=7, ge=1, le=3650)):
    return workflow_cleanup_old_runs(ttl_days=ttl_days)

@app.get('/workflow/stats')
def workflow_stats():
    return workflow_get_storage_stats()

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
    policy = guard['policy_result']
    if policy in ('reject', 'quarantine'):
        audit_id=record('memory_rejected',{'event_id':event_id,'guard':guard,'event':event.model_dump()})
        return {'event_id':event_id,'status':'rejected','guard':guard,'audit_id':audit_id}
    if policy == 'require_confirmation':
        audit_id=record('memory_pending_confirmation',{'event_id':event_id,'guard':guard})
        return {'event_id':event_id,'status':'pending_confirmation','guard':guard,'audit_id':audit_id}
    # allow / redact: redact content before storing
    from .security.redaction import redact_sensitive_text
    stored_text = redact_sensitive_text(text) if policy == 'redact' else text
    conn=get_conn(); conn.execute('INSERT INTO memory_events VALUES (?,?,?,?,?,?,?,?)',(event_id,event.source_type,event.scene,stored_text,quality,guard['sensitivity_level'],guard['trust_score'],utc_now_iso())); conn.execute('INSERT INTO memory_fts(event_id,content) VALUES (?,?)',(event_id,stored_text))
    capsule_id='cap_'+uuid.uuid4().hex[:12]; conn.execute('INSERT INTO memory_capsules VALUES (?,?,?,?,?,?)',(capsule_id,'event',stored_text,'active',guard['trust_score'],utc_now_iso())); conn.execute('INSERT INTO memory_event_capsules VALUES (?,?)',(event_id,capsule_id)); conn.commit()
    audit_id=record('memory_write',{'event_id':event_id,'capsule_id':capsule_id,'guard':guard}); return {'event_id':event_id,'capsule_id':capsule_id,'quality_score':quality,**guard,'audit_id':audit_id}

@app.get('/memory/search')
def search(q:str,scene:str='general',top_k:int=5):
    q, top_k = validate_search_params(q, top_k)
    results=do_search(q,scene,top_k); evidence=[{'source_event_id':r['event_id'],'source_type':r['source_type'],'trust_score':r['trust_score'],'actions':['view_source','correct','forget']} for r in results]
    return {'query':q,'results':results,'evidence_cards':evidence}

@app.post('/memory/forget/preview')
def forget_preview(req:ForgetPreviewIn):
    instruction, _ = validate_search_params(req.instruction, 10)
    capsules, retrieval = search_capsules_with_status(instruction, top_k=10)
    candidates = [
        {
            'capsule_id': item['capsule_id'],
            'memory_class': item['memory_class'],
            'content': item['content'],
            'retrieval_score': item.get('retrieval_score'),
            'retrieval_backend': item.get('retrieval_backend'),
            'vector_score': item.get('vector_score'),
        }
        for item in capsules
    ]
    legacy_candidates = do_search(instruction, 'general', 10)
    candidates.extend(legacy_candidates)
    forget_request_id='forget_'+uuid.uuid4().hex
    payload = {
        'forget_request_id': forget_request_id,
        'instruction': instruction,
        'scope': req.scope,
        'retrieval': retrieval,
        'candidates': candidates,
    }
    audit_candidates = [
        {key: item[key] for key in ('capsule_id', 'event_id') if item.get(key)}
        for item in candidates
        if item.get('capsule_id') or item.get('event_id')
    ]
    conn = get_conn()
    timestamp = utc_now_iso()
    try:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute(
            'INSERT INTO memory_forget_requests VALUES (?,?,?,?,?,?,?)',
            (forget_request_id, req.scope, json.dumps(audit_candidates), 'pending', None, timestamp, timestamp),
        )
        record_in_transaction(
            conn,
            'forget_preview',
            {
                'forget_request_id': forget_request_id,
                'scope': req.scope,
                'retrieval': retrieval,
                'candidates': audit_candidates,
            },
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return payload


def _replay_completed_forget(
    conn,
    forget_request_id: str,
    completed: dict,
    capsule_ids: list[str],
    event_ids: list[str],
    mode: str,
):
    if (
        completed.get('selected_capsule_ids') != capsule_ids
        or completed.get('selected_event_ids') != event_ids
        or completed.get('selected_mode') != mode
    ):
        raise HTTPException(status_code=409, detail='forget_request_already_completed')
    native_vector = completed.get('native_vector', {})
    from .memory_runtime.vector_index import pending_delete_vector_ids, remove_vectors

    durable_pending_vector_ids = pending_delete_vector_ids(
        completed.get('deleted_capsule_ids', []),
        conn=conn,
    )
    if native_vector.get('pending_vector_ids') or native_vector.get('reason') == 'native_delete_status_unknown' or durable_pending_vector_ids:

        try:
            completed['native_vector'] = remove_vectors(completed['deleted_capsule_ids'])
        except Exception:
            completed['native_vector'] = {
                'backend': 'fts_fallback',
                'deleted_vector_ids': native_vector.get('deleted_vector_ids', []),
                'pending_vector_ids': native_vector.get('pending_vector_ids', []),
                'reason': 'native_delete_status_unknown',
            }
        completed = _persist_completed_forget_result(
            conn,
            forget_request_id,
            completed,
        )
    return {key: value for key, value in completed.items() if not key.startswith('selected_')}


def _persist_completed_forget_result(
    conn,
    forget_request_id: str,
    proposed: dict,
) -> dict:
    try:
        conn.execute('BEGIN IMMEDIATE')
        from .memory_runtime.vector_index import pending_delete_vector_ids

        authoritative_pending_vector_ids = pending_delete_vector_ids(
            proposed.get('deleted_capsule_ids', []),
            conn=conn,
        )
        row = conn.execute(
            'SELECT status,result FROM memory_forget_requests WHERE forget_request_id=?',
            (forget_request_id,),
        ).fetchone()
        persisted = proposed
        if row and row['status'] == 'completed' and row['result']:
            current = json.loads(row['result'])
            if isinstance(current, dict):
                persisted = {
                    **proposed,
                    'native_vector': _merge_native_delete_results(
                        current.get('native_vector'),
                        proposed.get('native_vector'),
                        authoritative_pending_vector_ids=authoritative_pending_vector_ids or set(),
                    ),
                }
        conn.execute(
            'UPDATE memory_forget_requests SET result=?, updated_at=? WHERE forget_request_id=?',
            (json.dumps(persisted), utc_now_iso(), forget_request_id),
        )
        conn.commit()
        return persisted
    except Exception:
        conn.rollback()
        raise


def _merge_native_delete_results(
    current,
    proposed,
    *,
    authoritative_pending_vector_ids: set[int] | None = None,
) -> dict:
    current = current if isinstance(current, dict) else {}
    proposed = proposed if isinstance(proposed, dict) else {}
    authoritative_pending_vector_ids = authoritative_pending_vector_ids or set()
    current_states = _native_delete_states(current)
    proposed_states = _native_delete_states(proposed)
    vector_ids = current_states.keys() | proposed_states.keys()
    if authoritative_pending_vector_ids:
        vector_ids = vector_ids | authoritative_pending_vector_ids
    if (
        not authoritative_pending_vector_ids
        and all(proposed_states.get(vector_id, 0) >= current_states.get(vector_id, 0) for vector_id in vector_ids)
    ):
        return proposed
    if (
        not authoritative_pending_vector_ids
        and all(current_states.get(vector_id, 0) >= proposed_states.get(vector_id, 0) for vector_id in vector_ids)
    ):
        return current

    merged = {**current, **proposed}
    states = {}
    for vector_id in vector_ids:
        if vector_id in authoritative_pending_vector_ids:
            states[vector_id] = 1
        else:
            states[vector_id] = max(current_states.get(vector_id, 0), proposed_states.get(vector_id, 0))
    merged['deleted_vector_ids'] = sorted(vector_id for vector_id, state in states.items() if state == 2)
    merged['pending_vector_ids'] = sorted(vector_id for vector_id, state in states.items() if state == 1)
    if not merged['pending_vector_ids']:
        merged.pop('reason', None)
    return merged


def _native_delete_states(result: dict) -> dict[int, int]:
    states = {
        vector_id: 1
        for vector_id in result.get('pending_vector_ids', [])
        if isinstance(vector_id, int)
    }
    states.update({
        vector_id: 2
        for vector_id in result.get('deleted_vector_ids', [])
        if isinstance(vector_id, int)
    })
    return states


@app.post('/memory/forget/confirm')
def forget_confirm(req:ForgetConfirmIn):
    conn=get_conn()
    ticket = conn.execute(
        'SELECT * FROM memory_forget_requests WHERE forget_request_id=?',
        (req.forget_request_id,),
    ).fetchone()
    if not ticket:
        audit_id=record('forget_confirm_not_found',{'forget_request_id':req.forget_request_id})
        return {'status':'not_found','audit_id':audit_id,'deleted_capsule_ids':[],'deleted_event_ids':[]}
    if not req.confirm:
        if ticket['status'] == 'cancelled' and ticket['result']:
            return json.loads(ticket['result'])
        try:
            conn.execute('BEGIN IMMEDIATE')
            current = conn.execute(
                'SELECT status,result FROM memory_forget_requests WHERE forget_request_id=?',
                (req.forget_request_id,),
            ).fetchone()
            if current['status'] == 'completed':
                raise HTTPException(status_code=409, detail='forget_request_already_completed')
            if current['status'] == 'cancelled':
                conn.rollback()
                return json.loads(current['result']) if current['result'] else {'status': 'cancelled'}
            if current['status'] != 'pending':
                raise HTTPException(status_code=409, detail='forget_request_in_progress')
            audit_id = record_in_transaction(conn, 'forget_confirm_cancelled', req.model_dump())
            cancelled_result = {'status': 'cancelled', 'audit_id': audit_id}
            conn.execute(
                "UPDATE memory_forget_requests SET status='cancelled', result=?, updated_at=? WHERE forget_request_id=?",
                (json.dumps(cancelled_result), utc_now_iso(), req.forget_request_id),
            )
            conn.commit()
            return cancelled_result
        except Exception:
            conn.rollback()
            raise
    if ticket['status'] == 'cancelled':
        raise HTTPException(status_code=409, detail='forget_request_cancelled')

    preview_candidates = json.loads(ticket['candidates'])
    preview_capsule_ids = {
        item['capsule_id'] for item in preview_candidates if item.get('capsule_id')
    }
    preview_event_ids = {
        item['event_id'] for item in preview_candidates if item.get('event_id')
    }
    capsule_ids = list(dict.fromkeys(req.capsule_ids))
    event_ids = list(dict.fromkeys(req.event_ids))
    invalid_capsule_ids = sorted(set(capsule_ids) - preview_capsule_ids)
    invalid_event_ids = sorted(set(event_ids) - preview_event_ids)
    if invalid_capsule_ids or invalid_event_ids:
        raise HTTPException(
            status_code=422,
            detail={
                'error': 'forget_selection_not_in_preview',
                'invalid_capsule_ids': invalid_capsule_ids,
                'invalid_event_ids': invalid_event_ids,
            },
        )
    if not capsule_ids and not event_ids:
        audit_id=record('forget_confirm_selection_required',{'forget_request_id':req.forget_request_id})
        return {
            'status': 'selection_required',
            'audit_id': audit_id,
            'deleted_capsule_ids': [],
            'deleted_event_ids': [],
        }
    if ticket['status'] == 'completed':
        completed = json.loads(ticket['result'])
        return _replay_completed_forget(
            conn, req.forget_request_id, completed, capsule_ids, event_ids, req.mode
        )
    try:
        conn.execute('BEGIN IMMEDIATE')
        claimed = conn.execute(
            "UPDATE memory_forget_requests SET status='processing', updated_at=? "
            "WHERE forget_request_id=? AND (status='pending' OR "
            "(status='processing' AND julianday(updated_at)<=julianday('now','-1 hour')))",
            (utc_now_iso(), req.forget_request_id),
        )
        if claimed.rowcount != 1:
            current = conn.execute(
                'SELECT status,result FROM memory_forget_requests WHERE forget_request_id=?',
                (req.forget_request_id,),
            ).fetchone()
            conn.rollback()
            if current and current['status'] == 'completed':
                completed = json.loads(current['result'])
                return _replay_completed_forget(
                    conn, req.forget_request_id, completed, capsule_ids, event_ids, req.mode
                )
            raise HTTPException(status_code=409, detail='forget_request_in_progress')
        legacy_capsule_ids = {
            row['event_id']: row['capsule_id']
            for row in conn.execute(
                f"SELECT event_id,capsule_id FROM memory_event_capsules WHERE event_id IN ({','.join('?' for _ in event_ids)})",
                event_ids,
            ).fetchall()
        } if event_ids else {}
        if len(legacy_capsule_ids) != len(event_ids):
            for row in conn.execute("SELECT payload FROM audit_logs WHERE event_type='memory_write' ORDER BY created_at DESC"):
                audit_payload = json.loads(row['payload'])
                event_id = audit_payload.get('event_id')
                capsule_id = audit_payload.get('capsule_id')
                if event_id in event_ids and event_id not in legacy_capsule_ids and capsule_id:
                    legacy_capsule_ids[event_id] = capsule_id
                    conn.execute('INSERT OR IGNORE INTO memory_event_capsules VALUES (?,?)',(event_id,capsule_id))
        missing_legacy_links = sorted(set(event_ids) - set(legacy_capsule_ids))
        if missing_legacy_links:
            raise HTTPException(
                status_code=409,
                detail={
                    'error': 'legacy_capsule_link_missing',
                    'event_ids': missing_legacy_links,
                },
            )
        for event_id in event_ids:
            legacy_capsule_id = legacy_capsule_ids.get(event_id)
            if legacy_capsule_id and req.mode == 'hard_delete':
                conn.execute('DELETE FROM memory_capsules WHERE capsule_id=?',(legacy_capsule_id,))
            elif legacy_capsule_id:
                conn.execute("UPDATE memory_capsules SET lifecycle='forgotten' WHERE capsule_id=?",(legacy_capsule_id,))
            conn.execute('DELETE FROM memory_fts WHERE event_id=?',(event_id,))
            conn.execute('DELETE FROM memory_events WHERE event_id=?',(event_id,))
        result=forget_capsules_in_transaction(conn, capsule_ids, mode=req.mode)
        audit_id=record_in_transaction(
            conn,
            'forget_confirm',
            {
                'request': req.model_dump(),
                'deleted_capsule_ids': result['deleted_capsule_ids'],
                'deleted_event_ids': event_ids,
                'native_vector': result['native_vector'],
            },
        )
        response = {'status':'forgotten','audit_id':audit_id,'deleted_capsule_ids':result['deleted_capsule_ids'],'deleted_event_ids':event_ids,'native_vector':result['native_vector']}
        stored_result = {
            **response,
            'selected_capsule_ids': capsule_ids,
            'selected_event_ids': event_ids,
            'selected_mode': req.mode,
        }
        conn.execute(
            "UPDATE memory_forget_requests SET status='completed', result=?, updated_at=? WHERE forget_request_id=?",
            (json.dumps(stored_result), utc_now_iso(), req.forget_request_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    from .memory_runtime.vector_index import remove_vectors

    try:
        response['native_vector'] = remove_vectors(response['deleted_capsule_ids'])
    except Exception:
        response['native_vector'] = {
            'backend': 'fts_fallback',
            'deleted_vector_ids': [],
            'pending_vector_ids': result['native_vector'].get('pending_vector_ids', []),
            'reason': 'native_delete_status_unknown',
        }
    stored_result['native_vector'] = response['native_vector']
    stored_result = _persist_completed_forget_result(conn, req.forget_request_id, stored_result)
    response['native_vector'] = stored_result['native_vector']
    return response

# v0.6 MemoryOps Runtime endpoints
@app.post('/memory/v2/capsules')
def v2_write_capsule(req: CapsuleWriteIn):
    return write_capsule(**req.model_dump())

@app.get('/memory/v2/capsules')
def v2_list_capsules(limit: int = Query(default=50, ge=1, le=200)):
    return {'items': list_capsules(limit)}

@app.get('/memory/v2/capsules/{capsule_id}')
def v2_get_capsule(capsule_id: str):
    return get_capsule(capsule_id) or {'error':'not_found','capsule_id':capsule_id}

@app.get('/memory/v2/search')
def v2_search(q:str,top_k:int=5,high_risk:bool=False):
    q, top_k = validate_search_params(q, top_k)
    from .memory_runtime.evidence import build_evidence_card
    results, retrieval = search_capsules_with_status(q,top_k=top_k,high_risk=high_risk)
    return {'query':q,'retrieval':retrieval,'results':results,'evidence_cards':[build_evidence_card(r) for r in results]}

@app.post('/memory/v2/command')
def v2_command(req: CommandLoopIn):
    validate_goal_length(req.goal)
    return run_command_loop(goal=req.goal, scene=req.scene, top_k=req.top_k)

@app.post('/memory/v2/reflection')
def v2_reflection(req: ReflectionIn):
    return reflect_task(req.task_id, req.model_dump())

@app.get('/audit/logs')
def audit_logs(limit:int=50,trace_id:str|None=None):
    return {'items':list_logs(limit,trace_id)}
