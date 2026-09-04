"""Preference Graph（偏好记忆图）与偏好演化机制 — issue #198。

设计背景
--------
既有体系里偏好以**离散 capsule** 形式存在（``memory_class='preference'`` +
Beta 置信度 + 情感证据权重 + Outcome Validation）。系统能回答「用户喜欢什么」，
但无法回答：

- 偏好是如何形成的（哪条证据支撑它）
- 偏好是否演化过（新偏好是否替换了旧偏好）
- 冲突时该信谁（历史权重 vs 当前权重）
- 哪些记忆是偏好的派生来源

本模块在 capsule 之上建一层**偏好图视图**：

```text
Emotion Node ──emotion_for──▶ Preference Node ◀──evidence_for── Evidence Node
                                    │ ▲
                        replaces    │ │ conflicts_with
                                    ▼ │
                              Preference Node
                                    ▲
                        constraint_of │ derived_from
                                    │
                        Constraint / Emotion Node
```

存储口径（与既有基础设施零新表）
--------------------------------
- **节点即 capsule**：不建新表。Preference / Emotion(承载于
  affective_metadata) / Evidence(普通 knowledge capsule) / Constraint /
  Version 各类节点都是 ``memory_capsules_v2`` 里的行，节点类型由
  ``content.preference_graph_node_type`` 键标注（缺省按 ``memory_class``
  推断）。
- **边即 relation_edges**：图边写入 capsule 既有的 ``relation_edges``
  JSON 列（``[{"target": <id>, "type": <edge_type>, ...}]``，与
  ``rrf_fusion._load_relation_adjacency`` 兼容的键名格式），**有向**——
  RRF 图通道把边按无向消费是其自己的口径，本模块写入时带上 ``direction``
  字段供审计区分。
- 边类型受控词表：``evidence_for`` / ``emotion_for`` / ``constraint_of`` /
  ``replaces`` / ``conflicts_with`` / ``derived_from``（与 issue #198 设计
  一一对应）。不在词表内的边类型被图算法忽略，不影响既有 relation_edges
  消费方。

评分模型（preference_score）
----------------------------
    score = 0.35 × emotion_weight
          + 0.25 × recency_weight
          + 0.20 × frequency_weight
          + 0.20 × evidence_weight    # issue #198 偏好评分模型，权重进 tuning

- ``emotion_weight``：|pleasure| 归一（情感强度调制偏好固化，方向无关——
  强烈反感与强烈喜欢同样说明这不是临时情绪）；
- ``recency_weight``：30 天半衰指数衰减（与 conflict_resolution 同族公式）；
- ``frequency_weight``：Beta 后验 mean（被采纳次数 / 总证据次数）；
- ``evidence_weight``：图上指向该偏好的 evidence_for 边数 + 约束边数
  的 log 压缩归一（10 条证据 ≈ 0.68）。

冲突处理（诚实口径）
--------------------
与 ``conflict_resolution`` 的治理底线一致：**只计算建议，不自动覆盖**。
``active_preference`` 报告哪条偏好当前权重更高，但生命周期转移仍须走
``lifecycle.resolve_conflict(actor='human')`` 显式裁决。

级联遗忘
--------
忘记一条偏好时，沿 ``replaces`` 链回溯把被替换的旧版本一并遗忘（保留
演化终态一致），并把指向该偏好的 evidence_for / emotion_for 源胶囊的
**边**摘除（源胶囊本身不动——证据可能同时支撑其他偏好）。实际删除走
``capsule_store.forget_capsules``，其删除完整性校验照常生效。
"""
from __future__ import annotations

import logging
import math
import sqlite3
from datetime import datetime, timezone
from typing import Any

from ..db import get_conn
from .preference_confidence import confidence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 受控词表
# ---------------------------------------------------------------------------

#: 图边类型受控词表（issue #198 设计）。写入校验用；图算法消费同一集合。
EDGE_TYPES = frozenset({
    "evidence_for",    # Evidence --supports--> Preference
    "emotion_for",     # Emotion  --strengthens--> Preference
    "constraint_of",   # Constraint --limits--> Preference
    "replaces",        # 新偏好 --replaces--> 旧偏好（演化主链）
    "conflicts_with",  # 偏好对冲（待裁决信号）
    "derived_from",    # Preference --derived_from--> Emotion
})

#: 允许隐式推断为偏好图节点的 memory_class（content 缺省 node_type 键时）。
_NODE_CLASS_HINTS = {
    "preference": "preference",
    "knowledge": "evidence",
    "constraint": "constraint",
}

