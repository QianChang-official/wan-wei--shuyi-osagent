"""Tests for memory tier management (issue #56).

覆盖:
- schema 迁移（幂等、memory_tier 列、tier_transition_log 表、遗留 tier 列回收）
- tier_promote / tier_demote（基本流转、幂等 no-op、非法 tier、方向校验、审计日志）
- run_auto_flow 自动流转规则（闲置晋升 / 过期降级 / 使用频次 / 重要性）
- promote_capsules_for_workflow 批量回调
- get_tier_stats / list_capsules_by_tier / transition_history
- reflect_task 的 workflow 完成回调 hook
"""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.db import get_conn, transaction
from backend.app.init_db import main as init_db_main
from backend.app.memory_runtime.capsule_store import write_capsule
from backend.app.memory_runtime.evolution import reflect_task
from backend.app.memory_runtime.tier_manager import (
    get_tier_stats,
    list_capsules_by_tier,
    promote_capsules_for_workflow,
    run_auto_flow,
    tier_demote,
    tier_promote,
    transition_history,
)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _make_capsule(summary: str = "tier test") -> str:
    cap = write_capsule(
        memory_class="episodic",
        content={"kind": "memory_note", "summary": summary},
        source_type="user_input",
    )
    return cap["capsule_id"]


def _get_tier(capsule_id: str) -> str:
    row = get_conn().execute(
        "SELECT memory_tier FROM memory_capsules_v2 WHERE capsule_id=?",
        (capsule_id,),
    ).fetchone()
    assert row is not None
    return row["memory_tier"]


def _set_state(capsule_id: str, **fields) -> None:
    with transaction() as conn:
        for key, value in fields.items():
            conn.execute(
                f"UPDATE memory_capsules_v2 SET state=json_set(state, '{key}', ?) "
                "WHERE capsule_id=?",
                (value, capsule_id),
            )


def _set_timestamps(capsule_id: str, *, updated_at: str | None = None, created_at: str | None = None) -> None:
    with transaction() as conn:
        if updated_at is not None:
            conn.execute(
                "UPDATE memory_capsules_v2 SET updated_at=? WHERE capsule_id=?",
                (updated_at, capsule_id),
            )
        if created_at is not None:
            conn.execute(
                "UPDATE memory_capsules_v2 SET created_at=? WHERE capsule_id=?",
                (created_at, capsule_id),
            )


# ---------------------------------------------------------------- migration

def test_tier_unification_migration_idempotent(isolated_db):
    """迁移幂等：重复执行 init_db 不报错；memory_tier 列与审计表存在。"""
    init_db_main()  # second run over the same db
    with get_conn() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(memory_capsules_v2)")}
        assert "memory_tier" in columns
        assert "tier" not in columns, "冗余 tier 列不应存在（或已被统一迁移回收）"
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        assert "tier_transition_log" in tables
        migration = conn.execute(
            "SELECT 1 FROM memory_schema_migrations WHERE name='memory_tier_unify_v1'"
        ).fetchone()
        assert migration is not None


def test_legacy_tier_column_folded_back(isolated_db):
    """模拟跑过初版 MVP 迁移的库：遗留 tier 列的值应合并进 memory_tier 并被回收。"""
    capsule_id = _make_capsule("legacy tier row")
    with transaction() as conn:
        # 复刻旧迁移留下的现场：多余的 tier 列 + 旧迁移记录
        conn.execute(
            "ALTER TABLE memory_capsules_v2 ADD COLUMN tier TEXT NOT NULL DEFAULT 'working'"
        )
        conn.execute(
            "INSERT OR REPLACE INTO memory_schema_migrations(name, applied_at) "
            "VALUES ('memory_tier_column_v1', '2026-08-07T00:00:00Z')"
        )
        conn.execute(
            "DELETE FROM memory_schema_migrations WHERE name='memory_tier_unify_v1'"
        )
        # 旧代码路径可能写过 tier 而 memory_tier 仍是默认 working
        conn.execute(
            "UPDATE memory_capsules_v2 SET tier='short_term' WHERE capsule_id=?",
            (capsule_id,),
        )

    init_db_main()  # 重放统一迁移

    with get_conn() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(memory_capsules_v2)")}
        if sqlite3.sqlite_version_info >= (3, 35, 0):
            assert "tier" not in columns, "SQLite>=3.35 应 DROP 遗留 tier 列"
        row = conn.execute(
            "SELECT memory_tier FROM memory_capsules_v2 WHERE capsule_id=?",
            (capsule_id,),
        ).fetchone()
        assert row["memory_tier"] == "short_term", "遗留 tier 值应合并进 memory_tier"


