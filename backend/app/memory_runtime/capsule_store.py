import json
import threading
import uuid
from typing import Any

from ..db import get_conn, database_path, transaction
from ..audit.service import record, record_in_transaction
from ..utils.cjk_text import cjk_space
from ..utils.datetime_utils import utc_now_iso_compact
from ..memoryos.lifecycle import (
    HIGH_RISK_EXCLUDED_STATES,
    INDEXABLE_POLICIES,
    RETRIEVABLE_STATES,
    retrievable_sql_list,
)
from .policy_gate import evaluate_policy

# 策略闸门与生命周期的可检索口径统一由 memoryos.lifecycle 提供，避免这里和
# retrieval 各写一份 IN 列表而漂移。lifecycle 的纯词表段不 import
# memory_runtime，因此这个模块级导入不构成循环依赖。
RETRIEVABLE_POLICY = INDEXABLE_POLICIES
RETRIEVABLE_LIFECYCLE = RETRIEVABLE_STATES

#: SQL 片段：可检索状态的 IN 列表字面量（内容全为模块常量，拼接安全）。
_RETRIEVABLE_SQL = retrievable_sql_list()

# B2: 模块级 once 标记，按 db_path 缓存。避免每次 write_capsule 都跑完整
# init_db（~30 条 DDL + 迁移扫描 + print）。测试切换 WANWEI_MEMORY_DB 时
# 新路径不在缓存中，会重新 init。
_runtime_schema_done: set[str] = set()
_runtime_schema_lock = threading.Lock()


def now() -> str:
    return utc_now_iso_compact()


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def loads(text: str, default: Any = None) -> Any:
    if text is None:
        return default
    return json.loads(text)


def _content_text(content: dict[str, Any]) -> str:
    return dumps(content)


def _lifecycle_for_policy(policy_result: str) -> str:
    if policy_result == "quarantine":
        return "quarantined"
    if policy_result == "reject":
        return "rejected"
    if policy_result == "require_confirmation":
        return "candidate"
    return "active"


def init_runtime_schema() -> None:
    """初始化 runtime schema，每个 db_path 只跑一次（线程安全）。"""
    path = str(database_path())
    if path in _runtime_schema_done:
        return
    with _runtime_schema_lock:
        if path in _runtime_schema_done:
            return
        from ..init_db import main
        main()
        _runtime_schema_done.add(path)


