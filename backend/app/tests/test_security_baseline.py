from __future__ import annotations

import importlib
import os
import stat
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _client(tmp_path: Path, *, api_key: str = "test-key", production: bool = False):
    if production and api_key == "test-key":
        api_key = "test-key-for-production-32-characters"
    os.environ["WANWEI_API_KEY"] = api_key
    os.environ["WANWEI_MEMORY_DB"] = str(tmp_path / "memory.db")
    if production:
        os.environ["WANWEI_PRODUCTION"] = "1"
    else:
        os.environ.pop("WANWEI_PRODUCTION", None)
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    import backend.app.main as main_mod
    importlib.reload(main_mod)
    return TestClient(main_mod.app, raise_server_exceptions=False)


def test_write_requires_api_key(tmp_path):
    client = _client(tmp_path)
    body = {"memory_class": "preference", "content": {"text": "安全回归测试"}}
    assert client.get("/health").status_code == 200
    assert client.post("/memory/v2/capsules", json=body).status_code == 401
    assert client.post("/memory/v2/capsules", json=body, headers={"x-api-key": "wrong"}).status_code == 401
    assert client.post("/memory/v2/capsules", json=body, headers={"x-api-key": "test-key"}).status_code == 200


def test_legacy_event_rejects_secret_and_not_searchable(tmp_path):
    client = _client(tmp_path)
    payload = {"source_type": "user_input", "scene": "general", "content": {"note": "password=hunter2"}}
    r = client.post("/memory/events", json=payload, headers={"x-api-key": "test-key"})
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
    search = client.get("/memory/search", params={"q": "hunter2"}, headers={"x-api-key": "test-key"})
    assert search.status_code == 200
    assert search.json()["results"] == []


def test_rejected_legacy_event_audit_does_not_store_nested_secret(tmp_path):
    client = _client(tmp_path)
    secret = "secret=legacy-value-must-not-survive"

    response = client.post(
        "/memory/events",
        json={"source_type": "user_input", "scene": "general", "content": {"nested": {"value": secret}}},
        headers={"x-api-key": "test-key"},
    )
    audit_rows = client.get("/audit/logs", headers={"x-api-key": "test-key"}).json()["items"]
    rejected = next(row for row in audit_rows if row["event_type"] == "memory_rejected")

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert secret not in rejected["payload"]


def test_forget_confirm_hides_capsule_from_search(tmp_path):
    client = _client(tmp_path)
    body = {"memory_class": "knowledge", "content": {"text": "请生成周报，使用正式语气和三段式结构。"}}
    write = client.post("/memory/v2/capsules", json=body, headers={"x-api-key": "test-key"}).json()
    cap_id = write["capsule_id"]
    assert client.get("/memory/v2/search", params={"q": "周报"}, headers={"x-api-key": "test-key"}).json()["results"]
    result = client.post("/memory/forget/confirm", json={"forget_request_id": "manual", "confirm": True, "mode": "soft_delete"}, headers={"x-api-key": "test-key"})
    # manual request has no preview; direct helper path is tested via capsule lifecycle below
    assert result.status_code == 200
    from backend.app.memory_runtime.capsule_store import forget_capsules, get_capsule
    forget_capsules([cap_id])
    assert get_capsule(cap_id)["state"]["lifecycle"] == "forgotten"
    assert client.get("/memory/v2/search", params={"q": "周报"}, headers={"x-api-key": "test-key"}).json()["results"] == []


def test_forget_preview_selects_v2_capsule_before_confirm(tmp_path):
    client = _client(tmp_path)
    headers = {"x-api-key": "test-key"}
    body = {"memory_class": "knowledge", "content": {"text": "季度财务报表交给审计负责人。"}}
    capsule_id = client.post("/memory/v2/capsules", json=body, headers=headers).json()["capsule_id"]

    preview = client.post(
        "/memory/forget/preview",
        json={"instruction": "季度财务报表", "scope": "current_user"},
        headers=headers,
    )

    assert preview.status_code == 200
    preview_body = preview.json()
    assert capsule_id in [item.get("capsule_id") for item in preview_body["candidates"]]
    confirm = client.post(
        "/memory/forget/confirm",
        json={
            "forget_request_id": preview_body["forget_request_id"],
            "confirm": True,
            "mode": "cascade",
            "capsule_ids": [capsule_id],
        },
        headers=headers,
    )

    assert confirm.status_code == 200
    assert confirm.json()["deleted_capsule_ids"] == [capsule_id]
    assert client.get(f"/memory/v2/capsules/{capsule_id}", headers=headers).json()["state"]["lifecycle"] == "forgotten"


