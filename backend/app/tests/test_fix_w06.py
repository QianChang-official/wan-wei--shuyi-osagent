"""W06 智能体后端修复回归测试。

覆盖条目：
- 04-#4  _try_gateway 按 run 绑定的 provider_pid 解析配置，回退链明确，结果标注实际 provider
- 04-#6  RunIn/ChatIn/SubagentIn depth/gear 非法值 422
- 04-#7  chat 拒绝 `_` 前缀保留命名空间 agent_id
- 04-#10 SubagentIn 补齐 agent_id/depth/gear + 嵌套上限
- 04-#16 runs retention（每 agent 最近 500 条）+ limit/offset 分页
- 06-#4  chat/run 系统提示真实消费 memory_center 指令，失败如实降级
"""
from __future__ import annotations

import asyncio
import importlib
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

H = {"x-api-key": "test-key"}


@pytest.fixture()
def client(tmp_path):
    os.environ["WANWEI_API_KEY"] = "test-key"
    os.environ["WANWEI_MEMORY_DB"] = str(tmp_path / "memory.db")
    prev_dir = os.environ.get("WANWEI_PLATFORM_DIR")
    os.environ["WANWEI_PLATFORM_DIR"] = str(tmp_path / "platform")
    os.environ.pop("WANWEI_PRODUCTION", None)
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    import backend.app.main as main_mod
    importlib.reload(main_mod)
    yield TestClient(main_mod.app, raise_server_exceptions=False)
    if prev_dir is None:
        os.environ.pop("WANWEI_PLATFORM_DIR", None)
    else:
        os.environ["WANWEI_PLATFORM_DIR"] = prev_dir


def _agents_mod():
    import backend.app.platform_api.agents as agents_mod
    return agents_mod


def _make_agent(client, **overrides) -> str:
    body = {"name": "W06测试", "gear": "sandbox", "depth": "medium"}
    body.update(overrides)
    r = client.post("/platform/agents", json=body, headers=H)
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ---------------------------------------------------------------- 04-#6 校验


def test_run_in_rejects_invalid_depth_and_gear(client):
    aid = _make_agent(client)
    r = client.post(
        "/platform/agents/run",
        json={"agent_id": aid, "task": "t", "depth": "bogus"},
        headers=H,
    )
    assert r.status_code == 422, r.text
    r = client.post(
        "/platform/agents/run",
        json={"agent_id": aid, "task": "t", "gear": "bogus"},
        headers=H,
    )
    assert r.status_code == 422, r.text
    # 合法值不受影响
    r = client.post(
        "/platform/agents/run",
        json={"agent_id": aid, "task": "t", "depth": "low", "gear": "sandbox"},
        headers=H,
    )
    assert r.status_code == 201, r.text


def test_chat_in_rejects_invalid_depth_and_gear(client):
    r = client.post(
        "/platform/agents/chat",
        json={"message": "你好", "depth": "bogus"},
        headers=H,
    )
    assert r.status_code == 422, r.text
    r = client.post(
        "/platform/agents/chat",
        json={"message": "你好", "gear": "bogus"},
        headers=H,
    )
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------- 04-#7 保留命名空间


def test_chat_rejects_reserved_namespace_agent_id(client):
    for reserved in ("_teams", "_floating"):
        r = client.post(
            "/platform/agents/chat",
            json={"message": "你好", "agent_id": reserved},
            headers=H,
        )
        assert r.status_code == 404, (reserved, r.text)
    # 正常 agent 不受影响
    aid = _make_agent(client)
    r = client.post(
        "/platform/agents/chat",
        json={"message": "你好", "agent_id": aid},
        headers=H,
    )
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------- 04-#10 子代理


def test_subagent_accepts_binding_fields(client):
    aid = _make_agent(client)
    r = client.post(
        "/platform/agents/subagent",
        json={"task": "子任务", "agent_id": aid, "depth": "low", "gear": "sandbox"},
        headers=H,
    )
    assert r.status_code == 201, r.text
    run = r.json()["run"]
    assert run["agent_id"] == aid
    assert run["depth"] == "low"
    assert run["gear"] == "sandbox"
    assert run["subagent_depth"] == 0


def test_subagent_rejects_invalid_depth(client):
    r = client.post(
        "/platform/agents/subagent",
        json={"task": "子任务", "depth": "bogus"},
        headers=H,
    )
    assert r.status_code == 422, r.text


