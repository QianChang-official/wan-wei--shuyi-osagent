# Copyright (c) 2026 QianChang-official
#
# 宛委·枢忆 is licensed under Mulan PSL v2.
# You can use this software according to the terms of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
# http://license.coscl.org.cn/MulanPSL2
#
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

"""关联检索三路 RRF 融合排序（对应 #164 C1–C3）— 纯增量，不改单路检索语义。

设计背景
--------
既有单路检索（词面 FTS5 / 向量 / relation_edges 图扩散）各自维护一套
不可比的分数体系。C1 提出用 RRF（Reciprocal Rank Fusion）把多路**排序**
融合成单一分数：对每个胶囊取它在各路的排位 ``rank``（1 起），累加
``weight / (k + rank)``。C2 在 RRF 之上挂治理/时间乘子链
``final = rrf × recency_decay × confidence``。C3 用四组消融量化每路的贡献。

纯增量口径
----------
- **不触碰** ``retrieval.py`` / ``vector_index.py`` / ``forgetting.py`` /
  ``preference_confidence.py`` 的既有语义，只 import 复用；想继续用单路检索
  的调用方行为完全不变。``fused_search`` 是本模块独立入口。
- 乘子链复用既有实现，**不另造第二套公式**：
  - recency_decay：把 ``forgetting.effective_retention``（#162 遗忘曲线，
    ``forgetting.py:68`` 的 ``stored × exp(-λ·days/stability)``）的
    ``retention_score`` 基线置 1.0 后调用——只取纯时间衰减项，λ 与
    stability 常量全部来自 forgetting 模块。
  - confidence：复用 ``preference_confidence.confidence``，并遵守其文档
    warning（conf 是证据充分度不是质量先验），用 ``max(conf_floor, conf)``，
    ``conf_floor`` 默认 0.42、可配。

通道接口（duck typing）
----------------------
``fused_search`` 的三路通道均为注入式 callable，方便单测塞假通道：
- ``fts(query, *, top_k, owner_id, soul_id) -> list[str]``（排好序的 id 列表）
- ``vector(query, *, top_k, owner_id, soul_id) -> list[str]``
- ``graph(seed_ids, *, top_k, owner_id, soul_id) -> list[str]``（种子由
  fused_search 取词面+语义命中头部生成，供 Personalized PageRank 扩散）

模块同时提供内置默认通道 ``fts_candidates`` / ``vector_candidates`` /
``graph_candidates`` 直接对接既有实现。

诚实边界
--------
- 图扩散全内存跑（端侧 relation_edges 小图），读取时一次性载入
  ``GRAPH_LOAD_LIMIT`` 条可检索胶囊的边；超限部分不参与，属有界近似。
- RRF 分数量纲是倒数秩和（≈1/61 起步），与既有单路 retrieval_score 的
  0–1 加权和量纲不同，两者不可跨 API 直接比大小。
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable

from .forgetting import effective_retention
from .preference_confidence import confidence

logger = logging.getLogger(__name__)

#: RRF 平滑参数 k（惯例 60）。参与排名的文档至少拿到 1/(k+1) 的贡献。
DEFAULT_RRF_K = 60

#: 图扩散每跳衰减因子（requirement: 0.5/跳）。
GRAPH_HOP_DECAY = 0.5

#: 默认扩散跳数。
DEFAULT_GRAPH_HOPS = 2

#: 图读取上限：端侧小图全内存载入，超过该条数的部分不参与（有界近似）。
GRAPH_LOAD_LIMIT = 2000

#: 三路默认权重（tuning 风格常量，进 #118 可调权重键的口径）。
#: 读取方是本模块 ``_weights``；将来 tuning.service.TUNING_DEFAULTS 出现
#: ``"rrf_fusion"`` 段时自动接管，缺失/异常回落这里的内置常量。
_WEIGHTS_FALLBACK: dict[str, float] = {
    "fts": 1.0,
    "vector": 1.0,
    "graph": 0.7,
}
_WEIGHTS_CACHE: dict[str, float] | None = None

#: confidence 乘子下限：遵守 preference_confidence 文档 warning，乘
#: ``max(conf_floor, conf)`` 而非裸 conf，避免冷启动偏好被 uniform 砍分。
DEFAULT_CONF_FLOOR = 0.42


def _reload_weights() -> None:
    """测试/调参热更钩子：清空权重缓存，下次融合时重读。"""
    global _WEIGHTS_CACHE
    _WEIGHTS_CACHE = None


def _weights() -> dict[str, float]:
    global _WEIGHTS_CACHE
    if _WEIGHTS_CACHE is not None:
        return _WEIGHTS_CACHE
    weights = dict(_WEIGHTS_FALLBACK)
    try:
        from ..tuning.service import TUNING_DEFAULTS

        published = TUNING_DEFAULTS.get("rrf_fusion", {})
        for key in weights:
            value = published.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                weights[key] = float(value)
    except Exception as exc:  # noqa: BLE001 —— 调参模块不可用时回落常量
        logger.warning("tuning defaults 不可用，RRF 融合权重回落到内置常量: %s", exc)
    _WEIGHTS_CACHE = weights
    return weights


# ---------------------------------------------------------------------------
# 纯函数：RRF 融合
# ---------------------------------------------------------------------------

def rrf_fuse(
    rankings: list[list[str]],
    *,
    k: int = DEFAULT_RRF_K,
) -> dict[str, float]:
    """把多路排序融合为 ``dict[胶囊id -> RRF 分数]``（分数降序）。

    - ``rankings`` 每一路都是**按相关性降序**的胶囊 id 列表；rank 从 1 起，
      第 r 位贡献 ``1 / (k + r)``（k=60 时第一位得 1/61）。
    - 纯函数：不读库、不改状态。文档同时出现在一路多次时只计首见。
    - 返回按分数降序、分数并列时按 id 升序，保证确定性（方便手算对拍）。
    """
    acc: dict[str, float] = {}
    for ranking in rankings:
        _accumulate_ranking(acc, ranking, weight=1.0, k=k)
    return dict(sorted(acc.items(), key=lambda item: (-item[1], item[0])))


def _accumulate_ranking(
    acc: dict[str, float],
    ranking: list[str],
    *,
    weight: float,
    k: int,
) -> None:
    """把单路排序累加进 acc：rank 1 起，贡献 ``weight / (k + rank)``。"""
    if weight == 0.0:
        return
    seen: set[str] = set()
    for rank, capsule_id in enumerate(ranking, start=1):
        if capsule_id in seen:
            continue
        seen.add(capsule_id)
        acc[capsule_id] = acc.get(capsule_id, 0.0) + weight / (k + rank)


def _weighted_fuse(
    rankings: dict[str, list[str]],
    *,
    weights: dict[str, float],
    k: int,
) -> dict[str, float]:
    """三路加权 RRF：``score = Σ weight[channel] / (k + rank)``。

    ``rrf_fuse`` 保持规格要求的无权重纯函数形态；融合入口在此叠加通道权重，
    两者共享同一 ``_accumulate_ranking`` 累加逻辑，公式不漂移。
    """
    acc: dict[str, float] = {}
    for channel, ranking in rankings.items():
        _accumulate_ranking(acc, ranking, weight=weights.get(channel, 1.0), k=k)
    return dict(sorted(acc.items(), key=lambda item: (-item[1], item[0])))


# ---------------------------------------------------------------------------
# 图通道：relation_edges 两跳扩散（Personalized PageRank 简化版）
# ---------------------------------------------------------------------------

def _load_relation_adjacency(
    *,
    owner_id: str | None,
    soul_id: str | None,
    load_limit: int,
) -> tuple[dict[str, list[str]], set[str]]:
    """一次性载入可检索胶囊的 relation_edges，构建无向邻接表。

    relation_edges 的写入格式见 ``capsule_store.write_capsule``：JSON 数组，
    元素是形如 ``{"target": "<capsule_id>", "type": "..."}`` 的边字典；
    历史数据里有 ``target_id`` / ``capsule_id`` / ``to`` 等别名键（hippo_lite
    与 governance 残留检测都兼容多种键名），这里一并兼容。

    只把边保留在**两端都可检索**的胶囊之间：指向已遗忘/被拒胶囊的边无意义
    （目标不会被任何通道召回），跳过。边视为无向（与 hippo_lite 的
    ``_build_edge_map`` 同口径），自环排除。
    """
    from ..db import get_conn
    from .capsule_store import _RETRIEVABLE_SQL, _scope_predicate, loads

    scope_sql, scope_params = _scope_predicate(owner_id=owner_id, soul_id=soul_id)
    where = (
        f"json_extract(state,'$.lifecycle') IN ({_RETRIEVABLE_SQL}) "
        "AND json_extract(governance,'$.policy_result') IN ('allow','redact')"
    )
    params: list[Any] = list(scope_params)
    if scope_sql:
        where += f" AND {scope_sql}"
    params.append(load_limit)
    rows = get_conn().execute(
        f"SELECT capsule_id, relation_edges FROM memory_capsules_v2 "
        f"WHERE {where} LIMIT ?",
        params,
    ).fetchall()
    node_ids = {row["capsule_id"] for row in rows}
    adjacency: dict[str, set[str]] = {}
    for row in rows:
        cid = row["capsule_id"]
        for edge in loads(row["relation_edges"], []) or []:
            dst = (
                edge.get("target")
                or edge.get("target_id")
                or edge.get("capsule_id")
                or edge.get("to")
            )
            if not dst or dst == cid or dst not in node_ids:
                continue
            adjacency.setdefault(cid, set()).add(dst)
            adjacency.setdefault(dst, set()).add(cid)
    return {node: sorted(nbrs) for node, nbrs in adjacency.items()}, node_ids


def graph_expand(
    seed_ids: list[str],
    *,
    hops: int = DEFAULT_GRAPH_HOPS,
    owner_id: str | None = None,
    soul_id: str | None = None,
    load_limit: int = GRAPH_LOAD_LIMIT,
) -> dict[str, float]:
    """从种子胶囊沿 relation_edges 做 2 跳 Personalized PageRank 简化版。

    规则（全内存，端侧图小）：
    - 种子自身记 1.0；每个已知可检索的种子都会保留在结果里。
    - 每跳：前沿节点把自身质量按 ``质量 × GRAPH_HOP_DECAY / 邻居数`` 均分
      给邻居；衰减 0.5/跳，质量不守恒（每跳折半），与 hippo_lite 同族。
    - 无向边、去自环、邻接去重；两跳后跨端返回的质量会累加到早期节点上
      （PageRank 扩散的固有回流），测试手算对拍时按此口径。

    返回 ``dict[胶囊id -> 扩散分]``，含种子自身；无图数据 / 无可检索种子时
    返回空 dict（优雅降级，调用方按「图路缺席」处理）。
    """
    adjacency, node_ids = _load_relation_adjacency(
        owner_id=owner_id,
        soul_id=soul_id,
        load_limit=load_limit,
    )
    seeds = [cid for cid in dict.fromkeys(seed_ids) if cid in node_ids]
    if not seeds:
        return {}
    scores: dict[str, float] = {cid: 1.0 for cid in seeds}
    frontier = dict(scores)
    for _ in range(max(0, int(hops))):
        next_frontier: dict[str, float] = {}
        for node, mass in frontier.items():
            nbrs = adjacency.get(node)
            if not nbrs:
                continue
            spread = mass * GRAPH_HOP_DECAY / len(nbrs)
            for nbr in nbrs:
                next_frontier[nbr] = next_frontier.get(nbr, 0.0) + spread
        if not next_frontier:
            break
        for nbr, gain in next_frontier.items():
            scores[nbr] = scores.get(nbr, 0.0) + gain
        frontier = next_frontier
    return dict(sorted(scores.items(), key=lambda item: (-item[1], item[0])))


# ---------------------------------------------------------------------------
# 默认通道实现（对接既有单路检索，只 import 复用）
# ---------------------------------------------------------------------------

def fts_candidates(
    query: str,
    *,
    top_k: int,
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> list[str]:
    """词面 FTS5 单路：复用 ``retrieval._fts_candidate_ids`` 的排好序 id 列表。"""
    from .retrieval import _fts_candidate_ids

    return _fts_candidate_ids(
        query,
        limit=top_k,
        owner_id=owner_id,
        soul_id=soul_id,
    )


def vector_candidates(
    query: str,
    *,
    top_k: int,
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> list[str]:
    """向量单路：native（麒麟 SDK）优先，缺席时本地 BGE 通道，再缺席给空。

    语义与既有混合检索的回退链一致；某级不可用是常态（无模型/未配置），
    返回空列表即可——RRF 融合会如实忽略缺席通道。
    """
    from .vector_index import native_candidates

    rows, _status = native_candidates(query, top_k=top_k)
    if rows:
        return [cid for cid, _ in rows]
    from .local_embedding import search as _local_search

    local_rows = _local_search(
        query,
        top_k=top_k,
        owner_id=owner_id,
        soul_id=soul_id,
    )
    if local_rows:
        return [cid for cid, _ in local_rows]
    return []


def graph_candidates(
    seed_ids: list[str],
    *,
    top_k: int,
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> list[str]:
    """图通道：对种子做 Personalized PageRank 扩散后按扩散分取 top_k。

    种子由 fused_search 取词面+语义命中的头部 id 提供；扩散会把关联胶囊
    （共同事件/相互引用，无词面重合也能被召回）带进候选。
    """
    scores = graph_expand(
        seed_ids,
        owner_id=owner_id,
        soul_id=soul_id,
    )
    return list(scores)[:top_k]


# ---------------------------------------------------------------------------
# 融合入口
# ---------------------------------------------------------------------------

def _recency_decay(state: dict[str, Any], *, at: datetime | None) -> float:
    """取遗忘曲线的**纯时间衰减项** ``exp(-λ·days/stability)``。

    复用 ``forgetting.effective_retention`` 的公式/λ/stability/时间解析，
    只是把 ``retention_score`` 基线置 1.0，让返回不再混入存储强度——本融合链
    里 retention_score 应由 RRF 分数与 confidence 之外的环节表达，衰减项应当
    只含时间分量。无 ``last_accessed_at``（从未召回）→ 宽限期不衰减 → 1.0。
    """
    decay_state = dict(state)
    decay_state["retention_score"] = 1.0
    return effective_retention(decay_state, at=at)


def fused_search(
    query: str,
    *,
    top_k: int = 5,
    high_risk: bool = False,
    owner_id: str | None = None,
    soul_id: str | None = None,
    fts: Callable[..., list[str]] | None = None,
    vector: Callable[..., list[str]] | None = None,
    graph: Callable[..., list[str]] | None = None,
    weights: dict[str, float] | None = None,
    k: int = DEFAULT_RRF_K,
    conf_floor: float = DEFAULT_CONF_FLOOR,
    hops: int = DEFAULT_GRAPH_HOPS,
    at: datetime | None = None,
) -> list[dict[str, Any]]:
    """三路召回 RRF 融合 + 乘子链，返回按 ``rrf_fusion_score`` 降序的胶囊。

    流程：
    1. 并行收集三路排序：``fts(query)`` / ``vector(query)`` 各取候选池
       （``max(top_k*3, 12)``）；图路种子取两路命中头部并集，
       ``graph(seeds)`` 做 PPR 扩散得到图路排序。
    2. 加权 RRF 融合（通道权重默认 1.0/1.0/0.7，可经 ``weights`` 覆盖）。
    3. 批量取回胶囊 → ``allowed_for_context``（含 high_risk）过滤。
    4. 乘子链 ``final = rrf × recency_decay × max(conf_floor, conf)``，
       复用 forgetting / preference_confidence，不另写公式。

    通道传 ``None`` 表示该路缺席（如无图数据/无向量模型），融合自动跳过，
    不回退、不报错——缺一路只是少一路证据。

    只读路径：**不 bump usage_count**。本模块是增量研究入口，接入主检索
    路径前不应擅自改统计元数据。
    """
    from .capsule_store import allowed_for_context, get_capsules_batch

    pool_size = max(int(top_k) * 3, 12)
    rankings: dict[str, list[str]] = {}
    seed_pool: list[str] = []
    seen_seeds: set[str] = set()

    if fts is not None:
        ids = fts(query, top_k=pool_size, owner_id=owner_id, soul_id=soul_id)
        rankings["fts"] = ids or []
        for cid in rankings["fts"]:
            if cid not in seen_seeds:
                seen_seeds.add(cid)
                seed_pool.append(cid)
    if vector is not None:
        ids = vector(query, top_k=pool_size, owner_id=owner_id, soul_id=soul_id)
        rankings["vector"] = ids or []
        for cid in rankings["vector"]:
            if cid not in seen_seeds:
                seen_seeds.add(cid)
                seed_pool.append(cid)
    if graph is not None:
        seeds = seed_pool[:pool_size]
        gids = graph(seeds, top_k=pool_size, owner_id=owner_id, soul_id=soul_id)
        rankings["graph"] = gids or []

    if not rankings:
        return []

    merged = _weights() if weights is None else dict(weights)
    rrf_scores = _weighted_fuse(rankings, weights=merged, k=k)

    # 图路可能返回词面路没见过的关联胶囊，合并取全再一次性 batch 取回。
    all_ids = [cid for cid in rrf_scores]
    by_id = get_capsules_batch(all_ids, owner_id=owner_id, soul_id=soul_id)

    scored: list[dict[str, Any]] = []
    channel_ranks: dict[str, dict[str, int]] = {
        channel: {cid: rank for rank, cid in enumerate(ids, start=1)}
        for channel, ids in rankings.items()
    }
    for capsule_id, rrf_score in rrf_scores.items():
        cap = by_id.get(capsule_id)
        if not cap or not allowed_for_context(cap, high_risk=high_risk):
            continue
        state = cap.get("state") or {}
        decay = _recency_decay(state, at=at)
        conf_raw = confidence(state)["conf"]
        conf_mult = max(float(conf_floor), float(conf_raw))
        final = rrf_score * decay * conf_mult
        cap["rrf_fusion_score"] = round(final, 6)
        cap["rrf_score"] = round(rrf_score, 6)
        cap["rrf_recency_decay"] = decay
        cap["rrf_confidence"] = round(conf_mult, 4)
        cap["rrf_channels"] = {}
        for channel, ranks in channel_ranks.items():
            if capsule_id in ranks:
                cap["rrf_channels"][channel] = ranks[capsule_id]
        # shape-compat：旧检索结果带 retrieval_score，新入口保持一致键位，
        # 数值为融合后的最终分（量纲是倒数秩和，勿与单路 0-1 加权分直接比）。
        cap["retrieval_score"] = cap["rrf_fusion_score"]
        scored.append(cap)

    scored.sort(key=lambda c: (c["rrf_fusion_score"],), reverse=True)
    return scored[:top_k]


__all__ = [
    "DEFAULT_RRF_K",
    "GRAPH_HOP_DECAY",
    "DEFAULT_GRAPH_HOPS",
    "DEFAULT_CONF_FLOOR",
    "rrf_fuse",
    "graph_expand",
    "fts_candidates",
    "vector_candidates",
    "graph_candidates",
    "fused_search",
    "_reload_weights",
]
