"""偏好漂移检测测试。

锁定行为:
1. 短期与长期画像一致 → 无漂移
2. 短期偏好与长期相反 → 漂移事件(distance > 阈值)
3. 样本量不足(MIN_SHORT_SAMPLES)→ 不报漂移(噪声保护)
4. 无长期画像(全新主题)→ 不报漂移
5. 不同 preference_type 分组独立判定
6. scope 隔离:owner/soul 过滤
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.app.memory_runtime.preference_drift import compute_preference_drift


def _write_pref(write_capsule, ptype: str, days_ago: int, reinforce_n: int = 0):
    """写入一条 preference capsule,可选 reinforce n 次抬 alpha。"""
    r = write_capsule(
        memory_class="preference",
        content={"preference_type": ptype, "statement": f"{ptype} 偏好陈述"},
    )
    cid = r["capsule_id"]
    # 手工把 created_at 拨到 days_ago 天前(控制短期/长期窗口归属)
    from backend.app.db import get_conn

    past = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    get_conn().execute(
        "UPDATE memory_capsules_v2 SET created_at=? WHERE capsule_id=?", (past, cid)
    )
    get_conn().commit()
    # reinforce n 次(提升 alpha → 后验均值升高)
    if reinforce_n:
        from backend.app.memory_runtime import evolution

        for _ in range(reinforce_n):
            evolution.reinforce(cid, amount=0.05)
    return cid


def test_no_drift_when_short_long_agree(isolated_db):
    from backend.app.memory_runtime.capsule_store import write_capsule

    # 长期: 强正向(高 alpha); 短期: 同样正向
    _write_pref(write_capsule, "beverage", days_ago=30, reinforce_n=8)
    _write_pref(write_capsule, "beverage", days_ago=20, reinforce_n=8)
    _write_pref(write_capsule, "beverage", days_ago=1, reinforce_n=8)
    _write_pref(write_capsule, "beverage", days_ago=0, reinforce_n=8)

    events = compute_preference_drift()
    assert events == []


def test_drift_detected_when_short_reverses(isolated_db):
    """长期强正向,短期新信号反向(不 reinforce,后验均值回落)→ 漂移。"""
    from backend.app.memory_runtime.capsule_store import write_capsule

    # 长期画像: 4 条强正向
    for d in (40, 35, 30, 25):
        _write_pref(write_capsule, "beverage", days_ago=d, reinforce_n=10)
    # 短期画像: 2 条零强化(先验 mean≈0.5,显著低于长期的 ~0.85)
    _write_pref(write_capsule, "beverage", days_ago=1, reinforce_n=0)
    _write_pref(write_capsule, "beverage", days_ago=0, reinforce_n=0)

    events = compute_preference_drift()
    assert len(events) == 1
    assert events[0]["preference_type"] == "beverage"
    assert events[0]["mean_short"] < events[0]["mean_long"]
    assert events[0]["distance"] > 0.25


def test_insufficient_short_samples_no_drift(isolated_db):
    """短期只有 1 条(< MIN_SHORT_SAMPLES=2)→ 不报漂移。"""
    from backend.app.memory_runtime.capsule_store import write_capsule

    for d in (40, 30):
        _write_pref(write_capsule, "beverage", days_ago=d, reinforce_n=10)
    _write_pref(write_capsule, "beverage", days_ago=0, reinforce_n=0)

    assert compute_preference_drift() == []


def test_insufficient_long_samples_no_drift(isolated_db):
    """长期只有 1 条(< MIN_LONG_SAMPLES=2)→ 单条旧记录不能主导判定基准。"""
    from backend.app.memory_runtime.capsule_store import write_capsule

    _write_pref(write_capsule, "beverage", days_ago=40, reinforce_n=10)
    _write_pref(write_capsule, "beverage", days_ago=0, reinforce_n=0)
    _write_pref(write_capsule, "beverage", days_ago=1, reinforce_n=0)

    assert compute_preference_drift() == []


def test_no_long_profile_no_drift(isolated_db):
    """全新主题(无长期画像)→ 不报漂移。"""
    from backend.app.memory_runtime.capsule_store import write_capsule

    _write_pref(write_capsule, "newtopic", days_ago=1)
    _write_pref(write_capsule, "newtopic", days_ago=0)

    assert compute_preference_drift() == []


def test_groups_independent(isolated_db):
    """不同 preference_type 独立判定,互不干扰。"""
    from backend.app.memory_runtime.capsule_store import write_capsule

    # beverage: 有漂移
    for d in (40, 30):
        _write_pref(write_capsule, "beverage", days_ago=d, reinforce_n=10)
    _write_pref(write_capsule, "beverage", days_ago=0, reinforce_n=0)
    _write_pref(write_capsule, "beverage", days_ago=1, reinforce_n=0)
    # format: 无漂移(短期长期一致)
    for d in (40, 30, 1, 0):
        _write_pref(write_capsule, "format", days_ago=d, reinforce_n=8)

    events = compute_preference_drift()
    types = {e["preference_type"] for e in events}
    assert "beverage" in types
    assert "format" not in types
