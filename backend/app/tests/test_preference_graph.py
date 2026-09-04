"""Preference Graph 基础图结构测试（issue #198 验收：图建模）。

锁定行为：
1. 节点推断：memory_class 推断 preference/evidence/constraint 节点类型，
   显式 ``content.preference_graph_node_type`` 优先。
2. 边加载：只认 ``EDGE_TYPES`` 受控词表内的边；兼容 ``target`` /
   ``target_id`` / ``to`` 键名（与 rrf_fusion 同口径）；指向已遗忘
   胶囊的边被剔除。
3. 生命周期过滤：deprecated 节点不进可检索图视图（但原始出边保留在
   relation_edges 里供链回溯）。
4. scope 隔离：owner/soul 过滤。
5. stats 汇总口径正确。
"""
from __future__ import annotations

from backend.app.memory_runtime import preference_graph as pg
from backend.app.memory_runtime.capsule_store import write_capsule
from backend.app.memory_runtime import evolution


def _pref(subject: str, statement: str = "") -> str:
    return write_capsule(
        memory_class="preference",
        content={"subject": subject, "statement": statement or f"喜欢{subject}"},
    )["capsule_id"]


def test_node_type_inference_by_memory_class(isolated_db):
    pid = _pref("editor")
    kid = write_capsule(memory_class="knowledge", content={"text": "某知识"})["capsule_id"]
    cid = write_capsule(memory_class="constraint", content={"rule": "避免闭源"})["capsule_id"]
    oid = write_capsule(memory_class="affect", content={"mood": "joy"})["capsule_id"]

    g = pg.load_preference_graph()
    assert g["nodes"][pid]["node_type"] == "preference"
    assert g["nodes"][kid]["node_type"] == "evidence"
    assert g["nodes"][cid]["node_type"] == "constraint"
    assert g["nodes"][oid]["node_type"] == "other"  # 未登记类不参与偏好图


def test_node_type_explicit_annotation_wins(isolated_db):
    pid = write_capsule(
        memory_class="preference",
        content={"subject": "x", "statement": "s", "preference_graph_node_type": "evidence"},
    )["capsule_id"]
    g = pg.load_preference_graph()
    assert g["nodes"][pid]["node_type"] == "evidence"


def test_edges_only_from_controlled_vocab(isolated_db):
    """EDGE_TYPES 之外的边（如既有业务的 related_to）不进偏好图视图。"""
    pid = _pref("editor")
    kid = write_capsule(  # 载体胶囊（id 供边归属断言）
        memory_class="knowledge",
        content={"text": "证据"},
        relation_edges=[
            {"target": pid, "type": "evidence_for"},
            {"target": pid, "type": "related_to"},  # 不在受控词表 → 忽略
            {"target_id": pid, "type": "emotion_for"},  # 别名键 → 兼容
            {"to": pid, "type": "unrelated"},  # 不在词表 → 忽略
        ],
    )["capsule_id"]
    g = pg.load_preference_graph()
    loaded = [e["type"] for e in g["edges"][kid]]
    assert sorted(loaded) == ["emotion_for", "evidence_for"]


def test_edges_to_forgotten_targets_dropped(isolated_db):
    pid = _pref("editor")
    kid = write_capsule(
        memory_class="knowledge",
        content={"text": "证据"},
        relation_edges=[{"target": pid, "type": "evidence_for"}],
    )["capsule_id"]
    from backend.app.memory_runtime.capsule_store import forget_capsules

    forget_capsules([pid])
    g = pg.load_preference_graph()
    # 目标已遗忘 → 边剔除；但源胶囊仍在节点表里
    assert "edges" not in g or kid not in g["edges"]
    assert kid in g["nodes"]


def test_deprecated_node_excluded_from_graph_view(isolated_db):
    """deprecated 不在可检索集 → 图视图不包含；但原始 relation_edges 保留。"""
    old = _pref("editor", "喜欢 VSCode")
    new = _pref("editor", "喜欢 Cursor")
    pg.record_preference_evolution(new, old)

    g = pg.load_preference_graph()
    assert new in g["nodes"]
    assert old not in g["nodes"]
    # 可检索图视图里 new→old 的 replaces 边因目标缺席被剔除
    assert new not in g.get("edges", {})


def test_stats_summary(isolated_db):
    pid = _pref("editor")
    write_capsule(  # 载体胶囊（节点计数含它）
        memory_class="knowledge",
        content={"text": "证据"},
        relation_edges=[{"target": pid, "type": "evidence_for"}],
    )
    g = pg.load_preference_graph()
    assert g["stats"]["nodes"] == 2
    assert g["stats"]["edges"] == 1
    assert g["stats"]["nodes_by_type"] == {"preference": 1, "evidence": 1}
    assert g["stats"]["edges_by_type"] == {"evidence_for": 1}


def test_owner_scope_isolation(isolated_db):
    """owner 作用域外的胶囊不进图视图。"""
    from backend.app.memory_runtime.capsule_store import get_capsule

    mine = _pref("editor")
    other = write_capsule(
        memory_class="preference",
        content={"subject": "editor", "statement": "别人的偏好"},
        owner_id="id_owner_other",
    )["capsule_id"]

    g_all = pg.load_preference_graph()
    assert mine in g_all["nodes"] and other in g_all["nodes"]

    g_mine = pg.load_preference_graph(owner_id="id_owner_me")
    # 默认写入归属 configured_actor_id；显式 owner_id 过滤时只看自己
    cap = get_capsule(mine)
    my_owner = (cap.get("provenance") or {}).get("owner_id")
    assert (mine in g_mine["nodes"]) == (my_owner == "id_owner_me")


def test_preference_name_and_polarity(isolated_db):
    pid = write_capsule(
        memory_class="preference",
        content={"subject": "editor", "statement": "喜欢 Cursor", "polarity": "negative"},
    )["capsule_id"]
    # 抬 alpha → 后验均值高；但显式 polarity 优先
    for _ in range(6):
        evolution.reinforce(pid, amount=0.01)
    g = pg.load_preference_graph()
    assert g["nodes"][pid]["name"] == "editor"
    assert g["nodes"][pid]["polarity"] == "negative"

    # 无显式 polarity：均值 >0.55 → positive 推断
    pid2 = _pref("lang")
    for _ in range(6):
        evolution.reinforce(pid2, amount=0.01)
    g2 = pg.load_preference_graph()
    assert g2["nodes"][pid2]["polarity"] == "positive"


def test_raw_out_edges_reads_deprecated_nodes(isolated_db):
    """_load_raw_out_edges 不过滤 lifecycle——供级联回溯穿越 deprecated 节点。"""
    old = _pref("editor", "喜欢 VSCode")
    new = _pref("editor", "喜欢 Cursor")
    pg.record_preference_evolution(new, old)

    raw = pg._load_raw_out_edges()
    types = [e["type"] for e in raw.get(new, [])]
    assert "replaces" in types
    # update_capsule 落边后原始列里有它，即使 old 已 deprecated
    from backend.app.memory_runtime.capsule_store import get_capsule

    cap = get_capsule(new)
    assert any(
        isinstance(e, dict) and e.get("type") == "replaces" for e in cap["relation_edges"]
    )
