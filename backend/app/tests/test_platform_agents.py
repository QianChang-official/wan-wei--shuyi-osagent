# Copyright (c) 2026 QianChang-official
#
# 宛委·枢忆 is licensed under Mulan PSL v2.
# You can use this software according to the terms of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
# http://license.coscl.org.cn/MulanPSL2
#
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

"""platform_api /agents 审批语义回归测试。"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient


def _client(tmp_path, *, api_key: str = "test-key"):
    os.environ["WANWEI_API_KEY"] = api_key
    os.environ["WANWEI_MEMORY_DB"] = str(tmp_path / "memory.db")
    os.environ.pop("WANWEI_PRODUCTION", None)
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    import backend.app.app_runtime as runtime_mod
    import backend.app.main as main_mod
    importlib.reload(runtime_mod)
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


def test_approve_executes_step_instead_of_skipping(tmp_path, monkeypatch):
    """回归：needs_review 步骤审批通过后必须真正执行，而不是标 done 跳过。

    旧实现把游标处步骤直接标 done、游标前移，导致执行前挂起的步骤
    永远不会执行（Kilo CRITICAL）。执行器与收尾在此打桩，避免依赖
    外部网关；被测对象是审批端点与驱动循环的状态流转。
    """
    import time

    import backend.app.platform_api.agents as agents_mod

    client = _client(tmp_path)
    rid = _make_run_awaiting_review(client, tmp_path)

    executed = []

    async def fake_execute(rid_, run_, step_, ctx_):
        executed.append(step_.get("name"))
        return "【执行】测试执行产物", False

    async def fake_finalize(rid_):
        r_ = agents_mod._runs.get(rid_)
        if r_:
            r_["status"] = "done"
            agents_mod._runs.set(rid_, r_)

    monkeypatch.setattr(agents_mod, "_execute_step", fake_execute)
    monkeypatch.setattr(agents_mod, "_finalize_run", fake_finalize)

    r = client.post(
        f"/platform/agents/runs/{rid}/approve",
        json={"approved": True, "note": "放行"},
        headers={"x-api-key": "test-key"},
    )
    assert r.status_code == 200, r.text
    run = r.json()
    # 审批响应本身不得把步骤标成 done——那只是复位待执行，真正执行由驱动循环完成
    assert run["steps"][0]["status"] in ("pending", "running")
    assert run["cursor"] == 0

    deadline = time.time() + 10
    while time.time() < deadline:
        run = dict(agents_mod._runs.get(rid) or {})
        if run.get("status") in ("done", "failed", "cancelled", "rejected"):
            break
        time.sleep(0.05)

    assert run["status"] == "done", run
    step = run["steps"][0]
    # 该步被真实执行过一次，而不是跳过
    assert executed == ["review-step"]
    assert step["status"] == "done"
    assert step["finished_at"]
    detail = step["detail"] or ""
    # 既有真实执行产物，也保留审批备注
    assert "【执行】测试执行产物" in detail
    assert "【人工审查】通过" in detail
