"""Mission C 记忆/知识链路诚信回归测试。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _client(tmp_path, *, api_key: str = "test-key"):
    """构造隔离的 TestClient（平台 JSON 与 SQLite DB 均落在 tmp_path）。"""
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
# C1 Policy Gate 在 remember / instructions / phrases 入口生效
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "endpoint,method,payload",
    [
        ("/platform/memory/remember", "post", {"text": "password=123456"}),
        ("/platform/memory/instructions", "put", {"lines": ["api_key=sk-abc123", "正常记忆"]}),
        ("/platform/memory/phrases", "post", {"text": "身份证号：110101199001011234"}),
    ],
)
def test_memory_write_endpoints_reject_sensitive(endpoint, method, payload, tmp_path):
    """三个记忆写入入口对敏感内容返回 422。"""
    client = _client(tmp_path)
    r = getattr(client, method)(endpoint, json=payload, headers={"x-api-key": "test-key"})
    assert r.status_code == 422, f"{endpoint}: {r.text}"
    detail = r.json().get("detail", {})
    assert detail.get("policy_result") in ("reject", "quarantine")


def test_remember_and_instructions_allow_normal_text(tmp_path):
    """正常记忆内容可写入，并能在 context-size 中回显。"""
    client = _client(tmp_path)

    r = client.post(
        "/platform/memory/remember",
        json={"text": "每天早上 7 点提醒我喝水"},
        headers={"x-api-key": "test-key"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    r = client.put(
        "/platform/memory/instructions",
        json={"lines": ["项目目标：完成架构文档", "优先修复 P0 问题"]},
        headers={"x-api-key": "test-key"},
    )
    assert r.status_code == 200, r.text

    # /memory/instructions/prompt 应返回真实拼接文本
    r = client.get("/platform/memory/instructions/prompt", headers={"x-api-key": "test-key"})
    assert r.status_code == 200, r.text
    text = r.json()["text"]
    assert "完成架构文档" in text
    assert "优先修复 P0 问题" in text


# ---------------------------------------------------------------------------
# C2 记忆指令注入链路：context-size 拉取真实指令
# ---------------------------------------------------------------------------


def test_context_size_reflects_memory_instructions(tmp_path):
    """记住指令后，/platform/agents/context-size 应包含指令文本。"""
    client = _client(tmp_path)

    client.post(
        "/platform/memory/remember",
        json={"text": "所有回复先用中文思考"},
        headers={"x-api-key": "test-key"},
    )

    r = client.get("/platform/agents/context-size", headers={"x-api-key": "test-key"})
    assert r.status_code == 200, r.text
    preview = r.json()["previews"]["memory_instructions"]
    assert "中文思考" in preview


# ---------------------------------------------------------------------------
# C3 dream 调度诚实化 + sessions 数据源标注
# ---------------------------------------------------------------------------


def test_dream_schedule_is_honest(tmp_path):
    """/platform/memory/dreams/schedule 不再返回虚假的 enabled:true。"""
    client = _client(tmp_path)
    r = client.get("/platform/memory/dreams/schedule", headers={"x-api-key": "test-key"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["enabled"] is False
    assert data["mode"] == "manual"


def test_sessions_endpoint_reports_source(tmp_path):
    """会话列表接口诚实标注数据来源，而非假装对接真实会话表。"""
    client = _client(tmp_path)
    r = client.get("/platform/memory/sessions", headers={"x-api-key": "test-key"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert "source" in data
    assert "JsonStore" in data["source"]
    assert "未对接真实 conversation_turns" in data["note"]
    assert isinstance(data.get("sessions"), list)
