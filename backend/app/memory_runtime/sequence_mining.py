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

"""Pure sequence-based tool preference mining."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Iterable

DEFAULT_WINDOW = 20
DEFAULT_MIN_SUPPORT = 5
DEFAULT_THRESHOLD = 0.6

#: 无法解析时间戳的事件排到最早，视为最旧证据（不参与近期窗口）。
_EPOCH_MIN = datetime.min.replace(tzinfo=timezone.utc)

def _time_key(value: Any) -> datetime:
    """把事件时间戳规整为 **tz-aware UTC**，供排序使用。

    必须统一时区意识：真实事件流里 ``2026-01-01T00:00:00Z``（aware）与
    ``2026-01-01T00:00:00``（naive，历史/本地写入）或缺失 ts 会同时出现，
    直接排序会抛 ``TypeError: can't compare offset-naive and offset-aware
    datetimes``，让整个挖掘调用崩掉而不是降级。naive 时间戳按 UTC 解释，
    不可解析的一律排到最早。
    """
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return _EPOCH_MIN
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

def mine_tool_preferences(sequences: Iterable[dict[str, Any]], *, window: int = DEFAULT_WINDOW,
                          min_support: int = DEFAULT_MIN_SUPPORT,
                          threshold: float = DEFAULT_THRESHOLD) -> list[dict[str, Any]]:
    if window <= 0 or min_support <= 0 or not 0 <= threshold <= 1:
        return []
    events = [e for e in sequences if isinstance(e, dict) and e.get("scene") and e.get("tool")]
    events.sort(key=lambda e: _time_key(e.get("ts")))
    scene_counts: dict[str, int] = {}
    pair_counts: dict[tuple[str, str], int] = {}
    for event in events[-window:]:
        scene, tool = str(event["scene"]), str(event["tool"])
        scene_counts[scene] = scene_counts.get(scene, 0) + 1
        pair = (scene, tool)
        pair_counts[pair] = pair_counts.get(pair, 0) + 1
    result = []
    for (scene, tool), support in pair_counts.items():
        confidence = (support + 1) / (scene_counts[scene] + 2)
        if support >= min_support and confidence >= threshold:
            result.append({"subject": scene, "predicate": "prefers_tool", "object": tool,
                           "confidence": confidence, "support": support, "source": "sequence_mining"})
    return result

__all__ = ["mine_tool_preferences", "DEFAULT_WINDOW", "DEFAULT_MIN_SUPPORT", "DEFAULT_THRESHOLD"]
