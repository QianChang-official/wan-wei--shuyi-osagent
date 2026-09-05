"""TKE 双时态测试（issue #204 验收：valid_time 区间 / as-of 查询 / 区间判定）。

锁定行为：
1. ``set_valid_time``：写入/更新区间、显式清空、非法时间与区间自洽 422。
2. as-of ``truth`` 模式：valid_time 判真；延迟导入场景（今天录入历史真值）
   可回答过去时刻；命中者 recorded_at 如实暴露「事后导入」。
3. as-of ``belief`` 模式：transaction_time 双过滤——今天导入的知识在历史
   时刻上系统不认识（active=None）。
4. 区间判定：不重叠 → evolution（不再误报冲突）；重叠 → temporal 冲突。
5. ``detect_knowledge_conflicts`` 集成：有显式区间的先后真值不再进冲突
   命中（detector 标注 knowledge_tke_v1）。
"""
from __future__ import annotations

import pytest

from backend.app.memory_runtime import knowledge_evolution as ke
from backend.app.memory_runtime import temporal_knowledge as tk
from backend.app.memory_runtime.capsule_store import get_capsule, write_capsule


def _know(text: str) -> str:
    return write_capsule(memory_class="knowledge", content={"text": text})["capsule_id"]


# ---------------------------------------------------------------------------
# set_valid_time
# ---------------------------------------------------------------------------

def test_set_valid_time_roundtrip(isolated_db):
    cid = _know("默认浏览器 = Firefox")
    tk.set_valid_time(cid, valid_from="2025-01-01T00:00:00Z", valid_until="2026-01-01T00:00:00Z")
    vf, vu = tk.get_valid_time(get_capsule(cid))
    assert vf is not None and vf.year == 2025 and vf.month == 1
    assert vu is not None and vu.year == 2026

    # 更新单端点：另一端不动。
    tk.set_valid_time(cid, valid_until="2026-06-01T00:00:00Z")
    vf2, vu2 = tk.get_valid_time(get_capsule(cid))
    assert vf2 == vf
    assert vu2.year == 2026 and vu2.month == 6


def test_set_valid_time_explicit_clear(isolated_db):
    cid = _know("知识")
    tk.set_valid_time(cid, valid_from="2025-01-01T00:00:00Z", valid_until="2026-01-01T00:00:00Z")
    # 空字符串 = 显式清空该端点（无界）。
    tk.set_valid_time(cid, valid_until="")
    vf, vu = tk.get_valid_time(get_capsule(cid))
    assert vf is not None
    assert vu is None


def test_set_valid_time_rejects_bad_time(isolated_db):
    cid = _know("知识")
    with pytest.raises(ValueError, match="valid_from"):
        tk.set_valid_time(cid, valid_from="not-a-time")


def test_set_valid_time_rejects_inverted_interval(isolated_db):
    cid = _know("知识")
    with pytest.raises(ValueError, match="区间非法"):
        tk.set_valid_time(
            cid,
            valid_from="2026-01-01T00:00:00Z",
            valid_until="2025-01-01T00:00:00Z",
        )


def test_set_valid_time_requires_knowledge_class(isolated_db):
    pref = write_capsule(
        memory_class="preference", content={"subject": "e", "statement": "喜欢 X"}
    )["capsule_id"]
    with pytest.raises(ValueError, match="knowledge"):
        tk.set_valid_time(pref, valid_from="2025-01-01T00:00:00Z")


def test_set_valid_time_missing_capsule(isolated_db):
    with pytest.raises(KeyError):
        tk.set_valid_time("cap_missing", valid_from="2025-01-01T00:00:00Z")


# ---------------------------------------------------------------------------
# as-of：truth（世界真值，延迟导入场景）
# ---------------------------------------------------------------------------

