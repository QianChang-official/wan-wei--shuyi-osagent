"""TKE freshness 测试（issue #204 验收：verified_at / 引用频率进 freshness）。

锁定行为：
1. ``mark_verified``：写 state.verified_at（缺省当前时间）；provenance 的
   verified 布尔位不被覆盖（时间戳是补充不是替代）。
2. freshness 因子（knowledge_confidence.recency 的 TKE 升级口径）因果方向：
   - 最近验证过的知识 freshness 高于久未验证的；
   - 被 evidence_for/derived_from 引用的知识即使久未触碰 freshness 也
     有引用稳定度兜底（零引用不惩罚）；
   - verified_at 比使用时间更新时以验证时间为准（取较新的确认信号）。
3. ``reference_count``：evidence_for + derived_from 入边计数，不落库。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.app.memory_runtime import knowledge_evolution as ke
from backend.app.memory_runtime import temporal_knowledge as tk
from backend.app.memory_runtime.capsule_store import get_capsule, write_capsule


def _know(text: str) -> str:
    return write_capsule(memory_class="knowledge", content={"text": text})["capsule_id"]


def test_mark_verified_writes_timestamp(isolated_db):
    k = _know("知识")
    assert tk.get_verified_at(get_capsule(k)) is None  # 初始未验证

    tk.mark_verified(k, verified_at="2026-08-01T00:00:00Z")
    va = tk.get_verified_at(get_capsule(k))
    assert va is not None and va.year == 2026 and va.month == 8


def test_mark_verified_defaults_to_now(isolated_db):
    k = _know("知识")
    tk.mark_verified(k)
    va = tk.get_verified_at(get_capsule(k))
    assert va is not None
    assert abs((datetime.now(timezone.utc) - va).total_seconds()) < 60


def test_mark_verified_keeps_provenance_bool(isolated_db):
    """provenance.verified 布尔位由写入路径判定，mark_verified 不碰它。"""
    k = _know("知识")  # source_type=user_input → provenance.verified=True
    before = get_capsule(k)["provenance"]["verified"]
    tk.mark_verified(k, verified_at="2026-08-01T00:00:00Z")
    after = get_capsule(k)["provenance"]["verified"]
    assert after == before


def test_mark_verified_rejects_bad_time(isolated_db):
    k = _know("知识")
    with pytest.raises(ValueError, match="verified_at"):
        tk.mark_verified(k, verified_at="not-a-time")


def test_mark_verified_missing_capsule(isolated_db):
    with pytest.raises(KeyError):
        tk.mark_verified("cap_missing")


# ---------------------------------------------------------------------------
# freshness 因子因果方向
# ---------------------------------------------------------------------------

def test_freshness_recent_verification_beats_stale(isolated_db):
    """最近验证过的知识 freshness 高于 100 天前的旧知识。"""
    from backend.app.db import get_conn

    fresh = _know("端口 = 9000")
    stale = _know("端口 = 8080")
    # 两条都拨回 100 天前（时间衰减同底）。
    past = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
    get_conn().execute(
        "UPDATE memory_capsules_v2 SET created_at=?, updated_at=? WHERE capsule_id IN (?,?)",
        (past, past, fresh, stale),
    )
    get_conn().commit()
    # 只有 fresh 被近期验证过。
    tk.mark_verified(fresh, verified_at=datetime.now(timezone.utc).isoformat())

    at = datetime.now(timezone.utc)
    f_fresh = ke.knowledge_confidence(get_capsule(fresh), at=at)["factors"]["recency"]
    f_stale = ke.knowledge_confidence(get_capsule(stale), at=at)["factors"]["recency"]
    assert f_fresh > f_stale


def test_freshness_reference_stability(isolated_db):
    """被引用的**陈旧**知识 freshness 高于零引用的同龄知识（兜底语义）。

    时间信号新鲜时引用不加分（新鲜就是新鲜，max 兜底不掺水）；时间衰减
    之后引用稳定度把分数托起来——这才是「被反复引用的知识未必陈旧」。
    """
    from backend.app.db import get_conn

    referenced = _know("被引用的知识")
    lonely = _know("没人引用的知识")
    # 两条都拨回 100 天前（时间衰减同底，decay ≈ 0.10）。
    past = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
    get_conn().execute(
        "UPDATE memory_capsules_v2 SET created_at=?, updated_at=? WHERE capsule_id IN (?,?)",
        (past, past, referenced, lonely),
    )
    get_conn().commit()
    # 两条证据指向 referenced。
    for i in range(2):
        write_capsule(
            memory_class="knowledge",
            content={"text": f"证据 {i}"},
            relation_edges=[{"target": referenced, "type": "evidence_for"}],
        )

    at = datetime.now(timezone.utc)
    f_ref = ke.knowledge_confidence(get_capsule(referenced), at=at)["factors"]["recency"]
    f_lone = ke.knowledge_confidence(get_capsule(lonely), at=at)["factors"]["recency"]
    # 零引用陈旧知识 ≈ 纯衰减（~0.10）；被引用的同龄知识被托起来。
    assert f_lone < 0.2
    assert f_ref > f_lone


def test_freshness_reference_never_hurts_fresh_knowledge(isolated_db):
    """时间信号新鲜时，有引用不会比零引用差（max 兜底不掺水）。"""
    referenced = _know("新且被引用的知识")
    lonely = _know("新且没人引用的知识")
    write_capsule(
        memory_class="knowledge",
        content={"text": "证据"},
        relation_edges=[{"target": referenced, "type": "evidence_for"}],
    )

    at = datetime.now(timezone.utc)
    f_ref = ke.knowledge_confidence(get_capsule(referenced), at=at)["factors"]["recency"]
    f_lone = ke.knowledge_confidence(get_capsule(lonely), at=at)["factors"]["recency"]
    assert f_ref == pytest.approx(f_lone, abs=1e-6)


def test_freshness_zero_reference_no_penalty(isolated_db):
    """零引用不惩罚：新写入知识的 freshness 就是纯时间衰减，不被压分。"""
    k = _know("新知识")
    at = datetime.now(timezone.utc)
    f = ke.knowledge_confidence(get_capsule(k), at=at)["factors"]["recency"]
    # 纯时间衰减：刚写入 → decay ≈ 1.0（无引用修正项）。
    assert f == pytest.approx(1.0, abs=0.01)


def test_reference_count_counts_incoming_edges(isolated_db):
    k = _know("知识")
    for etype in ("evidence_for", "derived_from", "conflicts_with", "related_to"):
        write_capsule(
            memory_class="knowledge",
            content={"text": f"源 {etype}"},
            relation_edges=[{"target": k, "type": etype}],
        )
    # 只数 evidence_for + derived_from；conflicts_with/related_to 不算引用。
    assert tk.reference_count(k) == 2


def test_reference_count_no_self_loop(isolated_db):
    """自指边不算引用。"""
    from backend.app.memory_runtime.capsule_store import update_capsule

    k = _know("知识")
    update_capsule(k, relation_edges=[{"target": k, "type": "evidence_for"}])
    assert tk.reference_count(k) == 0


def test_reference_count_preloaded_edges(isolated_db):
    """raw_edges 预加载路径与自行加载结果一致（批量调用方共享读）。"""
    k = _know("知识")
    write_capsule(
        memory_class="knowledge",
        content={"text": "证据"},
        relation_edges=[{"target": k, "type": "evidence_for"}],
    )
    from backend.app.memory_runtime.knowledge_evolution import _load_knowledge_raw_edges

    preloaded = _load_knowledge_raw_edges()
    assert tk.reference_count(k, raw_edges=preloaded) == tk.reference_count(k) == 1
