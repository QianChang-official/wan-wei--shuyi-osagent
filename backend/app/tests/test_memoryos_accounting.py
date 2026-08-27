"""MemoryOS 经济账本测试（规范: AI优化/MemoryOS-Accounting经济账本.md §7 验收标准）。

覆盖规范列出的四条验收标准：
1. 写入/召回/维护三事件都有记账
2. ROI 自动重算（写入后、召回后）
3. 有害召回 ROI 转负
4. Decay Panel 数据来源 = decay_candidates()
"""

import pytest

from backend.app.db import get_conn, transaction
from backend.app.memoryos import accounting as acct
from backend.app.memory_runtime.capsule_store import get_capsule, write_capsule
from backend.app.memory_runtime.evolution import reflect_task
from backend.app.memory_runtime.retrieval import search_capsules


def _write(statement: str, **kwargs) -> str:
    return write_capsule(
        memory_class=kwargs.pop("memory_class", "knowledge"),
        content={"knowledge_type": "fact", "statement": statement},
        source_type=kwargs.pop("source_type", "manual_config"),
        **kwargs,
    )["capsule_id"]


def _age_account(capsule_id: str, days: float) -> None:
    """把账��� created_at 往前推，绕过 Decay Panel 的宽限期。"""
    with transaction() as conn:
        conn.execute(
            "UPDATE memory_accounts SET created_at=datetime('now', ?) WHERE capsule_id=?",
            (f"-{days} days", capsule_id),
        )


# ---------------------------------------------------------------------------
# 成本配置
# ---------------------------------------------------------------------------


def test_cost_config_reads_env(monkeypatch):
    monkeypatch.setenv("WANWEI_MEMORY_TOKEN_COST", "0.001")
    config = acct.CostConfig.from_env()
    assert config.token_cost == 0.001


def test_cost_config_tolerates_bad_env(monkeypatch):
    """配置写错不该让写入记忆整体失败——回退默认值即可。"""
    monkeypatch.setenv("WANWEI_MEMORY_TOKEN_COST", "not-a-number")
    assert acct.CostConfig.from_env().token_cost == 0.000002


def test_estimate_tokens_never_zero():
    assert acct.estimate_tokens("") >= 1
    assert acct.estimate_tokens("a" * 100) == 30
    assert acct.estimate_tokens(1000) == 300


# ---------------------------------------------------------------------------
# 1. 三事件记账
# ---------------------------------------------------------------------------


def test_write_creates_account(isolated_db):
    capsule_id = _write("记账写入 alpha")
    account = acct.account_for(capsule_id)
    assert account is not None
    assert account["storage_cost"] > 0
    assert account["total_cost"] > 0
    assert account["utility"] == 0
    # 尚未产生任何收益 → ROI 为 -1（成本已付、收益为零）
    assert account["roi"] == pytest.approx(-1.0)


def test_rejected_write_has_no_account(isolated_db):
    """被闸门拒绝的写入没落库，不该产生账户。"""
    result = write_capsule(
        memory_class="knowledge",
        content={"knowledge_type": "fact", "statement": "密码是 Hunter2Prod!"},
        source_type="user_input",
    )
    assert result["governance"]["policy_result"] == "reject"
    assert acct.account_for(result["capsule_id"]) is None


def test_search_records_neutral_recall(isolated_db):
    """检索先记 neutral：当下还不知道这条记忆有没有帮上忙。"""
    capsule_id = _write("检索记账 bravo")
    search_capsules("bravo")
    account = acct.account_for(capsule_id)
    assert account["neutral_recalls"] == 1
    assert account["retrieval_cost"] > 0
    assert account["utility"] == pytest.approx(0.1)
    assert account["last_accessed"]


def test_maintenance_accounting(isolated_db):
    capsule_id = _write("维护记账 charlie")
    before = acct.account_for(capsule_id)["total_cost"]
    acct.record_maintenance([capsule_id])
    after = acct.account_for(capsule_id)
    assert after["maintenance_cost"] > 0
    assert after["total_cost"] > before


def test_maintenance_empty_is_noop(isolated_db):
    acct.record_maintenance([])  # 不应抛异常


def test_accounts_backfilled_for_pre_existing_memories(isolated_db):
    """账本上线前写入的记忆没有账户，召回时必须补零行而不是静默丢弃成本。"""
    capsule_id = _write("补行 delta")
    with transaction() as conn:
        conn.execute("DELETE FROM memory_accounts WHERE capsule_id=?", (capsule_id,))
    assert acct.account_for(capsule_id) is None

    with transaction() as conn:
        acct.record_recalls_in_transaction(conn, [(capsule_id, "neutral", 50)])
    account = acct.account_for(capsule_id)
    assert account is not None
    assert account["neutral_recalls"] == 1