# ------------------------------------------------------- manual transitions

def test_tier_promote(isolated_db):
    capsule_id = _make_capsule("promote basic")
    assert _get_tier(capsule_id) == "working", "新 capsule 默认 working 层"

    result = tier_promote(capsule_id, to_tier="short_term", reason="test promotion")
    assert result["changed"] is True
    assert result["from_tier"] == "working"
    assert result["to_tier"] == "short_term"
    assert _get_tier(capsule_id) == "short_term"

    # 幂等 no-op
    again = tier_promote(capsule_id, to_tier="short_term", reason="redundant")
    assert again["changed"] is False
    assert again["reason"] == "already_at_target_tier"


def test_tier_promote_supports_skip_levels(isolated_db):
    capsule_id = _make_capsule("skip levels")
    result = tier_promote(capsule_id, to_tier="long_term", reason="user pinned")
    assert result["changed"] is True
    assert _get_tier(capsule_id) == "long_term"


def test_tier_demote(isolated_db):
    capsule_id = _make_capsule("demote basic")
    tier_promote(capsule_id, to_tier="medium_term", reason="setup")

    result = tier_demote(capsule_id, to_tier="short_term", reason="test demotion")
    assert result["changed"] is True
    assert result["from_tier"] == "medium_term"
    assert result["to_tier"] == "short_term"
    assert _get_tier(capsule_id) == "short_term"


def test_tier_transition_direction_guard(isolated_db):
    """promote 不允许降级、demote 不允许升级——方向语义必须严格。"""
    capsule_id = _make_capsule("direction guard")
    tier_promote(capsule_id, to_tier="medium_term", reason="setup")

    with pytest.raises(ValueError, match="use tier_demote"):
        tier_promote(capsule_id, to_tier="working", reason="wrong direction")
    with pytest.raises(ValueError, match="use tier_promote"):
        tier_demote(capsule_id, to_tier="long_term", reason="wrong direction")


def test_tier_promote_invalid_tier(isolated_db):
    capsule_id = _make_capsule("invalid tier")
    with pytest.raises(ValueError, match="Invalid tier"):
        tier_promote(capsule_id, to_tier="超长期", reason="invalid")


def test_tier_promote_nonexistent_capsule(isolated_db):
    with pytest.raises(ValueError, match="not found"):
        tier_promote("cap_nonexistent_id", to_tier="short_term", reason="test")


def test_tier_transition_audit_log(isolated_db):
    """每次流转必须写 tier_transition_log（审计追溯）。"""
    capsule_id = _make_capsule("audit trail")
    tier_promote(capsule_id, to_tier="short_term", reason="first")
    tier_promote(capsule_id, to_tier="medium_term", reason="second")
    tier_demote(capsule_id, to_tier="working", reason="third")

    history = transition_history(capsule_id)
    assert len(history) == 3
    # 倒序：最新在前
    assert history[0]["from_tier"] == "medium_term"
    assert history[0]["to_tier"] == "working"
    assert history[0]["reason"] == "third"
    assert history[0]["trigger_source"] == "manual"
    assert history[2]["from_tier"] == "working"
    assert history[2]["to_tier"] == "short_term"


# ------------------------------------------------------------- auto flow

def test_auto_flow_promotes_idle_working(isolated_db):
    """working 层闲置 ≥24h 自动晋升 short_term。"""
    capsule_id = _make_capsule("idle working")
    stale = _iso(datetime.now(timezone.utc) - timedelta(hours=25))
    _set_timestamps(capsule_id, updated_at=stale)

    summary = run_auto_flow()
    assert any(r["capsule_id"] == capsule_id for r in summary["promoted"])
    assert _get_tier(capsule_id) == "short_term"


def test_auto_flow_keeps_fresh_working(isolated_db):
    """刚写入/刚访问的 working 层不流转。"""
    capsule_id = _make_capsule("fresh working")
    summary = run_auto_flow()
    assert all(r["capsule_id"] != capsule_id for r in summary["promoted"])
    assert _get_tier(capsule_id) == "working"


