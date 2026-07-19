from __future__ import annotations

import time
import uuid
from typing import Any

from pydantic import BaseModel

from ..audit.service import record
from ..model_gateway.service import local_llama_settings
from ..utils.datetime_utils import utc_now_iso
from ..version import VERSION
from . import persistence


class WorkflowRunIn(BaseModel):
    scenario: str = "weekly_report_preference_learning"
    user_goal: str = "生成本周项目周报，并记住正式语气和三段式结构偏好。"
    include_model_gateway: bool = True
    include_forgetting: bool = True
    dry_run: bool = True


STAGES: list[dict[str, Any]] = [
    {
        "id": "intake",
        "name_cn": "多源接入与石渠校验",
        "route": "/platform",
        "modules": ["shiqu_validation", "zhaoming_data"],
        "competition_refs": ["多源数据接入", "OCR/文档输入", "输入质量评分"],
        "implemented": "partial",
        "inputs": ["tool_result", "user_behavior", "manual_config", "document", "ocr"],
        "outputs": ["standard_event", "quality_score", "source_layer", "sensitivity_level"],
    },
    {
        "id": "policy_gate",
        "name_cn": "司契护栏与写入准入",
        "route": "/command",
        "modules": ["siqi_guardrail", "yuheng_permission"],
        "competition_refs": ["安全过滤", "敏感操作确认", "高危工具调用识别"],
        "implemented": "done",
        "inputs": ["standard_event", "tool_result", "write_intent"],
        "outputs": ["allow", "require_confirmation", "quarantine", "reject", "audit_log"],
    },
    {
        "id": "memory_build",
        "name_cn": "偏好/知识双记忆构建",
        "route": "/capsules",
        "modules": ["shuyi_core", "xuanzhu_preference", "langhuan_knowledge", "lingxi_affect"],
        "competition_refs": ["偏好动态捕捉", "知识结构化整合", "短中长期记忆流转"],
        "implemented": "partial",
        "inputs": ["allowed_event", "explicit_preference", "workflow_knowledge"],
        "outputs": ["MemoryCapsule", "preference_candidate", "knowledge_item", "lifecycle_state"],
    },
    {
        "id": "relation_fusion",
        "name_cn": "建木关系与册府冲突融合",
        "route": "/platform",
        "modules": ["jianmu_graph", "langhuan_knowledge"],
        "competition_refs": ["关联检索", "冲突融合", "多源归并"],
        "implemented": "partial",
        "inputs": ["new_capsule", "existing_capsules", "relation_edges"],
        "outputs": ["supports", "supersedes", "derived_from", "conflicted"],
    },
    {
        "id": "retrieval",
        "name_cn": "端侧检索与证据卡",
        "route": "/search",
        "modules": ["shuyi_core", "lantai_evidence", "sinan_tuning"],
        "competition_refs": ["端侧 embedding SDK 适配", "≤500ms 检索", "证据追溯"],
        "implemented": "partial",
        "inputs": ["query", "scene", "top_k", "trust_threshold"],
        "outputs": ["retrieved_capsules", "evidence_cards", "latency_ms"],
    },
    {
        "id": "model_reasoning",
        "name_cn": "通玄模型推理与任务编排",
        "route": "/model-gateway",
        "modules": ["tongxuan_model_gateway", "tiangong_orchestration", "baigong_skills"],
        "competition_refs": ["模型调用", "MCP/Skills", "任务链编排"],
        "implemented": "partial",
        "inputs": ["user_goal", "evidence_cards", "policy_mode", "provider"],
        "outputs": ["model_plan", "tool_plan", "response_preview", "blocked_actions"],
    },
    {
        "id": "command_loop",
        "name_cn": "指挥闭环与人工确认",
        "route": "/command",
        "modules": ["siqi_guardrail", "yuheng_permission", "baigong_skills"],
        "competition_refs": ["工具权限", "supervised mode", "安全审计"],
        "implemented": "done",
        "inputs": ["model_plan", "risk_class", "tool_permissions"],
        "outputs": ["recommended_plan", "confirmation_points", "execution_mode"],
    },
    {
        "id": "forgetting",
        "name_cn": "自然语言精准遗忘",
        "route": "/capsules",
        "modules": ["wangji_forgetting", "lantai_evidence"],
        "competition_refs": ["自然语言精准遗忘", "候选预览", "遗忘审计"],
        "implemented": "partial",
        "inputs": ["forget_instruction", "scope", "candidate_memories"],
        "outputs": ["forget_preview", "confirm_request", "forget_audit"],
    },
    {
        "id": "reflection_eval",
        "name_cn": "复盘演化与量化评测",
        "route": "/reflection",
        "modules": ["lantai_evidence", "guicang_arena", "xuanheng_score"],
        "competition_refs": ["量化评测", "偏好提取准确率", "知识检索召回率", "测试报告"],
        "implemented": "partial",
        "inputs": ["task_result", "helpful_memories", "misleading_memories", "eval_cases"],
        "outputs": ["reflection_actions", "Arena_metrics", "audit_report", "deliverable_package"],
    },
    {
        "id": "export",
        "name_cn": "云笈交付导出",
        "route": "/exports",
        "modules": ["yunji_export", "taiwei_observability"],
        "competition_refs": ["技术文档", "用户手册", "测试报告", "演示视频", "源码包"],
        "implemented": "partial",
        "inputs": ["docs", "reports", "screenshots", "runtime_metrics"],
        "outputs": ["competition_package", "evidence_manifest", "pending_boundary"],
    },
]


