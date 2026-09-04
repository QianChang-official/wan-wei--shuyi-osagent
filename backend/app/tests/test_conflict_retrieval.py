"""知识检索增强测试（issue #202 验收：版本状态检索 / Knowledge Explain）。

锁定行为：
1. ``knowledge_rerank``：active 乘子 1.0 排前；deprecated 按代数衰减
   （0.5^depth 封底 0.1）；conflicted 0.60 可见但降权；stale 0.85。
2. 非知识候选恒等通过（偏好/情感通道不受影响）。
3. 只读：不 bump usage_count。
4. ``explain_knowledge``：版本/状态/置信度/演化链/冲突记录/来源证据
   一次返回。
5. 演化终态的检索语义：三代演化后，最新版本排最前、旧版本按代数衰减。
"""
from __future__ import annotations

from backend.app.memory_runtime import knowledge_evolution as ke
from backend.app.memory_runtime.capsule_store import get_capsule, write_capsule


def _know(text: str) -> str:
    return write_capsule(memory_class="knowledge", content={"text": text})["capsule_id"]


def _cand(cid: str, memory_class: str, score: float, lifecycle: str = "active") -> dict:
    return {
        "capsule_id": cid,
        "memory_class": memory_class,
        "retrieval_score": score,
        "state": {"lifecycle": lifecycle},
    }


def test_rerank_active_beats_deprecated_same_score(isolated_db):
    """同分下 active 知识排 deprecated 前；deprecated 乘子 0.5^depth。"""
    old = _know("默认浏览器 = Firefox")
    new = _know("默认浏览器 = Chrome")
    ke.evolve_knowledge(new, old)

    out = ke.knowledge_rerank([
        _cand(old, "knowledge", 0.9, "deprecated"),
        _cand(new, "knowledge", 0.9, "active"),
    ])
    assert out[0]["capsule_id"] == new
    assert out[1]["capsule_id"] == old
    assert out[0]["knowledge_multiplier"] == 1.0
    assert out[1]["knowledge_multiplier"] == 0.5
    assert out[1]["superseded_depth"] == 1


def test_rerank_generation_decay(isolated_db):
    """三代演化：v3 排最前，v1（两代深）衰减到 0.25。"""
    v1 = _know("浏览器 = Firefox")
    v2 = _know("浏览器 = Chrome")
    v3 = _know("浏览器 = Edge")
    ke.evolve_knowledge(v2, v1)
    ke.evolve_knowledge(v3, v2)

    out = ke.knowledge_rerank([
        _cand(v1, "knowledge", 0.9, "deprecated"),
        _cand(v2, "knowledge", 0.9, "deprecated"),
        _cand(v3, "knowledge", 0.9, "active"),
    ])
    assert [c["capsule_id"] for c in out] == [v3, v2, v1]
    by_id = {c["capsule_id"]: c for c in out}
    assert by_id[v3]["knowledge_multiplier"] == 1.0
    assert by_id[v2]["knowledge_multiplier"] == 0.5
    assert by_id[v1]["knowledge_multiplier"] == 0.25


def test_rerank_conflicted_visible_but_demoted(isolated_db):
    a = _know("端口 = 8080")
    b = _know("端口 = 9000")
    ke.evolve_knowledge(b, a, edge_type="conflicts_with")

    out = ke.knowledge_rerank([
        _cand(b, "knowledge", 0.9, "conflicted"),
        _cand(a, "knowledge", 0.6, "active"),
    ])
    by_id = {c["capsule_id"]: c for c in out}
    # conflicted 0.60 乘子 → 0.9×0.6=0.54 < 0.6，让位给 active
    assert out[0]["capsule_id"] == a
    assert by_id[b]["knowledge_multiplier"] == 0.6


def test_rerank_stale_demoted(isolated_db):
    out = ke.knowledge_rerank([_cand("cap_x", "knowledge", 0.9, "stale")])
    assert out[0]["knowledge_multiplier"] == 0.85


def test_rerank_non_knowledge_passthrough(isolated_db):
    """偏好/情感候选恒等通过——知识版本通道不碰其他类。"""
    out = ke.knowledge_rerank([
        _cand("cap_pref", "preference", 0.5, "deprecated"),
    ])
    assert out[0]["knowledge_multiplier"] == 1.0
    assert "superseded_depth" not in out[0]


def test_rerank_is_readonly(isolated_db):
    """重排不 bump usage_count、不改库内 state。"""
    k = _know("知识")
    before = get_capsule(k)["state"].get("usage_count", 0)
    for _ in range(3):
        ke.knowledge_rerank([_cand(k, "knowledge", 0.5)])
    assert get_capsule(k)["state"].get("usage_count", 0) == before


def test_rerank_preserves_retrieval_score_field(isolated_db):
    k = _know("知识")
    out = ke.knowledge_rerank([_cand(k, "knowledge", 0.42)])
    assert out[0]["retrieval_score"] == 0.42


def test_rerank_top_k(isolated_db):
    out = ke.knowledge_rerank(
        [_cand(f"cap_{i}", "knowledge", 0.1 * i) for i in range(5)], top_k=2
    )
    assert len(out) == 2


def test_rerank_empty(isolated_db):
    assert ke.knowledge_rerank([]) == []


# ---------------------------------------------------------------------------
# Knowledge Explain
# ---------------------------------------------------------------------------