def write_capsule(
    *,
    memory_class: str,
    content: dict[str, Any],
    source_type: str = "user_input",
    scene: str = "general",
    task_type: str = "planning",
    risk_class: str = "low",
    write_intent: str = "explicit",
    affects_future_behavior: bool = False,
    source_trust: str = "normal",
    provenance: dict[str, Any] | None = None,
    production_context: dict[str, Any] | None = None,
    alignment_metadata: dict[str, Any] | None = None,
    relation_edges: list[dict[str, Any]] | None = None,
    soul_id: str | None = None,
    owner_id: str | None = None,
) -> dict[str, Any]:
    init_runtime_schema()
    text = _content_text(content)
    governance = evaluate_policy(
        text=text,
        source_type=source_type,
        write_intent=write_intent,
        affects_future_behavior=affects_future_behavior,
        source_trust=source_trust,
        memory_class=memory_class,
    )
    capsule_id = "cap_" + uuid.uuid4().hex[:12]
    created = now()
    provenance = dict(provenance or {
        "origin": "human" if source_type in {"user_input", "user"} else ("tool" if source_type in {"tool_result", "cross_scene_trace"} else "config" if source_type == "manual_config" else source_type),
        "writer_identity": "runtime",
        "source_type": source_type,
        "source_ids": [],
        "evidence_ids": [],
        "verified": source_type in {"user_input", "eval", "file", "manual_config"},
        "verification_method": "manual" if source_type == "user_input" else "unknown",
    })
    resolved_soul_id = soul_id or provenance.get("soul_id")
    resolved_owner_id = owner_id
    if resolved_soul_id and resolved_owner_id is None:
        from ..soul.ownership import owner_id_for_soul

        resolved_owner_id = owner_id_for_soul(str(resolved_soul_id))
    if resolved_owner_id is None:
        from ..soul.ownership import configured_actor_id

        resolved_owner_id = configured_actor_id()
    if resolved_soul_id:
        provenance["soul_id"] = str(resolved_soul_id)
    if resolved_owner_id:
        provenance["owner_id"] = resolved_owner_id
    production_context = production_context or {
        "scene": scene, "task_type": task_type, "risk_class": risk_class,
        "tenant_scope": "local", "validity_scope": "project",
    }
    state = {
        "lifecycle": _lifecycle_for_policy(governance["policy_result"]),
        "version": 1,
        "importance_score": 0.5,
        "retention_score": 0.5,
        "usage_count": 0,
        "last_accessed_at": None,
        "supersedes": [],
        "superseded_by": [],
    }
    alignment_metadata = alignment_metadata or {
        "human_preference_links": [], "policy_links": [], "constraint_links": [],
        "oversight_required": governance.get("requires_confirmation", False),
        "confirmation_status": "pending" if governance.get("requires_confirmation") else "not_required",
        "last_human_feedback": "unknown",
    }
    relation_edges = relation_edges or []
    index_refs = {"fts_ref": capsule_id, "vector_ref": None, "graph_node_id": capsule_id}
    native_index = {"backend": "fts_fallback", "indexed": False, "reason": "policy_not_indexable"}

    if governance["policy_result"] == "reject":
        audit_id = record(
            "capsule_write",
            {
                "capsule_id": capsule_id,
                "policy_result": governance["policy_result"],
                "memory_class": memory_class,
            },
        )
        # 被拒的写入也要留账：治理面板要能回答「有多少次写入被闸门挡下」，
        # 而被拒记忆没有主表行，账本是唯一留痕处。不记内容哈希（内容未落库）。
        from ..memoryos.governance import append_ledger

        append_ledger(
            op_type="write_rejected",
            capsule_id=capsule_id,
            actor=provenance.get("writer_identity") or "runtime",
            after_state="rejected",
            reason=f"policy_reject:{','.join(governance.get('risk_tags') or [])}",
            risk_class="high",
            owner_id=resolved_owner_id,
            soul_id=str(resolved_soul_id) if resolved_soul_id else None,
        )
        return {
            "capsule_id": capsule_id,
            "memory_class": memory_class,
            "governance": governance,
            "state": state,
            "audit_id": audit_id,
            "native_index": native_index,
        }

    from ..memoryos.accounting import estimate_tokens, record_write_in_transaction
    from ..memoryos.governance import append_ledger_in_transaction

    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO memory_capsules_v2 (
                capsule_id, memory_class, content, source_events, provenance, governance,
                state, production_context, alignment_metadata, affective_metadata,
                relation_edges, index_refs, created_at, updated_at,
                memory_tier, emotional_weight, created_in_dream
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                capsule_id, memory_class, dumps(content), dumps([]), dumps(provenance), dumps(governance),
                dumps(state), dumps(production_context), dumps(alignment_metadata), dumps({}),
                dumps(relation_edges), dumps(index_refs), created, created,
                'working', 0.0, 0,
            ),
        )
        if governance["policy_result"] in RETRIEVABLE_POLICY and state["lifecycle"] == "active":
            # issue #119：FTS 索引列写 CJK 逐字插空格副本（与知识库 kb_fts 同一
            # 方案，共享实现见 utils.cjk_text）。unicode61 不切分连续中文，直写
            # 原文会让任何局部中文查询在倒排索引上恒 0 命中。主表 content 保持
            # 原文，索引列只服务召回，不用于展示。
            conn.execute(
                "INSERT INTO memory_capsules_v2_fts(capsule_id,text) VALUES (?,?)",
                (capsule_id, cjk_space(text)),
            )
        # 账本与经济账都在同一事务内落库：任一失败整体回滚，保证
        # 「记忆存在 ⇔ 有账目 ⇔ 有账户」三者不脱节。
        append_ledger_in_transaction(
            conn,
            op_type="write",
            capsule_id=capsule_id,
            actor=provenance.get("writer_identity") or "runtime",
            after_content=text,
            after_state=state["lifecycle"],
            reason=f"{source_type}:{write_intent}",
            risk_class=risk_class,
            owner_id=resolved_owner_id,
            soul_id=str(resolved_soul_id) if resolved_soul_id else None,
        )
        record_write_in_transaction(
            conn,
            capsule_id,
            content_bytes=len(text.encode("utf-8")),
            extraction_tokens=estimate_tokens(text),
        )
    audit_id = record("capsule_write", {"capsule_id": capsule_id, "policy_result": governance["policy_result"], "memory_class": memory_class})
    # The vector copy is optional and is never created for rejected,
    # quarantined, or confirmation-pending memories.
    if state["lifecycle"] == "active":
        try:
            from .vector_index import index_capsule

            native_index = index_capsule(capsule_id=capsule_id, content=content, index_refs=index_refs)
        except Exception:
            record("kylin_sdk_vector_index", {"capsule_id": capsule_id, "status": "fallback"})
            native_index = {"backend": "fts_fallback", "indexed": False, "reason": "native_index_exception"}
        # 本地语义通道:麒麟 SDK 缺席时,BGE 本地模型提供真正的语义召回。
        # 通道不可用(依赖/模型未配置)时静默跳过,不阻断写入。
        from .local_embedding import embed_and_store

        if embed_and_store(capsule_id, text, ts=created, owner_id=owner_id, soul_id=soul_id):
            native_index = {**native_index, "local_embedding": True}

    
    # 04-#02: Bind affect to capsule when soul_id is provided and lifecycle is active.
    # This closes the affective-aware memory write loop: emotion_memory writes the
    # affect, retrieval consumes it (see retrieval.py _affective_score). Before this,
    # bind_emotion_to_capsule was exported but never called, leaving affective_metadata
    # perpetually empty and the "affective-aware" loop half-implemented.
    if soul_id and state["lifecycle"] == "active":
        try:
            from ..affect.state_machine import load_affect
            from ..affect.emotion_memory import bind_emotion_to_capsule
            
            affect = load_affect(soul_id)
            bind_emotion_to_capsule(capsule_id, soul_id, affect)
        except Exception as exc:
            # Never let emotion binding kill a successful write — log and continue.
            import logging
            logging.getLogger(__name__).warning(
                "bind_emotion_to_capsule failed for capsule_id=%s soul_id=%s: %s",
                capsule_id, soul_id, exc
            )
    
    # 冲突候选检测(规则式,只产信号不裁决 — 「conflicted 必须显式裁决」)。
    # 失败不阻断写入:检测是增强信号,不是写入前置条件。
    conflict_candidates: list[dict[str, Any]] = []
    try:
        from .conflict_detection import find_conflict_candidates_for_write

        conflict_candidates = find_conflict_candidates_for_write(
            text,
            memory_class=memory_class,
            owner_id=owner_id,
            soul_id=soul_id,
            exclude_capsule_id=capsule_id,
        )
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "conflict detection failed for capsule_id=%s: %s", capsule_id, exc
        )

    return {
        "capsule_id": capsule_id,
        "memory_class": memory_class,
        "governance": governance,
        "state": state,
        "audit_id": audit_id,
        "native_index": native_index,
        "conflict_candidates": conflict_candidates,
    }


