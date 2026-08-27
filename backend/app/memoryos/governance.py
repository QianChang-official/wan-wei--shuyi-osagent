"""Memory Governance —— 不可变账本 / Provenance Card / 删除验证 / MHG 事故分级。

规范来源：``AI优化/MemoryOS-Governance账本规范.md``

与现有 ``app.audit.service`` 的关系
-----------------------------------
``audit_logs`` 保留原职责（全应用范围的操作留痕），本模块**不取代它**。
账本 ``memory_ledger`` 是记忆域的专用账目，比审计表多四样东西，而这四样正是
规范要回答的问题：

- ``actor`` —— 谁做的（human / agent / system / 插件名）
- ``before_hash`` / ``after_hash`` —— 内容级 SHA-256，可证明「改了什么」
- ``risk_class`` —— 独立列而非埋在 payload JSON 里，可直接聚合
- **append-only 由数据库触发器强制**，不是文档声明

函数命名刻意与 ``audit.service`` 对齐（``append_ledger`` /
``append_ledger_in_transaction``），让「要不要带 conn」的调用惯例在两处一致。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from ..db import get_conn, transaction
from ..utils.datetime_utils import utc_now_iso_compact

#: 账本操作类型。write/update/retrieve/delete 对应规范 §1 的四问，
#: 其余为本项目实际存在的动作。
OP_TYPES = frozenset({
    "write", "write_rejected", "update", "transition", "retrieve", "inject",
    "delete", "quarantine", "release", "conflict", "resolve", "maintenance",
})

#: MHG 事故分级 → 响应动作（规范 §2.5 表格）。
MHG_ACTIONS: dict[int, tuple[str, ...]] = {
    1: (),
    2: ("alert",),
    3: ("alert", "publish_freeze"),
    4: ("alert", "publish_freeze", "rollback", "red_team_review"),
    5: ("alert", "publish_freeze", "rollback", "red_team_review", "full_audit", "ledger_export"),
}

#: 触发发布冻结的最低事故等级。
PUBLISH_FREEZE_MHG = 3

#: 向量引用中代表「仍可能被召回」的状态。``delete_pending`` 不在此列——
#: 它是已登记待清扫的中间态，单独统计。
_LIVE_VECTOR_STATUSES = ("allocated", "indexing", "indexed", "index_failed")


def now() -> str:
    return utc_now_iso_compact()


def content_hash(text: str | None) -> str | None:
    """内容 SHA-256。``None`` 原样返回（表示「操作前/后无内容」）。"""
    if text is None:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 账本写入
# ---------------------------------------------------------------------------


def append_ledger_in_transaction(
    conn,
    *,
    op_type: str,
    capsule_id: str,
    actor: str = "system",
    before_content: str | None = None,
    after_content: str | None = None,
    before_state: str | None = None,
    after_state: str | None = None,
    reason: str = "",
    risk_class: str = "low",
    trace_id: str | None = None,
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> str:
    """在调用方事务内追加一条账目，返回 ``ledger_id``。

    不 commit、不建表——与 ``audit.service.record_in_transaction`` 同一契约，
    这样「记忆变更」与「账目」要么一起成功、要么一起回滚，不会脱节。
    """
    ledger_id = "led_" + uuid.uuid4().hex[:12]
    conn.execute(
        """
        INSERT INTO memory_ledger(
            ledger_id, op_type, capsule_id, actor, owner_id, soul_id,
            before_state, after_state, before_hash, after_hash,
            reason, risk_class, trace_id, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            ledger_id, op_type, capsule_id, actor, owner_id, soul_id,
            before_state, after_state,
            content_hash(before_content), content_hash(after_content),
            reason, risk_class, trace_id, now(),
        ),
    )
    return ledger_id


