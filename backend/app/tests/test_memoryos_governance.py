"""MemoryOS 治理账本测试（规范: AI优化/MemoryOS-Governance账本规范.md §5 验收标准）。

覆盖规范列出的四条验收标准：
1. 每次写/改/删都有账目
2. 删除后 verify_deletion 返回全零（主表/FTS/图边）
3. quarantine 的记忆不可被检索注入（在 test_memoryos_lifecycle 里另有覆盖）
4. MHG-3+ 触发 publish_freeze
"""

import sqlite3

import pytest

from backend.app.db import get_conn
from backend.app.memoryos import governance as gov
from backend.app.memory_runtime.capsule_store import (
    forget_capsules,
    get_capsule,
    update_capsule,
    write_capsule,
)


def _write(statement: str, **kwargs) -> dict:
    return write_capsule(
        memory_class=kwargs.pop("memory_class", "knowledge"),
        content={"knowledge_type": "fact", "statement": statement},
        source_type=kwargs.pop("source_type", "manual_config"),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# 哈希与账目写入
# ---------------------------------------------------------------------------


def test_content_hash_is_sha256_and_none_passthrough():
    assert gov.content_hash(None) is None
    digest = gov.content_hash("hello")
    assert len(digest) == 64
    assert digest == gov.content_hash("hello")
    assert digest != gov.content_hash("hello ")


def test_write_creates_ledger_entry(isolated_db):
    result = _write("账本写入 alpha")
    entries = gov.ledger_history(result["capsule_id"])
    write_entries = [row for row in entries if row["op_type"] == "write"]
    assert len(write_entries) == 1
    entry = write_entries[0]
    assert entry["after_hash"] is not None
    assert entry["before_hash"] is None  # 新写入没有「操作前内容」
    assert entry["after_state"] == "active"
    assert entry["actor"] == "runtime"


def test_rejected_write_still_leaves_ledger_trail(isolated_db):
    """被闸门拒绝的写入没有主表行，账本是唯一留痕处。"""
    result = _write("数据库密码是 Hunter2Prod!", source_type="user_input")
    assert result["governance"]["policy_result"] == "reject"
    assert get_capsule(result["capsule_id"]) is None

    entries = gov.ledger_history(result["capsule_id"])
    assert [row["op_type"] for row in entries] == ["write_rejected"]
    assert entries[0]["risk_class"] == "high"
    # 内容未落库，也不该留内容哈希
    assert entries[0]["after_hash"] is None


def test_update_records_before_and_after_hash(isolated_db):
    result = _write("账本更新 bravo")
    capsule_id = result["capsule_id"]
    state = dict(get_capsule(capsule_id)["state"])
    state["importance_score"] = 0.95
    update_capsule(capsule_id, state=state, reason="manual_bump")

    updates = [row for row in gov.ledger_history(capsule_id) if row["op_type"] == "update"]
    assert len(updates) == 1
    assert updates[0]["before_hash"] != updates[0]["after_hash"]
    assert updates[0]["reason"] == "manual_bump"


def test_delete_records_ledger_with_before_content(isolated_db):
    result = _write("账本删除 charlie")
    capsule_id = result["capsule_id"]
    forget_capsules([capsule_id])

    deletes = [row for row in gov.ledger_history(capsule_id) if row["op_type"] == "delete"]
    assert len(deletes) == 1
    assert deletes[0]["before_hash"] is not None
    assert deletes[0]["before_state"] == "active"
    assert deletes[0]["after_state"] == "forgotten"


def test_every_mutation_has_a_ledger_entry(isolated_db):
    """规范验收标准 1：抽查写/改/删，每次都有账目。"""
    result = _write("全链路账目 delta")
    capsule_id = result["capsule_id"]
    state = dict(get_capsule(capsule_id)["state"])
    state["retention_score"] = 0.7
    update_capsule(capsule_id, state=state)
    forget_capsules([capsule_id])

    ops = {row["op_type"] for row in gov.ledger_history(capsule_id)}
    assert {"write", "update", "delete"} <= ops


def test_ledger_batch_insert(isolated_db):
    from backend.app.db import transaction

    with transaction() as conn:
        ids = gov.append_ledger_batch_in_transaction(
            conn,
            [
                {"op_type": "retrieve", "capsule_id": "cap_batch_1", "reason": "hit"},
                {"op_type": "retrieve", "capsule_id": "cap_batch_2", "reason": "hit"},
            ],
        )
    assert len(ids) == 2
    assert len(gov.ledger_history("cap_batch_1")) == 1


def test_ledger_batch_empty_is_noop(isolated_db):
    from backend.app.db import transaction

    with transaction() as conn:
        assert gov.append_ledger_batch_in_transaction(conn, []) == []


# ---------------------------------------------------------------------------
# append-only 由数据库触发器强制
# ---------------------------------------------------------------------------


def test_ledger_rejects_update(isolated_db):
    """append-only 不是文档声明——UPDATE 必须被数据库 ABORT。"""
    result = _write("不可篡改 echo")
    ledger_id = gov.ledger_history(result["capsule_id"])[0]["ledger_id"]
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        get_conn().execute(
            "UPDATE memory_ledger SET reason='tampered' WHERE ledger_id=?", (ledger_id,)
        )


def test_ledger_rejects_delete(isolated_db):
    result = _write("不可删除 foxtrot")
    ledger_id = gov.ledger_history(result["capsule_id"])[0]["ledger_id"]
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        get_conn().execute("DELETE FROM memory_ledger WHERE ledger_id=?", (ledger_id,))


def test_ledger_summary_aggregates(isolated_db):
    _write("汇总 golf")
    _write("汇总 hotel")
    summary = gov.ledger_summary()
    assert summary["total"] >= 2
    assert summary["by_op_type"]["write"] >= 2
    assert "low" in summary["by_risk_class"]


# ---------------------------------------------------------------------------
# Provenance Card
# ---------------------------------------------------------------------------


def test_provenance_card_projects_all_required_fields(isolated_db):
    result = _write("来源卡 india", source_type="user_input", owner_id="owner_pc")
    cap = get_capsule(result["capsule_id"])
    card = gov.provenance_card(cap)

    for field in (
        "owner", "scope", "source", "confidence", "valid_from", "valid_until",
        "supersedes", "superseded_by", "verification", "evidence_ids",
    ):
        assert field in card, f"Provenance Card 缺字段 {field}"
    assert card["owner"] == "owner_pc"
    assert card["source"] == "user_input"
    assert card["verification"] == "manual"
    assert card["lifecycle"] == "active"


def test_provenance_card_marks_unverified_source(isolated_db):
    result = _write("未验证来源 juliett", source_type="cross_scene_trace")
    card = gov.provenance_card(get_capsule(result["capsule_id"]))
    assert card["verification"] == "unverified"


def test_provenance_card_prefers_explicit_source_confidence(isolated_db):
    result = _write(
        "explicit confidence juliett",
        source_type="manual_config",
        provenance={"confidence": 0.21},
    )
    card = gov.provenance_card(get_capsule(result["capsule_id"]))
    assert card["confidence"] == 0.21


# ---------------------------------------------------------------------------
# 删除验证
# ---------------------------------------------------------------------------


def test_verify_deletion_complete_after_soft_delete(isolated_db):
    """规范验收标准 2：删除后各项残留为零。"""
    result = _write("软删验证 kilo")
    capsule_id = result["capsule_id"]
    forget_capsules([capsule_id])

    verdict = gov.verify_deletion(capsule_id)
    assert verdict["complete"] is True
    assert verdict["residue_total"] == 0
    assert verdict["vector_pending"] == 0
    assert verdict["residue"]["fts"] == 0
    # 软删保留主表行供审计，但因 lifecycle=forgotten 不计为残留
    assert verdict["residue"]["capsules"] == 0
    assert get_capsule(capsule_id)["state"]["lifecycle"] == "forgotten"


def test_verify_deletion_complete_after_hard_delete(isolated_db):
    result = _write("硬删验证 lima")
    capsule_id = result["capsule_id"]
    forget_capsules([capsule_id], mode="hard_delete")
    verdict = gov.verify_deletion(capsule_id)
    assert verdict["complete"] is True
    assert get_capsule(capsule_id) is None


def test_verify_deletion_detects_live_capsule(isolated_db):
    """没删的记忆必须报残留，否则这个指标毫无意义。"""
    result = _write("尚未删除 mike")
    verdict = gov.verify_deletion(result["capsule_id"])
    assert verdict["complete"] is False
    assert verdict["residue"]["capsules"] == 1
    assert verdict["residue"]["fts"] == 1


def test_verify_deletion_detects_fts_residue(isolated_db):
    """模拟「主表删了但索引没删」——这是删除残留最典型的形态。"""
    result = _write("索引残留 november")
    capsule_id = result["capsule_id"]
    forget_capsules([capsule_id])
    # 手工把 FTS 行塞回去，模拟索引清理失败
    conn = get_conn()
    conn.execute(
        "INSERT INTO memory_capsules_v2_fts(capsule_id,text) VALUES (?,?)",
        (capsule_id, "索引残留 november"),
    )
    conn.commit()

    verdict = gov.verify_deletion(capsule_id)
    assert verdict["complete"] is False
    assert verdict["residue"]["fts"] == 1


def test_verify_deletion_detects_relation_edge_reference(isolated_db):
    """其他胶囊的 relation_edges 里残留反向引用同样算残留。"""
    target = _write("被引用者 oscar")["capsule_id"]
    _write(
        "引用者 papa",
        relation_edges=[{"type": "supports", "to": target}],
    )
    forget_capsules([target])
    verdict = gov.verify_deletion(target)
    assert verdict["complete"] is False
    assert verdict["residue"]["relation_edges"] == 1


def test_verify_deletion_uses_literal_substring_not_like_wildcard(isolated_db):
    """capsule_id 形如 ``cap_ab12`` 自带 ``_``，用 LIKE 会误匹配。

    这里造一个「只差一个字符」的引用：若实现用 LIKE，``_`` 通配符会让它假命中。
    """
    target = _write("通配符检查 quebec")["capsule_id"]
    decoy = target.replace("_", "X", 1)
    _write("引用了相似 id 的胶囊 romeo", relation_edges=[{"type": "ref", "to": decoy}])
    forget_capsules([target])
    verdict = gov.verify_deletion(target)
    assert verdict["residue"]["relation_edges"] == 0
    assert verdict["complete"] is True


def test_verify_deletions_batch(isolated_db):
    clean = _write("批量-已删 sierra")["capsule_id"]
    dirty = _write("批量-未删 tango")["capsule_id"]
    forget_capsules([clean])

    verdict = gov.verify_deletions([clean, dirty])
    assert verdict["checked"] == 2
    assert verdict["complete"] == 1
    assert verdict["all_complete"] is False
    assert [item["capsule_id"] for item in verdict["incomplete"]] == [dirty]


def test_forget_response_carries_deletion_evidence(isolated_db):
    """删除完整性证据随 forget 响应一起返回，调用方不必自己去猜。"""
    capsule_id = _write("随响应带证据 uniform")["capsule_id"]
    result = forget_capsules([capsule_id])
    assert result["deletion_verification"]["all_complete"] is True


def test_forget_reports_rejected_transitions_instead_of_raising(isolated_db):
    """批量遗忘对非法转移是「跳过并上报」，不抛异常掀翻整批。

    这是与单条 FSM 端点有意不同的语义：forget_capsules_in_transaction 的既有
    契约是「跳过查不到的 id」，硬抛会破坏批量调用方。
    """
    capsule_id = _write("二次硬删 victor")["capsule_id"]
    forget_capsules([capsule_id], mode="hard_delete")
    # 行已物理删除，第二次调用查不到 → 既不删也不报错
    again = forget_capsules([capsule_id], mode="hard_delete")
    assert again["deleted_capsule_ids"] == []
    assert again["rejected_transitions"] == []

    soft_id = _write("软删后再硬删 whiskey")["capsule_id"]
    forget_capsules([soft_id])
    upgraded = forget_capsules([soft_id], mode="hard_delete")
    assert upgraded["deleted_capsule_ids"] == [soft_id]
    assert upgraded["rejected_transitions"] == []


def test_forget_rejects_illegal_transition_from_deleted(isolated_db):
    """软删后再软删：forgotten → forgotten 是幂等，不算非法。"""
    capsule_id = _write("重复软删 xray")["capsule_id"]
    forget_capsules([capsule_id])
    second = forget_capsules([capsule_id])
    assert second["rejected_transitions"] == []
    assert second["deleted_capsule_ids"] == [capsule_id]


# ---------------------------------------------------------------------------
# MHG 事故与发布闸门
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "level,expected",
    [
        (1, set()),
        (2, {"alert"}),
        (3, {"alert", "publish_freeze"}),
        (4, {"alert", "publish_freeze", "rollback", "red_team_review"}),
        (5, {"alert", "publish_freeze", "rollback", "red_team_review",
             "full_audit", "ledger_export"}),
    ],
)
def test_mhg_actions_match_spec_table(isolated_db, level, expected):
    incident = gov.record_incident(level, "leakage", description=f"level {level}")
    assert set(incident["actions"]) == expected
    assert incident["publish_freeze"] is (level >= 3)


