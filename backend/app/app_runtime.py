import logging
import os
import json
import uuid
import sqlite3
import threading
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request, Response
from starlette.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from .security.auth import APIKeyMiddleware, get_api_key, is_production_mode, warn_if_exposed_bind
from .security import encryption
from .security.input_limits import BodySizeLimitMiddleware, validate_search_params, validate_goal_length, validate_prompt_length
from .security.headers import SecurityHeadersMiddleware
from .security.rate_limit import RateLimitMiddleware
from .security.redaction import redact_capsule_for_output
from .operations.health import readiness_report
from .operations.observability import ObservabilityMiddleware, metrics
from .schemas import (
    MemoryEventIn, ForgetPreviewIn, ForgetConfirmIn, CapsuleWriteIn,
    CommandLoopIn, ReflectionIn, SoulConnectIn, SoulChatIn,
    SoulPersonaUpdateIn, SoulDreamIn,
)
from .db import close_all, get_conn, transaction
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
from .memory_runtime.evidence import build_evidence_card
from .kylin_sdk.native import get_native_sdk
from .memory_runtime.command_loop import run_command_loop
from .memory_runtime.evolution import reflect_task
from .memory_arena.metrics_contract import arena_metrics_validation_error
from .platform.service import list_modules, module_summary
from .model_gateway.schemas import ModelGatewayConfigIn, ModelGatewayTestIn
from .model_gateway.service import (
    _run_smoke_in_dedicated_pool,
    _run_smoke_in_dedicated_pool_async,
    delete_config,
    list_configs,
    list_providers,
    run_provider_test_async,
    shutdown_smoke_executor,
    start_smoke_executor,
    upsert_config,
)
from .tool_registry.service import list_skills, list_tools
from .tuning.service import get_defaults, list_policy_modes
from .export_center.service import list_packages
from .research_adoption.service import list_routes as list_adoption_routes, list_technologies, version_map
from .utils.datetime_utils import utc_now_iso
from .soul import build_injection_prompt, create_persona, get_persona, update_persona, get_soul_state, route_chat
from .soul.persona import PersonaPolicyViolation, PersonaStoreError
from .soul.ownership import (
    SoulAccessDenied,
    SoulScope,
    SoulSelectionRequired,
    actor_id_for_request,
    configured_actor_id,
    resolve_owned_soul,
)
from .affect import (
    AffectSoulNotFoundError,
    AffectState,
    InvalidAffectIntensityError,
    SUPPORTED_AFFECT_TRIGGERS,
    UnsupportedAffectTriggerError,
    load_affect,
    save_affect,
    transition,
    tune_response_style,
)
from .affect.decay_daemon import run_decay_daemon
from .perception import intake_perception
from .dream import run_dream, run_dream_scheduler
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

logger = logging.getLogger(__name__)

ARENA_METRICS_PATH = (
    Path(__file__).resolve().parents[2]
    / "reports"
    / "production_memory_eval_metrics.json"
)

# 记忆事件质量分：内容长度超过阈值视为高质量（更可能包含有效语义），
# 否则按低质量处理。阈值为经验值，与 memory_events.quality 字段语义一致。
_QUALITY_HIGH = 0.9
_QUALITY_LOW = 0.5
_QUALITY_THRESHOLD_CHARS = 8


def _owned_soul_scope(
    request: Request | None,
    soul_id: str | None,
    *,
    allow_internal_unscoped: bool = False,
) -> SoulScope | None:
    """Resolve a request's Soul without leaking cross-owner existence.

    Direct Python callers predate HTTP ownership and are used by internal
    evaluation code.  They retain unscoped behavior only when explicitly
    allowed; every actual HTTP request is resolved to an owned Soul.
    """
    if request is None and allow_internal_unscoped:
        return None
    try:
        return resolve_owned_soul(request, soul_id)
    except SoulSelectionRequired as exc:
        raise HTTPException(
            status_code=422,
            detail={"error": "soul_id_required"},
        ) from exc
    except SoulAccessDenied as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": "soul_not_found", "soul_id": soul_id},
        ) from exc


def _public_capsule(capsule: dict) -> dict:
    """Redact content and remove internal ownership metadata from API output."""
    output = redact_capsule_for_output(capsule)
    provenance = output.get("provenance")
    if isinstance(provenance, dict):
        provenance.pop("owner_id", None)
    return output