def test_auto_flow_expires_short_term(isolated_db):
    """short_term 超过 TTL 未访问 → 降回 working（过期回收，不丢数据）。"""
    capsule_id = _make_capsule("expired short")
    tier_promote(capsule_id, to_tier="short_term", reason="setup")
    stale = _iso(datetime.now(timezone.utc) - timedelta(hours=30))
    _set_timestamps(capsule_id, updated_at=stale)

    summary = run_auto_flow()
    assert any(
        r["capsule_id"] == capsule_id and r["to_tier"] == "working"
        for r in summary["demoted"]
    )
    assert _get_tier(capsule_id) == "working"


def test_auto_flow_promotes_short_to_medium_by_usage(isolated_db):
    """short_term usage_count ≥5 → medium_term。"""
    capsule_id = _make_capsule("frequent short")
    tier_promote(capsule_id, to_tier="short_term", reason="setup")
    _set_state(capsule_id, **{"$.usage_count": 6})
    # 保持新鲜，避免先命中过期降级
    _set_state(capsule_id, **{"$.last_accessed_at": _iso(datetime.now(timezone.utc))})

    summary = run_auto_flow()
    assert any(
        r["capsule_id"] == capsule_id and r["to_tier"] == "medium_term"
        for r in summary["promoted"]
    )
    assert _get_tier(capsule_id) == "medium_term"


def test_auto_flow_promotes_medium_to_long_by_importance(isolated_db):
    """medium_term importance ≥0.8 → long_term。"""
    capsule_id = _make_capsule("important medium")
    tier_promote(capsule_id, to_tier="medium_term", reason="setup")
    _set_state(capsule_id, **{"$.importance_score": 0.85})
    _set_state(capsule_id, **{"$.last_accessed_at": _iso(datetime.now(timezone.utc))})

    summary = run_auto_flow()
    assert any(
        r["capsule_id"] == capsule_id and r["to_tier"] == "long_term"
        for r in summary["promoted"]
    )
    assert _get_tier(capsule_id) == "long_term"


def test_auto_flow_demotes_idle_medium(isolated_db):
    """medium_term 闲置 ≥7 天 → 降回 short_term。"""
    capsule_id = _make_capsule("idle medium")
    tier_promote(capsule_id, to_tier="medium_term", reason="setup")
    stale = _iso(datetime.now(timezone.utc) - timedelta(days=8))
    _set_timestamps(capsule_id, updated_at=stale)

    summary = run_auto_flow()
    assert any(
        r["capsule_id"] == capsule_id and r["to_tier"] == "short_term"
        for r in summary["demoted"]
    )
    assert _get_tier(capsule_id) == "short_term"


def test_auto_flow_skips_non_flowable_lifecycle(isolated_db):
    """quarantined / deprecated 等 lifecycle 不参与自动流转。"""
    capsule_id = _make_capsule("quarantined capsule")
    _set_state(capsule_id, **{"$.lifecycle": "quarantined"})
    stale = _iso(datetime.now(timezone.utc) - timedelta(days=30))
    _set_timestamps(capsule_id, updated_at=stale)

    summary = run_auto_flow()
    assert all(r["capsule_id"] != capsule_id for r in summary["promoted"])
    assert all(r["capsule_id"] != capsule_id for r in summary["demoted"])
    assert _get_tier(capsule_id) == "working"


# ------------------------------------------------------ workflow callback

def test_promote_capsules_for_workflow(isolated_db):
    """workflow 完成回调：working 批量晋升 short_term，更高层保持不动。"""
    working_id = _make_capsule("workflow working")
    medium_id = _make_capsule("workflow medium")
    tier_promote(medium_id, to_tier="medium_term", reason="preset")

    results = promote_capsules_for_workflow([working_id, medium_id, "cap_missing"])
    by_id = {r["capsule_id"]: r for r in results}

    assert by_id[working_id]["changed"] is True
    assert by_id[working_id]["to_tier"] == "short_term"
    assert by_id[medium_id]["changed"] is False
    assert by_id[medium_id]["reason"] == "already_medium_term"
    assert by_id["cap_missing"]["changed"] is False
    assert by_id["cap_missing"]["reason"] == "not_found"
    assert _get_tier(working_id) == "short_term"