def test_forget_confirm_rejects_capsule_outside_preview(tmp_path, monkeypatch):
    monkeypatch.delenv("WANWEI_PRODUCTION", raising=False)
    monkeypatch.delenv("WANWEI_KYLIN_SDK_BRIDGE", raising=False)
    client = _client(tmp_path)
    headers = {"x-api-key": "test-key"}
    client.post(
        "/memory/v2/capsules",
        json={"memory_class": "knowledge", "content": {"text": "周末给阳台绿植浇水。"}},
        headers=headers,
    )
    preview = client.post(
        "/memory/forget/preview",
        json={"instruction": "没有对应记忆", "scope": "current_user"},
        headers=headers,
    ).json()

    response = client.post(
        "/memory/forget/confirm",
        json={"forget_request_id": preview["forget_request_id"], "capsule_ids": ["cap_not_previewed"]},
        headers=headers,
    )

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "forget_selection_not_in_preview"


def test_forget_confirm_replay_is_idempotent(tmp_path):
    client = _client(tmp_path)
    headers = {"x-api-key": "test-key"}
    capsule_id = client.post(
        "/memory/v2/capsules",
        json={"memory_class": "knowledge", "content": {"text": "一次性遗忘确认测试。"}},
        headers=headers,
    ).json()["capsule_id"]
    preview = client.post(
        "/memory/forget/preview",
        json={"instruction": "一次性遗忘确认", "scope": "current_user"},
        headers=headers,
    ).json()
    payload = {"forget_request_id": preview["forget_request_id"], "capsule_ids": [capsule_id]}

    first = client.post("/memory/forget/confirm", json=payload, headers=headers)
    second = client.post("/memory/forget/confirm", json=payload, headers=headers)

    assert first.status_code == 200
    assert first.json()["deleted_capsule_ids"] == [capsule_id]
    assert second.status_code == 200
    assert second.json() == first.json()


def test_forget_cancel_consumes_ticket(tmp_path):
    client = _client(tmp_path)
    headers = {"x-api-key": "test-key"}
    capsule_id = client.post(
        "/memory/v2/capsules",
        json={"memory_class": "knowledge", "content": {"text": "取消后不能重新确认。"}},
        headers=headers,
    ).json()["capsule_id"]
    preview = client.post(
        "/memory/forget/preview",
        json={"instruction": "取消后不能重新确认", "scope": "current_user"},
        headers=headers,
    ).json()

    cancelled = client.post(
        "/memory/forget/confirm",
        json={"forget_request_id": preview["forget_request_id"], "confirm": False},
        headers=headers,
    )
    confirm = client.post(
        "/memory/forget/confirm",
        json={"forget_request_id": preview["forget_request_id"], "capsule_ids": [capsule_id]},
        headers=headers,
    )

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert confirm.status_code == 409
    assert confirm.json()["detail"] == "forget_request_cancelled"


def test_forget_rejects_unsupported_scope_and_mode(tmp_path):
    client = _client(tmp_path)
    headers = {"x-api-key": "test-key"}

    preview = client.post(
        "/memory/forget/preview",
        json={"instruction": "scope validation", "scope": "all_users"},
        headers=headers,
    )
    confirm = client.post(
        "/memory/forget/confirm",
        json={"forget_request_id": "forget_invalid", "mode": "drop_database"},
        headers=headers,
    )

    assert preview.status_code == 422
    assert confirm.status_code == 422


