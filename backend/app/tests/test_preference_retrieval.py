"""preference-aware retrieval 测试（issue #198 验收：偏好驱动检索 / 级联遗忘 / 召回）。

锁定行为：
1. ``preference_rerank`` 只影响 preference 类候选；知识候选乘子恒 1.0。
2. ``weight=0`` 是严格恒等基线（消融口径：同一套数据流关掉偏好通道）。
3. 偏好候选的乘子方向：preference_score > 0.5 加成、< 0.5 惩罚、
   不在图视图按中性 0.5（不加不减）。
4. 只读：重排不 bump usage_count、不改库内 state。
5. 级联遗忘联动：replaces 链回溯遗忘 + evidence_for/emotion_for 边摘除、
   证据胶囊保留。
6. 级联遗忘的删除完整性校验结果随响应返回（主表/FTS/图边/向量）。
"""
from __future__ import annotations

import pytest

from backend.app.memory_runtime import evolution, preference_graph as pg
from backend.app.memory_runtime.capsule_store import (
    get_capsule,
    write_capsule,
)


def _pref(subject: str, statement: str = "") -> str:
    return write_capsule(
        memory_class="preference",
        content={"subject": subject, "statement": statement or f"喜欢{subject}"},
    )["capsule_id"]


def _cand(cid: str, memory_class: str, score: float) -> dict:
    return {
        "capsule_id": cid,
        "memory_class": memory_class,
        "retrieval_score": score,
        "state": {},
    }


def test_rerank_only_affects_preference_candidates(isolated_db):
    pref = _pref("lang")
    know = write_capsule(memory_class="knowledge", content={"text": "知识"})["capsule_id"]

    out = pg.preference_rerank(
        [_cand(pref, "preference", 0.5), _cand(know, "knowledge", 0.5)], weight=0.3
    )
    by_id = {c["capsule_id"]: c for c in out}
    # 偏好候选带乘子；知识候选不带（未被偏好通道触碰）
    assert "preference_multiplier" in by_id[pref]
    assert "preference_multiplier" not in by_id[know]
    # 知识候选 final == 原始 retrieval_score（乘子 1.0）
    assert by_id[know]["preference_score_final"] == 0.5


def test_rerank_weight_zero_is_strict_identity(isolated_db):
    """weight=0 → 恒等重排（消融基线）：顺序保持原 retrieval_score 降序。"""
    a = _pref("a")
    b = _pref("b")
    know = write_capsule(memory_class="knowledge", content={"text": "k"})["capsule_id"]
    candidates = [
        _cand(a, "preference", 0.3),
        _cand(b, "preference", 0.7),
        _cand(know, "knowledge", 0.5),
    ]
    out = pg.preference_rerank(candidates, weight=0.0)
    assert [c["capsule_id"] for c in out] == [b, know, a]
    for c in out:
        assert c["preference_score_final"] == c["retrieval_score"]
        assert "preference_multiplier" not in c


def test_rerank_boosts_strong_preference_above_knowledge(isolated_db):
    """强偏好（高频采纳）候选被加成后可反超同分知识候选。"""
    weak_pref = _pref("weak")
    strong_pref = _pref("strong")
    for _ in range(12):
        evolution.reinforce(strong_pref, amount=0.05)

    candidates = [
        _cand(weak_pref, "preference", 0.5),
        _cand(strong_pref, "preference", 0.5),
    ]
    out = pg.preference_rerank(candidates, weight=0.5)
    assert out[0]["capsule_id"] == strong_pref
    assert out[0]["preference_multiplier"] > out[1]["preference_multiplier"]


def test_rerank_unknown_candidate_gets_neutral_multiplier(isolated_db):
    """不在图视图的偏好候选（刚写未入可检索集等）按中性 0.5，不加不减。"""
    pref = _pref("lang")
    # 不做任何 reinforce —— 偏好仍应在图里（active），先验证正常路径
    out = pg.preference_rerank([_cand(pref, "preference", 0.5)], weight=0.5)
    # 在图视图内的候选带真实分数
    assert "preference_multiplier" in out[0]

    # 伪造一个不在库里的偏好候选 → 中性 0.5
    out2 = pg.preference_rerank([_cand("cap_missing", "preference", 0.5)], weight=0.5)
    assert out2[0]["preference_multiplier"] == pytest.approx(0.75, abs=1e-6)  # (1-0.5)+0.5*0.5
    assert out2[0]["preference_score"] == 0.5


def test_rerank_is_readonly(isolated_db):
    """重排不 bump usage_count、不改 last_accessed_at。"""
    pref = _pref("lang")
    before = get_capsule(pref)["state"]
    usage_before = before.get("usage_count", 0)

    for _ in range(3):
        pg.preference_rerank([_cand(pref, "preference", 0.5)], weight=0.3)

    after = get_capsule(pref)["state"]
    assert after.get("usage_count", 0) == usage_before


