from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any

from ..db import get_conn
from ..memoryos.lifecycle import RETRIEVAL_SCORE_PENALTY, retrievable_sql_list
from ..utils.cjk_text import fts_match_expr
from .capsule_store import get_capsules_batch, allowed_for_context, bump_usage_batch, now
from .vector_index import PROVIDER, native_candidates

logger = logging.getLogger(__name__)

#: 可检索状态的 SQL IN 列表。派生自 memoryos.lifecycle 的状态机定义，
#: 不在这里另写一份字面量——两处各写一份是状态漂移的经典来源。
_RETRIEVABLE_SQL = retrievable_sql_list()

# 03-#15 搜索读路径写放大降频：
# usage_count / last_accessed_at 是统计性元数据。此前每次 search 都对全部命中
# 批量 UPDATE 一次并写一条聚合审计行，前端轮询/重试同一查询会造成 O(搜索次数)
# 的写放大与审计噪音。现按 capsule 做时间窗合并：同一 capsule 在窗口内的重复
# 命中只在首次落库，窗口外的命中再次落库。语义注释：
#   - 使用统计「最终一致」——窗口内被合并的访问不重复计数（这本身是期望语义：
#     短时间反复读到同一条记忆，按一次使用计）。
#   - _recent_usage_bumps 只保存「最近落库时间」的内存标记，不含未落盘数据，
#     进程退出不会有缓冲丢失；重启后窗口自然失效，下一次命中照常落库。
_USAGE_BUMP_MIN_INTERVAL_SECONDS = 60.0
_USAGE_BUMP_CACHE_MAX = 10000
_recent_usage_bumps: dict[str, float] = {}
_recent_usage_bumps_lock = threading.Lock()


def _usage_bump_due(capsule_id: str) -> bool:
    """判断并标记该 capsule 的 usage 落库是否到达时间窗（线程安全）。"""
    now_mono = time.monotonic()
    with _recent_usage_bumps_lock:
        if len(_recent_usage_bumps) >= _USAGE_BUMP_CACHE_MAX:
            _recent_usage_bumps.clear()
        last = _recent_usage_bumps.get(capsule_id)
        if last is not None and now_mono - last < _USAGE_BUMP_MIN_INTERVAL_SECONDS:
            return False
        _recent_usage_bumps[capsule_id] = now_mono
        return True


def _has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def _zh_terms(q: str) -> list[str]:
    q = q.strip().replace('"', ' ')
    if not q:
        return []
    parts = [p for p in re.split(r"\s+", q) if p]
    terms: list[str] = []
    for part in parts:
        terms.append(part)
        if _has_cjk(part) and len(part) >= 3:
            terms.extend(part[i:i+2] for i in range(len(part)-1))
    seen = []
    for term in terms:
        if term and term not in seen:
            seen.append(term)
    return seen


def _match_query(q: str) -> str:
    # issue #119：与入库侧 cjk_space 配套的查询侧切词——CJK bigram + 单字
    # 兜底 + 非 CJK 连续片段（共享实现 utils.cjk_text.fts_match_expr，与知识
    # 库同一套）。旧实现按空格整体加引号，连续中文是单个 phrase，在逐字
    # 索引上恒 0 命中。空 atom 时回落原始输入（保持既有空调询契约）。
    expr = fts_match_expr(q)
    return expr if expr else q