#: preference_score 四因子默认权重（issue #198 示例口径；进 tuning 可调）。
DEFAULT_SCORE_WEIGHTS: dict[str, float] = {
    "emotion": 0.35,
    "recency": 0.25,
    "frequency": 0.20,
    "evidence": 0.20,
}

#: recency 半衰期（天）——与 conflict_resolution._recency_factor 同族。
RECENCY_HALF_LIFE_DAYS = 30.0

#: evidence 归一的 log 压缩基准：10 条边 ≈ 0.68、50 条 ≈ 0.90。
_EVIDENCE_LOG_BASE = 50.0

#: 图读取上限（端侧小图全内存，与 rrf_fusion.GRAPH_LOAD_LIMIT 同口径）。
GRAPH_LOAD_LIMIT = 2000

#: 级联遗忘的 replaces 链回溯深度上限。环由 seen 集合防；此限防退化 DAG
#: （被污染数据串起超长替换链）把回溯 + strip 循环拖成全表遍历。真实偏好
#: 演化链远短于此；命中即截断并在结果里如实标 ``depth_truncated``。
MAX_CHAIN_DEPTH = 100


def _parse_ts(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _load_json(value: Any, default: Any) -> Any:
    import json

    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return default
    return default


# ---------------------------------------------------------------------------
# 偏好图视图构建（只读）
# ---------------------------------------------------------------------------

def _node_type(cap: dict[str, Any]) -> str:
    """推断 capsule 的偏好图节点类型。

    ``content.preference_graph_node_type`` 显式标注优先；缺省按 memory_class
    推断（preference→preference、knowledge→evidence、constraint→constraint，
    其余返回 ``"other"`` 不参与偏好图算法）。
    """
    content = cap.get("content") or {}
    explicit = content.get("preference_graph_node_type")
    if isinstance(explicit, str) and explicit:
        return explicit
    return _NODE_CLASS_HINTS.get(str(cap.get("memory_class") or ""), "other")


def load_preference_graph(
    *,
    owner_id: str | None = None,
    soul_id: str | None = None,
    load_limit: int = GRAPH_LOAD_LIMIT,
) -> dict[str, Any]:
    """一次性载入偏好图视图（节点表 + 邻接表），**只读、不写库**。

    返回结构::

        {
          "nodes": {capsule_id: {"node_type": ..., "name": ...,
                                 "polarity": ..., "state": ..., "cap": ...}},
          "edges": {capsule_id: [{"target": ..., "type": ...}, ...]},  # 出边
          "stats": {"nodes": N, "edges": M, "by_type": {...}},
        }

    只载入可检索胶囊（lifecycle 可检索 + policy allow/redact，与
    ``rrf_fusion._load_relation_adjacency`` 同一过滤口径），且只保留
    ``EDGE_TYPES`` 受控词表内的边——历史 relation_edges 里的其他业务边
    不进偏好图，不影响 RRF 图通道等其他消费方。
    """
    from .capsule_store import _RETRIEVABLE_SQL, _scope_predicate

    scope_sql, scope_params = _scope_predicate(owner_id=owner_id, soul_id=soul_id)
    where = (
        f"json_extract(state,'$.lifecycle') IN ({_RETRIEVABLE_SQL}) "
        "AND json_extract(governance,'$.policy_result') IN ('allow','redact')"
    )
    params: list[Any] = list(scope_params)
    if scope_sql:
        where += f" AND {scope_sql}"
    params.append(int(load_limit))
    rows = get_conn().execute(
        f"SELECT * FROM memory_capsules_v2 WHERE {where} LIMIT ?",
        params,
    ).fetchall()

    nodes: dict[str, dict[str, Any]] = {}
    raw_edges: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        cap = dict(row)
        cap["content"] = _load_json(cap.get("content"), {})
        cap["state"] = _load_json(cap.get("state"), {})
        cap["relation_edges"] = _load_json(cap.get("relation_edges"), [])
        cap["affective_metadata"] = _load_json(cap.get("affective_metadata"), {})
        cap["provenance"] = _load_json(cap.get("provenance"), {})
        cid = cap["capsule_id"]
        content = cap["content"]
        nodes[cid] = {
            "node_type": _node_type(cap),
            "name": _preference_name(cap),
            "polarity": _preference_polarity(cap),
            "state": cap["state"],
            "content": content,
            "provenance": cap["provenance"],
            "affective_metadata": cap.get("affective_metadata") or {},
            "created_at": cap.get("created_at"),
            "updated_at": cap.get("updated_at"),
        }
        for edge in cap["relation_edges"] or []:
            if not isinstance(edge, dict):
                continue
            etype = str(edge.get("type") or "")
            if etype not in EDGE_TYPES:
                continue
            dst = edge.get("target") or edge.get("target_id") or edge.get("to")
            if dst and dst != cid:
                raw_edges.setdefault(cid, []).append(
                    {"target": str(dst), "type": etype}
                )

    # 只保留两端都在节点表内的边（指向已遗忘胶囊的边无意义，同 RRF 口径）。
    edges = {
        cid: [e for e in elist if e["target"] in nodes]
        for cid, elist in raw_edges.items()
    }
    edges = {cid: elist for cid, elist in edges.items() if elist}

    by_type: dict[str, int] = {}
    for elist in edges.values():
        for e in elist:
            by_type[e["type"]] = by_type.get(e["type"], 0) + 1
    node_by_type: dict[str, int] = {}
    for meta in nodes.values():
        node_by_type[meta["node_type"]] = node_by_type.get(meta["node_type"], 0) + 1
    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "nodes": len(nodes),
            "edges": sum(by_type.values()),
            "nodes_by_type": node_by_type,
            "edges_by_type": by_type,
        },
    }