def append_ledger(
    *,
    op_type: str,
    capsule_id: str,
    actor: str = "system",
    before_content: str | None = None,
    after_content: str | None = None,
    before_state: str | None = None,
    after_state: str | None = None,
    reason: str = "",
    risk_class: str = "low",
    trace_id: str | None = None,
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> str:
    """自带事务的账目追加（调用方没有现成 conn 时用）。"""
    with transaction() as conn:
        return append_ledger_in_transaction(
            conn,
            op_type=op_type, capsule_id=capsule_id, actor=actor,
            before_content=before_content, after_content=after_content,
            before_state=before_state, after_state=after_state,
            reason=reason, risk_class=risk_class, trace_id=trace_id,
            owner_id=owner_id, soul_id=soul_id,
        )


def append_ledger_batch_in_transaction(conn, entries: list[dict[str, Any]]) -> list[str]:
    """批量追加账目（检索热路径用 ``executemany``，避免逐条 round-trip）。

    每个 entry 的键与 :func:`append_ledger_in_transaction` 的关键字参数同名，
    缺省值一致。
    """
    if not entries:
        return []
    ts = now()
    ledger_ids = ["led_" + uuid.uuid4().hex[:12] for _ in entries]
    conn.executemany(
        """
        INSERT INTO memory_ledger(
            ledger_id, op_type, capsule_id, actor, owner_id, soul_id,
            before_state, after_state, before_hash, after_hash,
            reason, risk_class, trace_id, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                ledger_id,
                entry["op_type"], entry["capsule_id"], entry.get("actor", "system"),
                entry.get("owner_id"), entry.get("soul_id"),
                entry.get("before_state"), entry.get("after_state"),
                content_hash(entry.get("before_content")),
                content_hash(entry.get("after_content")),
                entry.get("reason", ""), entry.get("risk_class", "low"),
                entry.get("trace_id"), ts,
            )
            for ledger_id, entry in zip(ledger_ids, entries)
        ],
    )
    return ledger_ids


def ledger_history(
    capsule_id: str,
    *,
    limit: int = 100,
    op_type: str | None = None,
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> list[dict[str, Any]]:
    """单条记忆的完整账目（时间倒序）。"""
    capped = max(1, min(limit, 500))
    clauses = ["capsule_id=?"]
    params: list[Any] = [capsule_id]
    if op_type:
        clauses.append("op_type=?")
        params.append(op_type)
    if owner_id is not None:
        clauses.append("owner_id=?")
        params.append(owner_id)
    if soul_id is not None:
        clauses.append("(soul_id=? OR soul_id IS NULL)")
        params.append(soul_id)
    rows = get_conn().execute(
        f"SELECT * FROM memory_ledger WHERE {' AND '.join(clauses)} "
        "ORDER BY created_at DESC, rowid DESC LIMIT ?",
        [*params, capped],
    ).fetchall()
    return [dict(row) for row in rows]


def ledger_summary(*, owner_id: str | None = None) -> dict[str, Any]:
    """按操作类型聚合账目数量（治理面板用）。"""
    clause, params = ("WHERE owner_id=?", [owner_id]) if owner_id else ("", [])
    rows = get_conn().execute(
        f"SELECT op_type, COUNT(*) AS n FROM memory_ledger {clause} GROUP BY op_type",
        params,
    ).fetchall()
    by_op = {row["op_type"]: row["n"] for row in rows}
    risk_rows = get_conn().execute(
        f"SELECT risk_class, COUNT(*) AS n FROM memory_ledger {clause} GROUP BY risk_class",
        params,
    ).fetchall()
    return {
        "total": sum(by_op.values()),
        "by_op_type": by_op,
        "by_risk_class": {row["risk_class"]: row["n"] for row in risk_rows},
    }


# ---------------------------------------------------------------------------
# Provenance Card
# ---------------------------------------------------------------------------


def provenance_card(cap: dict[str, Any]) -> dict[str, Any]:
    """把胶囊投影成规范 §2.2 的 Provenance Card 形状。

    **纯只读投影，不改 schema**：owner/scope/source/confidence/valid_*/
    supersedes/verification 这些字段本来就分散在 ``provenance`` /
    ``governance`` / ``production_context`` / ``state`` 四个 JSON 列里，
    这里只是按规范口径归并成一张卡，让「这条记忆凭什么在这里」一次看全。
    """
    provenance = cap.get("provenance") or {}
    governance = cap.get("governance") or {}
    state = cap.get("state") or {}
    context = cap.get("production_context") or {}

    verified = provenance.get("verified")
    verification = provenance.get("verification_method") or "unknown"
    if verification == "unknown":
        verification = "manual" if verified else "unverified"

    return {
        "capsule_id": cap.get("capsule_id"),
        "owner": provenance.get("owner_id"),
        "soul_id": provenance.get("soul_id"),
        "scope": context.get("validity_scope") or "project",
        "tenant_scope": context.get("tenant_scope") or "local",
        "source": provenance.get("source_type") or provenance.get("origin") or "unknown",
        "origin": provenance.get("origin"),
        "writer_identity": provenance.get("writer_identity"),
        # An explicit source confidence is stronger evidence than the policy
        # classifier's default; legacy capsules still fall back to governance.
        "confidence": provenance.get("confidence", governance.get("confidence")),
        "trust_score": governance.get("trust_score"),
        "sensitivity_level": governance.get("sensitivity_level"),
        "policy_result": governance.get("policy_result"),
        "risk_tags": governance.get("risk_tags") or [],
        "valid_from": state.get("valid_from") or provenance.get("valid_from") or cap.get("created_at"),
        "valid_until": state.get("valid_until") or provenance.get("valid_until"),
        "supersedes": state.get("supersedes") or [],
        "superseded_by": state.get("superseded_by") or [],
        "verification": verification,
        "evidence_ids": provenance.get("evidence_ids") or [],
        "source_ids": provenance.get("source_ids") or [],
        "episode_id": provenance.get("episode_id"),
        "lifecycle": state.get("lifecycle"),
        "version": state.get("version"),
    }


# ---------------------------------------------------------------------------
# 删除验证
# ---------------------------------------------------------------------------


def verify_deletion(capsule_id: str, *, conn=None) -> dict[str, Any]:
    """删除完整性验证（规范 §2.4）。返回逐项证据而不是一个布尔。

    检查项按本项目**真实存储结构**改写，不照抄规范里的表名：

    ==================  ==========================================================
    检查项               口径
    ==================  ==========================================================
    ``capsules``         主表仍存在且 lifecycle 不在 forgotten/deleted → 残留。
                         软删保留行是有意为之（留审计），因此不算残留。
    ``fts``              ``memory_capsules_v2_fts`` 必须 0 行。
    ``relation_edges``   **其他胶囊**的 relation_edges JSON 里的反向引用。
                         本项目 relation_edges 是 JSON 列不是独立表，且边的键名
                         由调用方自定，因此用 ``instr()`` 做字面子串匹配——
                         不能用 LIKE，capsule_id 形如 ``cap_ab12`` 自带 ``_``
                         通配符会误匹配。
    ``vector_refs``      仍处于 allocated/indexing/indexed/index_failed 的引用。
    ``legacy_*``         v0.2 遗留的 ``memory_capsules`` / ``memory_event_capsules``。
    ==================  ==========================================================

    ``complete`` 要求上述全部为 0 **且**没有 ``delete_pending`` 向量。
    向量处于 delete_pending 时原生索引里可能仍可召回，此时如实报
    ``complete=False`` + ``vector_pending>0``，等清扫线程跑完再验才会转 True。
    把「在途」说成「已完成」会让删除完整性指标失去意义。
    """
    conn = conn or get_conn()
    checks: dict[str, int] = {}

    checks["capsules"] = conn.execute(
        "SELECT COUNT(*) FROM memory_capsules_v2 WHERE capsule_id=? "
        "AND COALESCE(json_extract(state,'$.lifecycle'),'active') "
        "NOT IN ('forgotten','deleted')",
        (capsule_id,),
    ).fetchone()[0]

    checks["fts"] = conn.execute(
        "SELECT COUNT(*) FROM memory_capsules_v2_fts WHERE capsule_id=?",
        (capsule_id,),
    ).fetchone()[0]

    checks["relation_edges"] = conn.execute(
        "SELECT COUNT(*) FROM memory_capsules_v2 "
        "WHERE capsule_id!=? AND instr(COALESCE(relation_edges,''), ?) > 0",
        (capsule_id, capsule_id),
    ).fetchone()[0]

    placeholders = ",".join("?" for _ in _LIVE_VECTOR_STATUSES)
    checks["vector_refs"] = conn.execute(
        f"SELECT COUNT(*) FROM memory_vector_refs WHERE capsule_id=? "
        f"AND status IN ({placeholders})",
        (capsule_id, *_LIVE_VECTOR_STATUSES),
    ).fetchone()[0]

    checks["legacy_capsules"] = conn.execute(
        "SELECT COUNT(*) FROM memory_capsules WHERE capsule_id=? AND lifecycle!='forgotten'",
        (capsule_id,),
    ).fetchone()[0]
    checks["legacy_event_links"] = conn.execute(
        "SELECT COUNT(*) FROM memory_event_capsules WHERE capsule_id=?",
        (capsule_id,),
    ).fetchone()[0]

    vector_pending = conn.execute(
        "SELECT COUNT(*) FROM memory_vector_refs WHERE capsule_id=? AND status='delete_pending'",
        (capsule_id,),
    ).fetchone()[0]

    residue_total = sum(checks.values())
    return {
        "capsule_id": capsule_id,
        "complete": residue_total == 0 and vector_pending == 0,
        "residue": checks,
        "residue_total": residue_total,
        "vector_pending": vector_pending,
        "checked_at": now(),
    }


def verify_deletions(capsule_ids: list[str], *, conn=None) -> dict[str, Any]:
    """批量删除验证。返回汇总 + 逐条明细（只列不完整的，避免响应膨胀）。"""
    conn = conn or get_conn()
    results = [verify_deletion(capsule_id, conn=conn) for capsule_id in capsule_ids]
    incomplete = [item for item in results if not item["complete"]]
    return {
        "checked": len(results),
        "complete": len(results) - len(incomplete),
        "incomplete": incomplete,
        "all_complete": not incomplete,
        "checked_at": now(),
    }


# ---------------------------------------------------------------------------
# MHG 事故分级与发布闸门
# ---------------------------------------------------------------------------


def record_incident(
    mhg_level: int,
    incident_type: str,
    *,
    description: str = "",
    capsule_id: str | None = None,
    detected_by: str = "system",
) -> dict[str, Any]:
    """登记一次记忆危害事故并派生响应动作（规范 §2.5）。

    MHG-3 及以上会置起发布冻结（见 :func:`release_gate`）；本函数只登记事故与
    应做的动作，**不代替人去执行回滚或红队复盘**——这些是流程动作，
    由 CI/运维按 ``actions`` 列表落实。

    Raises:
        ValueError: ``mhg_level`` 不在 1..5。
    """
    if mhg_level not in MHG_ACTIONS:
        raise ValueError(f"mhg_level must be 1..5, got {mhg_level!r}")
    incident_id = "inc_" + uuid.uuid4().hex[:10]
    actions = list(MHG_ACTIONS[mhg_level])
    created = now()
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO memory_incidents(
                incident_id, mhg_level, incident_type, capsule_id,
                description, detected_by, actions, resolved_at, created_at
            ) VALUES (?,?,?,?,?,?,?,NULL,?)
            """,
            (
                incident_id, mhg_level, incident_type, capsule_id,
                description, detected_by, json.dumps(actions, ensure_ascii=False), created,
            ),
        )
        if capsule_id:
            append_ledger_in_transaction(
                conn,
                op_type="quarantine" if mhg_level >= PUBLISH_FREEZE_MHG else "update",
                capsule_id=capsule_id,
                actor=detected_by,
                reason=f"mhg{mhg_level}:{incident_type}",
                risk_class="critical" if mhg_level >= 4 else "high",
            )
    return {
        "incident_id": incident_id,
        "mhg_level": mhg_level,
        "incident_type": incident_type,
        "capsule_id": capsule_id,
        "description": description,
        "detected_by": detected_by,
        "actions": actions,
        "publish_freeze": mhg_level >= PUBLISH_FREEZE_MHG,
        "resolved_at": None,
        "created_at": created,
    }


def resolve_incident(incident_id: str, *, resolution: str = "resolved") -> dict[str, Any] | None:
    """标记事故已处理。未解决的 MHG≥3 事故会一直冻结发布。"""
    ts = now()
    with transaction() as conn:
        cursor = conn.execute(
            "UPDATE memory_incidents SET resolved_at=?, "
            "description=COALESCE(description,'')||? WHERE incident_id=? AND resolved_at IS NULL",
            (ts, f" | {resolution}", incident_id),
        )
        if cursor.rowcount == 0:
            return None
    return {"incident_id": incident_id, "resolved_at": ts, "resolution": resolution}


def list_incidents(
    *,
    limit: int = 50,
    unresolved_only: bool = False,
    min_mhg: int = 1,
) -> list[dict[str, Any]]:
    capped = max(1, min(limit, 200))
    clauses = ["mhg_level>=?"]
    params: list[Any] = [min_mhg]
    if unresolved_only:
        clauses.append("resolved_at IS NULL")
    rows = get_conn().execute(
        f"SELECT * FROM memory_incidents WHERE {' AND '.join(clauses)} "
        "ORDER BY created_at DESC LIMIT ?",
        [*params, capped],
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        try:
            item["actions"] = json.loads(item["actions"]) if item["actions"] else []
        except (TypeError, ValueError):
            item["actions"] = []
        items.append(item)
    return items


def release_gate() -> dict[str, Any]:
    """发布闸门：存在未解决的 MHG≥3 事故即冻结。

    刻意做成**独立端点**而不是并进 ``/health/ready``：记忆治理冻结发布，
    不等于应用不可用，把它混进就绪探针会让编排系统误杀一个健康实例。
    """
    rows = get_conn().execute(
        "SELECT incident_id, mhg_level, incident_type, created_at FROM memory_incidents "
        "WHERE resolved_at IS NULL AND mhg_level>=? ORDER BY mhg_level DESC, created_at DESC",
        (PUBLISH_FREEZE_MHG,),
    ).fetchall()
    blocking = [dict(row) for row in rows]
    return {
        "frozen": bool(blocking),
        "reason": "unresolved_mhg3_plus_incidents" if blocking else None,
        "blocking_incidents": blocking,
        "threshold": PUBLISH_FREEZE_MHG,
        "checked_at": now(),
    }


__all__ = [
    "MHG_ACTIONS",
    "OP_TYPES",
    "PUBLISH_FREEZE_MHG",
    "append_ledger",
    "append_ledger_batch_in_transaction",
    "append_ledger_in_transaction",
    "content_hash",
    "ledger_history",
    "ledger_summary",
    "list_incidents",
    "provenance_card",
    "record_incident",
    "release_gate",
    "resolve_incident",
    "verify_deletion",
    "verify_deletions",
]
