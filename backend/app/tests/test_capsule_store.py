"""
T2 core-module unit tests — capsule_store.py

覆盖核心记忆操作：write / get / list / update / forget / allowed_for_context。
使用 conftest.py 的 isolated_db fixture 保证测试隔离。

v0.9.6 stability-perf-baseline
"""

import pytest

from backend.app.memory_runtime import capsule_store as cs


def _write_basic(content=None, **kwargs):
    return cs.write_capsule(
        memory_class="knowledge",
        content=content or {"text": "周报应使用正式语气和三段式结构"},
        **kwargs,
    )


# ---------------------------------------------------------------------------
# helpers: now / dumps / loads
# ---------------------------------------------------------------------------

def test_now_is_compact_utc():
    ts = cs.now()
    assert ts.endswith("Z")
    assert "T" in ts


def test_dumps_is_sorted_and_unicode():
    s = cs.dumps({"b": 1, "a": "中文"})
    # sort_keys => 'a' before 'b'
    assert s.index('"a"') < s.index('"b"')
    # ensure_ascii=False => raw CJK preserved
    assert "中文" in s


def test_loads_roundtrip_and_default():
    assert cs.loads(None, default={"x": 1}) == {"x": 1}
    assert cs.loads('{"k": 2}') == {"k": 2}


def test_lifecycle_for_policy_mapping():
    assert cs._lifecycle_for_policy("quarantine") == "quarantined"
    assert cs._lifecycle_for_policy("reject") == "rejected"
    assert cs._lifecycle_for_policy("require_confirmation") == "candidate"
    assert cs._lifecycle_for_policy("allow") == "active"


# ---------------------------------------------------------------------------
# write_capsule
# ---------------------------------------------------------------------------

def test_write_capsule_basic(isolated_db):
    res = _write_basic()
    assert res["capsule_id"].startswith("cap_")
    assert res["memory_class"] == "knowledge"
    assert res["governance"]["policy_result"] == "allow"
    assert res["state"]["lifecycle"] == "active"
    assert "audit_id" in res


def test_write_capsule_rejects_secret_not_in_fts(isolated_db):
    # secret content should be rejected and NOT indexed in FTS
    res = _write_basic(content={"text": "password: hunter2trustme"})
    assert res["governance"]["policy_result"] == "reject"
    assert res["state"]["lifecycle"] == "rejected"
    # confirm not searchable
    hits = cs.get_conn().execute(
        "SELECT capsule_id FROM memory_capsules_v2_fts WHERE capsule_id=?",
        (res["capsule_id"],),
    ).fetchall()
    assert hits == []


def test_write_capsule_persists_row(isolated_db):
    res = _write_basic()
    got = cs.get_capsule(res["capsule_id"])
    assert got is not None
    assert got["capsule_id"] == res["capsule_id"]
    assert isinstance(got["content"], dict)
    assert isinstance(got["state"], dict)
    assert isinstance(got["relation_edges"], list)


def test_write_capsule_default_provenance_and_context(isolated_db):
    res = _write_basic(source_type="user_input", scene="weekly_report")
    got = cs.get_capsule(res["capsule_id"])
    assert got["provenance"]["origin"] == "human"
    assert got["provenance"]["verified"] is True
    assert got["production_context"]["scene"] == "weekly_report"


# ---------------------------------------------------------------------------
# get_capsule
# ---------------------------------------------------------------------------

def test_get_capsule_missing_returns_none(isolated_db):
    assert cs.get_capsule("cap_does_not_exist") is None


# ---------------------------------------------------------------------------
# list_capsules
# ---------------------------------------------------------------------------

def test_list_capsules_excludes_rejected(isolated_db):
    ok = _write_basic(content={"text": "正常知识条目一"})
    _write_basic(content={"text": "token: abcdefabcdef123456"})  # rejected
    ids = [c["capsule_id"] for c in cs.list_capsules(limit=50)]
    assert ok["capsule_id"] in ids
    # rejected lifecycle should be filtered out
    for c in cs.list_capsules(limit=50):
        assert c["state"]["lifecycle"] not in ("forgotten", "deleted", "rejected")