def test_forget_confirm_failure_can_retry_same_preview(tmp_path, monkeypatch):
    client = _client(tmp_path)
    headers = {"x-api-key": "test-key"}
    capsule_id = client.post(
        "/memory/v2/capsules",
        json={"memory_class": "knowledge", "content": {"text": "失败后允许安全重试。"}},
        headers=headers,
    ).json()["capsule_id"]
    preview = client.post(
        "/memory/forget/preview",
        json={"instruction": "失败后允许安全重试", "scope": "current_user"},
        headers=headers,
    ).json()
    payload = {"forget_request_id": preview["forget_request_id"], "capsule_ids": [capsule_id]}
    from backend.app import main as main_module

    actual_forget = main_module.forget_capsules_in_transaction
    attempts = 0

    def fail_once(conn, capsule_ids, *, mode):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("injected forget failure")
        return actual_forget(conn, capsule_ids, mode=mode)

    monkeypatch.setattr(main_module, "forget_capsules_in_transaction", fail_once)

    first = client.post("/memory/forget/confirm", json=payload, headers=headers)
    second = client.post("/memory/forget/confirm", json=payload, headers=headers)

    assert first.status_code == 500
    assert second.status_code == 200
    assert second.json()["deleted_capsule_ids"] == [capsule_id]
    assert attempts == 2


def test_forget_confirm_rolls_back_legacy_when_v2_stage_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("WANWEI_KYLIN_NATIVE_MODE", "off")
    headers = {"x-api-key": "test-key"}
    with _client(tmp_path) as client:
        written = client.post(
            "/memory/events",
            json={"source_type": "user_input", "scene": "general", "content": {"text": "旧版事务回滚检查"}},
            headers=headers,
        ).json()
        preview = client.post(
            "/memory/forget/preview",
            json={"instruction": "旧版事务回滚检查", "scope": "current_user"},
            headers=headers,
        ).json()
        from backend.app import main as main_module
        from backend.app.db import get_conn

        monkeypatch.setattr(
            main_module,
            "forget_capsules_in_transaction",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("injected v2 stage failure")),
        )

        response = client.post(
            "/memory/forget/confirm",
            json={"forget_request_id": preview["forget_request_id"], "event_ids": [written["event_id"]]},
            headers=headers,
        )

    conn = get_conn()
    assert response.status_code == 500
    assert conn.execute("SELECT 1 FROM memory_events WHERE event_id=?", (written["event_id"],)).fetchone()
    assert conn.execute("SELECT 1 FROM memory_fts WHERE event_id=?", (written["event_id"],)).fetchone()
    assert conn.execute(
        "SELECT lifecycle FROM memory_capsules WHERE capsule_id=?", (written["capsule_id"],)
    ).fetchone()["lifecycle"] == "active"
    assert conn.execute(
        "SELECT status FROM memory_forget_requests WHERE forget_request_id=?", (preview["forget_request_id"],)
    ).fetchone()["status"] == "pending"


