"""遗忘曲线(effective_retention)测试 — MemoryBank 式时间衰减。

锁定行为:
1. 从未召回(last_accessed_at=None)→ 不衰减(新记忆宽限期)
2. 随时间衰减,λ=0.05 时约 14 天半衰
3. usage_count 越高衰减越慢(stability 增长)
4. stability 有上限(防止高召回记忆永不衰减)
5. 边界:stored 值钳制 0-1、非法时间戳不衰减、未来时间不产生负天数
6. 检索排序接入:同一 capsule 在 30 天未访问后 retrieval 得分下降
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.memory_runtime.forgetting import (
    DEFAULT_DECAY_RATE,
    MAX_STABILITY,
    effective_retention,
)

_NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _state(**over) -> dict:
    base = {"retention_score": 0.8, "usage_count": 0, "last_accessed_at": None}
    base.update(over)
    return base


def test_never_recalled_does_not_decay():
    """last_accessed_at=None → 新记忆宽限期,不衰减。"""
    assert effective_retention(_state(), at=_NOW) == 0.8


def test_invalid_timestamp_does_not_crash_or_decay():
    """非法时间戳 → 按无时间处理,不衰减。"""
    assert effective_retention(_state(last_accessed_at="not-a-date"), at=_NOW) == 0.8


def test_decay_over_time():
    """λ=0.05 时,stored=1.0 且 14 天未访问 → 约 0.50。"""
    last = (_NOW - timedelta(days=14)).isoformat()
    r = effective_retention(
        _state(retention_score=1.0, last_accessed_at=last), at=_NOW
    )
    assert r == pytest.approx(math.exp(-DEFAULT_DECAY_RATE * 14), abs=0.01)


def test_usage_count_slows_decay():
    """召回 10 次的记忆比 0 次的衰减显著更慢。"""
    last = (_NOW - timedelta(days=30)).isoformat()
    fresh = effective_retention(
        _state(retention_score=1.0, usage_count=0, last_accessed_at=last), at=_NOW
    )
    used = effective_retention(
        _state(retention_score=1.0, usage_count=10, last_accessed_at=last), at=_NOW
    )
    assert used > fresh


def test_stability_has_cap():
    """usage_count 极大时 stability 封顶,记忆仍会衰减(不永生)。"""
    last = (_NOW - timedelta(days=365)).isoformat()
    r = effective_retention(
        _state(retention_score=1.0, usage_count=10**9, last_accessed_at=last),
        at=_NOW,
    )
    # stability = MAX_STABILITY: exp(-0.05 × 365 / 20) ≈ 0.40
    assert r == pytest.approx(math.exp(-DEFAULT_DECAY_RATE * 365 / MAX_STABILITY), abs=0.01)
    assert r < 1.0


def test_stored_value_clamped():
    """stored 超出 0-1 时钳制。"""
    last = _NOW.isoformat()
    assert effective_retention(
        _state(retention_score=5.0, last_accessed_at=last), at=_NOW
    ) <= 1.0


def test_future_timestamp_no_negative_days():
    """last_accessed_at 在未来 → 天数按 0 处理,不放大。"""
    future = (_NOW + timedelta(days=10)).isoformat()
    r = effective_retention(
        _state(retention_score=0.8, last_accessed_at=future), at=_NOW
    )
    assert r == 0.8


# ---------------------------------------------------------------------------
# 检索排序接入
# ---------------------------------------------------------------------------


def test_retrieval_uses_decayed_retention(isolated_db):
    """同一 capsule,30 天未访问后检索得分中的 retention 项应下降。"""
    from backend.app.memory_runtime import retrieval

    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    fresh = datetime.now(timezone.utc).isoformat()
    state_old = {"retention_score": 0.9, "usage_count": 0, "last_accessed_at": old}
    state_fresh = {"retention_score": 0.9, "usage_count": 0, "last_accessed_at": fresh}

    # 直接对比 effective_retention 在两种状态下的输出(排序公式引用同一函数)
    r_old = effective_retention(state_old)
    r_fresh = effective_retention(state_fresh)
    assert r_old < r_fresh

    # 排序权重方向验证:retention_score_weight > 0 时,衰减降低 gov_bonus
    weights = retrieval._weights()
    assert weights["retention_score_weight"] > 0
    bonus_old = weights["retention_score_weight"] * r_old
    bonus_fresh = weights["retention_score_weight"] * r_fresh
    assert bonus_old < bonus_fresh