def test_unknown_outcome_rejected(isolated_db):
    capsule_id = _write("非法 outcome echo")
    with pytest.raises(ValueError, match="unknown recall outcome"):
        with transaction() as conn:
            acct.record_recalls_in_transaction(conn, [(capsule_id, "wonderful", 10)])
    with pytest.raises(ValueError, match="unknown recall outcome"):
        acct.settle_recall_outcome([capsule_id], "wonderful")


# ---------------------------------------------------------------------------
# 2 & 3. ROI 重算与有害召回转负
# ---------------------------------------------------------------------------


def test_useful_recall_makes_roi_positive(isolated_db):
    capsule_id = _write("有用召回 foxtrot")
    acct.settle_recall_outcome([capsule_id], "useful")
    account = acct.account_for(capsule_id)
    assert account["useful_recalls"] == 1
    assert account["utility"] == pytest.approx(1.0)
    assert account["roi"] > 0


def test_harmful_recall_makes_roi_negative(isolated_db):
    """规范验收标准 3：有害召回 ROI 转负。"""
    capsule_id = _write("有害召回 golf")
    acct.settle_recall_outcome([capsule_id], "harmful")
    account = acct.account_for(capsule_id)
    assert account["harmful_recalls"] == 1
    assert account["utility"] == pytest.approx(-2.0)
    assert account["roi"] < 0


def test_settle_converts_existing_neutral_recall(isolated_db):
    """回填是「改判」而不是「追加」：neutral 减一，目标加一，收益补差额。"""
    capsule_id = _write("改判 hotel")
    search_capsules("hotel")
    assert acct.account_for(capsule_id)["neutral_recalls"] == 1

    acct.settle_recall_outcome([capsule_id], "useful")
    account = acct.account_for(capsule_id)
    assert account["neutral_recalls"] == 0
    assert account["useful_recalls"] == 1
    # 0.1（neutral）+ 0.9（补到 useful 的差额）= 1.0，不是 1.1
    assert account["utility"] == pytest.approx(1.0)


def test_settle_without_prior_neutral_adds_full_utility(isolated_db):
    """记忆被直接引用（未经检索命中）时，按一次新召回记满额收益。"""
    capsule_id = _write("直接引用 india")
    acct.settle_recall_outcome([capsule_id], "useful")
    assert acct.account_for(capsule_id)["utility"] == pytest.approx(1.0)


def test_settle_empty_list_is_noop(isolated_db):
    result = acct.settle_recall_outcome([], "useful")
    assert result["settled"] == 0


def test_settle_dedupes_capsule_ids(isolated_db):
    capsule_id = _write("去重 juliett")
    result = acct.settle_recall_outcome([capsule_id, capsule_id], "useful")
    assert result["settled"] == 1
    assert acct.account_for(capsule_id)["useful_recalls"] == 1


# ---------------------------------------------------------------------------
# 反思 → 收益回填（utility 的真实来源）
# ---------------------------------------------------------------------------


def test_reflection_settles_utility_from_helpful_and_misleading(isolated_db):
    """经济账本 utility 的真实来源：reflect_task 本来就在收集这两个列表。"""
    helpful = _write("帮上忙的记忆 kilo")
    misleading = _write("误导人的记忆 lima")
    search_capsules("kilo")
    search_capsules("lima")

    result = reflect_task(
        "task_settle",
        {"helpful_memories": [helpful], "misleading_memories": [misleading]},
    )

    settles = [a for a in result["evolution_actions"] if a["action"] == "account_settle"]
    assert {a["outcome"] for a in settles} == {"useful", "harmful"}
    assert acct.account_for(helpful)["useful_recalls"] == 1
    assert acct.account_for(helpful)["roi"] > 0
    assert acct.account_for(misleading)["harmful_recalls"] == 1
    assert acct.account_for(misleading)["roi"] < 0


def test_reflection_skips_terminal_capsules_without_crashing(isolated_db):
    """反思报告可能引用本轮中途被删掉的记忆——一条失败不该掀翻整次反思。"""
    from backend.app.memory_runtime.capsule_store import forget_capsules

    alive = _write("仍在的记忆 mike")
    gone = _write("已删的记忆 november")
    forget_capsules([gone])

    result = reflect_task(
        "task_partial",
        {"helpful_memories": [alive, gone]},
    )
    actions = {a["action"] for a in result["evolution_actions"]}
    assert "reinforce" in actions
    assert "reinforce_skipped" in actions
    assert acct.account_for(alive)["useful_recalls"] == 1


# ---------------------------------------------------------------------------
# 4. Decay Panel 三分类
# ---------------------------------------------------------------------------


def test_decay_candidates_respects_grace_period(isolated_db):
    """刚写入的记忆 ROI 天然为 -1，不设宽限期面板会被当天新写的记忆淹没。"""
    _write("刚写入 oscar")
    assert acct.decay_candidates() == []


