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

"""Codex 借鉴机制测试：沙箱策略矩阵 + 哈希链执行轨迹。

对应实现：
- ``platform_api/sandbox_policy.py``（借鉴 openai/codex Apache-2.0 机制）
- ``audit/rollout.py``（Codex rollout 持久化 + resume 思路）
"""

from __future__ import annotations

import importlib
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.app.audit import rollout
from backend.app.db import get_conn
from backend.app.perception import pipeline
from backend.app.platform_api import sandbox_policy as sp


# ---------------------------------------------------------------------------
# 沙箱策略矩阵
# ---------------------------------------------------------------------------


def test_read_only_mode_denies_write_with_retryable():
    decision = sp.decide(capability="fs_write", sandbox_mode="read_only")
    assert decision.outcome == "retryable"
    assert decision.escalate_to == "workspace_write"


def test_never_does_not_expand_sandbox():
    """Codex 的关键不变量：never 只关审批，不放宽技术边界。"""
    decision = sp.decide(
        capability="fs_write", sandbox_mode="read_only", approval_policy="never"
    )
    assert decision.outcome == "retryable"
    assert "never 只关闭审批" in decision.detail.get("policy_note", "")


def test_on_request_inside_sandbox_asks():
    decision = sp.decide(capability="fs_read", approval_policy="on_request")
    assert decision.outcome == "approval"
    assert sp.decide(capability="fs_read", approval_policy="never").outcome == "allow"


def test_protected_paths_recursively_read_only():
    for path in (".git/config", "sub/.git/HEAD", ".codex/config.toml", ".agents/x"):
        decision = sp.decide(
            capability="git", sandbox_mode="workspace_write", relative_path=path
        )
        assert decision.outcome == "retryable", path
        assert decision.detail["protected"] in {".git", ".codex", ".agents"}
    # full_access 下 Codex 不再施加特殊保护。
    assert sp.decide(
        capability="git", sandbox_mode="full_access", relative_path=".git/config"
    ).outcome == "allow"


def test_protected_direct_path_and_case_insensitive():
    """负测试：直达受保护目录本身、大小写变体同样被拦截。

    Windows/macOS 文件系统大小写不敏感，".GIT" 与 ".git" 同指一个目录；
    末段保护若区分大小写或只看下级路径，都会被绕过。
    """
    for path in (".git", "x/.git", ".GIT/HEAD", ".Git/config", "sub/.CODEX/x"):
        decision = sp.decide(
            capability="git", sandbox_mode="workspace_write", relative_path=path
        )
        assert decision.outcome == "retryable", path


def test_outside_workspace_approval_vs_never():
    approval = sp.decide(
        capability="fs_write", approval_policy="on_request", in_workspace=False
    )
    assert approval.outcome == "approval" and approval.escalate_to == "full_access"
    never = sp.decide(
        capability="fs_write", approval_policy="never", in_workspace=False
    )
    assert never.outcome == "retryable"


def test_network_default_closed_in_workspace_write():
    assert sp.decide(capability="network").outcome == "approval"
    enabled = sp.decide(
        capability="network", approval_policy="never", network_enabled=True
    )
    assert enabled.outcome == "allow"


def test_full_access_never_is_allowed_but_documented():
    """Codex 明确不推荐的组合，但策略层必须能表达（由部署选择）。"""
    decision = sp.decide(capability="network", sandbox_mode="full_access",
                         approval_policy="never")
    assert decision.outcome == "allow"


def test_invalid_inputs_rejected():
    for kwargs in (
        {"capability": "teleport"},
        {"capability": "fs_read", "sandbox_mode": "god_mode"},
        {"capability": "fs_read", "approval_policy": "maybe"},
    ):
        with pytest.raises(sp.SandboxPolicyError):
            sp.decide(**kwargs)


def test_policy_from_env_defaults_strict():
    policy = sp.policy_from_env()
    assert policy["sandbox_mode"] == "workspace_write"
    assert policy["approval_policy"] == "on_request"
    assert "on-failure" in policy["semantics_note"]


# ---------------------------------------------------------------------------
# 哈希链执行轨迹
# ---------------------------------------------------------------------------


def test_rollout_chain_verifies(isolated_db):
    for i in range(3):
        rollout.append_rollout(
            thread_id="t-1", item_type="tool_call", item={"seq": i}
        )
    result = rollout.verify_chain("t-1")
    assert result["complete"] is True and result["checked"] == 3


def test_rollout_tamper_is_detected_at_exact_entry(isolated_db):
    for i in range(4):
        rollout.append_rollout(thread_id="t-2", item_type="tool_call", item={"seq": i})
    # 绕过应用层直接改库：把第 3 条的 payload 换掉（哈希不变）。
    conn = get_conn()
    conn.execute(
        "UPDATE agent_rollouts SET item='{\"seq\": 999}' WHERE thread_id='t-2' "
        "AND turn_index=2"
    )
    conn.commit()
    result = rollout.verify_chain("t-2")
    assert result["complete"] is False
    assert result["reason"] == "hash_mismatch"
    assert result["broken_at"] is not None and result["checked"] == 2


