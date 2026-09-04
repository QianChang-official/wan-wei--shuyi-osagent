"""知识演化测试（issue #202 验收：Knowledge Version / Version Evolution）。

锁定行为：
1. ``supersedes``：新→旧边落 relation_edges；旧知识转 deprecated + 版本链；
   新知识 ``knowledge_version = 旧版本+1``（Firefox→Chrome→Edge = 1→2→3）。
2. ``invalidates``：旧知识转 deprecated 但**不递增版本**（证伪非替代）。
3. ``derived_from``：只写边，不动生命周期、不动版本号。
4. 幂等：重复演化不追加边、不重复转移（零 transition 账本噪音——与
   preference_graph 评审修复后的同一口径）。
5. 演化链回溯：``trace_evolution`` 沿 supersedes/invalidates 返回版本
   路径；限深防退化 DAG；环不挂死。
6. 输入校验：非 knowledge 类 / 非法 edge_type → ValueError；不存在 → KeyError。
"""
from __future__ import annotations

import pytest

from backend.app.memory_runtime import knowledge_evolution as ke
from backend.app.memory_runtime.capsule_store import get_capsule, write_capsule


def _know(text: str, source_type: str = "user_input") -> str:
    return write_capsule(
        memory_class="knowledge", content={"text": text}, source_type=source_type
    )["capsule_id"]


def test_supersedes_marks_old_deprecated_with_version_chain(isolated_db):
    old = _know("默认浏览器 = Firefox")
    new = _know("默认浏览器 = Chrome")

    res = ke.evolve_knowledge(new, old)
    assert res["edge_type"] == "supersedes"
    assert res["edge_added"] is True
    assert res["lifecycle_transitioned"] is True
    assert res["version_assigned"] == 2  # 旧无显式版本（默认 1）→ 新 = 2

    old_cap = get_capsule(old)
    assert old_cap["state"]["lifecycle"] == "deprecated"
    assert old_cap["state"]["superseded_by"] == [new]
    assert old_cap["state"]["deprecation_reason"] == f"superseded_by:{new}"

    new_cap = get_capsule(new)
    supersedes = [
        e for e in new_cap["relation_edges"]
        if isinstance(e, dict) and e.get("type") == "supersedes"
    ]
    assert len(supersedes) == 1 and supersedes[0]["target"] == old
    assert new_cap["state"]["knowledge_version"] == 2


def test_three_generation_chain_versions(isolated_db):
    """Firefox → Chrome → Edge 三代演化：版本 2 → 3，链完整。"""
    firefox = _know("默认浏览器 = Firefox")
    chrome = _know("默认浏览器 = Chrome")
    edge = _know("默认浏览器 = Edge")

    ke.evolve_knowledge(chrome, firefox)
    ke.evolve_knowledge(edge, chrome)

    assert get_capsule(firefox)["state"]["lifecycle"] == "deprecated"
    assert get_capsule(chrome)["state"]["lifecycle"] == "deprecated"
    assert get_capsule(edge)["state"]["lifecycle"] == "active"
    assert get_capsule(edge)["state"]["knowledge_version"] == 3

    path = ke.trace_evolution(edge)
    assert [p["capsule_id"] for p in path[:3]] == [edge, chrome, firefox]
    assert path[0]["lifecycle"] == "active"
    assert path[1]["lifecycle"] == "deprecated"


def test_invalidates_deprecates_without_version_bump(isolated_db):
    """证伪失效：旧知识转 deprecated，但没有继任版本（不递增）。"""
    old = _know("服务器装有 Firefox")
    refutation = _know("服务器没有安装 Firefox")

    res = ke.evolve_knowledge(refutation, old, edge_type="invalidates")
    assert res["lifecycle_transitioned"] is True
    assert res["version_assigned"] is None  # 无继任版本

    old_cap = get_capsule(old)
    assert old_cap["state"]["lifecycle"] == "deprecated"
    assert old_cap["state"]["deprecation_reason"] == f"invalidated_by:{refutation}"
    # 证伪方自己不带版本号
    assert "knowledge_version" not in (get_capsule(refutation)["state"] or {})