@asynccontextmanager
async def lifespan(app: FastAPI):
    from .init_db import main as init_db
    from .memory_runtime.vector_index import run_vector_delete_sweeper
    from .workflow.persistence import init_workflow_persistence

    if is_production_mode():
        get_api_key()
        encryption.startup_check()
    warn_if_exposed_bind()
    init_db()
    init_workflow_persistence()

    # -- existing vector delete sweeper --
    delete_sweeper_stop = threading.Event()
    delete_sweeper = threading.Thread(
        target=run_vector_delete_sweeper,
        args=(delete_sweeper_stop,),
        kwargs={'limit': 10},
        name='kylin-vector-delete-sweeper',
        daemon=True,
    )
    delete_sweeper.start()

    # -- new: affect decay daemon (P1) --
    affect_decay_stop = threading.Event()
    affect_decay_thread = threading.Thread(
        target=run_decay_daemon,
        kwargs={'interval_seconds': 1800, 'stop_event': affect_decay_stop},
        name='affect-decay-daemon',
        daemon=True,
    )
    affect_decay_thread.start()

    # -- new: dream scheduler (P1 placeholder, full impl in P4) --
    dream_scheduler_stop = threading.Event()
    dream_scheduler_thread = threading.Thread(
        target=run_dream_scheduler,
        kwargs={'interval_seconds': 600, 'stop_event': dream_scheduler_stop},
        name='dream-scheduler',
        daemon=True,
    )
    dream_scheduler_thread.start()

    # -- P2: resume agent runs interrupted by backend restart --
    # 03-#13: 统一相对导入（此前 from app.platform_api... 绝对导入会让
    # backend.app.* 与 app.* 两份模块身份并存，连接缓存/状态分裂）
    from .platform_api.agents import resume_runs
    resume_runs()

    start_smoke_executor()
    try:
        yield
    finally:
        delete_sweeper_stop.set()
        delete_sweeper.join(timeout=65)
        affect_decay_stop.set()
        affect_decay_thread.join(timeout=5)
        dream_scheduler_stop.set()
        dream_scheduler_thread.join(timeout=5)
        shutdown_smoke_executor()
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
    # 03-#19: readiness_report 内部已直接消费 failed_modules()，
    # 无需 main.py 再后处理。
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
    try:
        payload = json.loads(ARENA_METRICS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="arena_metrics_not_found") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        logger.warning("Arena metrics file could not be loaded: %s", exc)
        raise HTTPException(status_code=503, detail="arena_metrics_unavailable") from exc

    validation_error = arena_metrics_validation_error(payload)
    if validation_error is not None:
        logger.warning(
            "Arena metrics file does not satisfy the dashboard contract: %s",
            validation_error,
        )
        raise HTTPException(status_code=503, detail="arena_metrics_invalid")
    return payload

# v0.7 platform cockpit endpoints
@app.get('/platform/modules')
def platform_modules(status: str | None = None):
    return {'items': list_modules(status), 'summary': module_summary()}

@app.get('/model-gateway/providers')
def model_gateway_providers():
    return list_providers()

@app.get('/model-gateway/configs')
def model_gateway_configs():
    return list_configs()

@app.post('/model-gateway/configs')
def model_gateway_configs_upsert(req: ModelGatewayConfigIn):
    return upsert_config(
        req.provider,
        req.api_base,
        req.api_key,
        req.model,
        req.enabled,
        req.notes,
    )

@app.delete('/model-gateway/configs/{provider}')
def model_gateway_configs_delete(provider: str):
    return {"deleted": delete_config(provider)}

@app.post('/model-gateway/test')
async def model_gateway_test(req: ModelGatewayTestIn):
    return await run_provider_test_async(req)

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
def reproduction_hippo_graph(
    soul_id: str | None = None,
    request: Request = None,
):
    soul_scope = _owned_soul_scope(
        request,
        soul_id,
        allow_internal_unscoped=True,
    )
    return hippo_graph(
        owner_id=soul_scope.owner_id if soul_scope else None,
        soul_id=soul_scope.soul_id if soul_scope else None,
    )

@app.post('/reproduction/hippo-lite/recall')
def reproduction_hippo_recall(
    req: HippoRecallIn,
    soul_id: str | None = None,
    request: Request = None,
):
    soul_scope = _owned_soul_scope(
        request,
        soul_id,
        allow_internal_unscoped=True,
    )
    return hippo_recall(
        req,
        owner_id=soul_scope.owner_id if soul_scope else None,
        soul_id=soul_scope.soul_id if soul_scope else None,
    )