def _scope_sql(
    *,
    owner_id: str | None,
    soul_id: str | None,
    table_alias: str = "capsule",
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if owner_id is not None:
        clauses.append(f"json_extract({table_alias}.provenance, '$.owner_id')=?")
        params.append(owner_id)
    if soul_id is not None:
        clauses.append(
            f"(json_extract({table_alias}.provenance, '$.soul_id')=? "
            f"OR json_extract({table_alias}.provenance, '$.soul_id') IS NULL)"
        )
        params.append(soul_id)
    return (" AND ".join(clauses), params)


def _fts_rows(
    conn,
    q: str,
    limit: int,
    *,
    failed_collection: str | None = None,
    owner_id: str | None = None,
    soul_id: str | None = None,
):
    try:
        failed_join = ""
        params: list[Any] = []
        if failed_collection is not None:
            failed_join = """
                JOIN memory_vector_refs AS ref
                  ON ref.capsule_id=memory_capsules_v2_fts.capsule_id
                 AND ref.provider=? AND ref.collection_name=? AND ref.status='index_failed'
            """
            params.extend((PROVIDER, failed_collection))
        scope_sql, scope_params = _scope_sql(owner_id=owner_id, soul_id=soul_id)
        scope_clause = f" AND {scope_sql}" if scope_sql else ""
        params.extend(scope_params)
        params.extend((_match_query(q), limit))
        return conn.execute(
            f"""
            SELECT memory_capsules_v2_fts.capsule_id,
                   bm25(memory_capsules_v2_fts) AS bm25_rank
            FROM memory_capsules_v2_fts
            JOIN memory_capsules_v2 AS capsule
              ON capsule.capsule_id=memory_capsules_v2_fts.capsule_id
            {failed_join}
            WHERE 1=1
              {scope_clause}
              AND memory_capsules_v2_fts MATCH ?
              AND json_extract(capsule.state,'$.lifecycle') IN ({_RETRIEVABLE_SQL})
              AND json_extract(capsule.governance,'$.policy_result') IN ('allow','redact')
            ORDER BY bm25_rank
            LIMIT ?
            """,
            params,
        ).fetchall()
    except Exception as exc:
        # 03-#16: 降级但不静默——FTS 出错（如 MATCH 语法/缺表）记 warning，
        # 返回空后由 substring/原生通道兜底。
        logger.warning("FTS 检索失败，降级为空结果（substring/native 通道仍可命中）: %s", exc)
        return []


def _substring_rows(
    conn,
    q: str,
    limit: int,
    *,
    failed_collection: str | None = None,
    owner_id: str | None = None,
    soul_id: str | None = None,
):
    terms = _zh_terms(q)
    if not terms:
        return []
    clauses = " OR ".join(["content LIKE ?" for _ in terms])
    failed_join = ""
    params: list[Any] = []
    if failed_collection is not None:
        failed_join = """
            JOIN memory_vector_refs AS ref
              ON ref.capsule_id=capsule.capsule_id
             AND ref.provider=? AND ref.collection_name=? AND ref.status='index_failed'
        """
        params.extend((PROVIDER, failed_collection))
    scope_sql, scope_params = _scope_sql(owner_id=owner_id, soul_id=soul_id)
    scope_clause = f" AND {scope_sql}" if scope_sql else ""
    params.extend(f"%{term}%" for term in terms)
    params.extend(scope_params)
    params.append(limit)
    return conn.execute(
        f"""
        SELECT capsule.capsule_id FROM memory_capsules_v2 AS capsule
        {failed_join}
        WHERE ({clauses})
          AND json_extract(capsule.state,'$.lifecycle') IN ({_RETRIEVABLE_SQL})
          AND json_extract(capsule.governance,'$.policy_result') IN ('allow','redact')
          {scope_clause}
        ORDER BY capsule.updated_at DESC LIMIT ?
        """,
        params,
    ).fetchall()


def _fts_candidates(
    q: str,
    *,
    limit: int,
    failed_collection: str | None = None,
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> tuple[list[str], dict[str, float], set[str]]:
    """返回 ``(候选 id 列表, bm25 相关性映射, LIKE 兜底命中 id 集合)``。

    issue #118：bm25 分数必须在候选收集阶段保留下来供排序公式消费——
    旧实现只回传 id 列表，相关性证据在这一步就被丢弃了。bm25 返回值
    越小越好（SQLite FTS5 约定），这里取负转为「越大越好」后归一化到
    [0, 1]（候选集内相对值）；LIKE 兜底命中没有相关性证据，不进映射，
    排序时按 0 处理（见 search_capsules_with_status 注释）。
    """
    conn = get_conn()
    rows = _fts_rows(
        conn,
        q,
        limit,
        failed_collection=failed_collection,
        owner_id=owner_id,
        soul_id=soul_id,
    )
    ids: list[str] = []
    relevance: dict[str, float] = {}
    raw_scores: dict[str, float] = {}
    for row in rows:
        cid = row["capsule_id"]
        ids.append(cid)
        if "bm25_rank" in row.keys():
            raw_scores[cid] = -float(row["bm25_rank"])
    max_raw = max(raw_scores.values()) if raw_scores else 0.0
    if max_raw > 0:
        for cid, raw in raw_scores.items():
            relevance[cid] = max(0.0, raw) / max_raw
    like_ids: set[str] = set()
    if _has_cjk(q):
        seen = set(ids)
        for row in _substring_rows(
            conn,
            q,
            limit,
            failed_collection=failed_collection,
            owner_id=owner_id,
            soul_id=soul_id,
        ):
            if row["capsule_id"] not in seen:
                ids.append(row["capsule_id"])
                like_ids.add(row["capsule_id"])
                seen.add(row["capsule_id"])
    return ids, relevance, like_ids


def _fts_candidate_ids(
    q: str,
    *,
    limit: int,
    failed_collection: str | None = None,
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> list[str]:
    """兼容性包装：只需要 id 列表的旧调用方（相关性映射在此丢弃）。"""
    ids, _, _ = _fts_candidates(
        q,
        limit=limit,
        failed_collection=failed_collection,
        owner_id=owner_id,
        soul_id=soul_id,
    )
    return ids


def _normalized_native_score(score: float) -> float:
    # The official default metric is cosine, which can range from -1 to 1.
    return min(1.0, max(0.0, (score + 1.0) / 2.0))


def _affective_score(cap: dict[str, Any]) -> float:
    """Emotional weight of a capsule, in [0, 1].

    Retrieval-side counterpart of ``emotion_memory.apply_emotional_weight``:
    affectively-charged memories are prioritised so the "affective-aware
    memory" loop is actually closed (bind at write time, boost at query time).

    Prefers the explicit ``emotional_weight`` column; falls back to the bound
    ``mood_intensity`` inside ``affective_metadata`` when the column was never
    set (e.g. capsules created before the affective columns existed).
    """
    try:
        weight = float(cap.get("emotional_weight") or 0.0)
        if weight > 0:
            return min(1.0, max(0.0, weight))
    except (TypeError, ValueError):
        pass
    aff = cap.get("affective_metadata") or {}
    try:
        intensity = float(aff.get("mood_intensity") or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return min(1.0, max(0.0, intensity))


# ---------------------------------------------------------------------------
# 排序权重（issue #118）
# ---------------------------------------------------------------------------
# 旧公式 ``0.35 + 0.25*trust + 0.20*confidence + 0.05*retention + 0.15*affective``
# 没有任何查询相关项——查询词只决定候选集合，排序完全由治理元数据决定，而
# trust/confidence 对正常记忆是闸门常量，等价于排序与查询无关。
# 新公式引入 bm25（FTS 候选）/向量余弦（native 候选）作为主导相关项，
# 治理/情感分降为次级权重。权重键来自 tuning.service.TUNING_DEFAULTS——
# 这组键此前全仓无任何读取方且数值与真实公式不符（「假装可配置」），
# 此处接为真实读取点；读取失败回落到内置常量，检索可用性不依赖调参模块。
_WEIGHTS_FALLBACK: dict[str, float] = {
    "query_relevance_weight": 0.35,
    "trust_score_weight": 0.20,
    "confidence_weight": 0.10,
    "retention_score_weight": 0.05,
    "emotional_salience_weight": 0.10,
    "base_score": 0.20,
}
_WEIGHTS_CACHE: dict[str, float] | None = None


def _weights() -> dict[str, float]:
    global _WEIGHTS_CACHE
    if _WEIGHTS_CACHE is not None:
        return _WEIGHTS_CACHE
    weights = dict(_WEIGHTS_FALLBACK)
    try:
        from ..tuning.service import TUNING_DEFAULTS

        published = TUNING_DEFAULTS.get("retrieval", {})
        for key in weights:
            value = published.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                weights[key] = float(value)
    except Exception as exc:  # noqa: BLE001 —— 调参模块不可用时回落常量
        logger.warning("tuning defaults 不可用，检索权重回落到内置常量: %s", exc)
    _WEIGHTS_CACHE = weights
    return weights


def _reload_weights() -> None:
    """测试/调参热更钩子：清空权重缓存，下次检索时重读。"""
    global _WEIGHTS_CACHE
    _WEIGHTS_CACHE = None


def search_capsules_with_status(
    q: str,
    *,
    top_k: int = 5,
    high_risk: bool = False,
    owner_id: str | None = None,
    soul_id: str | None = None,
    with_trace: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """混合检索并返回 ``(命中列表, 检索状态)``。

    ``with_trace=True`` 时在返回的状态字典里附加规范
    ``AI优化/MemoryOS-BenchmarkHarness.md`` §2.2 要求的 Memory Trace
    （候选集 / 过滤条件 / 重排结果 / 注入项 / 耗时）。**默认关闭**：trace 需要
    保留全部候选的中间态，评测与排障时才有价值，常规检索路径不该为此付开销。
    """
    trace_started = time.monotonic() if with_trace else 0.0
    native_rows, status = native_candidates(q, top_k=top_k * 4)
    scoped_search = owner_id is not None or soul_id is not None
    native_scores: dict[str, float] = {}
    fts_fallback_ids: set[str] = set()
    relevance_scores: dict[str, float] = {}
    if native_rows is None:
        # 麒麟 SDK 缺席:先试本地语义通道(BGE 模型,可选能力)。
        # 本地通道提供真正的语义召回;不可用(依赖/模型未配置)才退回纯词面 FTS。
        # 三级回退链: native → local_embedding → fts_fallback,状态如实上报。
        from .local_embedding import search as _local_search

        local_rows = _local_search(q, top_k=top_k * 4, owner_id=owner_id, soul_id=soul_id)
        if local_rows is not None:
            candidate_ids = [cid for cid, _ in local_rows]
            relevance_scores = {cid: sim for cid, sim in local_rows}
            # FTS 补充词面精确命中(数字/代码/精确名),与语义候选合并
            fts_ids, fts_relevance, _ = _fts_candidates(
                q,
                limit=top_k * 4,
                owner_id=owner_id,
                soul_id=soul_id,
            )
            local_ids = set(candidate_ids)
            for capsule_id in fts_ids:
                if capsule_id not in local_ids:
                    candidate_ids.append(capsule_id)
                    fts_fallback_ids.add(capsule_id)
                    if capsule_id in fts_relevance:
                        relevance_scores[capsule_id] = fts_relevance[capsule_id]
            status["backend"] = "local_embedding"
            status["local_embedding"] = {"candidates": len(local_rows)}
        else:
            candidate_ids, relevance_scores, _ = _fts_candidates(
                q,
                limit=top_k * 4,
                owner_id=owner_id,
                soul_id=soul_id,
            )
    else:
        candidate_ids = []
        for capsule_id, raw_score in native_rows:
            if capsule_id not in native_scores:
                candidate_ids.append(capsule_id)
                native_scores[capsule_id] = raw_score
        # An isolated permanently-unindexable Capsule must not disable native
        # retrieval for every other Capsule.  Preserve it through a narrow,
        # observable FTS fallback instead of a whole-index fallback.
        failed_collection = None
        if status.get("native_index", {}).get("failed"):
            failed_collection = status.get("collection")
        fts_ids, fts_relevance, _ = _fts_candidates(
            q,
            limit=top_k * 4,
            failed_collection=failed_collection,
            owner_id=owner_id,
            soul_id=soul_id,
        )
        for capsule_id in fts_ids:
            if capsule_id not in native_scores:
                candidate_ids.append(capsule_id)
                fts_fallback_ids.add(capsule_id)
                if capsule_id in fts_relevance:
                    relevance_scores[capsule_id] = fts_relevance[capsule_id]

    # Batch-fetch all candidates in a single query (avoids N+1).
    by_id = get_capsules_batch(candidate_ids, owner_id=owner_id, soul_id=soul_id)
    accessed_at = now()
    weights = _weights()
    scored: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    updates: list[tuple[str, dict[str, Any]]] = []
    filtered_out: list[dict[str, str]] = []
    for capsule_id in candidate_ids:
        cap = by_id.get(capsule_id)
        if not cap or not allowed_for_context(cap, high_risk=high_risk):
            if with_trace:
                filtered_out.append({
                    "capsule_id": capsule_id,
                    "reason": "not_in_scope" if not cap else "policy_or_lifecycle_filtered",
                })
            continue
        gov = cap["governance"]; state = cap["state"]
        # issue #121：情感词表检测器内置最小标注集自检，准确率不达标时
        # affective 不再参与排序（布尔门禁；局部导入避免与检索模块顶层依赖纠缠）
        from ..affect.emotion_detector import ranking_factor as _emotion_ranking_factor

        affective = _affective_score(cap) * _emotion_ranking_factor()
        # MemoryBank 式遗忘曲线:retention 在读取时按时间衰减(只读计算,
        # 不改存储原始值)。召回越多的记忆衰减越慢(stability 随 usage_count
        # 增长);从未召回的记忆不衰减(新记忆宽限期)。
        from .forgetting import effective_retention

        retention_effective = effective_retention(state)
        gov_bonus = (
            weights["trust_score_weight"] * float(gov.get("trust_score", 0))
            + weights["confidence_weight"] * float(gov.get("confidence", 0))
            + weights["retention_score_weight"] * retention_effective
            + weights["emotional_salience_weight"] * affective
        )
        # issue #118：查询相关性主导排序。FTS 候选用 bm25 归一化值；LIKE 兜底
        # 命中没有相关性证据，按 0 处理（旧实现没有相关性项、排序与查询无关，
        # LIKE 命中曾因此和 bm25 命中混在一起不可分辨）。native 候选用余弦
        # 相似度归一化值，治理分保持同一口径。
        relevance = relevance_scores.get(capsule_id, 0.0)
        score = weights["base_score"] + weights["query_relevance_weight"] * relevance + gov_bonus
        if capsule_id in native_scores:
            semantic_score = _normalized_native_score(native_scores[capsule_id])
            score = weights["base_score"] + weights["query_relevance_weight"] * semantic_score + gov_bonus
            cap["vector_score"] = round(native_scores[capsule_id], 4)
        # 生命周期降权：stale（已过期）仍可召回但排在同等条件的新鲜记忆之后。
        # 规范 Lifecycle §1 把 stale 定为「低权重或弃权」而非直接不可见。
        penalty = RETRIEVAL_SCORE_PENALTY.get(str(state.get("lifecycle")), 0.0)
        if penalty:
            score = max(0.0, score - penalty)
            cap["retrieval_lifecycle_penalty"] = penalty
        cap["retrieval_affective"] = round(affective, 4)
        cap["retrieval_relevance"] = round(relevance, 4)
        cap["retrieval_retention_effective"] = retention_effective
        cap["retrieval_score"] = round(min(1.0, max(0.0, score)), 4)
        cap["retrieval_backend"] = "fts_fallback" if capsule_id in fts_fallback_ids else status["backend"]
        if capsule_id in fts_fallback_ids:
            cap["retrieval_fallback_reason"] = (
                "native_scope_supplement"
                if scoped_search and failed_collection is None
                else "native_index_failed_capsule"
            )
        elif status.get("fallback_reason") and status["backend"] == "fts_fallback":
            cap["retrieval_fallback_reason"] = status["fallback_reason"]
        scored.append((capsule_id, cap, state))
    # 04-#01: 综合评分真正参与排序（此前 retrieval_score 只作元数据记录，
    # 顺序完全由底层候选顺序决定，affective/trust 加权对排序无实际影响）。
    # 按 retrieval_score 降序取 top_k；usage bump 仍只对最终命中的胶囊落库。
    scored.sort(key=lambda item: item[1]["retrieval_score"], reverse=True)
    out = []
    injected_tokens: dict[str, int] = {}
    for capsule_id, cap, state in scored[:top_k]:
        # 03-#15: 时间窗内重复命中的 capsule 跳过落库（内存计数同步跳过，
        # 保持响应与库内一致）；窗口外命中照常累计并批量落库。
        if _usage_bump_due(capsule_id):
            state["usage_count"] = int(state.get("usage_count") or 0) + 1
            state["last_accessed_at"] = accessed_at
            updates.append((capsule_id, state))
            injected_tokens[capsule_id] = _injected_token_estimate(cap)
        out.append(cap)
    # Batch-update usage counts in a single executemany + one aggregated audit.
    # 经济账（检索成本）与检索账本也在这一个事务里，不额外增加写往返。
    bump_usage_batch(updates, injected_tokens=injected_tokens)
    if with_trace:
        status["trace"] = {
            "query": q,
            "query_terms": _zh_terms(q),
            "candidates": [
                {
                    "capsule_id": capsule_id,
                    "stage": "vector" if capsule_id in native_scores else "fts",
                    "score": round(cap["retrieval_score"], 4),
                }
                for capsule_id, cap, _ in scored
            ],
            "filters_applied": _describe_filters(owner_id, soul_id, high_risk),
            "filtered_out": filtered_out,
            "rerank": {"method": "weighted_sum", "final": [cap["capsule_id"] for cap in out]},
            "injected": list(injected_tokens) or [cap["capsule_id"] for cap in out],
            "injected_tokens": sum(injected_tokens.values()),
            "latency_ms": round((time.monotonic() - trace_started) * 1000, 2),
        }
    return out, status


def _injected_token_estimate(cap: dict[str, Any]) -> int:
    """估算这条记忆注入上下文的 token 数（经济账本的检索成本输入）。

    这是**估算不是实测**——真实注入量取决于上层如何拼 prompt，运行时这里拿不到。
    绝对金额因此只有相对比较意义，account 面板上须如实标注。
    """
    from ..memoryos.accounting import estimate_tokens

    try:
        import json as _json

        return estimate_tokens(_json.dumps(cap.get("content") or {}, ensure_ascii=False))
    except (TypeError, ValueError):
        return 0


def _describe_filters(owner_id: str | None, soul_id: str | None, high_risk: bool) -> list[str]:
    filters = [f"lifecycle IN ({_RETRIEVABLE_SQL})", "policy_result IN ('allow','redact')"]
    if owner_id is not None:
        filters.append(f"owner_id={owner_id}")
    if soul_id is not None:
        filters.append(f"soul_id={soul_id}")
    if high_risk:
        filters.append("high_risk: exclude conflicted/stale")
    return filters


def search_capsules(
    q: str,
    *,
    top_k: int = 5,
    high_risk: bool = False,
    owner_id: str | None = None,
    soul_id: str | None = None,
    with_trace: bool = False,
) -> list[dict[str, Any]]:
    """Compatibility wrapper for internal callers that expect only result rows."""
    results, _ = search_capsules_with_status(
        q,
        top_k=top_k,
        high_risk=high_risk,
        owner_id=owner_id,
        soul_id=soul_id,
        with_trace=with_trace,
    )
    return results