def test_invalid_mhg_level_rejected(isolated_db):
    with pytest.raises(ValueError):
        gov.record_incident(0, "leakage")
    with pytest.raises(ValueError):
        gov.record_incident(6, "leakage")


def test_release_gate_clean_when_no_incidents(isolated_db):
    gate = gov.release_gate()
    assert gate["frozen"] is False
    assert gate["blocking_incidents"] == []


def test_mhg3_freezes_release(isolated_db):
    """规范验收标准 4：MHG-3+ 触发 publish_freeze。"""
    gov.record_incident(2, "poisoning", description="低级事故不冻结")
    assert gov.release_gate()["frozen"] is False

    incident = gov.record_incident(3, "leakage", description="敏感记忆泄漏到错误 scope")
    gate = gov.release_gate()
    assert gate["frozen"] is True
    assert gate["reason"] == "unresolved_mhg3_plus_incidents"
    assert incident["incident_id"] in [item["incident_id"] for item in gate["blocking_incidents"]]


def test_resolving_incident_lifts_freeze(isolated_db):
    incident = gov.record_incident(4, "poisoning", description="投毒触发高风险工具")
    assert gov.release_gate()["frozen"] is True

    resolved = gov.resolve_incident(incident["incident_id"], resolution="rolled_back")
    assert resolved is not None
    assert gov.release_gate()["frozen"] is False

    # 幂等：已解决的事故再解决返回 None
    assert gov.resolve_incident(incident["incident_id"]) is None


def test_incident_with_capsule_writes_ledger(isolated_db):
    capsule_id = _write("涉事记忆 yankee")["capsule_id"]
    gov.record_incident(4, "poisoning", capsule_id=capsule_id, detected_by="red_team")
    entries = gov.ledger_history(capsule_id)
    assert any(row["risk_class"] == "critical" for row in entries)
    assert any("mhg4" in (row["reason"] or "") for row in entries)


def test_list_incidents_filters(isolated_db):
    gov.record_incident(1, "other", description="轻微")
    high = gov.record_incident(5, "leakage", description="跨租户泄漏")
    gov.resolve_incident(high["incident_id"])
    low_only = gov.record_incident(3, "deletion_failure", description="删除残留")

    unresolved = gov.list_incidents(unresolved_only=True, min_mhg=3)
    ids = [item["incident_id"] for item in unresolved]
    assert low_only["incident_id"] in ids
    assert high["incident_id"] not in ids
    assert all(isinstance(item["actions"], list) for item in unresolved)