def test_subagent_nesting_depth_capped(client):
    agents_mod = _agents_mod()
    aid = _make_agent(client)
    # 根 run（第 0 层）
    r = client.post(
        "/platform/agents/run",
        json={"agent_id": aid, "task": "根任务"},
        headers=H,
    )
    assert r.status_code == 201, r.text
    root_id = r.json()["id"]

    # 第 1 层：允许
    r = client.post(
        "/platform/agents/subagent",
        json={"task": "一层子代理", "parent_run_id": root_id},
        headers=H,
    )
    assert r.status_code == 201, r.text
    child_id = r.json()["run"]["id"]
    assert r.json()["run"]["subagent_depth"] == 1

    # 第 2 层：允许（达到上限）
    r = client.post(
        "/platform/agents/subagent",
        json={"task": "二层子代理", "parent_run_id": child_id},
        headers=H,
    )
    assert r.status_code == 201, r.text
    grandchild_id = r.json()["run"]["id"]
    assert r.json()["run"]["subagent_depth"] == 2

    # 第 3 层：超出上限 SUBAGENT_MAX_DEPTH=2 → 422
    r = client.post(
        "/platform/agents/subagent",
        json={"task": "三层子代理", "parent_run_id": grandchild_id},
        headers=H,
    )
    assert r.status_code == 422, r.text
    assert "嵌套深度超限" in r.text

    # 不存在的父运行仍 404
    r = client.post(
        "/platform/agents/subagent",
        json={"task": "孤儿", "parent_run_id": "run_不存在"},
        headers=H,
    )
    assert r.status_code == 404, r.text
    assert agents_mod.SUBAGENT_MAX_DEPTH == 2


# ---------------------------------------------------------------- 04-#16 retention + 分页


def _seed_runs(agents_mod, agent_id: str, count: int) -> list[str]:
    """直接向 store 灌入 count 条 created_at 递增的 run，返回 id 列表（旧→新）。"""
    base = datetime(2024, 1, 1).astimezone()
    ids = []
    for i in range(count):
        rid = f"run_seed{i:04d}"
        ids.append(rid)
        agents_mod._runs.set(rid, {
            "id": rid,
            "kind": "solo",
            "agent_id": agent_id,
            "task": f"种子任务{i}",
            "status": "done",
            "created_at": (base + timedelta(seconds=i)).isoformat(timespec="seconds"),
        })
    return ids


def test_runs_retention_keeps_recent_500_per_agent(client):
    agents_mod = _agents_mod()
    aid = _make_agent(client)
    ids = _seed_runs(agents_mod, aid, 505)
    agents_mod._enforce_runs_retention()  # noqa: SLF001
    remaining = [
        r for r in agents_mod._runs.all().values()  # noqa: SLF001
        if isinstance(r, dict) and r.get("agent_id") == aid
    ]
    assert len(remaining) == 500
    remaining_ids = {r["id"] for r in remaining}
    # 最旧的 5 条被裁剪，最新的保留
    for old in ids[:5]:
        assert old not in remaining_ids
    assert ids[-1] in remaining_ids


def test_new_run_creation_triggers_retention(client):
    agents_mod = _agents_mod()
    aid = _make_agent(client)
    _seed_runs(agents_mod, aid, 500)
    r = client.post(
        "/platform/agents/run",
        json={"agent_id": aid, "task": "触发裁剪"},
        headers=H,
    )
    assert r.status_code == 201, r.text
    new_id = r.json()["id"]
    remaining = [
        x for x in agents_mod._runs.all().values()  # noqa: SLF001
        if isinstance(x, dict) and x.get("agent_id") == aid
    ]
    assert len(remaining) == 500
    assert new_id in {x["id"] for x in remaining}


