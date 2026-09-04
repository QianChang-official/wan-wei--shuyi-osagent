"""偏好冲突处理测试（issue #198 验收：冲突判定 / 权重融合 / 建议式裁决）。

锁定行为：
1. ``conflicts_with`` 边建立后，图上形成冲突对，但双方生命周期不动
   （治理底线：不自动覆盖）。
2. ``suggest_active_preference`` 按多因子权重融合给出建议赢家；
   建议不执行任何生命周期转移。
3. 冲突对内新近 / 高频 / 多证据的一方胜出（各因子的因果方向验证）。
4. 显式 ``resolve_conflict``（人工裁决）仍是唯一生效路径，且裁决后
   图视图反映终态。
"""
from __future__ import annotations

from backend.app.memory_runtime import evolution, preference_graph as pg
from backend.app.memory_runtime.capsule_store import get_capsule, write_capsule
from backend.app.memoryos.lifecycle import resolve_conflict


def _pref(subject: str, statement: str = "") -> str:
    return write_capsule(
        memory_class="preference",
        content={"subject": subject, "statement": statement or f"喜欢{subject}"},
    )["capsule_id"]


def _evi(pid: str, text: str) -> str:
    return write_capsule(
        memory_class="knowledge",
        content={"text": text},
        relation_edges=[{"target": pid, "type": "evidence_for"}],
    )["capsule_id"]


def test_conflict_pair_marked_without_lifecycle_change(isolated_db):
    """conflicts_with 建立冲突对；双方保持 active 等待显式裁决。"""
    vscode = _pref("editor", "喜欢 VSCode")
    cursor = _pref("editor", "喜欢 Cursor")

    pg.record_preference_evolution(cursor, vscode, edge_type="conflicts_with")

    for cid in (vscode, cursor):
        assert get_capsule(cid)["state"]["lifecycle"] == "active"

    g = pg.load_preference_graph()
    conflict_edges = [
        e for e in g["edges"].get(cursor, []) if e["type"] == "conflicts_with"
    ]
    assert any(e["target"] == vscode for e in conflict_edges)


def test_suggestion_prefers_reinforced_candidate(isolated_db):
    """高频（被多次采纳）的一方在冲突建议中胜出。"""
    weak = _pref("editor", "喜欢 VSCode")
    strong = _pref("editor", "喜欢 Cursor")
    for _ in range(10):
        evolution.reinforce(strong, amount=0.05)

    suggestion = pg.suggest_active_preference([weak, strong])
    assert suggestion["suggested_active"] == strong


def test_suggestion_prefers_evidence_backed_candidate(isolated_db):
    """多证据支撑的一方胜出（evidence 因子的因果方向）。"""
    no_ev = _pref("editor", "喜欢 VSCode")
    backed = _pref("editor", "喜欢 Cursor")
    for i in range(4):
        _evi(backed, f"用户表示 Cursor 顺手 {i}")

    suggestion = pg.suggest_active_preference([no_ev, backed])
    assert suggestion["suggested_active"] == backed


def test_suggestion_reports_factors_for_both_sides(isolated_db):
    """建议里带 top1 的因子分解与完整排名——裁决界面要能展示证据。"""
    a = _pref("editor", "A")
    b = _pref("editor", "B")
    for _ in range(5):
        evolution.reinforce(b, amount=0.05)

    suggestion = pg.suggest_active_preference([a, b])
    assert set(suggestion["suggested_active_factors"]) == {
        "emotion", "recency", "frequency", "evidence",
    }
    assert len(suggestion["ranking"]) == 2
    assert {r["capsule_id"] for r in suggestion["ranking"]} == {a, b}


def test_suggestion_never_executes(isolated_db):
    """建议式裁决的硬边界：suggest 之后双方生命周期仍然是 active。"""
    a = _pref("editor", "A")
    b = _pref("editor", "B")
    pg.record_preference_evolution(b, a, edge_type="conflicts_with")
    suggestion = pg.suggest_active_preference([a, b])

    assert suggestion["auto_execute"] is False
    assert "resolve_conflict" in suggestion["note"]
    for cid in (a, b):
        assert get_capsule(cid)["state"]["lifecycle"] == "active"


def test_explicit_resolution_is_only_effective_path(isolated_db):
    """人工 resolve_conflict 是唯一生效裁决路径；裁决后图视图反映终态。"""
    vscode = _pref("editor", "喜欢 VSCode")
    cursor = _pref("editor", "喜欢 Cursor")
    pg.record_preference_evolution(cursor, vscode, edge_type="conflicts_with")
    suggestion = pg.suggest_active_preference([vscode, cursor])
    winner = suggestion["suggested_active"]
    loser = cursor if winner == vscode else vscode

    result = resolve_conflict(winner, loser, "human_decided", actor="human")
    assert result["winner"]["capsule"]["state"]["lifecycle"] == "active"
    # 败方默认归档（不删除，保留裁决现场）
    assert loser in result["winner"]["capsule"]["state"]["supersedes"]
    assert get_capsule(loser)["state"]["lifecycle"] == "deprecated"

    # 图视图：败方不再可检索
    g = pg.load_preference_graph()
    assert winner in g["nodes"]
    assert loser not in g["nodes"]


def test_conflict_then_replaces_evolution_path(isolated_db):
    """冲突 → 裁决建议 → 采纳建议落 replaces 演化边的完整链路。

    这是 issue #198 场景 1（新偏好产生）的端到端形态：先标记冲突，
    再用演化边记录替换关系，旧偏好归档并进版本链。
    """
    old = _pref("editor", "2025 年喜欢 VSCode")
    new = _pref("editor", "2026 年 Cursor 更适合我")
    _evi(new, "用户说 Cursor 更适合我")

    pg.record_preference_evolution(new, old, edge_type="conflicts_with")
    suggestion = pg.suggest_active_preference([old, new])
    assert suggestion["suggested_active"] == new  # 新近+证据占优

    res = pg.record_preference_evolution(new, old, edge_type="replaces")
    assert res["lifecycle_transitioned"] is True
    old_cap = get_capsule(old)
    assert old_cap["state"]["lifecycle"] == "deprecated"
    assert new in old_cap["state"]["superseded_by"]