def _preference_name(cap: dict[str, Any]) -> str:
    """偏好的显示名：content.subject / preference_type / topic / statement 前缀。"""
    content = cap.get("content") or {}
    for key in ("subject", "preference_type", "topic", "name"):
        value = content.get(key)
        if isinstance(value, str) and value:
            return value
    statement = content.get("statement") or content.get("preference_value")
    if isinstance(statement, str) and statement:
        return statement[:64]
    return cap.get("capsule_id", "")


def _preference_polarity(cap: dict[str, Any]) -> str:
    """偏好极性：positive / negative / neutral。

    显式 ``content.polarity`` 优先；缺省从 Beta 后验均值推断
    （mean > 0.5 → positive，< 0.5 → negative——注意 mean 低只说明
    「被违背的证据多」，不必然是反向偏好，故落在 0.45–0.55 中间带时
    报 neutral，不做方向性猜测）。
    """
    content = cap.get("content") or {}
    explicit = content.get("polarity")
    if isinstance(explicit, str) and explicit in ("positive", "negative", "neutral"):
        return explicit
    mean = confidence(cap.get("state") or {}).get("mean", 0.5)
    if mean > 0.55:
        return "positive"
    if mean < 0.45:
        return "negative"
    return "neutral"


# ---------------------------------------------------------------------------
# preference_score 四因子评分
# ---------------------------------------------------------------------------

def _emotion_weight(node_meta: dict[str, Any]) -> float:
    """情感因子：|pleasure| 归一到 [0, 1]。

    情感方向不进分数（强烈喜欢与强烈反感对「这是不是临时情绪」的判别力
    相同），强度才进。缺省取 state 里的 Beta conf 之前先看
    affective_metadata（emotion_memory.bind_emotion_to_capsule 的写入位）。
    """
    aff = node_meta.get("affective_metadata") or {}
    try:
        pleasure = float(aff.get("pleasure") or 0.0)
    except (TypeError, ValueError):
        pleasure = 0.0
    try:
        intensity = float(aff.get("mood_intensity") or 0.0)
    except (TypeError, ValueError):
        intensity = 0.0
    return min(1.0, max(abs(pleasure), intensity))


def _recency_weight(node_meta: dict[str, Any], *, at: datetime | None) -> float:
    """时间新近性：30 天半衰指数衰减，无时间戳按 0.5（与裁决因子同口径）。"""
    last = _parse_ts(
        (node_meta.get("state") or {}).get("last_accessed_at")
        or node_meta.get("updated_at")
        or node_meta.get("created_at")
    )
    if last is None:
        return 0.5
    now = at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    days = max(0.0, (now - last).total_seconds() / 86400.0)
    decay_rate = math.log(2.0) / RECENCY_HALF_LIFE_DAYS
    return math.exp(-decay_rate * days)


def _frequency_weight(node_meta: dict[str, Any]) -> float:
    """频次因子：Beta 后验均值（被采纳证据占比）。"""
    return min(1.0, max(0.0, confidence(node_meta.get("state") or {})["mean"]))


def _evidence_weight(node_meta: dict[str, Any], in_edges: dict[str, int]) -> float:
    """证据因子：指向该节点的 evidence_for + constraint_of 边数 log 压缩归一。

    ``in_edges`` 由 ``compute_preference_scores`` 预计算的入边计数
    （``{capsule_id: {"evidence_for": n, ...}}``）。
    """
    counts = in_edges.get(node_meta.get("capsule_id", ""), {}) if node_meta else {}
    total = counts.get("evidence_for", 0) + counts.get("constraint_of", 0)
    return math.log1p(total) / math.log1p(_EVIDENCE_LOG_BASE)