def test_forget_confirm_rolls_back_all_local_state_when_audit_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("WANWEI_KYLIN_NATIVE_MODE", "off")
    headers = {"x-api-key": "test-key"}
    with _client(tmp_path) as client:
        legacy = client.post(
            "/memory/events",
            json={"source_type": "user_input", "scene": "general", "content": {"text": "联合原子遗忘校验"}},
            headers=headers,
        ).json()
        capsule_id = client.post(
            "/memory/v2/capsules",
            json={"memory_class": "knowledge", "content": {"text": "联合原子遗忘校验"}},
            headers=headers,
        ).json()["capsule_id"]
        preview = client.post(
            "/memory/forget/preview",
            json={"instruction": "联合原子遗忘校验", "scope": "current_user"},
            headers=headers,
        ).json()
        from backend.app import main as main_module
        from backend.app.db import get_conn

        conn = get_conn()
        conn.execute(
            """
            INSERT INTO memory_vector_refs(
                capsule_id,provider,collection_name,status,created_at,updated_at
            ) VALUES (?,?,?,?,?,?)
            """,
            (capsule_id, "kylin_native_sdk", "wanwei_memory_capsules", "indexed", "2026-01-01", "2026-01-01"),
        )
        conn.commit()
        actual_record = main_module.record_in_transaction

        def fail_confirm_audit(transaction, event_type, payload):
            if event_type == "forget_confirm":
                raise RuntimeError("injected audit failure")
            return actual_record(transaction, event_type, payload)

        monkeypatch.setattr(main_module, "record_in_transaction", fail_confirm_audit)

        response = client.post(
            "/memory/forget/confirm",
            json={
                "forget_request_id": preview["forget_request_id"],
                "capsule_ids": [capsule_id],
                "event_ids": [legacy["event_id"]],
            },
            headers=headers,
        )

    conn = get_conn()
    assert response.status_code == 500
    assert conn.execute("SELECT 1 FROM memory_events WHERE event_id=?", (legacy["event_id"],)).fetchone()
    assert conn.execute("SELECT 1 FROM memory_fts WHERE event_id=?", (legacy["event_id"],)).fetchone()
    assert conn.execute(
        "SELECT lifecycle FROM memory_capsules WHERE capsule_id=?", (legacy["capsule_id"],)
    ).fetchone()["lifecycle"] == "active"
    assert conn.execute(
        "SELECT json_extract(state,'$.lifecycle') FROM memory_capsules_v2 WHERE capsule_id=?", (capsule_id,)
    ).fetchone()[0] == "active"
    assert conn.execute(
        "SELECT 1 FROM memory_capsules_v2_fts WHERE capsule_id=?", (capsule_id,)
    ).fetchone()
    assert conn.execute(
        "SELECT status FROM memory_vector_refs WHERE capsule_id=?", (capsule_id,)
    ).fetchone()["status"] == "indexed"
    assert conn.execute(
        "SELECT status FROM memory_forget_requests WHERE forget_request_id=?", (preview["forget_request_id"],)
    ).fetchone()["status"] == "pending"
    assert conn.execute("SELECT COUNT(*) FROM audit_logs WHERE event_type='forget_confirm'").fetchone()[0] == 0


