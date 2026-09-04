"""Active Knowledge Selection 测试（issue #202 验收：有效知识选择 / 裁决建议）。

锁定行为：
1. ``knowledge_confidence`` 四因子（recency/trust/source_authority/usage）
   各自的因果方向；分解随分数返回（可解释）。
2. ``suggest_active_knowledge``：新近 / 高来源可信度的一方胜出；
   **auto_execute 恒 False**（建议式裁决——治理底线：不自动覆盖）。
3. suggest 之后双方生命周期不变；生效路径是 evolve_knowledge 或
   resolve_conflict。
4. 空输入 / 查不到的 id → suggested_active=None（诚实降级）+ unknown_ids。
5. 显式 weights 参数覆盖默认权重。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.app.memory_runtime import knowledge_evolution as ke
from backend.app.memory_runtime.capsule_store import get_capsule, write_capsule


def _know(text: str, source_type: str = "user_input") -> str:
    return write_capsule(
        memory_class="knowledge", content={"text": text}, source_type=source_type
    )["capsule_id"]


def test_confidence_factors_recency_direction(isolated_db):
    """新知识 recency 因子高于 100 天前的旧知识。"""
    from backend.app.db import get_conn

    fresh = _know("端口 = 9000")
    stale = _know("端口 = 8080")
    past = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
    # 回拨 created_at 与 updated_at：write_capsule 两者都落在写入时刻，
    # 只拨 created_at 会被 updated_at 掩蔽（写入即最后更新）。
    get_conn().execute(
        "UPDATE memory_capsules_v2 SET created_at=?, updated_at=? WHERE capsule_id=?",
        (past, past, stale),
    )
    get_conn().commit()

    at = datetime.now(timezone.utc)
    c_fresh = ke.knowledge_confidence(get_capsule(fresh), at=at)
    c_stale = ke.knowledge_confidence(get_capsule(stale), at=at)
    assert c_fresh["factors"]["recency"] > c_stale["factors"]["recency"]
    assert c_fresh["score"] > c_stale["score"]


def test_confidence_factors_source_authority(isolated_db):
    """manual_config（1.0）> tool_result（0.2）——source 因子因果方向。"""
    manual = get_capsule(_know("配置项 A", source_type="manual_config"))
    tool = get_capsule(_know("配置项 B", source_type="tool_result"))
    c_manual = ke.knowledge_confidence(manual)
    c_tool = ke.knowledge_confidence(tool)
    assert c_manual["factors"]["source_authority"] > c_tool["factors"]["source_authority"]
    assert c_manual["score"] > c_tool["score"]


def test_confidence_factors_usage(isolated_db):
    """usage_count 高的知识 usage 因子高（log 压缩归一）。"""
    from backend.app.memory_runtime.capsule_store import update_capsule

    used = _know("常用知识")
    unused = _know("冷知识")
    update_capsule(used, state={
        **get_capsule(used)["state"], "usage_count": 50,
    })

    c_used = ke.knowledge_confidence(get_capsule(used))
    c_unused = ke.knowledge_confidence(get_capsule(unused))
    assert c_used["factors"]["usage"] > c_unused["factors"]["usage"]


def test_confidence_factors_explained(isolated_db):
    """每个分数带四因子分解（可解释性）。"""
    cap = get_capsule(_know("任意知识"))
    kc = ke.knowledge_confidence(cap)
    assert set(kc["factors"]) == {
        "recency", "trust", "source_authority", "usage",
    }
    assert 0.0 <= kc["score"] <= 1.0


def test_confidence_custom_weights(isolated_db):
    """显式 weights 覆盖默认权重（消融口径）。"""
    cap = get_capsule(_know("任意知识"))
    default = ke.knowledge_confidence(cap)
    recency_only = ke.knowledge_confidence(
        cap,
        weights={"recency": 1.0, "trust": 0.0, "source_authority": 0.0, "usage": 0.0},
    )
    assert recency_only["score"] == pytest.approx(default["factors"]["recency"], abs=1e-4)


def test_suggest_prefers_newer_knowledge(isolated_db):
    """新知识（recency 占优）在建议中胜出。"""
    from datetime import datetime, timedelta, timezone

    from backend.app.db import get_conn

    old = _know("默认浏览器 = Firefox")
    new = _know("默认浏览器 = Chrome")
    # 同秒写入时四因子同分且 created_at 相同，裁决退化为 id 字典序
    # （非确定）。回拨旧知识一秒，让「新知识更新」成为确定事实。
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    get_conn().execute(
        "UPDATE memory_capsules_v2 SET created_at=?, updated_at=? WHERE capsule_id=?",
        (past, past, old),
    )
    get_conn().commit()

    suggestion = ke.suggest_active_knowledge([old, new])
    assert suggestion["suggested_active"] == new
    assert suggestion["auto_execute"] is False
    assert suggestion["ranking"][0]["capsule_id"] == new


def test_suggest_prefers_higher_authority_source(isolated_db):
    """同新近度下，manual_config 来源胜过 tool_result。"""
    tool_based = _know("端口 = 8080", source_type="tool_result")
    manual = _know("端口 = 9000", source_type="manual_config")

    suggestion = ke.suggest_active_knowledge([tool_based, manual])
    assert suggestion["suggested_active"] == manual


def test_suggest_reports_factors_and_ranking(isolated_db):
    a = _know("知识 A")
    b = _know("知识 B")
    suggestion = ke.suggest_active_knowledge([a, b])
    assert set(suggestion["suggested_active_factors"]) == {
        "recency", "trust", "source_authority", "usage",
    }
    assert {r["capsule_id"] for r in suggestion["ranking"]} == {a, b}


def test_suggest_never_executes(isolated_db):
    """建议式裁决硬边界：suggest 后双方生命周期不变。"""
    a = _know("端口 = 8080")
    b = _know("端口 = 9000")
    ke.evolve_knowledge(b, a, edge_type="conflicts_with")
    suggestion = ke.suggest_active_knowledge([a, b])

    assert suggestion["auto_execute"] is False
    assert "evolve_knowledge" in suggestion["note"]
    for cid in (a, b):
        assert get_capsule(cid)["state"]["lifecycle"] == "active"


def test_suggest_degrades_honestly(isolated_db):
    empty = ke.suggest_active_knowledge([])
    assert empty["suggested_active"] is None

    missing = ke.suggest_active_knowledge(["cap_missing"])
    assert missing["suggested_active"] is None
    assert missing["unknown_ids"] == ["cap_missing"]


def test_suggest_skips_non_knowledge(isolated_db):
    pref = write_capsule(
        memory_class="preference", content={"subject": "e", "statement": "喜欢 X"}
    )["capsule_id"]
    suggestion = ke.suggest_active_knowledge([pref])
    assert suggestion["suggested_active"] is None
