"""MemoryBank 式遗忘曲线 — 时间衰减的只读计算。

设计口径(诚实标注):
- **只读**:衰减在读取时计算,不改写存储的 ``retention_score`` 原始值。
  审计侧永远能看到未衰减的原始分与当时的计算输入。
- **公式**: ``effective = stored × exp(-λ × days / stability)``,
  ``stability = 1 + ln(1 + usage_count)`` — MemoryBank(AAAI 2024)
  遗忘曲线的工程化变体:召回越多的记忆衰减越慢。
- **接入点**:检索排序(retention_score_weight 项)与健康面板。
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from ..utils.datetime_utils import utc_now

#: 基础衰减率 λ(每天)。λ=0.05 时,从未被召回的记忆约 14 天后
#: retention 降至原始值的 50%(exp(-0.05×14)≈0.50)。
DEFAULT_DECAY_RATE = 0.05

#: stability 上限:召回次数再多的记忆,衰减速率也不能无限放缓,
#: 否则 usage_count 大的记忆实际上永不衰减,遗忘曲线失去意义。
MAX_STABILITY = 20.0


def _parse_ts(value: Any) -> datetime | None:
    """解析 ISO 时间戳;非法输入返回 None(调用方按 0 天处理)。"""
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def effective_retention(
    state: dict[str, Any],
    *,
    at: datetime | None = None,
    decay_rate: float = DEFAULT_DECAY_RATE,
) -> float:
    """计算考虑时间衰减后的有效 retention_score(0.0-1.0)。

    ``state`` 取 capsule 的 state 字典(含 retention_score / usage_count /
    last_accessed_at)。缺失字段按保守默认处理:无时间戳 → 不衰减(视为
    刚写入,避免新记忆被误伤)。
    """
    stored = float(state.get("retention_score", 0.5) or 0.0)
    stored = max(0.0, min(1.0, stored))

    last = _parse_ts(state.get("last_accessed_at"))
    if last is None:
        # 从未被召回过:以创建时间不可知为由,不衰减(新记忆宽限期)
        return stored

    now = at or utc_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    days = max(0.0, (now - last).total_seconds() / 86400.0)

    usage = max(0, int(state.get("usage_count", 0) or 0))
    stability = min(MAX_STABILITY, 1.0 + math.log1p(usage))

    decayed = stored * math.exp(-decay_rate * days / stability)
    return round(max(0.0, min(1.0, decayed)), 4)


__all__ = ["DEFAULT_DECAY_RATE", "MAX_STABILITY", "effective_retention"]
