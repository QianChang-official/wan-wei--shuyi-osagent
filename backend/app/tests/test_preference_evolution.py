"""偏好演化机制测试（issue #198 验收：演化 / 版本链 / 冲突标记）。

锁定行为：
1. ``replaces``：新→旧边落 relation_edges；旧偏好 lifecycle → deprecated；
   旧 state.superseded_by 版本链追加新 id；幂等（重复记录不重复追加）。
2. ``conflicts_with``：只写边与账本留痕，**不动生命周期**（治理底线：
   冲突必须显式裁决）。
3. 输入校验：非 preference 类、edge_type 非法 → ValueError；不存在的
   胶囊 → KeyError。
4. preference_score 四因子随演化事件变化（recency / frequency /
   evidence 各自的因果方向）。
"""
from __future__ import annotations

import pytest

from backend.app.memory_runtime import evolution, preference_graph as pg
from backend.app.memory_runtime.capsule_store import get_capsule, write_capsule


def _pref(subject: str, statement: str = "") -> str:
    return write_capsule(
        memory_class="preference",
        content={"subject": subject, "statement": statement or f"喜欢{subject}"},
    )["capsule_id"]


def test_replaces_marks_old_deprecated_with_version_chain(isolated_db):
    old = _pref("editor", "喜欢 VSCode")
    new = _pref("editor", "喜欢 Cursor")

    res = pg.record_preference_evolution(new, old)
    assert res["edge_type"] == "replaces"
    assert res["edge_added"] is True
    assert res["lifecycle_transitioned"] is True

    old_cap = get_capsule(old)
    assert old_cap["state"]["lifecycle"] == "deprecated"
    assert new in old_cap["state"]["superseded_by"]
    assert old_cap["state"]["deprecation_reason"] == f"replaced_by:{new}"

    new_cap = get_capsule(new)
    replaces = [
        e for e in new_cap["relation_edges"]
        if isinstance(e, dict) and e.get("type") == "replaces"
    ]
    assert len(replaces) == 1 and replaces[0]["target"] == old


def test_replaces_idempotent(isolated_db):
    old = _pref("editor", "A")
    new = _pref("editor", "B")
    first = pg.record_preference_evolution(new, old)
    second = pg.record_preference_evolution(new, old)
    assert first["edge_added"] is True
    assert second["edge_added"] is False  # 边不重复追加
    # superseded_by 也只追加一次
    assert get_capsule(old)["state"]["superseded_by"].count(new) == 1


def test_conflicts_with_does_not_touch_lifecycle(isolated_db):
    """冲突标记只写边与账本，不动生命周期——裁决必须显式。"""
    a = _pref("editor", "喜欢 VSCode")
    b = _pref("editor", "喜欢 Cursor")

    res = pg.record_preference_evolution(b, a, edge_type="conflicts_with")
    assert res["edge_added"] is True
    assert res["lifecycle_transitioned"] is False

    # 双方生命周期都保持 active
    assert get_capsule(a)["state"]["lifecycle"] == "active"
    assert get_capsule(b)["state"]["lifecycle"] == "active"
    # b 的出边有 conflicts_with
    b_cap = get_capsule(b)
    assert any(
        isinstance(e, dict) and e.get("type") == "conflicts_with"
        for e in b_cap["relation_edges"]
    )


def test_evolution_requires_preference_class(isolated_db):
    pref = _pref("editor")
    knowledge = write_capsule(memory_class="knowledge", content={"text": "知识"})["capsule_id"]
    with pytest.raises(ValueError, match="preference"):
        pg.record_preference_evolution(pref, knowledge)
    with pytest.raises(ValueError, match="preference"):
        pg.record_preference_evolution(knowledge, pref)


def test_evolution_invalid_edge_type_rejected(isolated_db):
    a = _pref("editor", "A")
    b = _pref("editor", "B")
    with pytest.raises(ValueError, match="edge_type"):
        pg.record_preference_evolution(b, a, edge_type="evidence_for")