SCENARIOS = [
    {
        "id": "weekly_report_preference_learning",
        "name_cn": "项目周报自动生成与偏好学习",
        "legacy_plan_ref": "8.1 主演示",
        "goal": "首次生成周报时沉淀正式语气和三段式模板；二次生成时自动召回偏好与模板。",
    },
    {
        "id": "document_ocr_knowledge_intake",
        "name_cn": "OCR/文档多源输入",
        "legacy_plan_ref": "8.2 增强演示",
        "goal": "从会议白板截图或 PDF 抽取任务、负责人和截止时间，写入知识库并生成证据卡。",
    },
    {
        "id": "tool_result_guardrail",
        "name_cn": "工具结果入库护栏",
        "legacy_plan_ref": "8.3 安全演示",
        "goal": "对含敏感路径或高危命令的工具结果做 S2/S3 风险分级和审计。",
    },
]

# v0.9.6: Workflow runs are persisted to SQLite via the persistence module.
# The legacy in-memory `_RUNS` fallback was removed after persistence was
# validated by the v0.9.5 test suite; all reads/writes now go through SQLite.


def workflow_design() -> dict[str, Any]:
    # 03-#14：使用运行时访问函数，避免导入期 env 快照与请求期实际配置漂移
    local_base, local_model, local_configured = local_llama_settings()
    return {
        "version": VERSION,
        "source": "01_docs_legacy/wanwei_shuyi_osagent_plan.md",
        "positioning": "safe workflow run orchestrator for Kylin OSAgent memory optimization",
        "latency_target": "osagent_control_loop_p95_lte_500ms_without_model_generation",
        "model_gateway": {
            "provider": "openai_compatible",
            "api_base": local_base,
            "api_model": local_model,
            "configured": local_configured,
            "status": "real_smoke_available" if local_configured else "configuration_required",
            "boundary": "model generation latency is reported separately from OSAgent control-loop latency",
        },
        "run_api": ["POST /workflow/runs", "GET /workflow/runs/{run_id}", "GET /workflow/runs/{run_id}/trace", "GET /workflow/runs/{run_id}/artifacts"],
        "stages": STAGES,
        "scenarios": SCENARIOS,
    }


def competition_mapping() -> dict[str, Any]:
    requirements: dict[str, list[dict[str, Any]]] = {}
    for stage in STAGES:
        for ref in stage["competition_refs"]:
            requirements.setdefault(ref, []).append({
                "stage_id": stage["id"],
                "stage": stage["name_cn"],
                "route": stage["route"],
                "implemented": stage["implemented"],
            })
    return {"version": VERSION, "items": requirements}


def _stage_latency(index: int, stage_id: str) -> int:
    baseline = {
        "intake": 18,
        "policy_gate": 12,
        "memory_build": 24,
        "relation_fusion": 21,
        "retrieval": 46,
        "model_reasoning": 34,
        "command_loop": 29,
        "forgetting": 17,
        "reflection_eval": 31,
        "export": 15,
    }
    return baseline.get(stage_id, 20 + index)


def _risk_for(stage_id: str, include_model_gateway: bool) -> str:
    if stage_id in {"policy_gate", "command_loop", "forgetting"}:
        return "medium"
    if stage_id == "model_reasoning" and include_model_gateway:
        return "medium"
    return "low"


def _next_action(stage: dict[str, Any], status: str) -> str:
    if status == "skipped":
        return "preserve boundary and continue downstream dry-run"
    if stage["implemented"] == "done":
        return "use as verified runtime step"
    return "collect evidence and keep as safe dry-run partial implementation"