_JSON_COLUMNS = [
    "content", "source_events", "provenance", "governance", "state",
    "production_context", "alignment_metadata", "affective_metadata",
    "relation_edges", "index_refs",
]


def _row_to_capsule(row: Any) -> dict[str, Any]:
    """Deserialize a memory_capsules_v2 row into a capsule dict."""
    d = dict(row)
    for key in _JSON_COLUMNS:
        d[key] = loads(d[key], {} if key != "relation_edges" else [])
    return d


def _scope_predicate(
    *,
    owner_id: str | None,
    soul_id: str | None,
    table_alias: str = "",
) -> tuple[str, list[Any]]:
    prefix = f"{table_alias}." if table_alias else ""
    clauses: list[str] = []
    params: list[Any] = []
    if owner_id is not None:
        clauses.append(f"json_extract({prefix}provenance, '$.owner_id')=?")
        params.append(owner_id)
    if soul_id is not None:
        clauses.append(
            f"(json_extract({prefix}provenance, '$.soul_id')=? "
            f"OR json_extract({prefix}provenance, '$.soul_id') IS NULL)"
        )
        params.append(soul_id)
    return (" AND ".join(clauses), params)


def get_capsule(
    capsule_id: str,
    *,
    owner_id: str | None = None,
    soul_id: str | None = None,
    external_read: bool = False,
) -> dict[str, Any] | None:
    scope_sql, scope_params = _scope_predicate(owner_id=owner_id, soul_id=soul_id)
    clauses = ["capsule_id=?"]
    params: list[Any] = [capsule_id]
    if scope_sql:
        clauses.append(scope_sql)
        params.extend(scope_params)
    if external_read:
        clauses.extend([
            "json_extract(governance,'$.policy_result') IN ('allow','redact')",
            "json_extract(state,'$.lifecycle') NOT IN ('quarantined','candidate','rejected')",
        ])
    row = get_conn().execute(
        f"SELECT * FROM memory_capsules_v2 WHERE {' AND '.join(clauses)}",
        params,
    ).fetchone()
    if not row:
        return None
    return _row_to_capsule(row)


