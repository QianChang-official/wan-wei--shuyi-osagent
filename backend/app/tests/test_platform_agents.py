"""platform_api /agents 审批语义回归测试。"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _client(tmp_path, *, api_key: str = "test-key"):
    os.environ["WANWEI_API_KEY"] = api_key
    os.environ["WANWEI_MEMORY_DB"] = str(tmp_path / "memory.db")
    os.environ.pop("WANWEI_PRODUCTION", None)
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    import backend.app.main as main_mod
    importlib.reload(main_mod)
    return TestClient(main_mod.app, raise_server_exceptions=False)


def _make_run_awaiting_review(client, tmp_path):
    """通过 API 创建 agent 与 run，再把 run 直接置为 awaiting_review 状态。"""
    agent = {"name": "审批测试", "gear": "human_review", "depth": "low"}
    r = client.post("/platform/agents", json=agent, headers={"x-api-key": "test-key"})
    assert r.status_code == 201, r.text
    aid = r.json()["id"]

    r = client.post(
        "/platform/agents/run",
        json={"agent_id": aid, "task": "测试审批语义", "gear": "human_review"},
        headers={"x-api-key": "test-key"},
    )
    assert r.status_code == 201, r.text
    rid = r.json()["id"]

    # 绕过异步后台推进，直接把 run 写入 awaiting_review（测试目标仅为审批端点）
    import backend.app.platform_api.agents as agents_mod

    run = agents_mod._runs.get(rid)
    assert run is not None
    run["status"] = "awaiting_review"
    run["cursor"] = 0
    run["steps"] = [
        {
            "name": "review-step",
            "kind": "act",
            "status": "awaiting_review",
            "needs_review": True,
            "detail": "",
            "started_at": None,
            "finished_at": None,
        }
    ]
    agents_mod._runs.set(rid, run)
    return rid


def test_approve_rejects_when_approved_is_false(tmp_path):
    client = _client(tmp_path)
    rid = _make_run_awaiting_review(client, tmp_path)

    r = client.post(
        f"/platform/agents/runs/{rid}/approve",
        json={"approved": False, "note": "测试拒绝"},
        headers={"x-api-key": "test-key"},
    )
    assert r.status_code == 200, r.text
    run = r.json()
    assert run["status"] == "rejected"
    assert run["error"] == "人工审查拒绝"
    assert run["steps"][run["cursor"]]["status"] == "rejected"

    # 拒绝后不可再次审批
    r = client.post(
        f"/platform/agents/runs/{rid}/approve",
        json={"approved": True},
        headers={"x-api-key": "test-key"},
    )
    assert r.status_code == 409, r.text


def test_approve_accepts_when_approved_is_true(tmp_path):
    client = _client(tmp_path)
    rid = _make_run_awaiting_review(client, tmp_path)

    r = client.post(
        f"/platform/agents/runs/{rid}/approve",
        json={"approved": True, "note": "测试通过"},
        headers={"x-api-key": "test-key"},
    )
    assert r.status_code == 200, r.text
    run = r.json()
    assert run["status"] in ("running", "done")
