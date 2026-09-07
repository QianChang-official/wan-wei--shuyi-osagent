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

from backend.app.memory_runtime.sequence_mining import mine_tool_preferences
from backend.app.memory_runtime.policy_gate import evaluate_preference_candidate

def _events(scene, tool, n):
    return [{"scene": scene, "tool": tool, "ts": f"2026-01-01T00:00:{i:02d}"} for i in range(n)]

def test_recall_and_low_frequency_filter():
    rows = mine_tool_preferences(_events("build", "compiler", 6) + _events("build", "search", 2), window=20, min_support=5)
    assert rows and rows[0]["object"] == "compiler"

def test_threshold_and_support_boundaries():
    assert mine_tool_preferences(_events("x", "a", 4), min_support=5) == []
    assert mine_tool_preferences(_events("x", "a", 6) + _events("x", "b", 4), threshold=.7, min_support=5) == []
    assert mine_tool_preferences(_events("x", "a", 6) + _events("x", "b", 4), threshold=.55, min_support=5)

def test_dedup_and_reinforcement_confidence_monotonic():
    one = mine_tool_preferences(_events("x", "a", 5), min_support=1)[0]
    two = mine_tool_preferences(_events("x", "a", 10), min_support=1)[0]
    assert two["support"] > one["support"] and two["confidence"] >= one["confidence"]

def test_sequence_source_always_requires_confirmation():
    result = evaluate_preference_candidate({"subject": "x", "predicate": "prefers_tool", "object": "a", "source": "sequence_mining"})
    assert result["requires_confirmation"] is True

def test_empty_and_unsorted_timestamps_tolerated():
    assert mine_tool_preferences([]) == []
    assert len(mine_tool_preferences([{"scene": "x", "tool": "a", "ts": "bad"}] * 5, min_support=5)) == 1


def test_mixed_timezone_awareness_does_not_crash():
    """aware / naive / 不可解析时间戳混在同一事件流里也不能炸。

    统一按 UTC 归一前，排序会抛 TypeError（offset-naive vs offset-aware）。
    """
    events = [
        {"scene": "x", "tool": "a", "ts": "2026-01-01T00:00:00Z"},
        {"scene": "x", "tool": "a", "ts": "2026-01-01T00:00:01"},
        {"scene": "x", "tool": "a", "ts": "2026-01-01T08:00:02+08:00"},
        {"scene": "x", "tool": "a", "ts": None},
        {"scene": "x", "tool": "a", "ts": "bad"},
    ]
    rows = mine_tool_preferences(events, min_support=5)
    assert rows and rows[0]["support"] == 5


def test_window_keeps_most_recent_events_across_timezones():
    """窗口截取按归一后的真实时序，跨时区表示不影响先后。"""
    old = [{"scene": "x", "tool": "old", "ts": "2026-01-01T00:00:00Z"} for _ in range(3)]
    # 同一瞬间的 +08:00 表示晚于上面 8 小时，应被视为更近的事件。
    recent = [{"scene": "x", "tool": "new", "ts": "2026-01-01T12:00:00+08:00"} for _ in range(3)]
    rows = mine_tool_preferences(old + recent, window=3, min_support=3)
    assert [r["object"] for r in rows] == ["new"]

