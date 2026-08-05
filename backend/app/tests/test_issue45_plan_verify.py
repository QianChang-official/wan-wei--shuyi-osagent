"""给糯糯的 Issue#45 解法验证（月沐侧先行验证）"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

H = {"x-api-key": "test-key"}


def _agents_mod():
    import backend.app.platform_api.agents as agents_mod
    return agents_mod


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
    from fastapi.testclient import TestClient
    yield TestClient(main_mod.app, raise_server_exceptions=False)
    if prev_dir is None:
        os.environ.pop("WANWEI_PLATFORM_DIR", None)
    else:
        os.environ["WANWEI_PLATFORM_DIR"] = prev_dir


def test_pure_function_consumes_memory_instructions(client, isolated_db):
    """方案验证：纯函数级测记忆指令注入，绕开网关 502"""
    agents_mod = _agents_mod()

    # 1. 写入记忆指令（真实业务路径）
    r = client.post(
        "/platform/memory/remember",
        json={"text": "所有回复先用中文思考"},
        headers=H,
    )
    assert r.status_code == 200, r.text

    # 2. 直接调纯函数，不经过 /chat
    system_prompt, status = agents_mod._compose_system_prompt(
        {"goal": "测试目标"}, "medium", "sandbox"
    )
    assert status == "ok"
    assert "中文思考" in system_prompt
    assert "用户长期记忆指令" in system_prompt


def test_pure_function_empty_when_no_instructions(client, isolated_db):
    """方案验证：无指令时如实 empty"""
    agents_mod = _agents_mod()

    system_prompt, status = agents_mod._compose_system_prompt({}, "medium", "sandbox")
    assert status == "empty"
    assert "中文思考" not in system_prompt
