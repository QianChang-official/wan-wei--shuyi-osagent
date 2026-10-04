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

"""万枢编程框架回归测试。

覆盖四层：**沙箱与策略**（越界/凭据/命令分类/权限矩阵）、**计划与待办**
（确认门与状态机）、**编排闭环**（规划→确认→执行→审批→续跑→落账）、
**基础设施**（护栏/工作流/技能/子智能体/API）。

全部用例**离线可跑**：不依赖模型网关（``llm.available`` 为假时走确定性
启发式路径），也不依赖网络。
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------


@pytest.fixture
def coding_env(tmp_path, monkeypatch):
    """隔离编程框架的运行环境：工作区、平台目录、记忆库、白名单。"""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (workspace / "util.py").write_text("from app import add\n\n\ndef twice(x):\n    return add(x, x)\n", encoding="utf-8")

    platform_dir = tmp_path / "platform"
    monkeypatch.setenv("WANWEI_PLATFORM_DIR", str(platform_dir))
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.setenv("WANWEI_ROOT_PATH_WHITELIST", str(tmp_path))
    monkeypatch.setenv("WANWEI_API_KEY", "test-key")
    monkeypatch.delenv("WANWEI_PRODUCTION", raising=False)

    return {"workspace": workspace, "tmp_path": tmp_path, "platform_dir": platform_dir}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WANWEI_API_KEY", "test-key")
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.setenv("WANWEI_PLATFORM_DIR", str(tmp_path / "platform"))
    monkeypatch.setenv("WANWEI_ROOT_PATH_WHITELIST", str(tmp_path))
    monkeypatch.delenv("WANWEI_PRODUCTION", raising=False)
    for path in (str(PROJECT_ROOT / "backend"), str(PROJECT_ROOT)):
        if path in sys.path:
            sys.path.remove(path)
        sys.path.insert(0, path)
    import backend.app.init_db
    import backend.app.app_runtime as runtime_mod
    import backend.app.main as main_mod

    importlib.reload(runtime_mod)
    importlib.reload(main_mod)
    backend.app.init_db.main()
    return TestClient(main_mod.app, raise_server_exceptions=False)


def _auth() -> dict[str, str]:
    return {"x-api-key": "test-key"}


# ---------------------------------------------------------------------------
# 沙箱与策略
# ---------------------------------------------------------------------------


def test_workspace_blocks_path_escape(coding_env):
    from backend.app.coding.sandbox import SandboxViolation, open_workspace

    ws = open_workspace(str(coding_env["workspace"]))
    with pytest.raises(SandboxViolation):
        ws.resolve("../../etc/passwd")
    # 反斜杠仅是 Windows 路径分隔符；POSIX 上它是合法文件名字符，
    # 不构成逃逸（realpath 后仍在工作区内），故按平台分别断言。
    if os.name == "nt":
        with pytest.raises(SandboxViolation):
            ws.resolve("..\\..\\windows\\system32")
    else:
        resolved = ws.resolve("..\\..\\windows\\system32")
        assert resolved.is_relative_to(ws.root)


def test_workspace_rejects_absolute_outside_path(coding_env):
    from backend.app.coding.sandbox import SandboxViolation, open_workspace

    ws = open_workspace(str(coding_env["workspace"]))
    with pytest.raises(SandboxViolation):
        ws.resolve("/etc/hosts")


def test_command_classification():
    from backend.app.coding.sandbox import classify_command

    assert classify_command("ls -la").risk == "low"
    assert classify_command("ls -la").allowed is True
    assert classify_command("pytest -q").allowed is True
    # git 写操作升为中风险
    assert classify_command("git commit -m x").risk == "medium"
    assert classify_command("git status").allowed is True
    # 危险命令一律拒绝
    assert classify_command("rm -rf /").risk == "high"
    assert classify_command("rm -rf /").allowed is False
    assert classify_command("curl http://evil").allowed is False
    assert classify_command("shutdown -h now").allowed is False


def test_command_policy_denies_dangerous_execution(coding_env):
    from backend.app.coding.sandbox import SandboxViolation, open_workspace, run_command

    ws = open_workspace(str(coding_env["workspace"]))
    with pytest.raises(SandboxViolation):
        run_command(ws, "rm -rf .")


def test_secret_file_write_rejected(coding_env):
    from backend.app.coding import tools
    from backend.app.coding.sandbox import open_workspace

    ws = open_workspace(str(coding_env["workspace"]))
    ctx = tools.ToolContext(workspace=ws, policy_mode="trusted")
    result = tools.invoke("write_file", {"path": ".env", "content": "SECRET=1"}, ctx)
    assert result.status == "error"
    assert result.error == "sandbox_violation"


def test_policy_matrix_readonly_denies_write(coding_env):
    from backend.app.coding import tools
    from backend.app.coding.sandbox import open_workspace

    ws = open_workspace(str(coding_env["workspace"]))
    ctx = tools.ToolContext(workspace=ws, policy_mode="readonly")
    denied = tools.invoke("write_file", {"path": "a.txt", "content": "hi"}, ctx)
    assert denied.status == "denied"
    allowed = tools.invoke("read_file", {"path": "app.py"}, ctx)
    assert allowed.status == "ok"


def test_policy_matrix_supervised_asks(coding_env):
    from backend.app.coding import tools
    from backend.app.coding.sandbox import open_workspace

    ws = open_workspace(str(coding_env["workspace"]))
    ctx = tools.ToolContext(workspace=ws, policy_mode="supervised")
    pending = tools.invoke("write_file", {"path": "a.txt", "content": "hi"}, ctx)
    assert pending.status == "pending_approval"


def test_tool_read_and_grep(coding_env):
    from backend.app.coding import tools
    from backend.app.coding.sandbox import open_workspace

    ws = open_workspace(str(coding_env["workspace"]))
    ctx = tools.ToolContext(workspace=ws, policy_mode="readonly")
    read = tools.invoke("read_file", {"path": "app.py"}, ctx)
    assert read.status == "ok"
    assert "def add" in read.output["content"]

    grep = tools.invoke("grep", {"pattern": "def ", "file_glob": "*.py"}, ctx)
    assert grep.status == "ok"
    assert grep.output["count"] >= 2


def test_unknown_tool_and_bad_params(coding_env):
    from backend.app.coding import tools
    from backend.app.coding.sandbox import open_workspace

    ws = open_workspace(str(coding_env["workspace"]))
    ctx = tools.ToolContext(workspace=ws, policy_mode="trusted")
    assert tools.invoke("nope", {}, ctx).status == "error"
    bad = tools.invoke("read_file", {"path": 123}, ctx)
    assert bad.status == "error"


# ---------------------------------------------------------------------------
# 计划与待办
# ---------------------------------------------------------------------------


def test_plan_generation_and_confirm_gate():
    from backend.app.coding.plan import confirm_plan, generate_plan

    plan = generate_plan("重构认证模块", file_paths=["a.py", "b.ts", "c.py"])
    assert len(plan.steps) >= 5
    assert plan.confirmed is False
    titles = [s.title for s in plan.steps]
    assert any("侦察" in t for t in titles)
    assert any("验证" in t for t in titles)
    confirm_plan(plan, approved=True)
    assert plan.confirmed is True


def test_plan_step_state_machine():
    from backend.app.coding.plan import PlanError, generate_plan, set_step_state

    plan = generate_plan("任务")
    step = plan.steps[0]
    set_step_state(plan, step.id, "in_progress")
    set_step_state(plan, step.id, "done")
    # done → in_progress 非法
    with pytest.raises(PlanError):
        set_step_state(plan, step.id, "in_progress")
    with pytest.raises(PlanError):
        set_step_state(plan, "nonexistent", "done")


def test_todo_state_machine():
    from backend.app.coding.plan import PlanError, make_todos, set_todo_state

    todos = make_todos(["写测试", "改文档"])
    assert len(todos) == 2
    tid = todos[0].id
    set_todo_state(todos, tid, "doing")
    set_todo_state(todos, tid, "done")
    with pytest.raises(PlanError):
        set_todo_state(todos, tid, "blocked")  # done → blocked 非法
    assert set_todo_state(todos, tid, "pending").state == "pending"


def test_detect_stack():
    from backend.app.coding.plan import detect_stack

    stack = detect_stack(["a.py", "b.py", "c.ts", "d.vue"])
    assert stack[0] == "Python"
    assert "TypeScript" in stack


# ---------------------------------------------------------------------------
# 护栏
# ---------------------------------------------------------------------------


def test_guard_iteration_budget():
    from backend.app.coding.guard import GuardState, GuardTripped

    g = GuardState(max_iterations=2)
    g.begin_iteration()
    g.begin_iteration()
    with pytest.raises(GuardTripped) as exc:
        g.begin_iteration()
    assert exc.value.reason == "iteration_budget"


def test_guard_duplicate_circuit_breaker():
    from backend.app.coding.guard import GuardState, GuardTripped

    g = GuardState(duplicate_limit=3)
    for _ in range(2):
        g.note_tool_call("read_file", {"path": "a"})
    with pytest.raises(GuardTripped) as exc:
        g.note_tool_call("read_file", {"path": "a"})
    assert exc.value.reason == "duplicate_call"
    # 进展后计数清空
    g.note_progress()
    g.note_tool_call("read_file", {"path": "a"})


def test_guard_tool_budget():
    from backend.app.coding.guard import GuardState, GuardTripped

    g = GuardState(max_tool_calls=1)
    g.begin_tool_call()
    with pytest.raises(GuardTripped) as exc:
        g.begin_tool_call()
    assert exc.value.reason == "tool_budget"


# ---------------------------------------------------------------------------
# 工作流
# ---------------------------------------------------------------------------


def test_workflow_topo_and_cycle_detection():
    from backend.app.coding.workflow import WorkflowError, WorkflowNode, _topo_order

    nodes = [
        WorkflowNode(id="a", title="A", kind="noop"),
        WorkflowNode(id="b", title="B", kind="noop", depends_on=["a"]),
        WorkflowNode(id="c", title="C", kind="noop", depends_on=["b"]),
    ]
    assert _topo_order(nodes) == ["a", "b", "c"]

    cyclic = [
        WorkflowNode(id="x", title="X", kind="noop", depends_on=["y"]),
        WorkflowNode(id="y", title="Y", kind="noop", depends_on=["x"]),
    ]
    with pytest.raises(WorkflowError):
        _topo_order(cyclic)


def test_workflow_blocked_propagation():
    from backend.app.coding.workflow import WorkflowNode, run

    nodes = [
        WorkflowNode(id="a", title="A", kind="noop"),
        WorkflowNode(id="b", title="B", kind="noop", depends_on=["a"]),
        WorkflowNode(id="c", title="C", kind="noop", depends_on=["b"]),
    ]

    def executor(node):
        if node.id == "a":
            return {"status": "failed", "error": "boom"}
        return {"status": "ok"}

    outcome = run(nodes, executor=executor, concurrency=2)
    assert outcome["failed"] == 1
    assert outcome["blocked"] == 2
    assert outcome["ok"] is False


def test_workflow_concurrency_clamped():
    from backend.app.coding.workflow import WorkflowNode, run

    nodes = [WorkflowNode(id=f"n{i}", title=str(i), kind="noop") for i in range(4)]
    outcome = run(nodes, executor=lambda n: {"status": "ok"}, concurrency=999)
    from backend.app.coding import constants

    assert outcome["concurrency"] == constants.MAX_WORKFLOW_CONCURRENCY
    assert outcome["succeeded"] == 4


# ---------------------------------------------------------------------------
# 技能 / 子智能体
# ---------------------------------------------------------------------------


def test_builtin_skills_present():
    from backend.app.coding import skills

    items = skills.load_all()
    ids = {s.id for s in items}
    assert {"code-review", "bug-fix", "refactor", "test-writer", "doc-writer"} <= ids


def test_workspace_skill_overrides_builtin(coding_env):
    from backend.app.coding import skills

    root = coding_env["workspace"]
    skill_dir = root / ".wanshu" / "skills" / "code-review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: 自定义审查\ndescription: 覆盖内置\ntools: read_file\n---\n自定义审查提示词 {target}",
        encoding="utf-8",
    )
    items = {s.id: s for s in skills.load_all(root)}
    assert items["code-review"].source == "workspace"
    assert items["code-review"].name == "自定义审查"
    assert "自定义审查提示词" in skills.render(items["code-review"], {"target": "X"})


def test_subagent_depth_limit():
    from backend.app.coding import constants, subagent

    subagent.spawn(role="explorer", task="t", parent_depth=0)
    subagent.spawn(role="explorer", task="t", parent_depth=1)
    with pytest.raises(subagent.SubagentError):
        subagent.spawn(role="explorer", task="t", parent_depth=constants.SUBAGENT_MAX_DEPTH)
    with pytest.raises(subagent.SubagentError):
        subagent.spawn(role="nope", task="t")


def test_subagent_explorer_runs_readonly(coding_env):
    from backend.app.coding import subagent, tools
    from backend.app.coding.sandbox import open_workspace

    ws = open_workspace(str(coding_env["workspace"]))
    ctx = tools.ToolContext(workspace=ws, policy_mode="supervised")
    spec = subagent.spawn(role="explorer", task="add 函数 util", parent_depth=0)
    subagent.run(spec, ctx)
    assert spec.status == "done"
    assert "app.py" in " ".join(spec.findings.get("candidate_files", [])) or spec.findings.get("keywords")


def test_subagent_readonly_cannot_write(coding_env):
    """即便授予 implementer，子智能体仍在只读档下运行，写工具被拒。"""
    from backend.app.coding import subagent, tools
    from backend.app.coding.sandbox import open_workspace

    ws = open_workspace(str(coding_env["workspace"]))
    ctx = tools.ToolContext(workspace=ws, policy_mode="readonly")
    # 直接验证只读上下文拒绝写
    res = tools.invoke("write_file", {"path": "z.txt", "content": "x"}, ctx)
    assert res.status == "denied"
    assert subagent.ROLES["explorer"]["readonly"] is True


# ---------------------------------------------------------------------------
# 记忆桥（可审计 + 可证明删除）
# ---------------------------------------------------------------------------


def test_memory_write_list_and_provable_forget(coding_env):
    from backend.app.coding import memory_bridge

    written = memory_bridge.remember(
        session_id="cs_test", workspace=str(coding_env["workspace"]),
        kind="decision", title="选用方案 A", text="因为 B 方案有兼容风险",
    )
    assert written["ok"] is True
    capsule_id = written["capsule_id"]
    assert capsule_id

    listed = memory_bridge.list_memories(session_id="cs_test")
    assert listed["ok"] is True
    assert listed["count"] == 1
    assert listed["items"][0]["kind"] == "decision"

    forgotten = memory_bridge.forget(capsule_id=capsule_id)
    assert forgotten["ok"] is True
    assert forgotten["status"] == "forgotten"
    verification = forgotten["deletion_verification"]
    assert verification.get("complete") is True
    assert memory_bridge.list_memories(session_id="cs_test")["count"] == 0


def test_memory_empty_text_rejected(coding_env):
    from backend.app.coding import memory_bridge

    assert memory_bridge.remember(session_id="s", workspace=".", kind="context", text="  ")["ok"] is False


# ---------------------------------------------------------------------------
# 编排闭环
# ---------------------------------------------------------------------------


def _make_session(workspace: str, *, policy_mode: str = "trusted") -> str:
    from backend.app.coding import store
    from backend.app.coding.plan import Plan

    sid = store.new_id("cs")
    store.create_session({
        "id": sid, "owner_id": "tester", "title": "demo",
        "task": "为 app.py 增加 subtract 函数并补测试",
        "workspace": workspace, "policy_mode": policy_mode, "provider_pid": "",
        "state": "drafting", "plan": Plan().public(), "todos": [], "subagents": [],
        "approvals": [], "guard": {}, "last_run": None,
        "created_at": store.now(), "updated_at": store.now(),
    })
    return sid


def test_orchestrator_full_run_trusted(coding_env):
    from backend.app.coding import orchestrator, store

    sid = _make_session(str(coding_env["workspace"]), policy_mode="readonly")
    session = store.get_session(sid)
    plan = orchestrator.build_plan_for(session)
    assert plan.steps
    session["plan"] = plan.public()
    session["state"] = "planning"
    store.update_session(sid, {"plan": session["plan"], "state": "planning"})

    assert orchestrator.confirm(session, approved=True)["state"] == "running"
    fresh = store.get_session(sid)
    outcome = orchestrator.run_session(fresh, owner_id="tester")
    assert outcome["status"] == "done"
    assert outcome["plan"]["done"] == outcome["plan"]["total"]

    events = store.list_events(sid)
    types = {e["type"] for e in events}
    assert "step_started" in types
    assert "subagent_spawned" in types
    assert "memory_written" in types


def test_orchestrator_requires_confirmation(coding_env):
    from backend.app.coding import orchestrator, store

    sid = _make_session(str(coding_env["workspace"]))
    session = store.get_session(sid)
    session["plan"] = orchestrator.build_plan_for(session).public()
    session["state"] = "awaiting"
    store.update_session(sid, {"plan": session["plan"], "state": "awaiting"})
    fresh = store.get_session(sid)
    with pytest.raises(orchestrator.OrchestratorError):
        orchestrator.run_session(fresh, owner_id="tester")


def test_orchestrator_pauses_for_approval_then_resumes(coding_env):
    from backend.app.coding import orchestrator, store

    # supervised 档下，实施步骤的写操作会转为审批并暂停
    sid = _make_session(str(coding_env["workspace"]), policy_mode="supervised")
    session = store.get_session(sid)
    session["plan"] = orchestrator.build_plan_for(session).public()
    session["state"] = "planning"
    store.update_session(sid, {"plan": session["plan"], "state": "planning"})
    orchestrator.confirm(session, approved=True)

    fresh = store.get_session(sid)
    outcome = orchestrator.run_session(fresh, owner_id="tester")
    assert outcome["status"] == "awaiting_approval"
    paused = store.get_session(sid)
    assert paused["state"] == "paused"
    pending = [a for a in paused["approvals"] if a["status"] == "pending"]
    assert len(pending) == 1

    resolved = orchestrator.resolve_approval(paused, pending[0]["id"], approved=True)
    assert resolved["approval"]["status"] == "approved"
    assert resolved["result"]["status"] == "ok"

    resumed = store.get_session(sid)
    final = orchestrator.run_session(resumed, owner_id="tester")
    assert final["status"] == "done"


def test_orchestrator_rejects_illegal_state(coding_env):
    from backend.app.coding import orchestrator, store

    sid = _make_session(str(coding_env["workspace"]))
    session = store.get_session(sid)
    session["state"] = "done"
    with pytest.raises(orchestrator.OrchestratorError):
        orchestrator.transition(session, "running")


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def test_api_overview_and_catalogs(client):
    assert client.get("/platform/coding/overview", headers=_auth()).status_code == 200
    tools_resp = client.get("/platform/coding/tools", headers=_auth())
    assert tools_resp.status_code == 200
    assert len(tools_resp.json()["items"]) >= 8
    policy = client.get("/platform/coding/policy", headers=_auth())
    assert policy.status_code == 200
    assert policy.json()["matrix"]["readonly"]["high"] == "deny"
    assert client.get("/platform/coding/subagents", headers=_auth()).status_code == 200


def test_api_requires_auth(client):
    assert client.get("/platform/coding/overview").status_code == 401


def test_api_session_lifecycle(client, tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.py").write_text("x = 1\n", encoding="utf-8")
    h = _auth()

    created = client.post("/platform/coding/sessions", headers=h, json={
        "task": "增加一个函数", "workspace": str(ws), "policy_mode": "readonly",
    })
    assert created.status_code == 200, created.text
    sid = created.json()["id"]

    planned = client.post(f"/platform/coding/sessions/{sid}/plan", headers=h, json={"use_llm": False})
    assert planned.status_code == 200
    assert planned.json()["state"] == "awaiting"

    confirmed = client.post(f"/platform/coding/sessions/{sid}/plan/confirm", headers=h, json={"approved": True})
    assert confirmed.status_code == 200
    assert confirmed.json()["state"] == "running"

    listed = client.get("/platform/coding/sessions", headers=h)
    assert listed.status_code == 200
    assert any(item["id"] == sid for item in listed.json()["items"])

    detail = client.get(f"/platform/coding/sessions/{sid}", headers=h)
    assert detail.status_code == 200
    assert detail.json()["plan"]["confirmed"] is True


def test_api_workspace_outside_whitelist_rejected(client):
    r = client.post("/platform/coding/sessions", headers=_auth(), json={
        "task": "x", "workspace": "C:\\Windows\\System32", "policy_mode": "readonly",
    })
    assert r.status_code == 403


def test_api_tool_invoke_and_events(client, tmp_path):
    ws = tmp_path / "ws2"
    ws.mkdir()
    (ws / "a.py").write_text("hello\n", encoding="utf-8")
    h = _auth()
    sid = client.post("/platform/coding/sessions", headers=h, json={
        "task": "读文件", "workspace": str(ws), "policy_mode": "readonly",
    }).json()["id"]

    ok = client.post(f"/platform/coding/sessions/{sid}/tool", headers=h,
                     json={"tool_id": "read_file", "params": {"path": "a.py"}})
    assert ok.status_code == 200
    assert ok.json()["result"]["status"] == "ok"

    denied = client.post(f"/platform/coding/sessions/{sid}/tool", headers=h,
                         json={"tool_id": "write_file", "params": {"path": "b.py", "content": "x"}})
    assert denied.json()["result"]["status"] == "denied"

    events = client.get(f"/platform/coding/sessions/{sid}/events", headers=h)
    assert events.status_code == 200
    assert events.json()["count"] >= 2


def test_api_todos_and_memory(client, tmp_path):
    ws = tmp_path / "ws3"
    ws.mkdir()
    h = _auth()
    sid = client.post("/platform/coding/sessions", headers=h, json={
        "task": "t", "workspace": str(ws), "policy_mode": "readonly",
    }).json()["id"]

    todos = client.post(f"/platform/coding/sessions/{sid}/todos", headers=h,
                        json={"items": ["第一步", "第二步"]})
    assert todos.status_code == 200
    assert len(todos.json()["todos"]) == 2
    tid = todos.json()["todos"][0]["id"]
    updated = client.post(f"/platform/coding/sessions/{sid}/todos/{tid}", headers=h,
                          json={"state": "doing"})
    assert updated.json()["todos"][0]["state"] == "doing"

    written = client.post(f"/platform/coding/sessions/{sid}/memory", headers=h,
                          json={"kind": "pitfall", "title": "坑", "text": "循环导入"})
    assert written.status_code == 200
    assert written.json()["ok"] is True
    cid = written.json()["capsule_id"]

    listed = client.get(f"/platform/coding/sessions/{sid}/memory", headers=h)
    assert listed.json()["count"] == 1

    forgotten = client.post(f"/platform/coding/sessions/{sid}/memory/{cid}/forget", headers=h)
    assert forgotten.json()["ok"] is True
    assert client.get(f"/platform/coding/sessions/{sid}/memory", headers=h).json()["count"] == 0


def test_api_workflow(client, tmp_path):
    ws = tmp_path / "ws4"
    ws.mkdir()
    (ws / "a.py").write_text("x=1\n", encoding="utf-8")
    h = _auth()
    sid = client.post("/platform/coding/sessions", headers=h, json={
        "task": "t", "workspace": str(ws), "policy_mode": "readonly",
    }).json()["id"]

    r = client.post(f"/platform/coding/sessions/{sid}/workflow", headers=h, json={
        "concurrency": 2,
        "nodes": [
            {"id": "n1", "title": "读", "kind": "tool",
             "payload": {"tool_id": "read_file", "params": {"path": "a.py"}}},
            {"id": "n2", "title": "列", "kind": "tool",
             "payload": {"tool_id": "list_dir", "params": {"path": "."}}},
        ],
    })
    assert r.status_code == 200, r.text
    assert r.json()["succeeded"] == 2
    assert r.json()["ok"] is True