def test_derived_from_only_writes_edge(isolated_db):
    """派生溯源：只写边，不动生命周期、不动版本号。"""
    source = _know("团队使用 Python 3.10")
    derived = _know("项目 requirements.txt 指定 python>=3.10")

    res = ke.evolve_knowledge(derived, source, edge_type="derived_from")
    assert res["edge_added"] is True
    assert res["lifecycle_transitioned"] is False
    assert res["version_assigned"] is None

    for cid in (source, derived):
        assert get_capsule(cid)["state"]["lifecycle"] == "active"
    assert any(
        isinstance(e, dict) and e.get("type") == "derived_from"
        for e in get_capsule(derived)["relation_edges"]
    )


def test_supersedes_idempotent_no_ledger_noise(isolated_db):
    """幂等重调：边不重复、转移不重跑（transition 账目零追加）。"""
    from backend.app.db import get_conn

    old = _know("端口 = 8080")
    new = _know("端口 = 9000")

    first = ke.evolve_knowledge(new, old)
    count_after_first = get_conn().execute(
        "SELECT COUNT(*) FROM memory_ledger WHERE capsule_id=? AND op_type='transition'",
        (old,),
    ).fetchone()[0]

    second = ke.evolve_knowledge(new, old)
    assert first["lifecycle_transitioned"] is True
    assert second["lifecycle_transitioned"] is False
    count_after_second = get_conn().execute(
        "SELECT COUNT(*) FROM memory_ledger WHERE capsule_id=? AND op_type='transition'",
        (old,),
    ).fetchone()[0]
    assert count_after_second == count_after_first

    old_cap = get_capsule(old)
    assert old_cap["state"]["superseded_by"].count(new) == 1
    assert get_capsule(new)["state"]["knowledge_version"] == 2  # 版本不重复递增


def test_evolution_requires_knowledge_class(isolated_db):
    know = _know("知识")
    pref = write_capsule(
        memory_class="preference", content={"subject": "e", "statement": "喜欢 X"}
    )["capsule_id"]
    with pytest.raises(ValueError, match="knowledge"):
        ke.evolve_knowledge(know, pref)
    with pytest.raises(ValueError, match="knowledge"):
        ke.evolve_knowledge(pref, know)


def test_evolution_invalid_edge_type_rejected(isolated_db):
    a = _know("A")
    b = _know("B")
    with pytest.raises(ValueError, match="edge_type"):
        ke.evolve_knowledge(b, a, edge_type="evidence_for")


def test_evolution_missing_capsule_raises(isolated_db):
    a = _know("A")
    with pytest.raises(KeyError):
        ke.evolve_knowledge(a, "cap_does_not_exist")


def test_trace_evolution_depth_truncated(isolated_db):
    """超长链限深回溯：不挂死、如实截断。"""
    from backend.app.memory_runtime.capsule_store import update_capsule

    nodes = [_know(f"版本 {i}") for i in range(ke.MAX_EVOLUTION_DEPTH + 5)]
    for src, dst in zip(nodes, nodes[1:]):
        update_capsule(src, relation_edges=[{"target": dst, "type": "supersedes"}])

    path = ke.trace_evolution(nodes[0])
    # 限深 + 1 个节点（root 在 depth 0），外加截断标记行
    assert len(path) == ke.MAX_EVOLUTION_DEPTH + 2
    assert path[-1].get("note") == "depth_truncated"


def test_trace_evolution_cycle_safe(isolated_db):
    """演化环（脏数据）不挂死。"""
    from backend.app.memory_runtime.capsule_store import update_capsule

    a, b, c = _know("A"), _know("B"), _know("C")
    update_capsule(c, relation_edges=[{"target": b, "type": "supersedes"}])
    update_capsule(b, relation_edges=[{"target": a, "type": "supersedes"}])
    update_capsule(a, relation_edges=[{"target": c, "type": "supersedes"}])

    path = ke.trace_evolution(c)
    assert len(path) <= 3  # 环闭合不重入