@app.get('/reproduction/retention/state')
def reproduction_retention_state(
    soul_id: str | None = None,
    request: Request = None,
):
    soul_scope = _owned_soul_scope(
        request,
        soul_id,
        allow_internal_unscoped=True,
    )
    return retention_state(
        owner_id=soul_scope.owner_id if soul_scope else None,
        soul_id=soul_scope.soul_id if soul_scope else None,
    )

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
def reproduction_memory_tiers(
    soul_id: str | None = None,
    request: Request = None,
):
    soul_scope = _owned_soul_scope(
        request,
        soul_id,
        allow_internal_unscoped=True,
    )
    return memory_tiers(
        owner_id=soul_scope.owner_id if soul_scope else None,
        soul_id=soul_scope.soul_id if soul_scope else None,
    )

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
def add_event(event: MemoryEventIn, request: Request = None):
    soul_scope = _owned_soul_scope(
        request,
        event.soul_id,
        allow_internal_unscoped=True,
    )
    event_id='evt_'+uuid.uuid4().hex[:12]; text=json.dumps(event.content,ensure_ascii=False); guard=evaluate_policy(text=text); quality=_QUALITY_HIGH if len(text)>_QUALITY_THRESHOLD_CHARS else _QUALITY_LOW
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
    capsule_id='cap_'+uuid.uuid4().hex[:12]
    with transaction() as conn:
        conn.execute(
            """INSERT INTO memory_events(
                event_id, source_type, scene, content, quality_score,
                sensitivity_level, trust_score, created_at, soul_id, owner_id
            ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                event_id,
                event.source_type,
                event.scene,
                stored_text,
                quality,
                guard['sensitivity_level'],
                guard['trust_score'],
                utc_now_iso(),
                soul_scope.soul_id if soul_scope else event.soul_id,
                soul_scope.owner_id if soul_scope else None,
            ),
        )
        conn.execute('INSERT INTO memory_fts(event_id,content) VALUES (?,?)',(event_id,stored_text))
        conn.execute('INSERT INTO memory_capsules VALUES (?,?,?,?,?,?)',(capsule_id,'event',stored_text,'active',guard['trust_score'],utc_now_iso()))
        conn.execute('INSERT INTO memory_event_capsules VALUES (?,?)',(event_id,capsule_id))
    audit_id=record('memory_write',{'event_id':event_id,'capsule_id':capsule_id,'guard':guard}); return {'event_id':event_id,'capsule_id':capsule_id,'quality_score':quality,**guard,'audit_id':audit_id}

@app.get('/memory/search')
def search(
    q: str,
    scene: str = 'general',
    top_k: int = 5,
    soul_id: str | None = None,
    request: Request = None,
):
    soul_scope = _owned_soul_scope(
        request,
        soul_id,
        allow_internal_unscoped=True,
    )
    q, top_k = validate_search_params(q, top_k)
    results = do_search(
        q,
        top_k,
        owner_id=soul_scope.owner_id if soul_scope else None,
        soul_id=soul_scope.soul_id if soul_scope else None,
    )
    evidence = [
        {
            'source_event_id': result['event_id'],
            'source_type': result['source_type'],
            'trust_score': result['trust_score'],
            'actions': ['view_source', 'correct', 'forget'],
        }
        for result in results
    ]
    return {'query':q,'results':results,'evidence_cards':evidence}

@app.post('/memory/forget/preview')
def forget_preview(req: ForgetPreviewIn, request: Request = None):
    soul_scope = _owned_soul_scope(
        request,
        req.soul_id,
        allow_internal_unscoped=True,
    )
    instruction, _ = validate_search_params(req.instruction, 10)
    capsules, retrieval = search_capsules_with_status(
        instruction,
        top_k=10,
        owner_id=soul_scope.owner_id if soul_scope else None,
        soul_id=soul_scope.soul_id if soul_scope else None,
    )
    capsules = [_public_capsule(item) for item in capsules]
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
    legacy_candidates = do_search(
        instruction,
        10,
        owner_id=soul_scope.owner_id if soul_scope else None,
        soul_id=soul_scope.soul_id if soul_scope else None,
    )
    candidates.extend(legacy_candidates)
    forget_request_id='forget_'+uuid.uuid4().hex
    payload = {
        'forget_request_id': forget_request_id,
        'instruction': instruction,
        'scope': req.scope,
        'soul_id': soul_scope.soul_id if soul_scope else req.soul_id,
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
        if soul_scope is not None:
            conn.execute(
                """INSERT INTO memory_forget_request_scopes(
                    forget_request_id, owner_id, soul_id
                ) VALUES (?,?,?)""",
                (forget_request_id, soul_scope.owner_id, soul_scope.soul_id),
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


def _legacy_capsule_links(
    conn,
    event_ids: list[str],
    *,
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> dict[str, str]:
    """从 memory_event_capsules 读取 event→capsule 持久链接（只读）。"""
    if not event_ids:
        return {}
    placeholders = ','.join('?' for _ in event_ids)
    joins = ""
    clauses = [f"link.event_id IN ({placeholders})"]
    params: list[object] = list(event_ids)
    if owner_id is not None or soul_id is not None:
        joins = "JOIN memory_events AS event ON event.event_id=link.event_id"
    if owner_id is not None:
        clauses.append("event.owner_id=?")
        params.append(owner_id)
    if soul_id is not None:
        clauses.append("(event.soul_id=? OR event.soul_id IS NULL)")
        params.append(soul_id)
    return {
        row['event_id']: row['capsule_id']
        for row in conn.execute(
            "SELECT link.event_id,link.capsule_id FROM memory_event_capsules AS link "
            f"{joins} WHERE {' AND '.join(clauses)}",
            params,
        ).fetchall()
    }


def _audit_legacy_capsule_links(conn, event_ids: list[str], known: set[str]) -> dict[str, str]:
    """从 audit_logs 回捞缺失的 legacy event→capsule 链接（只读物化）。

    03-#7: 原实现在 BEGIN IMMEDIATE 写事务内无 LIMIT 全表扫 audit_logs 并逐行
    json.loads，事务窗口随审计表增长无限拉大。现改为：
      - 调用方在进入写事务前物化（本函数只读，不占写锁）；
      - json_extract 在 SQL 层预过滤候选行，仅对命中的少数行 json.loads；
      - JSON1 不可用的旧 SQLite 构建回退原全表扫（兼容兜底，仍在事务外）。
    语义保持：按 created_at DESC 遍历，每个 event 取最新一条有效链接。
    """
    missing = [e for e in event_ids if e not in known]
    if not missing:
        return {}
    placeholders = ','.join('?' for _ in missing)
    try:
        rows = conn.execute(
            "SELECT payload FROM audit_logs WHERE event_type='memory_write' "
            f"AND json_extract(payload,'$.event_id') IN ({placeholders}) "
            "ORDER BY created_at DESC",
            missing,
        ).fetchall()
    except sqlite3.OperationalError:
        rows = conn.execute(
            "SELECT payload FROM audit_logs WHERE event_type='memory_write' ORDER BY created_at DESC"
        ).fetchall()
    found: dict[str, str] = {}
    for row in rows:
        try:
            audit_payload = json.loads(row['payload'])
        except (TypeError, ValueError):
            # 个别历史坏行不再拖垮整个 forget 流程
            continue
        event_id = audit_payload.get('event_id')
        capsule_id = audit_payload.get('capsule_id')
        if event_id in missing and event_id not in found and capsule_id:
            found[event_id] = capsule_id
    return found


@app.post('/memory/forget/confirm')
def forget_confirm(req: ForgetConfirmIn, request: Request = None):
    conn=get_conn()
    ticket = conn.execute(
        """SELECT ticket.*,
                  scope.owner_id AS ticket_owner_id,
                  scope.soul_id AS ticket_soul_id
           FROM memory_forget_requests AS ticket
           LEFT JOIN memory_forget_request_scopes AS scope
             ON scope.forget_request_id=ticket.forget_request_id
           WHERE ticket.forget_request_id=?""",
        (req.forget_request_id,),
    ).fetchone()
    request_owner_id = actor_id_for_request(request) if request is not None else None
    ticket_owner_id = ticket['ticket_owner_id'] if ticket else None
    ticket_soul_id = ticket['ticket_soul_id'] if ticket else None
    if not ticket or (
        request_owner_id is not None
        and (not ticket_owner_id or ticket_owner_id != request_owner_id)
    ):
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
    # 03-#7: legacy event→capsule 链接在进入写事务前物化（只读）——原先在
    # BEGIN IMMEDIATE 内全表扫 audit_logs + 逐行 json.loads，写事务窗口随
    # 审计表增长无限拉大。缺失链接的 409 判定也随之前置，事务内只剩幂等
    # 回填与删除。
    legacy_capsule_ids = _legacy_capsule_links(
        conn,
        event_ids,
        owner_id=ticket_owner_id if request is not None else None,
        soul_id=ticket_soul_id if request is not None else None,
    )
    audit_discovered_links: dict[str, str] = {}
    if len(legacy_capsule_ids) != len(event_ids):
        audit_discovered_links = _audit_legacy_capsule_links(conn, event_ids, set(legacy_capsule_ids))
        legacy_capsule_ids.update(audit_discovered_links)
    missing_legacy_links = sorted(set(event_ids) - set(legacy_capsule_ids))
    if missing_legacy_links:
        raise HTTPException(
            status_code=409,
            detail={
                'error': 'legacy_capsule_link_missing',
                'event_ids': missing_legacy_links,
            },
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
        # 事务内仅幂等回填物化结果（不再扫描 audit_logs）
        for event_id, capsule_id in audit_discovered_links.items():
            conn.execute('INSERT OR IGNORE INTO memory_event_capsules VALUES (?,?)',(event_id,capsule_id))
        for event_id in event_ids:
            legacy_capsule_id = legacy_capsule_ids.get(event_id)
            if legacy_capsule_id and req.mode == 'hard_delete':
                conn.execute('DELETE FROM memory_capsules WHERE capsule_id=?',(legacy_capsule_id,))
            elif legacy_capsule_id:
                conn.execute("UPDATE memory_capsules SET lifecycle='forgotten' WHERE capsule_id=?",(legacy_capsule_id,))
            event_scope_sql = ""
            event_scope_params: list[object] = []
            if request is not None:
                event_scope_sql = (
                    " AND owner_id=? AND (soul_id=? OR soul_id IS NULL)"
                )
                event_scope_params = [ticket_owner_id, ticket_soul_id]
            deleted_event = conn.execute(
                f"DELETE FROM memory_events WHERE event_id=?{event_scope_sql}",
                [event_id, *event_scope_params],
            )
            if deleted_event.rowcount:
                conn.execute('DELETE FROM memory_fts WHERE event_id=?',(event_id,))
        if request is not None and capsule_ids:
            placeholders = ','.join('?' for _ in capsule_ids)
            scoped_rows = conn.execute(
                f"""SELECT capsule_id FROM memory_capsules_v2
                    WHERE capsule_id IN ({placeholders})
                      AND json_extract(provenance, '$.owner_id')=?
                      AND (json_extract(provenance, '$.soul_id')=?
                           OR json_extract(provenance, '$.soul_id') IS NULL)""",
                [*capsule_ids, ticket_owner_id, ticket_soul_id],
            ).fetchall()
            if {row['capsule_id'] for row in scoped_rows} != set(capsule_ids):
                raise HTTPException(
                    status_code=404,
                    detail={'error': 'memory_not_found'},
                )
        # Keep the established helper call contract for internal extensions;
        # the scoped membership check above executes in this same write
        # transaction, so IDs cannot cross the owner boundary before deletion.
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

# ---------------------------------------------------------------------------
# v0.11 Soul Awakening endpoints
# ---------------------------------------------------------------------------

def _ensure_dream_lock(soul_id: str) -> None:
    """Idempotently seed a dream_lock row for the soul.

    03-#10 兼容：FOREIGN KEY 已启用，soul_persona 不存在的幽灵 soul 不再
    播种 dream_lock 孤儿行（WHERE EXISTS 守卫），调用方语义不变。
    """
    conn = get_conn()
    ts = utc_now_iso()
    conn.execute(
        """
        INSERT INTO dream_lock(soul_id, pid, started_at, last_dream_at, last_dream_duration_ms, last_dream_summary)
        SELECT ?, NULL, NULL, NULL, 0, NULL
        WHERE EXISTS (SELECT 1 FROM soul_persona WHERE soul_id=?)
        ON CONFLICT(soul_id) DO NOTHING
        """,
        (soul_id, soul_id),
    )
    conn.commit()


@app.post('/soul/connect')
def soul_connect(req: SoulConnectIn, request: Request = None):
    """Soul injection handshake — returns soul_id + injection_prompt."""
    owner_id = actor_id_for_request(request) if request is not None else configured_actor_id()
    try:
        soul_id = create_persona(req.soul_id, owner_id=owner_id)
    except SoulAccessDenied as exc:
        raise HTTPException(
            status_code=404,
            detail={'error': 'soul_not_found', 'soul_id': req.soul_id},
        ) from exc
    except PersonaStoreError as exc:
        # 03-#6: 建 persona 失败不再假成功返回 sid，显式 500
        raise HTTPException(
            status_code=500,
            detail={'error': 'persona_create_failed', 'soul_id': req.soul_id},
        ) from exc
    _ensure_dream_lock(soul_id)
    injection = build_injection_prompt(soul_id)
    return {
        'soul_id': soul_id,
        'injection_prompt': injection,
        'persona': get_persona(soul_id),
    }


@app.get('/soul/state/{soul_id}')
def soul_state(soul_id: str, request: Request = None):
    """Full soul state: persona + affect + core memories."""
    _owned_soul_scope(request, soul_id)
    return get_soul_state(soul_id)


@app.put('/soul/persona/{soul_id}')
def soul_persona_update(
    soul_id: str,
    req: SoulPersonaUpdateIn,
    request: Request = None,
):
    """Update persona fields (name, core_traits, voice, soul_values, self_narrative)."""
    _owned_soul_scope(request, soul_id)
    try:
        update_persona(soul_id, **req.model_dump(exclude_unset=True))
    except PersonaPolicyViolation as exc:
        raise HTTPException(
            status_code=422,
            detail={
                'error': 'persona_policy_violation',
                'field': exc.field,
                'policy_result': exc.policy_result,
                'risk_tags': exc.risk_tags,
                'sensitivity_level': exc.sensitivity_level,
            },
        ) from exc
    except PersonaStoreError as exc:
        # 03-#6: 写库失败不再 HTTP 200 返回旧值假成功，显式 500
        raise HTTPException(
            status_code=500,
            detail={'error': 'persona_update_failed', 'soul_id': soul_id},
        ) from exc
    return get_persona(soul_id)


@app.get('/soul/affect/{soul_id}')
def soul_affect_get(soul_id: str, request: Request = None):
    """Current PAD affect state."""
    _owned_soul_scope(request, soul_id)
    state = load_affect(soul_id)
    return {
        'soul_id': soul_id,
        'pleasure': state.pleasure,
        'arousal': state.arousal,
        'dominance': state.dominance,
        'current_mood': state.current_mood,
        'mood_intensity': state.mood_intensity,
    }


@app.put('/soul/affect/{soul_id}')
def soul_affect_put(
    soul_id: str,
    trigger: str = Query(default='manual', min_length=1, max_length=100),
    intensity: float = 1.0,
    request: Request = None,
):
    """Apply a validated affect transition to an existing soul."""
    _owned_soul_scope(request, soul_id)
    try:
        new_state = transition(soul_id, trigger, intensity)
    except InvalidAffectIntensityError as exc:
        # Do not echo NaN/Infinity in the response: non-finite JSON values can
        # make Starlette fail while serializing the intended 422 response.
        raise HTTPException(
            status_code=422,
            detail={'error': 'invalid_intensity', 'valid_range': [0.0, 10.0]},
        ) from exc
    except UnsupportedAffectTriggerError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                'error': 'invalid_trigger',
                'valid_triggers': sorted(SUPPORTED_AFFECT_TRIGGERS),
            },
        ) from exc
    except AffectSoulNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={'error': 'soul_not_found', 'soul_id': soul_id},
        ) from exc

    return {
        'soul_id': soul_id,
        'trigger': trigger,
        'affect': {
            'pleasure': new_state.pleasure,
            'arousal': new_state.arousal,
            'dominance': new_state.dominance,
            'current_mood': new_state.current_mood,
            'mood_intensity': new_state.mood_intensity,
        },
    }


@app.post('/soul/dream')
def soul_dream(req: SoulDreamIn, request: Request = None):
    """Manually trigger a dream cycle for the soul."""
    _owned_soul_scope(request, req.soul_id)
    result = run_dream(req.soul_id)
    return {
        'soul_id': req.soul_id,
        'dream': result,
    }


# ---------------------------------------------------------------------------
# /soul/chat — OpenAI-compatible soul-injected chat
# ---------------------------------------------------------------------------


def _chat_request_context(messages: list[dict], model: str) -> tuple[str, str, str] | None:
    """Resolve the configured provider once and bound the prompt payload."""
    from .model_gateway.service import local_llama_settings

    api_base, env_model, _configured = local_llama_settings()
    api_model = env_model if model == 'default' else model
    if not api_base or not api_model:
        return None
    prompt = '\n'.join(
        str(message.get('content', ''))
        for message in messages
        if isinstance(message, dict)
    )[-4000:]
    return api_base, api_model, prompt


def _provider_error_completion(api_model: str, exc: Exception) -> dict:
    """Return a stable public error while keeping provider details in logs only."""
    logger.warning(
        'OpenAI-compatible provider request failed: model=%s error_type=%s',
        api_model,
        type(exc).__name__,
        exc_info=True,
    )
    return {
        'provider': 'openai_compatible',
        'model': api_model,
        'content': '',
        'latency_ms': 0,
        'status': 'provider_error',
        'error': 'provider_unavailable',
    }


def _chat_complete(messages: list[dict], model: str = 'default') -> dict:
    """Lightweight chat completion via the configured model gateway.

    03-#14: env 解析、allowlist 解析与超时常量统一走 model_gateway.service
    的单源访问函数，不再在本函数内各自重读/重解析。
    03-#18 加固：真实调用复用 model_gateway 的 hardened smoke path，
    共享 pinned-IP SSRF 防护、较短超时和有界专用线程池；避免本路由
    私自重建一套 httpx/DNS 解析逻辑。
    issue #45 (4.1): local_mock 回退已删除——未配置网关时如实
    provider_error，不产出任何模型口吻文本。
    """
    context = _chat_request_context(messages, model)
    if context is None:
        return {
            'provider': 'none',
            'model': model,
            'content': '',
            'latency_ms': 0,
            'status': 'provider_error',
            'error': 'gateway_not_configured',
        }
    api_base, api_model, prompt = context
    try:
        status, latency_ms, content = _run_smoke_in_dedicated_pool(
            'openai_compatible', api_base, '', api_model, prompt, 512,
        )
        if status != 'ok':
            raise RuntimeError(f'gateway_status={status}')
        return {
            'provider': 'openai_compatible',
            'model': api_model,
            'content': content,
            'latency_ms': latency_ms,
            'status': 'ok',
        }
    except Exception as exc:
        # B3: 失败如实返回 provider_error，不静默回退 mock
        return _provider_error_completion(api_model, exc)


async def _chat_complete_async(messages: list[dict], model: str = 'default') -> dict:
    """Async counterpart that leaves the Starlette worker pool available."""
    context = _chat_request_context(messages, model)
    if context is None:
        # issue #45 (4.1): 未配置网关不再回退 local_mock，如实报错。
        return {
            'provider': 'none',
            'model': model,
            'content': '',
            'latency_ms': 0,
            'status': 'provider_error',
            'error': 'gateway_not_configured',
        }
    api_base, api_model, prompt = context
    try:
        status, latency_ms, content = await _run_smoke_in_dedicated_pool_async(
            'openai_compatible', api_base, '', api_model, prompt, 512,
        )
        if status != 'ok':
            raise RuntimeError(f'gateway_status={status}')
        return {
            'provider': 'openai_compatible',
            'model': api_model,
            'content': content,
            'latency_ms': latency_ms,
            'status': 'ok',
        }
    except Exception as exc:
        return _provider_error_completion(api_model, exc)


@app.post('/soul/chat')
async def soul_chat(req: SoulChatIn, request: Request = None):
    """Soul-injected chat endpoint.

    1. Inject soul prompt into messages
    2. Retrieve relevant memories (optional enrichment)
    3. Call model gateway
    4. Perception intake on user + assistant turns
    5. Tune response style by affect
    6. Return full result
    """
    soul_id = req.soul_id
    soul_scope = _owned_soul_scope(request, soul_id)
    assert soul_scope is not None

    # 1. Soul injection
    routed = route_chat(soul_id, req.messages)
    injected_messages = routed['injected_messages']

    # 2. Perception: intake 当轮新增的 user 消息（最后一条，避免历史重复摄入）
    # OpenAI 风格客户端每轮重发完整历史，若逐条 intake 会导致记忆 O(N²) 膨胀
    # 和情绪重复累积；只取最后一条（当轮新增）即可。
    user_contents = [m['content'] for m in req.messages if m.get('role') == 'user']
    if user_contents:
        intake_perception(
            soul_id,
            role='user',
            content=user_contents[-1],
            owner_id=soul_scope.owner_id,
        )

    # 3. Call model gateway
    completion = await _chat_complete_async(injected_messages, model=req.model)

    # 4. Perception: intake assistant reply
    assistant_content = completion.get('content', '')
    if assistant_content:
        intake_perception(
            soul_id,
            role='assistant',
            content=assistant_content,
            owner_id=soul_scope.owner_id,
        )

    # 5. Tune response style by current affect
    current_affect = load_affect(soul_id)
    tuned_content = tune_response_style(assistant_content, current_affect)
    completion['content'] = tuned_content

    return {
        'soul_id': soul_id,
        'injection_prompt': routed['injection_prompt'],
        'messages': injected_messages,
        'completion': completion,
    }

# v0.6 MemoryOps Runtime endpoints
@app.post('/memory/v2/capsules')
def v2_write_capsule(req: CapsuleWriteIn, request: Request = None):
    soul_scope = _owned_soul_scope(
        request,
        req.soul_id,
        allow_internal_unscoped=True,
    )
    payload = req.model_dump()
    if soul_scope is not None:
        payload["soul_id"] = soul_scope.soul_id
        payload["owner_id"] = soul_scope.owner_id
    return write_capsule(**payload)

@app.get('/memory/v2/capsules')
def v2_list_capsules(
    limit: int = Query(default=50, ge=1, le=200),
    soul_id: str | None = None,
    request: Request = None,
):
    soul_scope = _owned_soul_scope(
        request,
        soul_id,
        allow_internal_unscoped=True,
    )
    items = [
        _public_capsule(item)
        for item in list_capsules(
            limit,
            owner_id=soul_scope.owner_id if soul_scope else None,
            soul_id=soul_scope.soul_id if soul_scope else None,
        )
    ]
    return {'items': items}

@app.get('/memory/v2/capsules/{capsule_id}')
def v2_get_capsule(
    capsule_id: str,
    soul_id: str | None = None,
    request: Request = None,
):
    soul_scope = _owned_soul_scope(
        request,
        soul_id,
        allow_internal_unscoped=True,
    )
    cap = get_capsule(
        capsule_id,
        owner_id=soul_scope.owner_id if soul_scope else None,
        soul_id=soul_scope.soul_id if soul_scope else None,
        external_read=True,
    )
    if not cap:
        if request is not None:
            raise HTTPException(status_code=404, detail={'error': 'not_found'})
        return {'error':'not_found','capsule_id':capsule_id}
    return _public_capsule(cap)

@app.get('/memory/v2/search')
def v2_search(
    q: str,
    top_k: int = 5,
    high_risk: bool = False,
    soul_id: str | None = None,
    request: Request = None,
):
    soul_scope = _owned_soul_scope(
        request,
        soul_id,
        allow_internal_unscoped=True,
    )
    q, top_k = validate_search_params(q, top_k)
    results, retrieval = search_capsules_with_status(
        q,
        top_k=top_k,
        high_risk=high_risk,
        owner_id=soul_scope.owner_id if soul_scope else None,
        soul_id=soul_scope.soul_id if soul_scope else None,
    )
    results = [_public_capsule(result) for result in results]
    return {'query':q,'retrieval':retrieval,'results':results,'evidence_cards':[build_evidence_card(r) for r in results]}

@app.post('/memory/v2/command')
def v2_command(req: CommandLoopIn, request: Request = None):
    soul_scope = _owned_soul_scope(
        request,
        req.soul_id,
        allow_internal_unscoped=True,
    )
    validate_goal_length(req.goal)
    result = run_command_loop(
        goal=req.goal,
        scene=req.scene,
        top_k=req.top_k,
        owner_id=soul_scope.owner_id if soul_scope else None,
        soul_id=soul_scope.soul_id if soul_scope else None,
    )
    recalled_memories = [
        _public_capsule(item) for item in result['recalled_memories']
    ]
    result['recalled_memories'] = recalled_memories
    result['evidence_cards'] = [
        build_evidence_card(item, used_for='planning') for item in recalled_memories
    ]
    return result

@app.post('/memory/v2/reflection')
def v2_reflection(req: ReflectionIn, request: Request = None):
    soul_scope = _owned_soul_scope(
        request,
        req.soul_id,
        allow_internal_unscoped=True,
    )
    return reflect_task(
        req.task_id,
        req.model_dump(),
        owner_id=soul_scope.owner_id if soul_scope else None,
        soul_id=soul_scope.soul_id if soul_scope else None,
    )

@app.get('/audit/logs')
def audit_logs(limit:int=50,trace_id:str|None=None):
    return {'items':list_logs(limit,trace_id)}

# 万枢协作平台聚合路由：platform_api 包自动发现子模块 router，
# 单个子模块导入失败记 error 日志并跳过，不影响整体启动（03-#19）。
# 03-#13: 统一相对导入。
from .platform_api import api_router as platform_api_router
app.include_router(platform_api_router, prefix='/platform')