def test_forget_confirm_reclaims_stale_processing_ticket(tmp_path):
    client = _client(tmp_path)
    headers = {"x-api-key": "test-key"}
    capsule_id = client.post(
        "/memory/v2/capsules",
        json={"memory_class": "knowledge", "content": {"text": "崩溃后的遗忘票据可以回收。"}},
        headers=headers,
    ).json()["capsule_id"]
    preview = client.post(
        "/memory/forget/preview",
        json={"instruction": "遗忘票据可以回收", "scope": "current_user"},
        headers=headers,
    ).json()
    from backend.app.db import get_conn

    conn = get_conn()
    conn.execute(
        "UPDATE memory_forget_requests SET status='processing', updated_at=? WHERE forget_request_id=?",
        ("2000-01-01T00:00:00+00:00", preview["forget_request_id"]),
    )
    conn.commit()

    response = client.post(
        "/memory/forget/confirm",
        json={"forget_request_id": preview["forget_request_id"], "capsule_ids": [capsule_id]},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["deleted_capsule_ids"] == [capsule_id]


def test_legacy_forget_also_forgets_linked_capsule(tmp_path):
    headers = {"x-api-key": "test-key"}
    with _client(tmp_path) as client:
        written = client.post(
            "/memory/events",
            json={"source_type": "user_input", "scene": "general", "content": {"text": "旧版事件也要完整遗忘"}},
            headers=headers,
        ).json()
        preview = client.post(
            "/memory/forget/preview",
            json={"instruction": "旧版事件也要完整遗忘", "scope": "current_user"},
            headers=headers,
        ).json()

        response = client.post(
            "/memory/forget/confirm",
            json={"forget_request_id": preview["forget_request_id"], "event_ids": [written["event_id"]]},
            headers=headers,
        )

    from backend.app.db import get_conn

    conn = get_conn()
    assert response.status_code == 200
    assert response.json()["deleted_event_ids"] == [written["event_id"]]
    assert conn.execute("SELECT 1 FROM memory_events WHERE event_id=?", (written["event_id"],)).fetchone() is None
    legacy_capsule = conn.execute(
        "SELECT lifecycle FROM memory_capsules WHERE capsule_id=?", (written["capsule_id"],)
    ).fetchone()
    assert legacy_capsule["lifecycle"] == "forgotten"


def test_legacy_forget_refuses_incomplete_unlinked_data(tmp_path):
    headers = {"x-api-key": "test-key"}
    with _client(tmp_path) as client:
        written = client.post(
            "/memory/events",
            json={"source_type": "user_input", "scene": "general", "content": {"text": "缺少映射时不能假装遗忘完成"}},
            headers=headers,
        ).json()
        preview = client.post(
            "/memory/forget/preview",
            json={"instruction": "缺少映射时不能假装遗忘完成", "scope": "current_user"},
            headers=headers,
        ).json()
        from backend.app.db import get_conn

        conn = get_conn()
        conn.execute("DELETE FROM memory_event_capsules WHERE event_id=?", (written["event_id"],))
        conn.execute(
            "DELETE FROM audit_logs WHERE event_type='memory_write' AND payload LIKE ?",
            (f'%{written["event_id"]}%',),
        )
        conn.commit()

        response = client.post(
            "/memory/forget/confirm",
            json={"forget_request_id": preview["forget_request_id"], "event_ids": [written["event_id"]]},
            headers=headers,
        )
        event_still_exists = conn.execute(
            "SELECT 1 FROM memory_events WHERE event_id=?", (written["event_id"],)
        ).fetchone()
        capsule_lifecycle = conn.execute(
            "SELECT lifecycle FROM memory_capsules WHERE capsule_id=?", (written["capsule_id"],)
        ).fetchone()[0]

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "legacy_capsule_link_missing"
    assert event_still_exists
    assert capsule_lifecycle == "active"


def test_forget_preview_audit_omits_instruction_and_candidate_content(tmp_path):
    client = _client(tmp_path)
    headers = {"x-api-key": "test-key"}
    sensitive_text = "私人诊疗安排只应返回给当前请求。"
    client.post(
        "/memory/v2/capsules",
        json={"memory_class": "knowledge", "content": {"text": sensitive_text}},
        headers=headers,
    )

    preview = client.post(
        "/memory/forget/preview",
        json={"instruction": "私人诊疗安排", "scope": "current_user"},
        headers=headers,
    )
    audit_rows = client.get("/audit/logs", headers=headers).json()["items"]
    audit_payload = next(row["payload"] for row in audit_rows if row["event_type"] == "forget_preview")

    assert preview.status_code == 200
    assert sensitive_text in preview.text
    assert sensitive_text not in audit_payload
    assert "私人诊疗安排" not in audit_payload


def test_chinese_search_hits_real_capsule_not_latest_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("WANWEI_KYLIN_NATIVE_MODE", "off")
    client = _client(tmp_path)
    first = {"memory_class": "knowledge", "content": {"text": "请生成周报，使用正式语气和三段式结构。"}}
    second = {"memory_class": "knowledge", "content": {"text": "完全无关的部署日志。"}}
    w1 = client.post("/memory/v2/capsules", json=first, headers={"x-api-key": "test-key"}).json()
    client.post("/memory/v2/capsules", json=second, headers={"x-api-key": "test-key"}).json()
    for q in ["周报", "正式语气", "三段式结构"]:
        res = client.get("/memory/v2/search", params={"q": q}, headers={"x-api-key": "test-key"}).json()["results"]
        assert res and res[0]["capsule_id"] == w1["capsule_id"]
    assert client.get("/memory/v2/search", params={"q": "不存在关键词"}, headers={"x-api-key": "test-key"}).json()["results"] == []


@pytest.mark.skipif(os.name == "nt", reason="Windows uses ACLs instead of POSIX mode bits")
def test_db_file_permission_600(tmp_path):
    client = _client(tmp_path)
    assert client.get("/health").status_code == 200
    client.get("/audit/logs", headers={"x-api-key": "test-key"})
    mode = stat.S_IMODE((tmp_path / "memory.db").stat().st_mode)
    assert mode == 0o600


def test_production_disables_docs_and_openapi(tmp_path):
    client = _client(tmp_path, production=True)
    assert client.get("/health").status_code == 200
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