def test_as_of_truth_delayed_import(isolated_db):
    """立身场景：今天导入历史真值，过去时刻仍可按世界真值回答。

    按 created_at 排序会把「今天导入的旧真值」当最新——truth 模式按
    valid_time 判真，两个方向都答对，且 recorded_at 暴露事后导入。
    """
    ff = _know("默认浏览器 = Firefox")
    ch = _know("默认浏览器 = Chrome")
    tk.set_valid_time(ff, valid_from="2025-01-01T00:00:00Z", valid_until="2026-01-01T00:00:00Z")
    tk.set_valid_time(ch, valid_from="2026-01-01T00:00:00Z")

    r_then = tk.knowledge_as_of([ff, ch], at="2025-07-01T00:00:00Z")
    assert r_then["active"]["text"] == "默认浏览器 = Firefox"
    # 事后导入可辨识：记录时间是今天（今天 > 2025-07）。
    assert str(r_then["active"]["recorded_at"])[:4] == "2026"

    r_now = tk.knowledge_as_of([ff, ch], at="2026-06-01T00:00:00Z")
    assert r_now["active"]["text"] == "默认浏览器 = Chrome"


def test_as_of_truth_half_open_interval(isolated_db):
    """区间半开：at == valid_until 时旧知识已失效、新知识生效。"""
    a = _know("版本 A")
    b = _know("版本 B")
    tk.set_valid_time(a, valid_from="2025-01-01T00:00:00Z", valid_until="2026-01-01T00:00:00Z")
    tk.set_valid_time(b, valid_from="2026-01-01T00:00:00Z")

    boundary = tk.knowledge_as_of([a, b], at="2026-01-01T00:00:00Z")
    assert boundary["active"]["text"] == "版本 B"  # A 的 until 是开区间端点


def test_as_of_truth_none_when_no_coverage(isolated_db):
    a = _know("知识")
    tk.set_valid_time(a, valid_from="2025-01-01T00:00:00Z", valid_until="2025-06-01T00:00:00Z")
    r = tk.knowledge_as_of([a], at="2026-01-01T00:00:00Z")
    assert r["active"] is None
    assert r["rejected_interval"] == [
        {"capsule_id": a, "valid_from": "2025-01-01T00:00:00+00:00", "valid_until": "2025-06-01T00:00:00+00:00"}
    ]


def test_as_of_unknown_ids_reported(isolated_db):
    r = tk.knowledge_as_of(["cap_missing"], at="2025-01-01T00:00:00Z")
    assert r["active"] is None
    assert r["unknown_ids"] == ["cap_missing"]


def test_as_of_invalid_time_rejected(isolated_db):
    with pytest.raises(ValueError, match="at"):
        tk.knowledge_as_of([_know("知识")], at="not-a-time")


def test_as_of_invalid_mode_rejected(isolated_db):
    with pytest.raises(ValueError, match="mode"):
        tk.knowledge_as_of([_know("知识")], at="2025-01-01T00:00:00Z", mode="bogus")


# ---------------------------------------------------------------------------
# as-of：belief（系统当时认知，严格双时态）
# ---------------------------------------------------------------------------

def test_as_of_belief_strict_bitemporal(isolated_db):
    """belief：今天导入的知识在历史时刻上系统并不认识。"""
    ff = _know("默认浏览器 = Firefox")
    tk.set_valid_time(ff, valid_from="2025-01-01T00:00:00Z")

    r = tk.knowledge_as_of([ff], at="2025-07-01T00:00:00Z", mode="belief")
    assert r["active"] is None  # created_at(今天) > at(2025-07)
    assert r["rejected_not_recorded"] == [ff]


def test_as_of_belief_knows_what_existed(isolated_db):
    """belief：created_at 之前的时刻（如今天晚些）系统认识。"""
    k = _know("知识")
    tk.set_valid_time(k, valid_from="2025-01-01T00:00:00Z")
    # at = 明天（晚于 created_at 且 valid_from 之后）→ 系统已认识且为真。
    from datetime import datetime, timedelta, timezone

    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    r = tk.knowledge_as_of([k], at=tomorrow, mode="belief")
    assert r["active"] is not None
    assert r["active"]["capsule_id"] == k


