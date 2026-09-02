"""偏好漂移检测(Preference Drift Detection)— EGPM 演化阶段。

核心思路(对应 WHY_WE_WIN / 算法建议第 3 条):
- 维护**短期偏好**(近窗口内的偏好信号)与**长期偏好**(稳定积累)两幅画像
- 计算同一偏好主题下两幅画像的 Beta 后验均值距离 D = |mean_short − mean_long|
- D > δ 触发 **Drift Event**:说明用户对该主题的偏好正在改变,
  应生成新版本(接 lifecycle 的 supersede 版本链)

设计口径(诚实标注):
- 距离度量用 Beta 后验均值(#167 合并的 preference_confidence),不是词面相似度
- 按 ``content.preference_type`` 分组(偏好主题: beverage / output_format 等)
- 只读检测,不自动改写生命周期 — 漂移事件写入审计日志,版本化由裁决流程触发
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from ..db import get_conn
from .preference_confidence import confidence

logger = logging.getLogger(__name__)

#: 漂移判定阈值:短期与长期后验均值距离超过此值即触发漂移事件
DRIFT_THRESHOLD = 0.25

#: 短期窗口(天):近 N 天写入/召回的偏好算「短期画像」
SHORT_WINDOW_DAYS = 7

#: 参与判定的最小样本量:短期窗口内该主题少于 N 条不报漂移(噪声保护)
MIN_SHORT_SAMPLES = 2

#: 长期画像同样需要最小样本:单条旧记录不能主导「长期偏好」的判定基准
MIN_LONG_SAMPLES = 2


def _parse_ts(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def compute_preference_drift(
    *,
    owner_id: str | None = None,
    soul_id: str | None = None,
    window_days: int = SHORT_WINDOW_DAYS,
    threshold: float = DRIFT_THRESHOLD,
) -> list[dict[str, Any]]:
    """检测偏好漂移,返回漂移事件列表(按漂移幅度降序)。

    每个事件: {preference_type, mean_short, mean_long, distance, short_n, long_n}
    无漂移返回空列表。
    """
    from ..memoryos.lifecycle import retrievable_sql_list

    cutoff_epoch = (
        datetime.now(timezone.utc) - timedelta(days=window_days)
    ).timestamp()

    # 生命周期过滤复用 lifecycle 单一事实源,不与状态机各持一份
    clauses = ["memory_class='preference'",
               f"json_extract(state,'$.lifecycle') IN ({retrievable_sql_list()})"]
    params: list[Any] = []
    if owner_id is not None:
        clauses.append("json_extract(provenance,'$.owner_id')=?")
        params.append(owner_id)
    if soul_id is not None:
        clauses.append("json_extract(provenance,'$.soul_id')=?")
        params.append(soul_id)

    rows = get_conn().execute(
        f"SELECT capsule_id, content, state, created_at FROM memory_capsules_v2 "
        f"WHERE {' AND '.join(clauses)}",
        params,
    ).fetchall()

    # 按 preference_type 分组,拆短期/长期两窗口(epoch 数值比较,不拼字符串)
    groups: dict[str, dict[str, list[dict]]] = {}
    for row in rows:
        state = _load_json(row["state"])
        content = _load_json(row["content"])
        ptype = str(content.get("preference_type") or content.get("topic") or "_default")
        entry = {"state": state, "created_at": row["created_at"]}
        bucket = groups.setdefault(ptype, {"short": [], "long": []})
        created = _parse_ts(row["created_at"])
        if created and created.timestamp() >= cutoff_epoch:
            bucket["short"].append(entry)
        else:
            bucket["long"].append(entry)

    events: list[dict[str, Any]] = []
    for ptype, bucket in groups.items():
        short, long_ = bucket["short"], bucket["long"]
        # 双侧最小样本保护:单条旧记录不能主导「长期画像」
        if len(short) < MIN_SHORT_SAMPLES or len(long_) < MIN_LONG_SAMPLES:
            continue
        mean_short = _group_mean(short)
        mean_long = _group_mean(long_)
        distance = abs(mean_short - mean_long)
        if distance > threshold:
            events.append({
                "preference_type": ptype,
                "mean_short": round(mean_short, 4),
                "mean_long": round(mean_long, 4),
                "distance": round(distance, 4),
                "short_n": len(short),
                "long_n": len(long_),
            })

    events.sort(key=lambda e: e["distance"], reverse=True)
    return events


def _group_mean(entries: list[dict]) -> float:
    """一组偏好 capsule 的 Beta 后验均值的总平均(证据加权)。"""
    if not entries:
        return 0.5
    total_alpha = total_beta = 0.0
    for e in entries:
        c = confidence(e["state"])
        total_alpha += c["alpha"]
        total_beta += c["beta"]
    return total_alpha / (total_alpha + total_beta)


def _load_json(value: Any) -> dict:
    import json

    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return {}
    return {}


__all__ = ["compute_preference_drift", "DRIFT_THRESHOLD", "SHORT_WINDOW_DAYS"]