def test_decay_candidates_lists_aged_negative_roi(isolated_db):
    capsule_id = _write("陈旧无用 papa")
    _age_account(capsule_id, 30)
    candidates = acct.decay_candidates()
    assert [item["capsule_id"] for item in candidates] == [capsule_id]
    assert candidates[0]["classification"] == "archive_candidate"
    assert candidates[0]["rationale"] == "negative_roi"


def test_decay_classifies_harmful_as_delete_candidate(isolated_db):
    capsule_id = _write("误导过的记忆 quebec")
    acct.settle_recall_outcome([capsule_id], "harmful")
    _age_account(capsule_id, 30)
    candidates = acct.decay_candidates()
    assert candidates[0]["classification"] == "delete_candidate"
    assert candidates[0]["rationale"] == "harmful_recall_recorded"


def test_decay_protects_high_importance(isolated_db):
    """高价值记忆即使 ROI 为负也不该被自动清理。"""
    capsule_id = _write("高价值 romeo")
    state = dict(get_capsule(capsule_id)["state"])
    state["importance_score"] = 0.95
    from backend.app.memory_runtime.capsule_store import update_capsule

    update_capsule(capsule_id, state=state)
    _age_account(capsule_id, 30)
    candidates = acct.decay_candidates()
    assert candidates[0]["classification"] == "protected"


def test_decay_protects_long_term_tier(isolated_db):
    capsule_id = _write("长期层 sierra")
    with transaction() as conn:
        conn.execute(
            "UPDATE memory_capsules_v2 SET memory_tier='long_term' WHERE capsule_id=?",
            (capsule_id,),
        )
    _age_account(capsule_id, 30)
    assert acct.decay_candidates()[0]["classification"] == "protected"


def test_decay_protects_sensitive(isolated_db):
    """S1 以上敏感记忆按合规保留，不进自动清理。"""
    capsule_id = _write("联系邮箱 contact@example.com tango")
    assert get_capsule(capsule_id)["governance"]["sensitivity_level"] == "S1"
    _age_account(capsule_id, 30)
    assert acct.decay_candidates()[0]["classification"] == "protected"


def test_decay_excludes_already_forgotten(isolated_db):
    from backend.app.memory_runtime.capsule_store import forget_capsules

    capsule_id = _write("已遗忘 uniform")
    _age_account(capsule_id, 30)
    forget_capsules([capsule_id])
    assert acct.decay_candidates() == []


def test_decay_respects_owner_scope(isolated_db):
    mine = _write("我的负 ROI victor", owner_id="owner_x")
    theirs = _write("别人的负 ROI whiskey", owner_id="owner_y")
    _age_account(mine, 30)
    _age_account(theirs, 30)

    ids = [item["capsule_id"] for item in acct.decay_candidates(owner_id="owner_x")]
    assert mine in ids
    assert theirs not in ids


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------


def test_summary_aggregates(isolated_db):
    good = _write("有用 xray")
    bad = _write("有害 yankee")
    acct.settle_recall_outcome([good], "useful")
    acct.settle_recall_outcome([bad], "harmful")

    summary = acct.summary()
    assert summary["memories"] == 2
    assert summary["useful_recalls"] == 1
    assert summary["harmful_recalls"] == 1
    assert summary["negative_roi_memories"] >= 1
    assert summary["cost_per_useful_recall"] is not None
    assert "token_cost" in summary["cost_config"]


def test_summary_empty_library(isolated_db):
    summary = acct.summary()
    assert summary["memories"] == 0
    assert summary["avg_roi"] == 0.0
    assert summary["cost_per_useful_recall"] is None


def test_summary_respects_owner_scope(isolated_db):
    _write("属主 A zulu", owner_id="owner_a")
    _write("属主 B zulu", owner_id="owner_b")
    assert acct.summary(owner_id="owner_a")["memories"] == 1
    assert acct.summary()["memories"] == 2


# ---------------------------------------------------------------------------
# 热路径性质
# ---------------------------------------------------------------------------


def test_search_adds_no_extra_write_transaction(isolated_db):
    """检索侧记账必须搭 usage 落库的车，不新增写往返。

    直接数 SQLite 的写事务次数不现实，这里退一步验证可观测的等价性质：
    时间窗内重复检索不产生额外的召回记账（说明记账与 usage 门控同源）。
    """
    capsule_id = _write("窗口内重复检索 alfa")
    search_capsules("alfa")
    first = acct.account_for(capsule_id)["neutral_recalls"]
    for _ in range(5):
        search_capsules("alfa")
    assert acct.account_for(capsule_id)["neutral_recalls"] == first


def test_roi_index_exists(isolated_db):
    """负 ROI 查询是 Decay Panel 的主路径，必须有索引兜着。"""
    rows = get_conn().execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='memory_accounts'"
    ).fetchall()
    assert "idx_accounts_roi" in {row["name"] for row in rows}