def test_evolution_missing_capsule_raises_keyerror(isolated_db):
    a = _pref("editor")
    with pytest.raises(KeyError):
        pg.record_preference_evolution(a, "cap_does_not_exist")


# ---------------------------------------------------------------------------
# preference_score 因子随演化事件变化
# ---------------------------------------------------------------------------

def test_score_frequency_rises_with_reinforce(isolated_db):
    """连续 reinforce → Beta 均值升高 → frequency 因子上升 → 总分上升。"""
    pid = _pref("lang")
    g0 = pg.load_preference_graph()
    s0 = pg.compute_preference_scores(g0)[pid]

    for _ in range(8):
        evolution.reinforce(pid, amount=0.05)

    g1 = pg.load_preference_graph()
    s1 = pg.compute_preference_scores(g1)[pid]
    assert s1["factors"]["frequency"] > s0["factors"]["frequency"]
    assert s1["score"] > s0["score"]


def test_score_evidence_factor_counts_in_edges(isolated_db):
    """指向偏好的 evidence_for / constraint_of 边越多，evidence 因子越高。"""
    pid = _pref("editor")
    write_capsule(
        memory_class="knowledge",
        content={"text": "证据1"},
        relation_edges=[{"target": pid, "type": "evidence_for"}],
    )
    g = pg.load_preference_graph()
    s_one = pg.compute_preference_scores(g)[pid]
    assert s_one["factors"]["evidence"] > 0.0

    # 再加两条证据
    for i in (2, 3):
        write_capsule(
            memory_class="knowledge",
            content={"text": f"证据{i}"},
            relation_edges=[{"target": pid, "type": "evidence_for"}],
        )
    g2 = pg.load_preference_graph()
    s_three = pg.compute_preference_scores(g2)[pid]
    assert s_three["factors"]["evidence"] > s_one["factors"]["evidence"]


def test_score_custom_weights_override(isolated_db):
    """显式 weights 参数覆盖默认四因子权重。"""
    pid = _pref("lang")
    for _ in range(8):
        evolution.reinforce(pid, amount=0.05)
    g = pg.load_preference_graph()

    default = pg.compute_preference_scores(g)[pid]
    freq_only = pg.compute_preference_scores(
        g, weights={"emotion": 0.0, "recency": 0.0, "frequency": 1.0, "evidence": 0.0}
    )[pid]
    assert freq_only["score"] == pytest.approx(default["factors"]["frequency"], abs=1e-4)


def test_score_sorted_descending_and_factors_explained(isolated_db):
    """返回按 score 降序；每个分数带四因子分解（可解释性）。"""
    strong = _pref("strong")
    _ = _pref("weak")  # 低分对照节点（排序断言覆盖多元素）
    for _ in range(10):
        evolution.reinforce(strong, amount=0.05)

    g = pg.load_preference_graph()
    scores = pg.compute_preference_scores(g)
    items = list(scores.items())
    for (_ida, sa), (_idb, sb) in zip(items, items[1:]):
        assert sa["score"] >= sb["score"]
    for _cid, s in items:
        assert set(s["factors"]) == {"emotion", "recency", "frequency", "evidence"}
        assert 0.0 <= s["score"] <= 1.0


def test_suggest_active_preference_prefers_higher_score(isolated_db):
    """建议式裁决：分数高者为 suggested_active，auto_execute 恒为 False。"""
    weak = _pref("weak")
    strong = _pref("strong")
    for _ in range(10):
        evolution.reinforce(strong, amount=0.05)

    suggestion = pg.suggest_active_preference([weak, strong])  # weak 用于对照排名
    assert suggestion["suggested_active"] == strong
    assert suggestion["auto_execute"] is False
    assert suggestion["suggested_active_score"] > 0.0
    assert suggestion["ranking"][0]["capsule_id"] == strong


def test_suggest_active_empty_input_degrades_honestly(isolated_db):
    suggestion = pg.suggest_active_preference([])
    assert suggestion["suggested_active"] is None
    suggestion2 = pg.suggest_active_preference(["cap_missing"])
    assert suggestion2["suggested_active"] is None