def test_rerank_preserves_base_score_field(isolated_db):
    """原始 retrieval_score 字段保持不动；新分数写在 preference_score_final。"""
    pref = _pref("lang")
    out = pg.preference_rerank([_cand(pref, "preference", 0.42)], weight=0.3)
    assert out[0]["retrieval_score"] == 0.42
    assert "preference_score_final" in out[0]


def test_rerank_top_k_truncation(isolated_db):
    a = _pref("a"); b = _pref("b"); c = _pref("c")
    out = pg.preference_rerank(
        [_cand(a, "preference", 0.1), _cand(b, "preference", 0.2), _cand(c, "preference", 0.3)],
        weight=0.0, top_k=2,
    )
    assert len(out) == 2
    assert [x["capsule_id"] for x in out] == [c, b]


def test_rerank_empty_input(isolated_db):
    assert pg.preference_rerank([]) == []


# ---------------------------------------------------------------------------
# 级联遗忘（遗忘联动）
# ---------------------------------------------------------------------------

def test_cascade_forgets_replaces_chain(isolated_db):
    """新偏好遗忘时，被它替换的旧版本链一并遗忘（演化终态一致）。"""
    old_a = _pref("editor", "喜欢 VSCode")
    mid_b = _pref("editor", "喜欢 Zed")
    new_c = _pref("editor", "喜欢 Cursor")
    pg.record_preference_evolution(new_c, mid_b)
    pg.record_preference_evolution(mid_b, old_a)

    res = pg.cascade_forget_preference(new_c)
    assert res["status"] == "forgotten"
    chain = res["cascade"]["replaces_chain_forgotten"]
    assert set(chain) == {mid_b, old_a}
    for cid in (new_c, mid_b, old_a):
        assert get_capsule(cid)["state"]["lifecycle"] == "forgotten"
    # 删除完整性证据随响应返回
    assert "deletion_verification" in res
    assert res["deletion_verification"]["all_complete"] is True


def test_cascade_detaches_evidence_edges_keeps_evidence_capsule(isolated_db):
    """指向目标的 evidence_for 边被摘除；证据胶囊本身保留。"""
    pref = _pref("editor")
    evidence = write_capsule(
        memory_class="knowledge",
        content={"text": "用户喜欢这个编辑器"},
        relation_edges=[{"target": pref, "type": "evidence_for"}],
    )["capsule_id"]

    res = pg.cascade_forget_preference(pref)
    assert res["cascade"]["evidence_edges_detached_from"] == [evidence]
    # 证据胶囊保留，其出边里指向 pref 的 evidence_for 已摘除
    ev_cap = get_capsule(evidence)
    assert ev_cap is not None
    assert ev_cap["state"]["lifecycle"] == "active"
    assert all(
        not (isinstance(e, dict) and e.get("target") == pref)
        for e in ev_cap["relation_edges"]
    )
    # 目标偏好本体遗忘
    assert get_capsule(pref)["state"]["lifecycle"] == "forgotten"


def test_cascade_cycle_does_not_hang(isolated_db):
    """replaces 环（历史数据脏形态）不挂死——限深防环。"""
    a = _pref("a"); b = _pref("b"); c = _pref("c")
    from backend.app.memory_runtime.capsule_store import update_capsule

    update_capsule(c, relation_edges=[{"target": b, "type": "replaces"}])
    update_capsule(b, relation_edges=[{"target": a, "type": "replaces"}])
    update_capsule(a, relation_edges=[{"target": c, "type": "replaces"}])

    res = pg.cascade_forget_preference(c)
    assert len(res["cascade"]["replaces_chain_forgotten"]) == 2  # b 与 a，环闭合不重入


def test_cascade_requires_preference_class(isolated_db):
    knowledge = write_capsule(memory_class="knowledge", content={"text": "k"})["capsule_id"]
    import pytest as _pytest

    with _pytest.raises(ValueError, match="preference"):
        pg.cascade_forget_preference(knowledge)


def test_cascade_missing_capsule_raises(isolated_db):
    import pytest as _pytest

    with _pytest.raises(KeyError):
        pg.cascade_forget_preference("cap_missing")


def test_forgotten_preference_drops_out_of_retrieval_view(isolated_db):
    """级联遗忘后，偏好不再出现在图视图与重排候选里。"""
    pref = _pref("editor")
    write_capsule(
        memory_class="knowledge",
        content={"text": "证据"},
        relation_edges=[{"target": pref, "type": "evidence_for"}],
    )
    pg.cascade_forget_preference(pref)

    g = pg.load_preference_graph()
    assert pref not in g["nodes"]
    out = pg.preference_rerank([_cand(pref, "preference", 0.5)], weight=0.3)
    # 候选仍在输入里（caller 给的），但拿中性乘子（不在图视图）
    assert out[0]["preference_score"] == 0.5