def test_explain_full_picture(isolated_db):
    """explain 一次返回：版本/状态/置信度/演化链/冲突/来源。"""
    old = _know("默认浏览器 = Firefox")
    new = _know("默认浏览器 = Chrome")
    ke.evolve_knowledge(new, old)

    exp = ke.explain_knowledge(new)
    assert exp["capsule_id"] == new
    assert exp["knowledge_version"] == 2
    assert exp["lifecycle"] == "active"
    assert set(exp["confidence"]["factors"]) == {
        "recency", "trust", "source_authority", "usage",
    }
    # 演化链含两代
    assert [p["capsule_id"] for p in exp["evolution_path"]] == [new, old]
    assert exp["evolution_path"][1]["lifecycle"] == "deprecated"
    # 来源证据
    assert exp["provenance"]["source_type"] == "user_input"


def test_explain_includes_conflicts_and_suggestion(isolated_db):
    """有冲突记录时附带裁决建议。"""
    a = _know("端口 = 8080")
    b = _know("端口 = 9000")
    ke.evolve_knowledge(b, a, edge_type="conflicts_with")

    exp = ke.explain_knowledge(b)
    assert len(exp["conflicts"]) == 1
    assert exp["conflicts"][0]["with"] == a
    assert exp["resolution_suggestion"] is not None
    assert exp["resolution_suggestion"]["auto_execute"] is False


def test_explain_incoming_conflict_detected(isolated_db):
    """对方指向我的冲突边（incoming）也算我的冲突记录。"""
    a = _know("端口 = 8080")
    b = _know("端口 = 9000")
    ke.evolve_knowledge(b, a, edge_type="conflicts_with")

    exp_a = ke.explain_knowledge(a)
    assert len(exp_a["conflicts"]) == 1
    assert exp_a["conflicts"][0]["direction"] == "incoming"
    assert exp_a["conflicts"][0]["with"] == b


def test_explain_missing_capsule_raises(isolated_db):
    import pytest as _pytest

    with _pytest.raises(KeyError):
        ke.explain_knowledge("cap_missing")


# ---------------------------------------------------------------------------
# 端到端：检测 → 建议 → 演化 → 检索（issue #202 场景闭环）
# ---------------------------------------------------------------------------

def test_conflict_to_evolution_to_retrieval_e2e(isolated_db):
    """端到端：写新知识 → 检测到冲突 → 建议裁决 → 落演化边 → 检索降权旧版。"""
    from datetime import datetime, timedelta, timezone

    from backend.app.db import get_conn

    old = _know("默认浏览器 = Firefox")
    new = _know("默认浏览器 = Chrome")
    # 同秒写入时四因子完全同分、created_at 也相同，裁决退化为 id 字典序
    # （非确定）。回拨旧知识一秒，让「新知识更新」成为确定事实。
    past = (
        datetime.now(timezone.utc) - timedelta(seconds=1)
    ).isoformat()
    get_conn().execute(
        "UPDATE memory_capsules_v2 SET created_at=?, updated_at=? WHERE capsule_id=?",
        (past, past, old),
    )
    get_conn().commit()

    # 1) 检测：新知识与 active 旧知识 fact 冲突
    hits = ke.detect_knowledge_conflicts(new)
    assert [h["capsule_id"] for h in hits] == [old]
    assert hits[0]["type"] == "fact"

    # 2) 建议：新知识胜出（recency 占优）
    suggestion = ke.suggest_active_knowledge([old, new])
    assert suggestion["suggested_active"] == new

    # 3) 演化：采纳建议落 supersedes 边
    res = ke.evolve_knowledge(new, old, conflict_type="fact")
    assert res["lifecycle_transitioned"] is True
    assert get_capsule(old)["state"]["lifecycle"] == "deprecated"

    # 4) 检索：旧版本降权，新版本排前
    out = ke.knowledge_rerank([
        _cand(old, "knowledge", 0.9, "deprecated"),
        _cand(new, "knowledge", 0.9, "active"),
    ])
    assert out[0]["capsule_id"] == new


# ---------------------------------------------------------------------------
# 评审修复回归（PR #203 review）
# ---------------------------------------------------------------------------

def test_rerank_invisible_lifecycle_zero_multiplier(isolated_db):
    """forgotten/quarantined/rejected 乘子显式归零，不按 active 缺省 1.0。"""
    for lifecycle in ("forgotten", "quarantined", "rejected", "candidate", "deleted"):
        out = ke.knowledge_rerank([_cand("cap_x", "knowledge", 0.9, lifecycle)])
        assert out[0]["knowledge_multiplier"] == 0.0, lifecycle


def test_rerank_mixed_classes_fair_base(isolated_db):
    """混合重排的缺省基础分跨类一致（都 0.5）：

    知识缺省 0.5 而非知识缺省 0.0 时，active 知识会无条件碾压非知识
    候选——跨类比较失去意义。
    """
    k = _know("知识")
    out = ke.knowledge_rerank([
        _cand(k, "knowledge", 0.9, "active"),
        {"capsule_id": "cap_pref", "memory_class": "preference",
         "state": {"lifecycle": "active"}},  # 无 retrieval_score 字段
    ])
    # 非知识候选缺省 0.5×1.0 = 0.5；active 知识 0.9×1.0 = 0.9 排前
    assert out[0]["capsule_id"] == k
    # 两者都有意义的分数（非 0.0 一边倒）
    assert out[0]["knowledge_multiplier"] == 1.0


def test_explain_no_writer_identity(isolated_db):
    """explain 不外发 writer_identity（作者身份最小披露）。"""
    old = _know("默认浏览器 = Firefox")
    exp = ke.explain_knowledge(old)
    assert "writer_identity" not in exp["provenance"]
    assert "source_type" in exp["provenance"]