def compute_preference_scores(
    graph: dict[str, Any],
    *,
    weights: dict[str, float] | None = None,
    at: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """对图内全部 preference 节点计算 preference_score（issue #198 评分模型）。

    返回 ``{capsule_id: {"score", "factors": {...}, "polarity", "name"}}``，
    按 score 降序。四因子分解全部随分数返回（可解释性），供
    ``preference-aware retrieval`` 与健康面板直接消费。

    显式 ``weights`` 参数优先；缺省时读 ``tuning.service.TUNING_DEFAULTS``
    的 ``preference_graph`` 段（缺失/异常回落 :data:`DEFAULT_SCORE_WEIGHTS`）。
    """
    w = dict(DEFAULT_SCORE_WEIGHTS)
    if weights:
        for key in w:
            if key in weights:
                w[key] = float(weights[key])
    else:
        # tuning 段 ``preference_graph`` 出现时自动接管（与 rrf_fusion 同口径）；
        # 缺失/异常回落内置常量，评分可用性不依赖调参模块。
        try:
            from ..tuning.service import TUNING_DEFAULTS

            published = TUNING_DEFAULTS.get("preference_graph", {})
            for key in w:
                value = published.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    w[key] = float(value)
        except Exception as exc:  # noqa: BLE001 —— 调参模块不可用时回落常量
            logger.warning(
                "tuning defaults 不可用，preference_score 权重回落到内置常量: %s", exc
            )

    # 入边计数（evidence_for / constraint_of → 目标偏好节点）
    in_edges: dict[str, dict[str, int]] = {}
    for _src, elist in (graph.get("edges") or {}).items():
        for edge in elist:
            if edge["type"] in ("evidence_for", "constraint_of"):
                bucket = in_edges.setdefault(edge["target"], {})
                bucket[edge["type"]] = bucket.get(edge["type"], 0) + 1

    out: dict[str, dict[str, Any]] = {}
    for cid, node_meta in (graph.get("nodes") or {}).items():
        if node_meta["node_type"] != "preference":
            continue
        factors = {
            "emotion": round(_emotion_weight(node_meta), 4),
            "recency": round(_recency_weight(node_meta, at=at), 4),
            "frequency": round(_frequency_weight(node_meta), 4),
            "evidence": round(
                _evidence_weight({**node_meta, "capsule_id": cid}, in_edges), 4
            ),
        }
        score = sum(w[k] * factors[k] for k in factors)
        out[cid] = {
            "score": round(score, 4),
            "factors": factors,
            "polarity": _preference_polarity(
                {"content": node_meta.get("content") or {},
                 "state": node_meta.get("state") or {}}
            ),
            "name": node_meta.get("name") or cid,
        }
    return dict(
        sorted(out.items(), key=lambda item: (-item[1]["score"], item[0]))
    )


# ---------------------------------------------------------------------------
# 偏好演化：replaces 链 / 冲突裁决建议
# ---------------------------------------------------------------------------

def record_preference_evolution(
    new_capsule_id: str,
    old_capsule_id: str,
    *,
    edge_type: str = "replaces",
    owner_id: str | None = None,
    soul_id: str | None = None,
    actor: str = "agent",
) -> dict[str, Any]:
    """在两条偏好胶囊之间记录一条演化边（``replaces`` / ``conflicts_with``）。

    - ``replaces``：新偏好替代旧偏好。同时把旧偏好 lifecycle 转
      ``deprecated``（经 ``apply_transition`` 状态机校验，账本留痕），
      并写双向边：新→旧 ``replaces``、旧 state 的 ``superseded_by`` 追加
      新 id（复用 ``resolve_conflict`` 的版本链字段语义）。
    ``conflicts_with``：只写边标记冲突，**不转移任何生命周期**——冲突必须
    显式裁决（治理底线），裁决建议走 ``suggest_active_preference``。

    幂等：重复记录同一条边不会重复追加。
    """
    if edge_type not in ("replaces", "conflicts_with"):
        raise ValueError(f"edge_type 必须是 'replaces' 或 'conflicts_with': {edge_type!r}")
    from .capsule_store import get_capsule, update_capsule

    new_cap = get_capsule(new_capsule_id, owner_id=owner_id, soul_id=soul_id)
    old_cap = get_capsule(old_capsule_id, owner_id=owner_id, soul_id=soul_id)
    if not new_cap:
        raise KeyError(new_capsule_id)
    if not old_cap:
        raise KeyError(old_capsule_id)
    for cap, label in ((new_cap, "new"), (old_cap, "old")):
        if cap.get("memory_class") != "preference":
            raise ValueError(f"{label} capsule 必须是 preference 类（得到 {cap.get('memory_class')!r}）")

    def _edge_present(edges: list[dict[str, Any]], dst: str, etype: str) -> bool:
        return any(
            isinstance(e, dict)
            and e.get("type") == etype
            and (e.get("target") or e.get("target_id") or e.get("to")) == dst
            for e in edges or []
        )

    new_edges = list(new_cap["relation_edges"] or [])
    edge_added = False
    if not _edge_present(new_edges, old_capsule_id, edge_type):
        new_edges.append({
            "target": old_capsule_id,
            "type": edge_type,
            "direction": "outgoing",
            "created_at": _now_compact(),
        })
        edge_added = True

    result: dict[str, Any] = {
        "edge_type": edge_type,
        "new_capsule_id": new_capsule_id,
        "old_capsule_id": old_capsule_id,
        "edge_added": edge_added,
        "lifecycle_transitioned": False,
    }

    if edge_type == "replaces":
        from ..memoryos.governance import append_ledger
        from ..memoryos.lifecycle import LifecycleState, apply_transition

        # 版本链以 apply_transition 事务内读到的 state 为准（它有自己的
        # BEGIN IMMEDIATE，本地修改不会也不会需要参与写入）。这里只从
        # 快照算「是否需要追加」，避免幂等重调时重复写转移/账本。
        superseded_by = list((old_cap["state"] or {}).get("superseded_by") or [])
        chain_mutated = new_capsule_id not in superseded_by
        if chain_mutated:
            superseded_by.append(new_capsule_id)
            apply_transition(
                old_capsule_id,
                LifecycleState.DEPRECATED.value,
                f"preference_replaced_by:{new_capsule_id}",
                actor=actor,
                owner_id=owner_id,
                soul_id=soul_id,
                state_patch={
                    "superseded_by": superseded_by,
                    "deprecation_reason": f"replaced_by:{new_capsule_id}",
                },
            )
        result["lifecycle_transitioned"] = chain_mutated
        append_ledger(
            op_type="preference_evolution",
            capsule_id=new_capsule_id,
            actor=actor,
            reason=f"replaces:{old_capsule_id}",
            owner_id=owner_id or (new_cap.get("provenance") or {}).get("owner_id"),
            soul_id=soul_id or (new_cap.get("provenance") or {}).get("soul_id"),
        )
    else:
        # conflicts_with：账本留痕但不碰生命周期（裁决前不动状态）。
        from ..memoryos.governance import append_ledger

        append_ledger(
            op_type="preference_conflict_marked",
            capsule_id=new_capsule_id,
            actor=actor,
            reason=f"conflicts_with:{old_capsule_id}",
            owner_id=owner_id or (new_cap.get("provenance") or {}).get("owner_id"),
            soul_id=soul_id or (new_cap.get("provenance") or {}).get("soul_id"),
        )

    if edge_added:
        update_capsule(
            new_capsule_id,
            relation_edges=new_edges,
            owner_id=owner_id,
            soul_id=soul_id,
            actor=actor,
            reason=f"preference_graph:{edge_type}",
        )
    return result


def suggest_active_preference(
    preference_ids: list[str],
    *,
    owner_id: str | None = None,
    soul_id: str | None = None,
    at: datetime | None = None,
) -> dict[str, Any]:
    """对一组（冲突中的）偏好胶囊给出「当前应相信谁」的建议。

    **只建议，不执行**（与 ``conflict_resolution.suggest_conflict_resolution``
    同一治理口径）：按 preference_score 排序，报告 top1 为
    ``suggested_active``，实际裁决仍须 ``lifecycle.resolve_conflict``。

    输入为空 / 胶囊查不到时返回 ``suggested_active=None``（诚实降级，
    不猜测）。
    """
    graph = load_preference_graph(owner_id=owner_id, soul_id=soul_id)
    nodes = graph.get("nodes") or {}
    wanted = [cid for cid in dict.fromkeys(preference_ids) if cid in nodes]
    if not wanted:
        return {
            "suggested_active": None,
            "auto_execute": False,
            "note": "无可评估的 preference 节点",
        }
    scores = compute_preference_scores(
        {"nodes": {cid: nodes[cid] for cid in wanted}, "edges": graph.get("edges") or {}},
        at=at,
    )
    if not scores:
        return {
            "suggested_active": None,
            "auto_execute": False,
            "note": "输入胶囊均不是 preference 类",
        }
    ranked = list(scores.items())
    top_id, top = ranked[0]
    return {
        "suggested_active": top_id,
        "suggested_active_score": top["score"],
        "suggested_active_factors": top["factors"],
        "ranking": [
            {"capsule_id": cid, "score": s["score"], "name": s["name"]}
            for cid, s in ranked
        ],
        "auto_execute": False,
        "note": "建议式裁决: 需 resolve_conflict(actor='human') 显式确认才生效",
    }


def _load_raw_out_edges(
    *,
    owner_id: str | None = None,
    soul_id: str | None = None,
    load_limit: int = GRAPH_LOAD_LIMIT,
) -> dict[str, list[dict[str, Any]]]:
    """读全部胶囊的**原始** relation_edges 出边（不过滤 lifecycle / 边类型）。

    仅供级联遗忘的 replaces 链回溯使用：旧偏好在落 replaces 边时已被转
    ``deprecated``，不在可检索图视图里，链回溯必须看原始边才能穿过
    deprecated 节点继续向前追溯。

    诚实边界：``load_limit`` 是**软截断**（``relation_edges`` JSON 列无索引，
    无界全表读对端侧不可接受）。达到上限时如实记 warning——链上被截掉的
    旧版本不会被本次级联遗忘（宁可漏不可挂死的同一口径）。排序不保证，
    上限内的取集是「取到哪算哪」；真实端侧数据远低于该上限。
    """
    from .capsule_store import _scope_predicate

    scope_sql, scope_params = _scope_predicate(owner_id=owner_id, soul_id=soul_id)
    where = "relation_edges IS NOT NULL AND relation_edges != '[]'"
    params: list[Any] = list(scope_params)
    if scope_sql:
        where += f" AND {scope_sql}"
    # 多取一行探测截断：返回 load_limit+1 行说明还有剩余没读进来。
    params.append(int(load_limit) + 1)
    rows = get_conn().execute(
        f"SELECT capsule_id, relation_edges FROM memory_capsules_v2 "
        f"WHERE {where} LIMIT ?",
        params,
    ).fetchall()
    truncated = len(rows) > load_limit
    if truncated:
        rows = rows[:load_limit]
        logger.warning(
            "_load_raw_out_edges 命中 %d 行上限，剩余带边胶囊未读入——"
            "级联遗忘的 replaces 链可能不完整（宁可漏不可挂死）",
            load_limit,
        )
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        cid = row["capsule_id"]
        for edge in _load_json(row["relation_edges"], []) or []:
            if not isinstance(edge, dict):
                continue
            dst = edge.get("target") or edge.get("target_id") or edge.get("to")
            etype = str(edge.get("type") or "")
            if dst and dst != cid:
                out.setdefault(cid, []).append({"target": str(dst), "type": etype})
    return out


# ---------------------------------------------------------------------------
# 级联遗忘
# ---------------------------------------------------------------------------

def cascade_forget_preference(
    capsule_id: str,
    *,
    mode: str = "soft_delete",
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> dict[str, Any]:
    """遗忘一条偏好时做图级联（issue #198「遗忘联动」）。

    级联范围（保守，宁少勿多——遗忘是不可逆动作，误伤比漏网更糟）：
    1. 目标偏好本身；
    2. 沿 ``replaces`` 出边回溯：被该偏好替换的**旧版本**一并遗忘
       （保演化终态一致——新偏好没了，被替换链上的历史版本不该复活）；
    3. 指向目标偏好的 ``evidence_for`` / ``emotion_for`` 源胶囊**不删**，
       只摘除指向目标的边（证据可能同时支撑其他偏好，且证据胶囊可能是
       用户的其他类记忆）。

    实际删除复用 ``capsule_store.forget_capsules``（生命周期校验 +
    FTS/向量同步 + 删除完整性验证全部照常生效）。
    """
    from .capsule_store import forget_capsules, get_capsule, update_capsule

    cap = get_capsule(capsule_id, owner_id=owner_id, soul_id=soul_id)
    if not cap:
        raise KeyError(capsule_id)
    if cap.get("memory_class") != "preference":
        raise ValueError("级联遗忘只适用于 preference 类胶囊")

    graph = load_preference_graph(owner_id=owner_id, soul_id=soul_id)
    edges = graph.get("edges") or {}

    # 1) replaces 链回溯。两层保护：
    #    - ``seen`` 集合防环（图上历史边可能成环）；
    #    - ``MAX_CHAIN_DEPTH`` 限深防退化 DAG：深度无界的替换链（如被污染
    #      数据从单根串起超长链）会让回溯 + strip 循环跑遍全表并锁死请求
    #      路径，宁可漏忘（partial 标记如实上报）不可挂死。
    # 注意不能用上面的可检索图视图做链回溯：record_preference_evolution 落
    # replaces 边的同时会把旧偏好转 deprecated，而 deprecated 不在可检索集，
    # 用可检索视图回溯会得到空链。这里直接读原始 relation_edges（含
    # deprecated 节点的出边），deprecated → forgotten 是合法转移，链上节点
    # 可以被 forget_capsules 正常级联。
    raw_edges = _load_raw_out_edges(owner_id=owner_id, soul_id=soul_id)
    chain: list[str] = []
    seen = {capsule_id}
    frontier = [capsule_id]
    depth_truncated = False
    for _ in range(MAX_CHAIN_DEPTH):
        if not frontier:
            break
        nxt: list[str] = []
        for src in frontier:
            for edge in raw_edges.get(src) or []:
                if edge["type"] == "replaces" and edge["target"] not in seen:
                    seen.add(edge["target"])
                    chain.append(edge["target"])
                    nxt.append(edge["target"])
        frontier = nxt
    else:
        if frontier:
            depth_truncated = True
            logger.warning(
                "replaces 链深度超过 %d（capsule_id=%s），级联遗忘只处理前 %d 个"
                "旧版本，剩余链路保留待查（数据可能被污染）",
                MAX_CHAIN_DEPTH, capsule_id, len(chain),
            )

    # 2) 摘除指向目标的 evidence_for / emotion_for 入边（源胶囊保留）。
    detached: list[str] = []
    for src, elist in edges.items():
        if src == capsule_id or src in chain:
            continue
        must_detach = any(
            e["type"] in ("evidence_for", "emotion_for") and e["target"] == capsule_id
            for e in elist
        )
        if not must_detach:
            continue
        src_cap = get_capsule(src, owner_id=owner_id, soul_id=soul_id)
        if not src_cap:
            continue
        kept = [
            e for e in (src_cap["relation_edges"] or [])
            if not (
                isinstance(e, dict)
                and e.get("type") in ("evidence_for", "emotion_for")
                and (e.get("target") or e.get("target_id") or e.get("to")) == capsule_id
            )
        ]
        if len(kept) != len(src_cap["relation_edges"] or []):
            update_capsule(
                src,
                relation_edges=kept,
                owner_id=owner_id,
                soul_id=soul_id,
                reason=f"cascade_detach:{capsule_id}",
            )
            detached.append(src)

    forget_ids = [capsule_id] + chain
    result = forget_capsules(
        forget_ids, mode=mode, owner_id=owner_id, soul_id=soul_id
    )
    # 3) 清除已遗忘胶囊自身的图足迹：forget_capsules 只软删行（留审计），
    # 不清 relation_edges，被忘胶囊上指向彼此的 replaces 边会成为
    # verify_deletion 判定的残留（「图边」四处残留之一）。级联语义下把
    # 这些死边一并摘除，删除完整性才真正成立。
    if mode != "hard_delete":
        for cid in forget_ids:
            forgotten_cap = get_capsule(cid, owner_id=owner_id, soul_id=soul_id)
            if not forgotten_cap:
                continue
            kept = [
                e for e in (forgotten_cap["relation_edges"] or [])
                if not (
                    isinstance(e, dict)
                    and e.get("type") in EDGE_TYPES
                    and (e.get("target") or e.get("target_id") or e.get("to")) in set(forget_ids)
                )
            ]
            if len(kept) != len(forgotten_cap["relation_edges"] or []):
                update_capsule(
                    cid,
                    relation_edges=kept,
                    owner_id=owner_id,
                    soul_id=soul_id,
                    reason=f"cascade_strip:{cid}",
                )
        # 边清理后再验一次删除完整性：forget_capsules 响应里的证据是在
        # strip 之前算的，如实上报会永远带一条已消除的残留。级联语义的
        # 「删除完成」以 strip 之后为准（复用同一 verify_deletions，不另
        # 写第二套口径）。异常口径收窄到 sqlite/运行时/OS 层：宽 except 会
        # 吞掉 NameError/TypeError/AttributeError（本仓真实事故：静默失效的
        # 快照采样器让整个 benchmark 假绿），这些是代码 bug 必须炸出来。
        try:
            from ..memoryos.governance import verify_deletions

            result["deletion_verification"] = verify_deletions(
                result["deleted_capsule_ids"]
            )
        except (sqlite3.Error, RuntimeError, OSError):
            # pragma: no cover - 验证失败不反噬删除事实（删除已提交），
            # exc_info=True 让静默降级路径在日志里留下完整栈。
            logger.warning(
                "cascade deletion re-verification failed, "
                "deletion_verification 保留 forget 时的原值",
                exc_info=True,
            )
    result["cascade"] = {
        "replaces_chain_forgotten": chain,
        "evidence_edges_detached_from": detached,
        # 限深截断如实上报：截断时链上剩余旧版本未遗忘，调用方需要知道
        # 级联是 partial 的，不能把「 forgotten」当成完整语义消费。
        "depth_truncated": depth_truncated,
    }
    return result


# ---------------------------------------------------------------------------
# preference-aware retrieval
# ---------------------------------------------------------------------------

def preference_rerank(
    candidates: list[dict[str, Any]],
    *,
    weight: float = 0.30,
    top_k: int | None = None,
    owner_id: str | None = None,
    soul_id: str | None = None,
    at: datetime | None = None,
) -> list[dict[str, Any]]:
    """对一次检索的候选列表做 preference-aware 重排（issue #198「检索增强」）。

    ``final = retrieval_score × (1 − weight + weight × preference_score)``

    - 只影响 ``memory_class == 'preference'`` 的候选；非偏好候选乘子恒为
      1.0（语义/知识记忆排序不受偏好通道干扰——偏好驱动的是「该信哪条
      偏好」，不是「知识是否相关」）。
    - ``weight=0`` 时严格恒等（消融基线：关掉偏好通道，同一套数据流）。
    - 偏好候选不在图视图里（刚写还没进可检索集）时乘子按中性 0.5 处理，
      不惩罚也不加成；此时 ``preference_score=None`` 明示「无信号」，
      与「实测恰好 0.5」可区分（telemetry/门控消费方不得混用两者）。
    - 只读重排：**不 bump usage_count、不改任何库内状态**；caller 拿到的
      顺序变了，原始 retrieval_score 字段保留不动，新字段
      ``preference_multiplier`` / ``preference_score`` /
      ``preference_score_final`` 随结果返回。
    """
    if not candidates:
        return []
    pref_ids = [c["capsule_id"] for c in candidates if c.get("memory_class") == "preference"]
    scores: dict[str, float] = {}
    if pref_ids and weight > 0.0:
        graph = load_preference_graph(owner_id=owner_id, soul_id=soul_id)
        nodes = graph.get("nodes") or {}
        wanted = [cid for cid in pref_ids if cid in nodes]
        if wanted:
            computed = compute_preference_scores(
                {"nodes": {cid: nodes[cid] for cid in wanted},
                 "edges": graph.get("edges") or {}},
                at=at,
            )
            scores = {cid: s["score"] for cid, s in computed.items()}

    out = []
    for cap in candidates:
        if cap.get("memory_class") == "preference" and weight > 0.0:
            measured = cap["capsule_id"] in scores
            # 不在图视图（刚写未入可检索集 / 已遗忘等）→ 无信号：乘子按
            # 中性 0.5，但 ``preference_score=None`` 如实区分「没测到」与
            # 「测出来正好 0.5」——telemetry/门控消费方不能把前者当后者。
            ps = scores.get(cap["capsule_id"], 0.5)
            multiplier = (1.0 - weight) + weight * ps
        else:
            ps = None
            measured = False
            multiplier = 1.0
        base = float(cap.get("retrieval_score") or 0.0)
        final = base * multiplier
        cap = dict(cap)
        cap["preference_score_final"] = round(final, 4)
        if cap.get("memory_class") == "preference" and weight > 0.0:
            cap["preference_multiplier"] = round(multiplier, 4)
            cap["preference_score"] = round(ps, 4) if measured else None
        out.append((final, cap))
    out.sort(key=lambda item: (-item[0], item[1]["capsule_id"]))
    ranked = [cap for _, cap in out]
    return ranked[:top_k] if top_k is not None else ranked


def _now_compact() -> str:
    from ..utils.datetime_utils import utc_now_iso_compact

    return utc_now_iso_compact()


__all__ = [
    "EDGE_TYPES",
    "DEFAULT_SCORE_WEIGHTS",
    "GRAPH_LOAD_LIMIT",
    "MAX_CHAIN_DEPTH",
    "load_preference_graph",
    "compute_preference_scores",
    "record_preference_evolution",
    "suggest_active_preference",
    "cascade_forget_preference",
    "preference_rerank",
]