def get_capsules_batch(
    capsule_ids: list[str],
    *,
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Fetch multiple capsules in a single query (avoids N+1).

    Returns a mapping of capsule_id -> capsule dict. Missing ids are omitted.
    Preserves no particular order; callers should order via capsule_ids.
    """
    if not capsule_ids:
        return {}
    placeholders = ",".join("?" for _ in capsule_ids)
    scope_sql, scope_params = _scope_predicate(owner_id=owner_id, soul_id=soul_id)
    where = f"capsule_id IN ({placeholders})"
    if scope_sql:
        where += f" AND {scope_sql}"
    rows = get_conn().execute(
        f"SELECT * FROM memory_capsules_v2 WHERE {where}",
        [*capsule_ids, *scope_params],
    ).fetchall()
    return {row["capsule_id"]: _row_to_capsule(row) for row in rows}


def list_capsules(
    limit: int = 50,
    *,
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> list[dict[str, Any]]:
    scope_sql, scope_params = _scope_predicate(owner_id=owner_id, soul_id=soul_id)
    scope_clause = f" AND {scope_sql}" if scope_sql else ""
    rows = get_conn().execute(
        f"""
        SELECT capsule_id FROM memory_capsules_v2
        WHERE json_extract(state,'$.lifecycle') NOT IN (
            'forgotten','deleted','rejected','quarantined','candidate'
        )
          AND json_extract(governance,'$.policy_result') IN ('allow','redact')
          {scope_clause}
        ORDER BY created_at DESC LIMIT ?
        """,
        [*scope_params, limit],
    ).fetchall()
    ids = [r["capsule_id"] for r in rows]
    by_id = get_capsules_batch(ids, owner_id=owner_id, soul_id=soul_id)
    return [by_id[i] for i in ids if i in by_id]


def update_capsule(
    capsule_id: str,
    *,
    state: dict[str, Any] | None = None,
    relation_edges: list[dict[str, Any]] | None = None,
    owner_id: str | None = None,
    soul_id: str | None = None,
    actor: str = "runtime",
    reason: str = "capsule_update",
) -> dict[str, Any]:
    """通用状态/关系边更新。

    注意：本函数**不做生命周期转移校验**——它是底层 setter，`state` 由调用方
    整体替换。需要改 ``state.lifecycle`` 的调用方应走
    ``memoryos.lifecycle.apply_transition``，那里才有合法转移裁决与 FTS 同步。
    这里只负责把 before/after 内容哈希记进账本，让「谁改了什么」可追。
    """
    from ..memoryos.governance import append_ledger_in_transaction

    cap = get_capsule(capsule_id, owner_id=owner_id, soul_id=soul_id)
    if not cap:
        raise KeyError(capsule_id)
    new_state = state or cap["state"]
    new_edges = relation_edges if relation_edges is not None else cap["relation_edges"]
    before_snapshot = dumps({"state": cap["state"], "relation_edges": cap["relation_edges"]})
    after_snapshot = dumps({"state": new_state, "relation_edges": new_edges})
    scope_sql, scope_params = _scope_predicate(owner_id=owner_id, soul_id=soul_id)
    scope_clause = f" AND {scope_sql}" if scope_sql else ""
    with transaction() as conn:
        conn.execute(
            "UPDATE memory_capsules_v2 SET state=?, relation_edges=?, updated_at=? "
            f"WHERE capsule_id=?{scope_clause}",
            [dumps(new_state), dumps(new_edges), now(), capsule_id, *scope_params],
        )
        append_ledger_in_transaction(
            conn,
            op_type="update",
            capsule_id=capsule_id,
            actor=actor,
            before_content=before_snapshot,
            after_content=after_snapshot,
            before_state=(cap["state"] or {}).get("lifecycle"),
            after_state=(new_state or {}).get("lifecycle"),
            reason=reason,
            owner_id=owner_id or (cap.get("provenance") or {}).get("owner_id"),
            soul_id=soul_id or (cap.get("provenance") or {}).get("soul_id"),
        )
    record("capsule_update", {"capsule_id": capsule_id, "state": new_state})
    return get_capsule(capsule_id, owner_id=owner_id, soul_id=soul_id)


def bump_usage_batch(
    updates: list[tuple[str, dict[str, Any]]],
    *,
    injected_tokens: dict[str, int] | None = None,
) -> None:
    """Persist usage-count/state updates for many capsules in one round-trip.

    ``updates`` is a list of (capsule_id, new_state) pairs. Uses a single
    ``executemany`` plus one aggregated audit record, replacing the per-capsule
    get+update+audit+get chain that caused N+1 query amplification in the
    retrieval hot path.

    经济账与检索账本挂在**同一个事务**里，且只对已经通过
    ``retrieval._usage_bump_due`` 60 秒时间窗门控的胶囊执行——也就是说搜索路径
    **不新增任何一次写往返**，记账完全搭既有 usage 落库的车。改动这里时请保持
    该性质：不要在 search 里单独开事务记账，那会把只读搜索变成每次都写库。

    先记 ``neutral``：检索当下还不知道这条记忆有没有帮上忙，等
    ``evolution.reflect_task`` 回来再用 ``accounting.settle_recall_outcome``
    回填成 useful/harmful。
    """
    if not updates:
        return
    from ..memoryos.accounting import record_recalls_in_transaction
    from ..memoryos.governance import append_ledger_batch_in_transaction

    ts = now()
    tokens = injected_tokens or {}
    with transaction() as conn:
        conn.executemany(
            f"""
            UPDATE memory_capsules_v2
            SET state=json_set(
                    state,
                    '$.usage_count', COALESCE(CAST(json_extract(state,'$.usage_count') AS INTEGER), 0) + 1,
                    '$.last_accessed_at', ?
                ),
                updated_at=?
            WHERE capsule_id=?
              AND json_extract(state,'$.lifecycle') IN ({_RETRIEVABLE_SQL})
              AND json_extract(governance,'$.policy_result') IN ('allow','redact')
            """,
            [(state.get("last_accessed_at") or ts, ts, cid) for cid, state in updates],
        )
        record_recalls_in_transaction(
            conn,
            [(cid, "neutral", tokens.get(cid, 0)) for cid, _ in updates],
        )
        append_ledger_batch_in_transaction(
            conn,
            [
                {
                    "op_type": "retrieve",
                    "capsule_id": cid,
                    "actor": "runtime",
                    "after_state": (state or {}).get("lifecycle"),
                    "reason": "retrieval_hit",
                }
                for cid, state in updates
            ],
        )
    record("capsule_usage_batch", {"capsule_ids": [cid for cid, _ in updates], "count": len(updates)})


def forget_capsules_in_transaction(
    conn,
    capsule_ids: list[str],
    *,
    mode: str = "soft_delete",
    owner_id: str | None = None,
    soul_id: str | None = None,
    actor: str = "runtime",
) -> dict[str, Any]:
    """Apply local forget state using the caller's transaction.

    生命周期转移经 ``memoryos.lifecycle`` 校验。**批量语义例外**：本函数的既有
    契约是「跳过查不到的 id」而不是整批失败，因此非法转移（例如对已 ``deleted``
    的胶囊再次硬删）同样按跳过处理，并列进返回值的 ``rejected_transitions``，
    而不是抛异常中断整批。单条操作要硬拒非法转移时走
    ``lifecycle.apply_transition``（``POST /memory/lifecycle/transition``），
    那里会抛 ``IllegalTransitionError``。
    """
    from ..memoryos.governance import append_ledger_batch_in_transaction
    from ..memoryos.lifecycle import LifecycleState, can_transition
    from .vector_index import mark_vectors_delete_pending_in_transaction

    deleted: list[str] = []
    rejected: list[dict[str, str]] = []
    ledger_entries: list[dict[str, Any]] = []
    unique_ids = list(dict.fromkeys(capsule_ids))
    if unique_ids:
        placeholders = ",".join("?" for _ in unique_ids)
        scope_sql, scope_params = _scope_predicate(owner_id=owner_id, soul_id=soul_id)
        scope_clause = f" AND {scope_sql}" if scope_sql else ""
        rows = conn.execute(
            f"SELECT capsule_id,state,content,provenance FROM memory_capsules_v2 "
            f"WHERE capsule_id IN ({placeholders}){scope_clause}",
            [*unique_ids, *scope_params],
        ).fetchall()
    else:
        rows = []
    by_id = {row["capsule_id"]: row for row in rows}
    timestamp = now()
    target = (
        LifecycleState.DELETED.value if mode == "hard_delete" else LifecycleState.FORGOTTEN.value
    )
    for capsule_id in unique_ids:
        row = by_id.get(capsule_id)
        if not row:
            continue
        state = loads(row["state"], {})
        from_state = str(state.get("lifecycle") or LifecycleState.ACTIVE.value)
        if from_state != target and not can_transition(from_state, target):
            rejected.append({
                "capsule_id": capsule_id,
                "from_state": from_state,
                "to_state": target,
                "reason": "illegal_lifecycle_transition",
            })
            continue
        state["lifecycle"] = target
        state["forgotten_at"] = timestamp
        if mode == "hard_delete":
            conn.execute("DELETE FROM memory_capsules_v2 WHERE capsule_id=?", (capsule_id,))
        else:
            conn.execute(
                "UPDATE memory_capsules_v2 SET state=?, updated_at=? WHERE capsule_id=?",
                (dumps(state), timestamp, capsule_id),
            )
        conn.execute("DELETE FROM memory_capsules_v2_fts WHERE capsule_id=?", (capsule_id,))
        # 本地向量同步删除(删除验证的一环:主记录/FTS/向量三处一致)。
        # 必须传入 conn:delete_vector 在传入连接时不自行 commit,
        # 提交权归本事务(避免提前提交破坏回滚能力)。
        from .local_embedding import delete_vector

        delete_vector(capsule_id, conn=conn)
        provenance = loads(row["provenance"], {}) or {}
        ledger_entries.append({
            "op_type": "delete",
            "capsule_id": capsule_id,
            "actor": actor,
            "before_content": row["content"],
            "before_state": from_state,
            "after_state": target,
            "reason": f"forget:{mode}",
            "risk_class": "medium",
            "owner_id": owner_id or provenance.get("owner_id"),
            "soul_id": soul_id or provenance.get("soul_id"),
        })
        deleted.append(capsule_id)
    append_ledger_batch_in_transaction(conn, ledger_entries)
    native_vector = mark_vectors_delete_pending_in_transaction(conn, deleted)
    return {
        "status": "forgotten",
        "deleted_capsule_ids": deleted,
        "rejected_transitions": rejected,
        "native_vector": native_vector,
    }


def forget_capsules(
    capsule_ids: list[str],
    *,
    mode: str = "soft_delete",
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> dict[str, Any]:
    init_runtime_schema()
    conn = get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        result = forget_capsules_in_transaction(
            conn,
            capsule_ids,
            mode=mode,
            owner_id=owner_id,
            soul_id=soul_id,
        )
        audit_id = record_in_transaction(
            conn,
            "forget_confirm",
            {"deleted_capsule_ids": result["deleted_capsule_ids"], "mode": mode},
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    try:
        from .vector_index import remove_vectors

        native_vector = remove_vectors(result["deleted_capsule_ids"])
    except Exception:
        native_vector = {
            "backend": "fts_fallback",
            "deleted_vector_ids": [],
            "pending_vector_ids": result["native_vector"]["pending_vector_ids"],
            "reason": "native_delete_status_unknown",
        }
    return {
        "status": "forgotten",
        "deleted_capsule_ids": result["deleted_capsule_ids"],
        "rejected_transitions": result.get("rejected_transitions", []),
        "audit_id": audit_id,
        "native_vector": native_vector,
        # 删除完整性证据（规范 §2.4）：删完立刻验，把「主表/FTS/图边/向量」
        # 四处的残留情况随响应一起返回，而不是让调用方自己去猜删干净没有。
        "deletion_verification": _verify_deleted(result["deleted_capsule_ids"]),
    }


def _verify_deleted(capsule_ids: list[str]) -> dict[str, Any]:
    """删除后校验，失败不影响删除本身已提交的事实（只降级为无证据）。"""
    if not capsule_ids:
        return {"checked": 0, "complete": 0, "incomplete": [], "all_complete": True}
    try:
        from ..memoryos.governance import verify_deletions

        return verify_deletions(capsule_ids)
    except Exception as exc:  # pragma: no cover - 验证失败不该反噬删除结果
        import logging

        logging.getLogger(__name__).warning("deletion verification failed: %s", exc)
        return {"error": "verification_unavailable", "reason": type(exc).__name__}


def allowed_for_context(cap: dict[str, Any], *, high_risk: bool = False) -> bool:
    """该记忆能否进入本次上下文注入。

    高风险任务额外排除 ``conflicted``（有矛盾未裁决）与 ``stale``（已过期）——
    这两类内容用于低风险问答尚可，用于高风险决策则应先让人确认。
    """
    gov = cap["governance"]
    state = cap["state"]
    if gov.get("policy_result") not in RETRIEVABLE_POLICY:
        return False
    if gov.get("sensitivity_level") == "S3":
        return False
    if state.get("lifecycle") not in RETRIEVABLE_LIFECYCLE:
        return False
    if high_risk and state.get("lifecycle") in HIGH_RISK_EXCLUDED_STATES:
        return False
    return True
