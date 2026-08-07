"""Issue #45 (P0-3): 网关不可用/异常时 chat 必须如实失败。

P0-3 要求删除 mock 回退分支：网关不可用时不得产出任何模型口吻文本，
必须返回明确错误与 provider 失败原因。本文件覆盖两条路径：

1. 未配置任何网关 -> 502 + gateway_unavailable；
2. 网关调用抛异常   -> 非 2xx，且响应体不含伪造的模型回答文本。

patch 点说明（踩过的坑）：monkeypatch 必须打在 chat 实际调用的那个模块
属性上，即 ``agents._try_gateway``；patch 其他模块的同名函数不会生效。
"""
from __future__ import annotations

import importlib
import os
import sys
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


def test_chat_without_gateway_fails_honestly(client):
    """无网关配置：502 + 机器可读 error，不产出模型口吻文本。"""
    r = client.post("/platform/agents/chat", json={"message": "你好"}, headers=H)
    assert r.status_code == 502, r.text
    detail = r.json()["detail"]
    assert detail["error"] == "gateway_unavailable"
    # 必须给出失败原因，且不得夹带任何"回答"字段伪装成功。
    assert detail.get("reason")
    assert "reply" not in detail
    assert "response" not in detail


def test_chat_gateway_exception_does_not_fall_back_to_mock(client, monkeypatch):
    """网关抛异常时不得静默回退 mock 文本。"""
    agents_mod = _agents_mod()
    marker = "这是一段绝不该出现的模型口吻回答"

    async def boom(*_args, **_kwargs):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(agents_mod, "_try_gateway", boom)

    r = client.post("/platform/agents/chat", json={"message": "你好"}, headers=H)
    assert r.status_code >= 400, r.text
    assert marker not in r.text
    # 成功语义不得与失败共存。
    assert '"status":"done"' not in r.text.replace(" ", "")
