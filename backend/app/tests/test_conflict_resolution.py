"""多因子冲突裁决建议测试(#164 A1 建议式)。

锁定行为:
1. 手动配置来源 > 工具结果(权威因子主导)
2. 近期活跃 > 长期未用(recency 因子)
3. 高频 reinforce > 零 reinforce(reinforce 因子)
4. 建议式: auto_execute=False,不触发任何生命周期转移
5. 得分可解释: 返回三因子分解
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.app.memory_runtime.conflict_resolution import (
    score_candidate,
    suggest_conflict_resolution,
)

_NOW = datetime(2026, 9, 2, tzinfo=timezone.utc)


def _cap(cid, *, source="user_input", days_ago=0, usage=0):
    ts = (_NOW - timedelta(days=days_ago)).isoformat()
    return {
        "capsule_id": cid,
        "state": {"last_accessed_at": ts, "usage_count": usage},
        "provenance": {"source": source},
    }


def test_authority_manual_beats_tool():
    manual = _cap("a", source="manual_config", days_ago=30, usage=0)
    tool = _cap("b", source="tool_result", days_ago=0, usage=5)
    # manual 权威 1.0 vs tool 0.2,即便 tool 更新更近
    r = suggest_conflict_resolution(manual, tool)
    assert r["suggested_winner"] == "a"


def test_recency_recent_beats_stale():
    fresh = _cap("a", days_ago=0)
    stale = _cap("b", days_ago=90)
    r = suggest_conflict_resolution(fresh, stale)
    assert r["suggested_winner"] == "a"


def test_reinforce_count_high_beats_zero():
    used = _cap("a", usage=40)
    fresh = _cap("b", usage=0)
    r = suggest_conflict_resolution(used, fresh)
    assert r["suggested_winner"] == "a"


def test_advisory_only_no_auto_execute():
    """硬约束: 建议式裁决绝不自动执行,auto_execute 恒 False。"""
    a = _cap("a", source="manual_config")
    b = _cap("b", source="tool_result")
    r = suggest_conflict_resolution(a, b)
    assert r["auto_execute"] is False
    assert "resolve_conflict" in r["note"]


def test_factors_explainable():
    """返回三因子分解,可解释(答辩演示用)。"""
    a = _cap("a", source="manual_config", days_ago=1, usage=10)
    s = score_candidate(a)
    assert set(s["factors"]) == {"recency", "source_authority", "reinforce_count"}
    assert 0.0 <= s["score"] <= 1.0
    assert s["factors"]["source_authority"] == 1.0


def test_margin_direction():
    """高分者 winner,margin 为正。"""
    a = _cap("a", source="manual_config")
    b = _cap("b", source="tool_result")
    r = suggest_conflict_resolution(a, b)
    assert r["winner_score"] > r["loser_score"]
    assert r["margin"] > 0