def test_reflect_task_triggers_tier_promotion(isolated_db):
    """reflect_task（workflow 反思入口）对 helpful 记忆自动晋升 short_term。"""
    capsule_id = _make_capsule("helpful memory")
    result = reflect_task(
        "task_tier_hook",
        {"goal_achieved": True, "helpful_memories": [capsule_id]},
    )
    tier_actions = [a for a in result["evolution_actions"] if a["action"] == "tier_promote"]
    assert tier_actions, "reflect_task 应产生 tier_promote 动作"
    assert capsule_id in tier_actions[0]["capsule_ids"]
    assert _get_tier(capsule_id) == "short_term"


# ------------------------------------------------------------------ queries

def test_list_capsules_by_tier_and_stats(isolated_db):
    a = _make_capsule("tier list A")
    b = _make_capsule("tier list B")
    _make_capsule("tier list C")  # stays working
    tier_promote(a, to_tier="short_term", reason="setup")
    tier_promote(b, to_tier="long_term", reason="setup")

    short_items = list_capsules_by_tier("short_term")
    assert [item["capsule_id"] for item in short_items] == [a]

    stats = get_tier_stats()
    assert stats["short_term"] == 1
    assert stats["long_term"] == 1
    assert stats["working"] == 1
    assert stats["medium_term"] == 0

    with pytest.raises(ValueError, match="Invalid tier"):
        list_capsules_by_tier("not_a_tier")


# ------------------------------------------- review hardening (#63 kilo)

def test_transition_writes_audit_in_same_transaction(isolated_db):
    """tier 变更与 audit 行同事务提交（双通道不脱节）。"""
    capsule_id = _make_capsule("audit same-tx")
    tier_promote(capsule_id, to_tier="short_term", reason="audit check")

    row = get_conn().execute(
        "SELECT payload FROM audit_logs WHERE event_type='tier_transition' "
        "ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    assert row is not None, "audit_logs 应存在 tier_transition 记录"
    payload = json.loads(row["payload"])
    assert payload["capsule_id"] == capsule_id
    assert payload["from_tier"] == "working"
    assert payload["to_tier"] == "short_term"


def test_get_tier_stats_surfaces_unknown_tier(isolated_db, caplog):
    """未知 tier 值必须保留在统计中（不静默丢弃）并记 warning。"""
    capsule_id = _make_capsule("corrupted tier")
    with transaction() as conn:
        conn.execute(
            "UPDATE memory_capsules_v2 SET memory_tier='corrupted_tier' WHERE capsule_id=?",
            (capsule_id,),
        )

    with caplog.at_level("WARNING", logger="backend.app.memory_runtime.tier_manager"):
        stats = get_tier_stats()
    assert stats["corrupted_tier"] == 1, "未知 tier 应单列计数而非被吞掉"
    assert any("corrupted_tier" in r.message for r in caplog.records)


def test_workflow_promote_system_error_is_distinguishable(isolated_db, monkeypatch, caplog):
    """系统级故障标记为 system_error:{Type} 并记日志，与业务拒绝可区分。"""
    from backend.app.memory_runtime import tier_manager as tm

    capsule_id = _make_capsule("system failure path")

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(tm, "get_capsule", boom)
    with caplog.at_level("WARNING", logger="backend.app.memory_runtime.tier_manager"):
        results = promote_capsules_for_workflow([capsule_id])

    assert results[0]["changed"] is False
    assert results[0]["reason"] == "system_error:RuntimeError"
    assert any("workflow tier promote failed" in r.message for r in caplog.records)


def test_tier_history_api_requires_visible_capsule(isolated_db, monkeypatch):
    """history 端点：不可见/不存在的 capsule 返回 404，不泄露流转元数据。"""
    from fastapi.testclient import TestClient
    from backend.app import main as main_module

    monkeypatch.delenv("WANWEI_PRODUCTION", raising=False)
    monkeypatch.setenv("WANWEI_API_KEY", "tier-history-test-key")
    capsule_id = _make_capsule("history api target")
    tier_promote(capsule_id, to_tier="short_term", reason="setup")

    with TestClient(main_module.app) as client:
        headers = {"X-API-Key": "tier-history-test-key"}
        ok = client.get(f"/memory/tier/history/{capsule_id}", headers=headers)
        missing = client.get("/memory/tier/history/cap_ghost", headers=headers)
        no_auth = client.get(f"/memory/tier/history/{capsule_id}")

    assert ok.status_code == 200
    body = ok.json()
    assert body["capsule_id"] == capsule_id
    assert len(body["items"]) == 1
    assert body["items"][0]["to_tier"] == "short_term"
    assert missing.status_code == 404
    assert no_auth.status_code in (401, 403)