def test_list_capsules_respects_limit(isolated_db):
    for i in range(5):
        _write_basic(content={"text": f"条目 {i}"})
    assert len(cs.list_capsules(limit=3)) == 3


# ---------------------------------------------------------------------------
# update_capsule
# ---------------------------------------------------------------------------

def test_update_capsule_changes_state(isolated_db):
    res = _write_basic()
    new_state = dict(res["state"])
    new_state["usage_count"] = 7
    updated = cs.update_capsule(res["capsule_id"], state=new_state)
    assert updated["state"]["usage_count"] == 7


def test_update_capsule_missing_raises(isolated_db):
    with pytest.raises(KeyError):
        cs.update_capsule("cap_missing", state={"lifecycle": "active"})


def test_update_capsule_edges(isolated_db):
    res = _write_basic()
    edges = [{"type": "supports", "target": "cap_other"}]
    updated = cs.update_capsule(res["capsule_id"], relation_edges=edges)
    assert updated["relation_edges"] == edges


# ---------------------------------------------------------------------------
# forget_capsules
# ---------------------------------------------------------------------------

def test_forget_capsules_soft_delete(isolated_db):
    res = _write_basic()
    out = cs.forget_capsules([res["capsule_id"]])
    assert out["status"] == "forgotten"
    assert res["capsule_id"] in out["deleted_capsule_ids"]
    got = cs.get_capsule(res["capsule_id"])
    assert got["state"]["lifecycle"] == "forgotten"
    # removed from FTS
    hits = cs.get_conn().execute(
        "SELECT capsule_id FROM memory_capsules_v2_fts WHERE capsule_id=?",
        (res["capsule_id"],),
    ).fetchall()
    assert hits == []


def test_forget_capsules_hard_delete_lifecycle(isolated_db):
    res = _write_basic()
    cs.forget_capsules([res["capsule_id"]], mode="hard_delete")
    got = cs.get_capsule(res["capsule_id"])
    assert got["state"]["lifecycle"] == "deleted"


def test_forget_capsules_skips_missing(isolated_db):
    out = cs.forget_capsules(["cap_missing_1", "cap_missing_2"])
    assert out["deleted_capsule_ids"] == []


# ---------------------------------------------------------------------------
# allowed_for_context
# ---------------------------------------------------------------------------

def test_allowed_for_context_allows_active(isolated_db):
    res = _write_basic()
    cap = cs.get_capsule(res["capsule_id"])
    assert cs.allowed_for_context(cap) is True


def test_allowed_for_context_blocks_rejected_policy():
    cap = {
        "governance": {"policy_result": "reject", "sensitivity_level": "S3"},
        "state": {"lifecycle": "rejected"},
    }
    assert cs.allowed_for_context(cap) is False


def test_allowed_for_context_blocks_s3():
    cap = {
        "governance": {"policy_result": "allow", "sensitivity_level": "S3"},
        "state": {"lifecycle": "active"},
    }
    assert cs.allowed_for_context(cap) is False


def test_allowed_for_context_blocks_forgotten():
    cap = {
        "governance": {"policy_result": "allow", "sensitivity_level": "S0"},
        "state": {"lifecycle": "forgotten"},
    }
    assert cs.allowed_for_context(cap) is False


def test_allowed_for_context_high_risk_blocks_conflicted():
    cap = {
        "governance": {"policy_result": "allow", "sensitivity_level": "S0"},
        "state": {"lifecycle": "conflicted"},
    }
    assert cs.allowed_for_context(cap, high_risk=True) is False
    # not high risk => conflicted is allowed
    assert cs.allowed_for_context(cap, high_risk=False) is True
