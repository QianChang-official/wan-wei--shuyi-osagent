"""W09 核心架构整洁修复的针对性回归测试。

覆盖任务包条目：
- 03-#10 db.py 启用 PRAGMA foreign_keys=ON（兼容：幽灵 soul 种子不再产生孤儿行）
- 03-#20 db.py mkdir/chmod 按路径 once 化
- 03-#15 retrieval.py 搜索读路径 usage 落库降频（时间窗合并）
- 03-#16 retrieval.py FTS 失败记 warning 日志（降级不静默）
- 03-#11 injector/persona/decay_daemon 的 `row["x"] or 默认值` 吃掉合法 0.0
- 03-#6  persona 写接口异常不再假成功（显式 PersonaStoreError → API 5xx）
- 03-#17 state_machine.transition load→save→log 单事务原子性
- 03-#7  main.forget_confirm 事务外物化 legacy 链接（json_extract 精准回捞）
- 03-#13 main 绝对/相对导入统一（platform 路由模块身份唯一）
- 03-#21 audit list_logs trace_id json_extract 精确匹配
- 03-#14 model_gateway 配置单源化（运行时访问函数为唯一事实源）
- 03-#19 platform_api 自动发现失败 log error + failed_modules 暴露
- 复测  policy_gate 自然语言敏感表述增强（中英文夹带修饰语写法）
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _client(tmp_path, *, api_key: str = "test-key"):
    """构造隔离的 TestClient（与 mission 测试同款）。"""
    os.environ["WANWEI_API_KEY"] = api_key
    os.environ["WANWEI_MEMORY_DB"] = str(tmp_path / "memory.db")
    os.environ["WANWEI_PLATFORM_DIR"] = str(tmp_path / "platform")
    os.environ.pop("WANWEI_PRODUCTION", None)

    import importlib
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    import backend.app.init_db
    import backend.app.main as main_mod

    importlib.reload(main_mod)
    backend.app.init_db.main()
    return TestClient(main_mod.app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# 03-#10 PRAGMA foreign_keys=ON
# ---------------------------------------------------------------------------


def test_foreign_keys_pragma_enabled(isolated_db):
    from backend.app.db import get_conn

    assert get_conn().execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_foreign_key_enforced_for_orphan_affect_row(isolated_db):
    from backend.app.db import transaction

    with pytest.raises(sqlite3.IntegrityError):
        with transaction() as conn:
            conn.execute(
                "INSERT INTO affect_state(soul_id, pleasure, arousal, dominance, "
                "current_mood, mood_intensity, updated_at) "
                "VALUES ('ghost_w09_fk', 0.5, 0.4, 0.5, 'calm', 0.3, '2024-01-01')"
            )


def test_load_affect_ghost_soul_returns_default_without_orphan(isolated_db):
    """FK 启用后，幽灵 soul 的种子播种被 WHERE EXISTS 守卫跳过且不报错。"""
    from backend.app.affect.state_machine import load_affect
    from backend.app.db import get_conn

    state = load_affect("ghost_w09_fk")
    assert state.pleasure == 0.5
    assert state.current_mood == "calm"
    assert (
        get_conn()
        .execute("SELECT 1 FROM affect_state WHERE soul_id='ghost_w09_fk'")
        .fetchone()
        is None
    )


# ---------------------------------------------------------------------------
# 03-#20 _db_path 按路径 once 化
# ---------------------------------------------------------------------------


def test_db_path_prepared_once_per_generation(isolated_db):
    from backend.app import db as db_mod

    # 释放 init_db 期间缓存的连接（Windows 下句柄未关无法 unlink）
    db_mod.close_all()
    p = db_mod.database_path()  # 新代际首次访问：prepare
    assert p.exists()
    p.unlink()
    # 同一代际内不再重复 mkdir/touch：文件不会被重建
    db_mod.database_path()
    assert not p.exists()
    # close_all 后缓存失效，下一次访问重新 prepare
    db_mod.close_all()
    assert db_mod.database_path().exists()


# ---------------------------------------------------------------------------
# 03-#15 搜索读路径 usage 落库降频
# ---------------------------------------------------------------------------


def test_usage_bump_coalesced_within_time_window(isolated_db):
    from backend.app.memory_runtime import retrieval as rt
    from backend.app.memory_runtime.capsule_store import get_capsule, write_capsule

    res = write_capsule(
        memory_class="knowledge",
        content={"text": "w09 降频验证 三段式结构 周报"},
    )
    cid = res["capsule_id"]
    try:
        rt.search_capsules("三段式", top_k=5)
        assert get_capsule(cid)["state"]["usage_count"] == 1
        # 时间窗内的重复命中被合并，不再重复落库/计数
        rt.search_capsules("三段式", top_k=5)
        assert get_capsule(cid)["state"]["usage_count"] == 1
        # 模拟时间窗过去（清除内存标记），下一次命中重新落库
        rt._recent_usage_bumps.pop(cid, None)
        rt.search_capsules("三段式", top_k=5)
        assert get_capsule(cid)["state"]["usage_count"] == 2
    finally:
        rt._recent_usage_bumps.pop(cid, None)


# ---------------------------------------------------------------------------
# 03-#16 FTS 失败降级记 warning 日志
# ---------------------------------------------------------------------------


def test_fts_failure_logs_warning_and_degrades(caplog):
    from backend.app.memory_runtime import retrieval as rt

    class _BrokenConn:
        def execute(self, *args, **kwargs):
            raise RuntimeError("w09 synthetic fts failure")

    with caplog.at_level(logging.WARNING, logger="backend.app.memory_runtime.retrieval"):
        rows = rt._fts_rows(_BrokenConn(), "查询", 5)
    assert rows == []  # 仍降级为空
    assert "FTS 检索失败" in caplog.text  # 但不再静默


# ---------------------------------------------------------------------------
# 03-#11 `row["x"] or 默认值` 吃掉合法 0.0
# ---------------------------------------------------------------------------


def test_persona_baseline_zero_not_eaten(isolated_db):
    from backend.app.soul.persona import create_persona, get_persona, update_persona

    sid = create_persona("soul_w09_zero")
    update_persona(sid, baseline_pleasure=0.0)
    assert get_persona(sid)["baseline_pleasure"] == 0.0


def test_injector_affect_zero_not_eaten(isolated_db):
    from backend.app.affect.state_machine import AffectState, save_affect
    from backend.app.soul.injector import _get_affect
    from backend.app.soul.persona import create_persona

    sid = create_persona("soul_w09_inj")
    save_affect(
        sid,
        AffectState(pleasure=0.0, arousal=0.0, dominance=0.0, current_mood="calm", mood_intensity=0.0),
    )
    affect = _get_affect(sid)
    assert affect["pleasure"] == 0.0
    assert affect["arousal"] == 0.0
    assert affect["dominance"] == 0.0
    assert affect["mood_intensity"] == 0.0


def test_decay_honors_zero_baseline(isolated_db):
    from backend.app.affect.decay_daemon import decay_affect
    from backend.app.affect.state_machine import AffectState, save_affect
    from backend.app.soul.persona import create_persona, update_persona

    sid = create_persona("soul_w09_decay")
    update_persona(sid, baseline_pleasure=0.0, baseline_arousal=0.0, baseline_dominance=0.0)
    save_affect(
        sid,
        AffectState(pleasure=1.0, arousal=1.0, dominance=1.0, current_mood="excited", mood_intensity=1.0),
    )
    state = decay_affect(sid)
    # 若 0.0 被 `or` 吃成默认 baseline（0.6/0.4/0.5），结果将是 0.94/0.92/0.925
    assert abs(state.pleasure - 0.85) < 1e-9
    assert abs(state.arousal - 0.80) < 1e-9
    assert abs(state.dominance - 0.85) < 1e-9


# ---------------------------------------------------------------------------
# 03-#6 persona 写接口异常显式化
# ---------------------------------------------------------------------------


def _broken_transaction():
    @contextmanager
    def _cm():
        raise RuntimeError("w09 synthetic db failure")
        yield

    return _cm()


def test_update_persona_raises_on_store_failure(isolated_db, monkeypatch):
    from backend.app.soul import persona as persona_mod
    from backend.app.soul.persona import PersonaStoreError, create_persona, update_persona

    sid = create_persona("soul_w09_err")
    monkeypatch.setattr(persona_mod, "transaction", _broken_transaction())
    with pytest.raises(PersonaStoreError):
        update_persona(sid, name="改名")


def test_create_persona_idempotent_and_error_honest(isolated_db, monkeypatch):
    from backend.app.soul import persona as persona_mod
    from backend.app.soul.persona import PersonaStoreError, create_persona

    sid = create_persona("soul_w09_dup")
    # 幂等：soul_id 已存在时返回既有 id（核验过持久化行真实存在）
    assert create_persona("soul_w09_dup") == sid
    # 非冲突类异常不再假成功返回 sid
    monkeypatch.setattr(persona_mod, "transaction", _broken_transaction())
    with pytest.raises(PersonaStoreError):
        create_persona("soul_w09_new")


def test_persona_update_api_returns_explicit_error(tmp_path, monkeypatch):
    client = _client(tmp_path)
    from backend.app.soul import persona as persona_mod

    monkeypatch.setattr(persona_mod, "transaction", _broken_transaction())
    r = client.put(
        "/soul/persona/soul_w09_api",
        json={"name": "新名字"},
        headers={"x-api-key": "test-key"},
    )
    assert r.status_code == 500
    assert r.json()["detail"]["error"] == "persona_update_failed"


# ---------------------------------------------------------------------------
# 03-#17 transition load→save→log 单事务原子性
# ---------------------------------------------------------------------------


def test_transition_rolls_back_state_when_event_log_fails(isolated_db, monkeypatch):
    from backend.app.affect import state_machine as sm
    from backend.app.db import get_conn
    from backend.app.soul.persona import create_persona

    sid = create_persona("soul_w09_txn")

    def _boom_log(soul_id, emotion, state, intensity, trigger=None, bound_capsule_ids=None, conn=None):
        raise RuntimeError("w09 synthetic log failure")

    monkeypatch.setattr(sm, "_log_event", _boom_log)
    with pytest.raises(RuntimeError):
        sm.transition(sid, "user_thank")

    # save_affect 已执行但与 log 同事务 → 整体回滚，不产生半提交状态
    row = get_conn().execute(
        "SELECT pleasure FROM affect_state WHERE soul_id=?", (sid,)
    ).fetchone()
    assert abs(row["pleasure"] - 0.5) < 1e-9
    assert not get_conn().in_transaction


def test_transition_persists_state_and_event_atomically(isolated_db):
    from backend.app.affect import state_machine as sm
    from backend.app.db import get_conn
    from backend.app.soul.persona import create_persona

    sid = create_persona("soul_w09_ok")
    state = sm.transition(sid, "user_thank")
    assert state.current_mood == "happy"
    cnt = get_conn().execute(
        "SELECT COUNT(*) AS c FROM affect_events WHERE soul_id=?", (sid,)
    ).fetchone()["c"]
    assert cnt == 1


# ---------------------------------------------------------------------------
# 03-#7 forget_confirm 事务外物化 + 精准回捞
# ---------------------------------------------------------------------------


def test_audit_legacy_link_scan_filtered_and_newest_wins(isolated_db):
    from backend.app.db import get_conn, transaction
    from backend.app.main import _audit_legacy_capsule_links

    with transaction() as conn:
        conn.execute(
            "INSERT INTO audit_logs VALUES ('w09_a1','memory_write',?,'2024-01-01T00:00:00Z')",
            (json.dumps({"event_id": "e1", "capsule_id": "cap_old"}),),
        )
        conn.execute(
            "INSERT INTO audit_logs VALUES ('w09_a2','memory_write',?,'2024-01-02T00:00:00Z')",
            (json.dumps({"event_id": "e1", "capsule_id": "cap_new"}),),
        )
        conn.execute(
            "INSERT INTO audit_logs VALUES ('w09_a3','memory_write','not-a-json','2024-01-03T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO audit_logs VALUES ('w09_a4','memory_write',?,'2024-01-04T00:00:00Z')",
            (json.dumps({"event_id": "e_other", "capsule_id": "cap_other"}),),
        )

    found = _audit_legacy_capsule_links(get_conn(), ["e1", "e_missing"], set())
    # 只回捞请求的 event；坏行被跳过；同 event 取最新一条
    assert found == {"e1": "cap_new"}
    # 已存在链接的 event 不再回捞
    assert _audit_legacy_capsule_links(get_conn(), ["e1"], {"e1"}) == {}


def test_forget_confirm_uses_materialized_legacy_links(tmp_path):
    client = _client(tmp_path)
    headers = {"x-api-key": "test-key"}

    from backend.app.audit.service import record
    from backend.app.db import get_conn, transaction

    with transaction() as txn:
        txn.execute(
            "INSERT INTO memory_capsules(capsule_id, memory_type, payload, lifecycle, trust_score, created_at) "
            "VALUES ('cap_legacy_w09','note','{}','active',0.5,'2024-01-01T00:00:00Z')"
        )
        txn.execute(
            "INSERT INTO memory_events(event_id, source_type, scene, content, quality_score, "
            "sensitivity_level, trust_score, created_at) "
            "VALUES ('evt_w09_1','user_input','chat','旧记忆内容',0.5,'S0',0.9,'2024-01-01T00:00:00Z')"
        )
        txn.execute(
            "INSERT INTO memory_forget_requests(forget_request_id, scope, candidates, status, result, "
            "created_at, updated_at) VALUES ('fr_w09_1','assistant',?,'pending',NULL,"
            "'2024-01-02T00:00:00Z','2024-01-02T00:00:00Z')",
            (json.dumps([{"event_id": "evt_w09_1"}]),),
        )
    # legacy 链接只存在于 audit_logs（memory_event_capsules 无记录），触发精准回捞
    record("memory_write", {"event_id": "evt_w09_1", "capsule_id": "cap_legacy_w09"})

    r = client.post(
        "/memory/forget/confirm",
        json={
            "forget_request_id": "fr_w09_1",
            "confirm": True,
            "mode": "soft_delete",
            "event_ids": ["evt_w09_1"],
            "capsule_ids": [],
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "forgotten"
    assert body["deleted_event_ids"] == ["evt_w09_1"]

    lifecycle = get_conn().execute(
        "SELECT lifecycle FROM memory_capsules WHERE capsule_id='cap_legacy_w09'"
    ).fetchone()["lifecycle"]
    assert lifecycle == "forgotten"
    link = get_conn().execute(
        "SELECT capsule_id FROM memory_event_capsules WHERE event_id='evt_w09_1'"
    ).fetchone()
    assert link["capsule_id"] == "cap_legacy_w09"  # 已幂等回填
    assert (
        get_conn().execute("SELECT 1 FROM memory_events WHERE event_id='evt_w09_1'").fetchone()
        is None
    )


def test_forget_confirm_missing_legacy_link_still_409(tmp_path):
    """回捞不到的 event 仍在事务外前置 409（语义保持）。"""
    client = _client(tmp_path)

    from backend.app.db import transaction

    with transaction() as txn:
        txn.execute(
            "INSERT INTO memory_forget_requests(forget_request_id, scope, candidates, status, result, "
            "created_at, updated_at) VALUES ('fr_w09_2','assistant',?,'pending',NULL,"
            "'2024-01-02T00:00:00Z','2024-01-02T00:00:00Z')",
            (json.dumps([{"event_id": "evt_w09_missing"}]),),
        )

    r = client.post(
        "/memory/forget/confirm",
        json={
            "forget_request_id": "fr_w09_2",
            "confirm": True,
            "mode": "soft_delete",
            "event_ids": ["evt_w09_missing"],
            "capsule_ids": [],
        },
        headers={"x-api-key": "test-key"},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "legacy_capsule_link_missing"


# ---------------------------------------------------------------------------
# 03-#13 导入统一：platform 路由模块身份唯一
# ---------------------------------------------------------------------------


def test_platform_router_single_module_identity():
    import backend.app.main as main_mod
    import backend.app.platform_api as platform_api_pkg

    assert main_mod.platform_api_router is platform_api_pkg.api_router


# ---------------------------------------------------------------------------
# 03-#21 audit trace_id json_extract 精确匹配
# ---------------------------------------------------------------------------


def test_audit_trace_id_exact_match_no_wildcard_no_nested(isolated_db):
    from backend.app.audit.service import list_logs, record

    record("workflow_run", {"trace_id": "t_1", "note": "a"})
    record("workflow_run", {"trace_id": "tX1", "note": "b"})  # LIKE 下 _ 通配会误中
    record("workflow_run", {"outer": {"trace_id": "nested_1"}})  # LIKE 下子串会误中

    rows = list_logs(50, trace_id="t_1")
    assert len(rows) == 1
    assert '"trace_id": "t_1"' in rows[0]["payload"]
    # 嵌套同名字段不再被命中
    assert list_logs(50, trace_id="nested_1") == []


# ---------------------------------------------------------------------------
# 03-#14 model_gateway 配置单源化
# ---------------------------------------------------------------------------


def test_model_gateway_config_single_source(monkeypatch):
    from backend.app.model_gateway import service as svc

    monkeypatch.setenv("WANWEI_OPENAI_COMPATIBLE_BASE", "https://w09.example/v1")
    monkeypatch.setenv("WANWEI_OPENAI_COMPATIBLE_MODEL", "w09-model")
    assert svc.local_llama_settings() == ("https://w09.example/v1", "w09-model", True)
    items = {p["provider"]: p for p in svc.list_providers()["items"]}
    assert items["openai_compatible"]["enabled"] is True
    assert items["openai_compatible"]["api_base"] == "https://w09.example/v1"

    # 不 reload 模块也能反映 env 变化——运行时访问函数是唯一事实源
    monkeypatch.delenv("WANWEI_OPENAI_COMPATIBLE_BASE", raising=False)
    monkeypatch.delenv("WANWEI_OPENAI_COMPATIBLE_MODEL", raising=False)
    items = {p["provider"]: p for p in svc.list_providers()["items"]}
    assert items["openai_compatible"]["enabled"] is False
    assert items["openai_compatible"]["status"] == "configuration_required"


def test_chat_complete_consumes_single_source(monkeypatch):
    import backend.app.main as main_mod

    monkeypatch.delenv("WANWEI_OPENAI_COMPATIBLE_BASE", raising=False)
    monkeypatch.delenv("WANWEI_OPENAI_COMPATIBLE_MODEL", raising=False)
    out = main_mod._chat_complete([{"role": "user", "content": "hi"}])
    assert out["provider"] == "local_mock"

    monkeypatch.setenv("WANWEI_OPENAI_COMPATIBLE_BASE", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("WANWEI_OPENAI_COMPATIBLE_MODEL", "w09-unreachable")
    out = main_mod._chat_complete([{"role": "user", "content": "hi"}])
    assert out["provider"] == "openai_compatible"
    assert out["status"] == "provider_error"  # 失败如实返回，不回退 mock


def test_chat_complete_does_not_expose_provider_exception(monkeypatch):
    import httpx

    import backend.app.main as main_mod

    marker = "sensitive-provider-exception-detail"

    class FailingClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            raise RuntimeError(marker)

        def __exit__(self, *args):
            return False

    monkeypatch.setenv("WANWEI_OPENAI_COMPATIBLE_BASE", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("WANWEI_OPENAI_COMPATIBLE_MODEL", "w09-failing-provider")
    monkeypatch.setattr(httpx, "Client", FailingClient)

    out = main_mod._chat_complete([{"role": "user", "content": "hi"}])

    assert out["status"] == "provider_error"
    assert out["provider"] == "openai_compatible"
    assert out["error"] == "provider_unavailable"
    assert marker not in json.dumps(out, ensure_ascii=False)


def test_workflow_design_uses_runtime_local_llama_settings(monkeypatch):
    """workflow/service.py 不再消费导入期 LOCAL_LLAMA_BASE 快照。"""
    from backend.app.workflow import service as workflow_service

    monkeypatch.delenv("WANWEI_OPENAI_COMPATIBLE_BASE", raising=False)
    monkeypatch.delenv("WANWEI_OPENAI_COMPATIBLE_MODEL", raising=False)
    out = workflow_service.workflow_design()
    mg = out["model_gateway"]
    assert mg["provider"] == "openai_compatible"
    assert mg["api_base"] == ""
    assert mg["configured"] is False
    assert mg["status"] == "configuration_required"

    monkeypatch.setenv("WANWEI_OPENAI_COMPATIBLE_BASE", "http://127.0.0.1:2/v1")
    monkeypatch.setenv("WANWEI_OPENAI_COMPATIBLE_MODEL", "w09-workflow")
    out = workflow_service.workflow_design()
    mg = out["model_gateway"]
    assert mg["api_base"] == "http://127.0.0.1:2/v1"
    assert mg["api_model"] == "w09-workflow"
    assert mg["configured"] is True
    assert mg["status"] == "real_smoke_available"


# ---------------------------------------------------------------------------
# 03-#19 platform_api 自动发现失败：log error + failed_modules + readiness
# ---------------------------------------------------------------------------


def test_platform_api_discovery_failure_logged_and_exposed(monkeypatch, caplog):
    from backend.app import platform_api as pa

    class _FakeInfo:
        name = "w09_broken_mod"

    monkeypatch.setattr(pa.pkgutil, "iter_modules", lambda path: [_FakeInfo()])

    def _boom(name):
        raise RuntimeError("w09 synthetic import failure")

    monkeypatch.setattr(pa.importlib, "import_module", _boom)

    loaded_snapshot = list(pa._LOADED_MODULES)
    failed_snapshot = dict(pa._FAILED_MODULES)
    try:
        pa._LOADED_MODULES.clear()
        pa._FAILED_MODULES.clear()
        with caplog.at_level(logging.ERROR, logger="backend.app.platform_api"):
            pa._discover_routers()
        assert set(pa.failed_modules()) == {"w09_broken_mod"}
        assert "w09_broken_mod" in caplog.text
        assert pa.loaded_modules() == []
    finally:
        pa._LOADED_MODULES[:] = loaded_snapshot
        pa._FAILED_MODULES.clear()
        pa._FAILED_MODULES.update(failed_snapshot)


def test_readiness_still_ready_and_exposes_platform_check(tmp_path):
    client = _client(tmp_path)
    r = client.get("/health/ready")
    assert r.status_code == 200
    check = r.json()["checks"]["platform_api"]
    assert check["status"] == "ok"
    # 无失败模块时不挂载 failed_modules 字段（保持既有响应形状）
    assert "failed_modules" not in check


# ---------------------------------------------------------------------------
# 复测新发现：policy_gate 自然语言敏感表述增强
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "我的银行卡密码是 123456",
        "我的银行卡密码是123456",
        "my root password is hunter2",
        "the api key is abcdef123",
        "我的身份证号是 1101011990",
        "开机口令为 open Sesame!",
    ],
)
def test_policy_gate_nl_secret_phrasing_rejected(text):
    from backend.app.memory_runtime.policy_gate import evaluate_policy

    r = evaluate_policy(text=text)
    assert r["policy_result"] == "reject", f"应拒绝：{text}"
    assert r["sensitivity_level"] == "S3"


@pytest.mark.parametrize(
    "text",
    [
        # test_batch4_p1 钉死的非误伤用例
        "请修改密码策略，要求最少 12 位",
        "下次登录需要重置密码",
        "今天讨论了密钥轮换的方案设计",
        # test_mission_c 钉死的正常记忆
        "每天早上 7 点提醒我喝水",
        "项目目标：完成架构文档",
        "优先修复 P0 问题",
        "记住：冒烟测试通过后要归档",
        "所有回复先用中文思考",
    ],
)
def test_policy_gate_nl_patterns_no_false_positive(text):
    from backend.app.memory_runtime.policy_gate import evaluate_policy

    r = evaluate_policy(text=text)
    assert r["policy_result"] != "reject", f"误伤：{text}"
