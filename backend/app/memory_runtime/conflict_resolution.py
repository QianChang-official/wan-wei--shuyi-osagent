"""多因子冲突裁决建议(对应 #164 A1)— 建议式,不自动覆盖。

设计约束(与治理底线对齐):
- lifecycle 硬规则「conflicted 必须显式裁决,不自动覆盖」不可破坏。
- 因此本模块只**计算多因子得分并推荐赢家**,写入审计;实际生命周期
  转移仍由 ``resolve_conflict(actor='human')`` 显式确认。算法创新
  (多因子融合)与治理底线(不自动覆盖)由此兼得。

三因子(权重进 tuning 可调,呼应 #118 可调权重键的口径):
1. recency — 复用 #162 遗忘曲线的时间衰减(effective_retention 同源)
2. source_authority — 来源可信度分级: 手动配置 > 显式确认 > 行为推断 > 工具结果
3. reinforce_count — 复用 evolution 的 usage_count(被采纳次数)
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

#: 来源可信度分级(数值越大越可信)
SOURCE_AUTHORITY = {
    "manual_config": 1.0,
    "user_input": 0.8,       # 显式确认
    "eval": 0.6,
    "cross_scene_trace": 0.4,  # 行为推断
    "tool_result": 0.2,      # 工具结果
}

#: 三因子默认权重(可调)
DEFAULT_WEIGHTS = {
    "recency": 0.35,
    "source_authority": 0.40,
    "reinforce_count": 0.25,
}


def _parse_ts(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _recency_factor(state: dict[str, Any], *, at: datetime) -> float:
    """时间新近性 0-1: 用与遗忘曲线同族的指数衰减,半衰期 30 天。"""
    last = _parse_ts(state.get("last_accessed_at") or state.get("updated_at"))
    if last is None:
        return 0.5
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    days = max(0.0, (at - last).total_seconds() / 86400.0)
    return math.exp(-0.023 * days)  # ln2/30 ≈ 0.023,30 天半衰


def _authority_factor(provenance: dict[str, Any]) -> float:
    src = str(provenance.get("source") or provenance.get("source_type") or "")
    return SOURCE_AUTHORITY.get(src, 0.5)


def _reinforce_factor(state: dict[str, Any]) -> float:
    """reinforce 次数归一: log 压缩,10 次≈0.7,50 次≈0.9。"""
    n = max(0, int(state.get("usage_count", 0) or 0))
    return math.log1p(n) / math.log1p(50)


def score_candidate(
    capsule: dict[str, Any],
    *,
    weights: dict[str, float] | None = None,
    at: datetime | None = None,
) -> dict[str, Any]:
    """对一条冲突候选计算多因子得分。返回得分与各因子分解(可解释)。"""
    w = weights or DEFAULT_WEIGHTS
    now = at or datetime.now(timezone.utc)
    state = capsule.get("state") or {}
    prov = capsule.get("provenance") or {}
    parts = {
        "recency": _recency_factor(state, at=now),
        "source_authority": _authority_factor(prov),
        "reinforce_count": _reinforce_factor(state),
    }
    score = sum(w[k] * parts[k] for k in parts)
    return {"score": round(score, 4), "factors": {k: round(v, 4) for k, v in parts.items()}}


def suggest_conflict_resolution(
    winner_candidate: dict[str, Any],
    loser_candidate: dict[str, Any],
    *,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """对一对冲突候选给出建议赢家。**只建议,不执行转移。**

    返回: 推荐方、双方得分、各因子分解、推荐理由。供人工/确认流程参考,
    实际裁决仍走 ``lifecycle.resolve_conflict``。
    """
    a = score_candidate(winner_candidate, weights=weights)
    b = score_candidate(loser_candidate, weights=weights)
    a_id = winner_candidate.get("capsule_id")
    b_id = loser_candidate.get("capsule_id")
    if a["score"] >= b["score"]:
        winner, loser, ws, ls = a_id, b_id, a, b
    else:
        winner, loser, ws, ls = b_id, a_id, b, a
    return {
        "suggested_winner": winner,
        "suggested_loser": loser,
        "winner_score": ws["score"],
        "loser_score": ls["score"],
        "margin": round(ws["score"] - ls["score"], 4),
        "winner_factors": ws["factors"],
        "loser_factors": ls["factors"],
        "auto_execute": False,
        "note": "建议式裁决: 需 resolve_conflict(actor='human') 显式确认才生效",
    }


__all__ = ["suggest_conflict_resolution", "score_candidate", "SOURCE_AUTHORITY", "DEFAULT_WEIGHTS"]