# ---------------------------------------------------------------------------
# 区间判定（时效冲突升级）
# ---------------------------------------------------------------------------

def test_interval_non_overlap_is_evolution(isolated_db):
    """先后真值区间不重叠 → 演化，不是冲突。"""
    old = _know("默认浏览器 = Firefox")
    new = _know("默认浏览器 = Chrome")
    tk.set_valid_time(old, valid_from="2025-01-01T00:00:00Z", valid_until="2026-01-01T00:00:00Z")
    tk.set_valid_time(new, valid_from="2026-01-01T00:00:00Z")

    rel = tk.classify_temporal_relation(get_capsule(new), get_capsule(old))
    assert rel is not None
    assert rel["relation"] == "evolution"
    assert "演化" in rel["evidence"]


def test_interval_overlap_is_conflict(isolated_db):
    """区间重叠 → 真 temporal 冲突（两段真值声称覆盖同一时段）。"""
    a = _know("服务器端口 = 8080")
    b = _know("服务器端口 = 9000")
    tk.set_valid_time(a, valid_from="2025-01-01T00:00:00Z", valid_until="2026-06-01T00:00:00Z")
    tk.set_valid_time(b, valid_from="2025-06-01T00:00:00Z", valid_until="2026-12-01T00:00:00Z")

    rel = tk.classify_temporal_relation(get_capsule(b), get_capsule(a))
    assert rel is not None
    assert rel["relation"] == "conflict"
    assert rel["type"] == "temporal"
    assert "重叠" in rel["evidence"]


def test_no_interval_falls_back_to_markers(isolated_db):
    """无显式 valid_from → 区间证据不足，回落 None（词面口径接管）。"""
    a = _know("端口 = 8080")
    b = _know("端口 = 9000")
    assert tk.classify_temporal_relation(get_capsule(b), get_capsule(a)) is None


def test_detect_conflicts_interval_upgrade(isolated_db):
    """集成：有显式区间的先后真值不再误报为冲突命中。"""
    old = _know("默认浏览器 = Firefox")  # noqa: F841 —— 语义标签
    new = _know("默认浏览器 = Chrome")
    tk.set_valid_time(old, valid_from="2025-01-01T00:00:00Z", valid_until="2026-01-01T00:00:00Z")
    tk.set_valid_time(new, valid_from="2026-01-01T00:00:00Z")

    # 区间不重叠 → 演化 → 不进冲突命中（词面「=Firefox vs =Chrome」本是 fact 冲突）。
    hits = ke.detect_knowledge_conflicts(new)
    assert [h["capsule_id"] for h in hits if h["capsule_id"] == old] == []


def test_detect_conflicts_overlap_reported_as_temporal(isolated_db):
    """集成：区间重叠按 temporal 冲突计入，detector 标注 tke 口径。"""
    a = _know("服务器端口 = 8080")
    b = _know("服务器端口 = 9000")
    tk.set_valid_time(a, valid_from="2025-01-01T00:00:00Z", valid_until="2026-06-01T00:00:00Z")
    tk.set_valid_time(b, valid_from="2025-06-01T00:00:00Z", valid_until="2026-12-01T00:00:00Z")

    hits = ke.detect_knowledge_conflicts(b)
    hit_a = [h for h in hits if h["capsule_id"] == a]
    assert len(hit_a) == 1
    assert hit_a[0]["type"] == "temporal"
    assert hit_a[0]["detector"] == "knowledge_tke_v1"
    assert "重叠" in hit_a[0]["evidence"]


def test_detect_conflicts_no_interval_unchanged(isolated_db):
    """无显式区间的行为与 #202 完全一致（detector 仍是 knowledge_v1）。"""
    _know("默认浏览器 = Firefox")  # 冲突对面的 active 旧知识
    new = _know("默认浏览器 = Chrome")
    hits = ke.detect_knowledge_conflicts(new)
    assert len(hits) == 1
    assert hits[0]["detector"] == "knowledge_v1"
    assert hits[0]["type"] == "fact"