def test_rollout_link_break_detected(isolated_db):
    rollout.append_rollout(thread_id="t-3", item_type="a", item={"x": 1})
    rollout.append_rollout(thread_id="t-3", item_type="b", item={"x": 2})
    conn = get_conn()
    conn.execute(
        "UPDATE agent_rollouts SET prev_sha256='deadbeef' WHERE thread_id='t-3' "
        "AND turn_index=1"
    )
    conn.commit()
    result = rollout.verify_chain("t-3")
    assert result["complete"] is False and result["reason"] == "broken_link"


def test_rollout_turn_auto_increments_and_resume(isolated_db):
    rollout.append_rollout(thread_id="t-4", item_type="turn", item={"n": 1})
    rollout.append_rollout(thread_id="t-4", item_type="turn", item={"n": 2})
    resume = rollout.resume_point("t-4")
    assert resume["turn_index"] == 1
    assert [e["item"]["n"] for e in resume["entries"]] == [2]
    assert rollout.resume_point("t-unknown") is None


def test_rollout_scope_isolation(isolated_db):
    rollout.append_rollout(thread_id="t-5", item_type="x", item={}, owner_id="owner-a")
    assert rollout.list_rollout("t-5", owner_id="owner-a")
    assert rollout.list_rollout("t-5", owner_id="owner-b") == []


def test_rollout_item_size_limit(isolated_db):
    with pytest.raises(rollout.RolloutError):
        rollout.append_rollout(
            thread_id="t-6", item_type="big", item={"blob": "x" * 70000}
        )


def test_perception_writes_rollout_entries(isolated_db):
    """感知动作落链：成功一条、故障一条，链完整可校验。"""
    def _png():
        buf = io.BytesIO()
        Image.new("RGB", (16, 16), (10, 20, 30)).save(buf, format="PNG")
        return buf.getvalue()

    session = pipeline.get_or_create_session(owner_id="owner-a")
    ok = pipeline.ingest_image(
        session, image_bytes=_png(), caption="巡检照片", owner_id="owner-a"
    )
    assert ok["ok"] is True
    bad = pipeline.ingest_audio(session, wav_bytes=b"junk", transcribe=False,
                                owner_id="owner-a")
    assert bad["ok"] is False

    thread = f"perception:{session.session_id}"
    entries = rollout.list_rollout(thread, owner_id="owner-a")
    assert [e["item_type"] for e in entries] == [
        "perception_completed", "perception_fault",
    ]
    assert rollout.verify_chain(thread, owner_id="owner-a")["complete"] is True


# ---------------------------------------------------------------------------
# HTTP 端点
# ---------------------------------------------------------------------------

_API_KEY = "codex-borrowed-policy-key-0123456789"


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("WANWEI_API_KEY", _API_KEY)
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.delenv("WANWEI_PRODUCTION", raising=False)

    from backend.app import init_db
    from backend.app import main as main_module
    from backend.app.db import close_all

    close_all()
    importlib.reload(main_module)
    init_db.main()
    return TestClient(main_module.app, raise_server_exceptions=False)


def test_api_policy_endpoint_and_decide(client):
    policy = client.get(
        "/memory/perception/policy", headers={"x-api-key": _API_KEY}
    )
    assert policy.status_code == 200
    assert policy.json()["sandbox_mode"] in sp.SANDBOX_MODES

    decision = client.post(
        "/memory/perception/policy/decide",
        headers={"x-api-key": _API_KEY},
        json={"capability": "git", "sandbox_mode": "workspace_write",
              "relative_path": ".git/config"},
    )
    assert decision.status_code == 200
    assert decision.json()["outcome"] == "retryable"

    bad = client.post(
        "/memory/perception/policy/decide",
        headers={"x-api-key": _API_KEY},
        json={"capability": "teleport"},
    )
    assert bad.status_code == 422


def test_api_rollout_list_and_verify(client):
    """端到端：感知接入 → 轨迹落链 → 列表 + 链校验。

    轨迹由感知管道写入，owner 与 API 作用域一致（项目口径：空 owner 的
    记录对具名调用方不可见）。
    """
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (200, 30, 30)).save(buf, format="PNG")
    import base64

    ingest = client.post(
        "/memory/perception/image",
        headers={"x-api-key": _API_KEY},
        json={
            "data_base64": base64.b64encode(buf.getvalue()).decode(),
            "caption": "轨迹来源照片",
        },
    )
    assert ingest.status_code == 200, ingest.text
    thread = f"perception:{ingest.json()['session_id']}"

    listed = client.get(
        f"/memory/audit/rollout/{thread}", headers={"x-api-key": _API_KEY}
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["count"] == 1
    assert listed.json()["entries"][0]["item_type"] == "perception_completed"

    verified = client.get(
        f"/memory/audit/rollout/{thread}/verify",
        headers={"x-api-key": _API_KEY},
    )
    assert verified.json()["complete"] is True