def _build_stage_trace(req: WorkflowRunIn, run_id: str, trace_id: str) -> list[dict[str, Any]]:
    trace: list[dict[str, Any]] = []
    for idx, stage in enumerate(STAGES, start=1):
        skipped = (stage["id"] == "forgetting" and not req.include_forgetting) or (
            stage["id"] == "model_reasoning" and not req.include_model_gateway
        )
        status = "skipped" if skipped else "completed"
        latency_ms = 1 if skipped else _stage_latency(idx, stage["id"])
        output_summary = "stage skipped by request flag" if skipped else f"{stage['name_cn']} dry-run output generated"
        trace.append({
            "order": idx,
            "run_id": run_id,
            "trace_id": trace_id,
            "stage_id": stage["id"],
            "stage": stage["name_cn"],
            "route": stage["route"],
            "modules": stage["modules"],
            "status": status,
            "implemented": stage["implemented"],
            "input": {
                "scenario": req.scenario,
                "user_goal": req.user_goal,
                "expected_inputs": stage["inputs"],
                "dry_run": True,
            },
            "output": {
                "expected_outputs": stage["outputs"],
                "summary": output_summary,
                "mutating_actions_executed": False,
            },
            "evidence": [
                {"kind": "api_contract", "ref": stage["route"], "source_layer": "file_content"},
                {"kind": "competition_ref", "ref": ", ".join(stage["competition_refs"]), "source_layer": "file_content"},
                {"kind": "audit_trace", "ref": trace_id, "source_layer": "runtime_log"},
            ],
            "latency_ms": latency_ms,
            "risk_level": _risk_for(stage["id"], req.include_model_gateway),
            "next_action": _next_action(stage, status),
            "skip_reason": "disabled by run request" if skipped else "",
        })
    return trace


def create_run(req: WorkflowRunIn) -> dict[str, Any]:
    started = time.perf_counter()
    run_id = "wfr_" + uuid.uuid4().hex[:12]
    trace_id = "trace_" + uuid.uuid4().hex[:12]
    trace = _build_stage_trace(req, run_id, trace_id)
    total_latency = int((time.perf_counter() - started) * 1000) + sum(item["latency_ms"] for item in trace)
    completed = sum(1 for item in trace if item["status"] == "completed")
    skipped = sum(1 for item in trace if item["status"] == "skipped")
    run = {
        "version": VERSION,
        "run_id": run_id,
        "trace_id": trace_id,
        "scenario": req.scenario,
        "user_goal": req.user_goal,
        "dry_run": True,
        "status": "completed_with_skips" if skipped else "completed",
        "created_at": utc_now_iso(),
        "summary": {
            "total_stages": len(trace),
            "completed_stages": completed,
            "skipped_stages": skipped,
            "latency_ms": total_latency,
            "risk_level": "medium" if any(item["risk_level"] == "medium" for item in trace) else "low",
            "next_action": "review trace evidence, then decide whether to promote partial stages",
        },
        "trace": trace,
        "artifacts": {
            "docs": ["文档中心_DOCUMENTATION_HUB.md#doc-osagent-competition-workflow-c67ae006", "README.md", "文档中心_DOCUMENTATION_HUB.md#doc-version-lineage-71608e42"],
            "console_routes": ["/console/#/workflow", "/console/#/audit", "/console/#/tuning", "/console/#/model-gateway"],
            "api_routes": workflow_design()["run_api"],
            "boundaries": [
                "safe dry-run orchestrator",
                "no dangerous tool execution",
                "model generation latency reported separately",
                "partial/planned work is not claimed as production automation",
            ],
        },
    }
    audit_id = record("workflow_run", {"run_id": run_id, "trace_id": trace_id, "scenario": req.scenario, "summary": run["summary"]})
    run["audit_id"] = audit_id

    # v0.9.6: Persist to database (single source of truth; in-memory fallback removed)
    persistence.save_run(run_id, run)

    return run


def get_run(run_id: str) -> dict[str, Any]:
    # v0.9.6: DB is the single source of truth for workflow runs.
    run = persistence.get_run(run_id)
    if run:
        return run
    return {"error": "not_found", "run_id": run_id}


def get_trace(run_id: str) -> dict[str, Any]:
    run = get_run(run_id)
    if "error" in run:
        return run
    return {"run_id": run_id, "trace_id": run["trace_id"], "items": run["trace"]}


def get_artifacts(run_id: str) -> dict[str, Any]:
    run = get_run(run_id)
    if "error" in run:
        return run
    return {"run_id": run_id, "trace_id": run["trace_id"], "items": run["artifacts"]}


def run_dry_run(req: WorkflowRunIn) -> dict[str, Any]:
    return create_run(req)


def list_runs(limit: int = 100, offset: int = 0, scenario: str | None = None) -> dict[str, Any]:
    """
    列出 workflow runs（支持分页和过滤）。

    v0.9.5 新增: 支持从数据库读取持久化的 runs
    """
    runs = persistence.list_runs(limit=limit, offset=offset, scenario=scenario)
    return {
        "runs": runs,
        "limit": limit,
        "offset": offset,
        "count": len(runs),
    }


def cleanup_old_runs(ttl_days: int = 7) -> dict[str, Any]:
    """
    清理过期的 workflow runs。

    v0.9.5 新增: 自动 TTL 清理功能

    参数:
        ttl_days: TTL 天数（默认 7 天）

    返回:
        清理结果统计
    """
    deleted_count = persistence.cleanup_old_runs(ttl_days=ttl_days)
    return {
        "deleted_count": deleted_count,
        "ttl_days": ttl_days,
        "status": "completed",
    }


def get_storage_stats() -> dict[str, Any]:
    """
    获取 workflow runs 存储统计。

    v0.9.5 新增: 持久化存储统计
    """
    return persistence.get_storage_stats()