def test_runs_pagination_limit_offset(client):
    aid = _make_agent(client)
    agents_mod = _agents_mod()
    _seed_runs(agents_mod, aid, 10)
    # 无分页参数：向后兼容全量返回
    r = client.get("/platform/agents/runs", headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 10
    assert len(body["items"]) == 10
    # limit/offset 分页：total 恒为全量
    r = client.get("/platform/agents/runs?limit=3&offset=2", headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 10
    assert len(body["items"]) == 3
    assert body["limit"] == 3
    assert body["offset"] == 2
    # 倒序：offset=2 之后的第一条是全量倒序的第 3 条
    full = client.get("/platform/agents/runs", headers=H).json()["items"]
    assert body["items"][0]["id"] == full[2]["id"]
    # 非法分页参数 422
    r = client.get("/platform/agents/runs?limit=0", headers=H)
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------- 04-#4 网关 provider 解析


def test_gateway_target_prefers_run_bound_platform_provider(client):
    """run 绑定 platform provider 且已启用 → 用其 base_url/model/解密 key。"""
    agents_mod = _agents_mod()
    r = client.put(
        "/platform/providers/configs/lm_studio",
        json={
            "enabled": True,
            "api_key": "sk-test-1234",
            "base_url": "http://127.0.0.1:1234/v1",
            "model": "qwen/qwen3-8b",
        },
        headers=H,
    )
    assert r.status_code == 200, r.text
    target = agents_mod._resolve_gateway_target({"provider_pid": "lm_studio"})  # noqa: SLF001
    assert target is not None
    api_base, api_key, model, label = target
    assert api_base == "http://127.0.0.1:1234/v1"
    assert api_key == "sk-test-1234"
    assert model == "qwen/qwen3-8b"
    assert label == "lm_studio"


def test_gateway_target_falls_back_to_openai_compatible(client, monkeypatch):
    """绑定的 provider 不可用时 → 回退 model_gateway 的 openai_compatible。"""
    agents_mod = _agents_mod()
    # 生产代码以 `app.*` 绝对导入（与 `backend.app.*` 为不同模块对象），须 patch 同一身份
    import app.model_gateway.service as mgw

    def fake_config(name):
        if name == "openai_compatible":
            return {
                "provider": "openai_compatible",
                "api_base": "http://127.0.0.1:8080/v1",
                "api_key": "",
                "model": "local-model",
                "enabled": True,
            }
        return None

    monkeypatch.setattr(mgw, "_provider_config", fake_config)
    # 未启用的 platform provider（CATALOG 有但 store 无记录）→ 继续回退
    target = agents_mod._resolve_gateway_target({"provider_pid": "lm_studio"})  # noqa: SLF001
    assert target is not None
    assert target[3] == "openai_compatible"
    # 无绑定 → 直接兜底
    target = agents_mod._resolve_gateway_target({"provider_pid": ""})  # noqa: SLF001
    assert target is not None
    assert target[3] == "openai_compatible"


def test_finalize_run_annotates_actual_provider(client, monkeypatch):
    """网关真实生成时，run 结果标注实际使用的 provider。"""
    agents_mod = _agents_mod()
    import app.model_gateway.service as mgw

    monkeypatch.setattr(mgw, "_provider_config", lambda name: {
        "provider": name,
        "api_base": "http://127.0.0.1:8080/v1",
        "api_key": "",
        "model": "local-model",
        "enabled": True,
    } if name == "openai_compatible" else None)
    monkeypatch.setattr(
        mgw, "_openai_compatible_smoke",
        lambda api_base, api_key, model, prompt, max_tokens: ("ok", 1, "真实结论"),
    )
    aid = _make_agent(client)
    r = client.post(
        "/platform/agents/run",
        json={"agent_id": aid, "task": "网关标注"},
        headers=H,
    )
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    # 直接置为 running 后手动 finalize，避免后台异步推进的不确定性
    run = agents_mod._runs.get(rid)  # noqa: SLF001
    run["status"] = "running"
    agents_mod._runs.set(rid, run)  # noqa: SLF001
    asyncio.run(agents_mod._finalize_run(rid))  # noqa: SLF001
    run = agents_mod._runs.get(rid)  # noqa: SLF001
    assert run["engine"] == "gateway"
    assert run["provider_used"] == "openai_compatible"
    assert "provider=openai_compatible" in run["result"]
    assert "真实结论" in run["result"]


# ---------------------------------------------------------------- 06-#4 记忆指令注入


def test_chat_consumes_memory_instructions(client):
    r = client.post(
        "/platform/memory/remember",
        json={"text": "所有回复先用中文思考"},
        headers=H,
    )
    assert r.status_code == 200, r.text

    r = client.post(
        "/platform/agents/chat",
        json={"message": "你好"},
        headers=H,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["memory_injection"] == "ok"
    # run 记录内系统提示真实包含指令文本
    run = client.get(f"/platform/agents/runs/{body['run_id']}", headers=H).json()
    assert run["memory_injection"] == "ok"
    assert "中文思考" in run["system_prompt"]
    assert "用户长期记忆指令" in run["system_prompt"]


def test_chat_memory_injection_empty_when_no_instructions(client):
    r = client.post(
        "/platform/agents/chat",
        json={"message": "你好"},
        headers=H,
    )
    assert r.status_code == 200, r.text
    assert r.json()["memory_injection"] == "empty"


def test_memory_injection_failure_degrades_honestly(client, monkeypatch):
    """指令拉取失败时如实标注 unavailable，不假装已注入。"""
    agents_mod = _agents_mod()
    import app.platform_api.memory_center as mc

    def boom():
        raise RuntimeError("store 损坏")

    monkeypatch.setattr(mc, "_read_lines", boom)
    text, status = agents_mod._memory_instructions_block()  # noqa: SLF001
    assert status == "unavailable"
    assert "拉取失败" in text
    prompt, inj = agents_mod._compose_system_prompt({}, "medium", "sandbox")  # noqa: SLF001
    assert inj == "unavailable"
    assert "拉取失败" in prompt
