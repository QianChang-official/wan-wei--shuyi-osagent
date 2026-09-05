"""TKE Knowledge Timeline 测试（issue #204 验收：时间轴聚合 / 历史回放）。

锁定行为：
1. ``knowledge_timeline``：演化链 + 账本事件 + 双时态区间聚合为升序事件流。
2. 事件覆盖完整生命周期：created（write）→ evolution_edge（supersedes 落边）
   → lifecycle_transition（旧版本 deprecated）。
3. 链成员带 valid_time 与 transaction_time 双时态摘要。
4. as-of 回放演示点：链根的 valid_from（或 created_at）时刻的 active。
5. 未知 op_type 原样透传（不吞新事件类型）。
"""
from __future__ import annotations

from backend.app.memory_runtime import knowledge_evolution as ke
from backend.app.memory_runtime import temporal_knowledge as tk
from backend.app.memory_runtime.capsule_store import write_capsule


def _know(text: str) -> str:
    return write_capsule(memory_class="knowledge", content={"text": text})["capsule_id"]


def _build_chain() -> tuple[str, str, str]:
    """三代演化链 Firefox → Chrome → Edge（带 valid_time）。"""
    ff = _know("默认浏览器 = Firefox")
    ch = _know("默认浏览器 = Chrome")
    edge = _know("默认浏览器 = Edge")
    tk.set_valid_time(ff, valid_from="2025-01-01T00:00:00Z", valid_until="2025-09-01T00:00:00Z")
    tk.set_valid_time(ch, valid_from="2025-09-01T00:00:00Z", valid_until="2026-05-01T00:00:00Z")
    tk.set_valid_time(edge, valid_from="2026-05-01T00:00:00Z")
    ke.evolve_knowledge(ch, ff)
    ke.evolve_knowledge(edge, ch)
    return ff, ch, edge


def test_timeline_aggregates_chain_events_and_intervals(isolated_db):
    ff, ch, edge = _build_chain()

    tl = tk.knowledge_timeline(edge)
    # 链三代，从最新回溯。
    assert [c["capsule_id"] for c in tl["chain"]] == [edge, ch, ff]
    # 链成员带双时态摘要。
    by_id = {c["capsule_id"]: c for c in tl["chain"]}
    assert by_id[ff]["valid_from"] is not None and by_id[ff]["valid_until"] is not None
    assert by_id[edge]["valid_until"] is None  # 无界
    assert by_id[ch]["knowledge_version"] == 2
    assert by_id[ff]["lifecycle"] == "deprecated"
    assert by_id[edge]["lifecycle"] == "active"


def test_timeline_events_sorted_and_complete(isolated_db):
    ff, ch, edge = _build_chain()

    tl = tk.knowledge_timeline(edge)
    events = tl["events"]
    # 升序（ISO 字符串字典序 = 时间序）。
    ats = [e["at"] for e in events if e.get("at")]
    assert ats == sorted(ats)

    # 事件类型覆盖：三代的 created + 两条演化边 + 两次转移。
    kinds = [e["event"] for e in events]
    assert kinds.count("created") >= 3
    assert kinds.count("evolution_edge") == 2
    assert "lifecycle_transition" in kinds


def test_timeline_events_reference_chain_members(isolated_db):
    ff, ch, edge = _build_chain()
    tl = tk.knowledge_timeline(edge)
    member_ids = {ff, ch, edge}
    for e in tl["events"]:
        assert e["capsule_id"] in member_ids  # 不混入链外胶囊的事件


def test_timeline_as_of_demo(isolated_db):
    """as-of 演示点：链根的 valid_from 时刻，active 应是链根本身。"""
    ff, ch, edge = _build_chain()
    tl = tk.knowledge_timeline(edge)
    demo = tl["as_of_demo"]
    assert demo is not None
    # edge 的 valid_from = 2026-05-01，该时刻 active 是 edge。
    assert demo["active"]["capsule_id"] == edge


def test_timeline_unknown_ops_passthrough(isolated_db):
    """未知 op_type 原样透传（未来新增账目类型不会在时间轴上消失）。"""
    ff, ch, edge = _build_chain()  # noqa: F841 —— 链成员供可读性
    from backend.app.memoryos.governance import append_ledger

    append_ledger(
        op_type="future_op_type", capsule_id=edge, actor="test", reason="注入"
    )
    tl2 = tk.knowledge_timeline(edge)
    kinds = [e["event"] for e in tl2["events"]]
    assert "future_op_type" in kinds


def test_timeline_single_capsule_no_chain(isolated_db):
    """无演化链的知识也有时间轴（自己的账本事件）。"""
    k = _know("孤立知识")
    tl = tk.knowledge_timeline(k)
    assert [c["capsule_id"] for c in tl["chain"]] == [k]
    assert any(e["event"] == "created" for e in tl["events"])


def test_timeline_missing_capsule_raises(isolated_db):
    import pytest as _pytest

    with _pytest.raises(KeyError):
        tk.knowledge_timeline("cap_missing")


# ---------------------------------------------------------------------------
# 历史回放（timeline + as-of 组合）
# ---------------------------------------------------------------------------

def test_history_replay_across_generations(isolated_db):
    """回放：沿时间轴在三个代际时刻各问一次 as-of，答案随时间切换。"""
    ff, ch, edge = _build_chain()
    ids = [ff, ch, edge]

    answers = [
        tk.knowledge_as_of(ids, at="2025-05-01T00:00:00Z")["active"]["text"],
        tk.knowledge_as_of(ids, at="2025-12-01T00:00:00Z")["active"]["text"],
        tk.knowledge_as_of(ids, at="2026-08-01T00:00:00Z")["active"]["text"],
    ]
    assert answers == [
        "默认浏览器 = Firefox",
        "默认浏览器 = Chrome",
        "默认浏览器 = Edge",
    ]
