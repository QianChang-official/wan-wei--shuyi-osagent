"""智能体网关回退链回归测试（agents._resolve_gateway_target / _try_gateway）。

覆盖：
1. agent 未绑定 provider 时，回退到模型接入舱中用户显式启用的云端 provider
   （与 /soul/chat 同一事实源 get_active_provider）；
2. agent 绑定 anthropic 时经统一分发器走原生协议（而非 openai_compatible 通路）;
3. 全部不可用时如实回退模拟（text=None），不伪造网关结果。
"""

from __future__ import annotations

import pytest

from backend.app.model_gateway import service as gateway_service
from backend.app.platform_api import agents as agents_mod
from backend.app.platform_api import providers as providers_mod
from backend.app.security import encryption


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("WANWEI_PLATFORM_DIR", str(tmp_path / "platform"))
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.delenv("WANWEI_OPENAI_COMPATIBLE_BASE", raising=False)
    monkeypatch.delenv("WANWEI_OPENAI_COMPATIBLE_MODEL", raising=False)


def _seed(pid: str, *, model: str | None = None):
    record = {
        "enabled": True,
        "api_key_encrypted": encryption.encrypt("sk-test-1234"),
        "updated_at": "2026-01-01T00:00:00Z",
    }
    if model:
        record["model"] = model
    providers_mod._store.set(pid, record)


def test_unbound_agent_falls_back_to_enabled_deepseek():
    _seed("deepseek")
    target = agents_mod._resolve_gateway_target(run={"provider_pid": ""})
    assert target is not None
    api_base, api_key, model, label = target
    assert label == "deepseek"
    assert api_base == "https://api.deepseek.com"
    assert model == "deepseek-chat"
    assert api_key == "sk-test-1234"


def test_explicit_pid_outranks_global_active_provider():
    _seed("kimi_moonshot")
    _seed("zai")
    # agent 显式绑定 zai：即使目录顺序里 kimi 在前，也以绑定为先
    _, _, model, label = agents_mod._resolve_gateway_target(
        run={"provider_pid": "zai"},
    )
    assert label == "zai"


def test_anthropic_binding_routes_through_native_dispatch(monkeypatch):
    import asyncio
    import sys

    _seed("anthropic", model="claude-sonnet-4-5")
    seen: dict = {}

    def fake_dispatch(provider, api_base, api_key, model, prompt, max_tokens):
        seen.update(provider=provider)
        return "ok", 5, "native-reply"

    # agents.py 以 ``app.model_gateway.service`` 短名导入（conftest 双路径），
    # 与测试的 ``backend.app...`` 长名是不同模块对象；两处都要打补丁。
    patched = 0
    for name, mod in list(sys.modules.items()):
        if name.endswith("model_gateway.service") and mod is not None:
            monkeypatch.setattr(mod, "_provider_dispatch", fake_dispatch)
            patched += 1
    assert patched >= 1

    async def _run():
        return await agents_mod._try_gateway(
            "hello", run={"provider_pid": "anthropic"},
        )

    text, label = asyncio.run(_run())
    assert text == "native-reply"
    assert label == "anthropic"
    assert seen["provider"] == "anthropic"  # 原生协议分发，不再硬走 openai_compatible


def test_real_gateway_selection_uses_run_owner(monkeypatch):
    calls: list[str | None] = []

    def fake_active_provider(owner_id=None):
        calls.append(owner_id)
        if owner_id == "owner-a":
            return {
                "pid": "deepseek", "base_url": "https://a.example/v1",
                "api_key": "a-key", "model": "a-model",
            }
        return None

    monkeypatch.setattr(providers_mod, "get_active_provider", fake_active_provider)
    target = agents_mod._resolve_gateway_target(
        {"provider_pid": "", "owner_id": "owner-a"},
    )
    assert target == ("https://a.example/v1", "a-key", "a-model", "deepseek")
    assert calls == ["owner-a"]


def test_nothing_configured_returns_none_for_mock_fallback():
    assert agents_mod._resolve_gateway_target(run={"provider_pid": ""}) is None

    import asyncio

    text, label = asyncio.run(agents_mod._try_gateway("hello", run=None))
    assert text is None
    assert label is None
