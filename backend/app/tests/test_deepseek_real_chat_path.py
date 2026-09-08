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

"""DeepSeek 真实调用通路回归测试。

覆盖：
1. ``get_active_provider`` 选择语义：enabled + 密钥可解密 + base_url/model 齐备；
   禁用 / 密钥损坏 / OAuth-only / 占位端点 / 本地类一律跳过。
2. ``/soul/chat`` 对话通路优先消费模型接入舱中启用的 DeepSeek，
   响应 provider 字段如实回 ``deepseek``，密钥经 Fernet 解密后仅用于调用。
3. 无启用 provider 时回退 ``WANWEI_OPENAI_COMPATIBLE_*``，既有契约不变
   （未配置如实 gateway_not_configured）。
4. model_gateway 目录包含 deepseek；未配置 DB config 时不再报 not_implemented。
5. google_ai_studio → gemini 原生通路别名与 /v1beta 端点归一化。
"""

from __future__ import annotations

import pytest

from backend.app.model_gateway import service as gateway_service
from backend.app.model_gateway.schemas import ModelGatewayTestIn
from backend.app.platform_api import providers as providers_mod
from backend.app.security import encryption


@pytest.fixture(autouse=True)
def _isolated_platform_dir(tmp_path, monkeypatch):
    """隔离 JsonStore('providers') 与本地端点 env，杜绝读真实 data/platform。"""
    monkeypatch.setenv("WANWEI_PLATFORM_DIR", str(tmp_path / "platform"))
    monkeypatch.delenv("WANWEI_OPENAI_COMPATIBLE_BASE", raising=False)
    monkeypatch.delenv("WANWEI_OPENAI_COMPATIBLE_MODEL", raising=False)


@pytest.fixture(autouse=True)
def _smoke_cleanup():
    yield
    gateway_service.shutdown_smoke_executor()


def _seed_provider(pid: str, *, enabled: bool = True, api_key="sk-test-1234", **extra):
    record = {"enabled": enabled, "updated_at": "2026-01-01T00:00:00Z"}
    if api_key is not None:
        record["api_key_encrypted"] = encryption.encrypt(api_key)
    record.update(extra)
    providers_mod._store.set(pid, record)


# ---------------------------------------------------------------------------
# 1. get_active_provider 选择语义
# ---------------------------------------------------------------------------


def test_get_active_provider_returns_enabled_deepseek():
    _seed_provider("deepseek")
    active = providers_mod.get_active_provider()
    assert active is not None
    assert active["pid"] == "deepseek"
    assert active["kind"] == "cloud"
    assert active["base_url"] == "https://api.deepseek.com"
    assert active["model"] == "deepseek-chat"
    assert active["api_key"] == "sk-test-1234"


def test_selection_skips_disabled_keyless_oauth_placeholder_and_local():
    _seed_provider("github_copilot")  # OAuth-only：即使有记录也不参与选择
    _seed_provider("azure_foundry")  # 占位端点未改写 base_url
    _seed_provider("openai", enabled=False)  # 未启用
    _seed_provider("lm_studio", api_key=None)  # local 类不参与对话自动选择
    _seed_provider("deepseek")
    assert providers_mod.get_active_provider()["pid"] == "deepseek"


def test_selection_returns_none_when_nothing_usable():
    _seed_provider("openai", enabled=False)
    _seed_provider("qwen_oauth")  # OAuth-only 且无密钥
    assert providers_mod.get_active_provider() is None


def test_selection_treats_undecryptable_key_as_unconfigured():
    _seed_provider("deepseek", api_key=None)
    providers_mod._store.set(
        "deepseek",
        {"enabled": True, "api_key_encrypted": "not-a-fernet-token"},
    )
    assert providers_mod.get_active_provider() is None


# ---------------------------------------------------------------------------
# 2. 对话通路消费启用的 DeepSeek
# ---------------------------------------------------------------------------


def test_chat_complete_uses_enabled_deepseek(monkeypatch):
    from backend.app import app_runtime

    _seed_provider("deepseek", model="deepseek-reasoner")
    observed: dict = {}

    def fake_dispatch(provider, api_base, api_key, model, prompt, max_tokens):
        observed.update(
            provider=provider, base=api_base, key=api_key, model=model,
        )
        return "ok", 42, "pong"

    monkeypatch.setattr(gateway_service, "_provider_dispatch", fake_dispatch)

    out = app_runtime._chat_complete([{"role": "user", "content": "你好"}])

    assert out["status"] == "ok"
    assert out["provider"] == "deepseek"  # 如实回实际来源，不再笼统 openai_compatible
    assert out["model"] == "deepseek-reasoner"
    assert out["content"] == "pong"
    assert out["latency_ms"] == 42
    assert observed == {
        "provider": "deepseek",
        "base": "https://api.deepseek.com",
        "key": "sk-test-1234",
        "model": "deepseek-reasoner",
    }


def test_chat_complete_async_uses_enabled_deepseek(monkeypatch):
    import asyncio

    from backend.app import app_runtime

    _seed_provider("deepseek")
    monkeypatch.setattr(
        gateway_service,
        "_provider_dispatch",
        lambda *args: ("ok", 7, "async-pong"),
    )

    out = asyncio.run(
        app_runtime._chat_complete_async([{"role": "user", "content": "hi"}])
    )
    assert out["status"] == "ok"
    assert out["provider"] == "deepseek"
    assert out["content"] == "async-pong"


def test_deepseek_failure_reports_provider_error_without_mock_fallback(monkeypatch):
    from backend.app import app_runtime

    _seed_provider("deepseek")

    def failing_dispatch(*_args):
        raise OSError("connection refused")

    monkeypatch.setattr(gateway_service, "_provider_dispatch", failing_dispatch)

    out = app_runtime._chat_complete([{"role": "user", "content": "hi"}])
    assert out["provider"] == "deepseek"
    assert out["status"] == "provider_error"
    assert out["error"] == "provider_unavailable"
    assert "connection refused" not in str(out)  # 异常细节只进日志不进响应


# ---------------------------------------------------------------------------
# 3. 回退契约：无启用 provider 时行为与既有 env 通路一致
# ---------------------------------------------------------------------------


def test_chat_falls_back_to_env_local_endpoint(monkeypatch):
    from backend.app import app_runtime

    # 接入舱为空：未配置任何端点时如实 gateway_not_configured
    out = app_runtime._chat_complete([{"role": "user", "content": "hi"}])
    assert out["provider"] == "none"
    assert out["error"] == "gateway_not_configured"

    # env 本地端点仍作为第二优先级
    monkeypatch.setenv("WANWEI_OPENAI_COMPATIBLE_BASE", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("WANWEI_OPENAI_COMPATIBLE_MODEL", "local-model")
    out2 = app_runtime._chat_complete([{"role": "user", "content": "hi"}])
    assert out2["provider"] == "openai_compatible"
    assert out2["status"] == "provider_error"  # 回环不可达，如实失败不回退 mock


def test_enabled_provider_outranks_env_local_endpoint(monkeypatch):
    from backend.app import app_runtime

    monkeypatch.setenv("WANWEI_OPENAI_COMPATIBLE_BASE", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("WANWEI_OPENAI_COMPATIBLE_MODEL", "env-model")
    _seed_provider("deepseek")
    monkeypatch.setattr(
        gateway_service,
        "_provider_dispatch",
        lambda *args: ("ok", 1, "from-deepseek"),
    )
    out = app_runtime._chat_complete([{"role": "user", "content": "hi"}])
    assert out["provider"] == "deepseek"


# ---------------------------------------------------------------------------
# 4. model_gateway 目录与测试分发
# ---------------------------------------------------------------------------


def test_gateway_catalog_contains_deepseek():
    items = {p["provider"]: p for p in gateway_service.list_providers()["items"]}
    assert items["deepseek"]["api_base"] == "https://api.deepseek.com"
    assert items["deepseek"]["status"] == "configuration_required"


def test_deepseek_test_not_reported_as_not_implemented():
    prepared = gateway_service._prepare_provider_test(
        ModelGatewayTestIn(provider="deepseek", dry_run=False),
    )
    # 无 DB 配置时走目录默认值：enabled=False → not_configured（而非 not_implemented）
    assert prepared.status == "not_configured"


# ---------------------------------------------------------------------------
# 5. google_ai_studio 别名与 Gemini 端点归一化
# ---------------------------------------------------------------------------


def test_google_ai_studio_alias_routes_to_gemini_smoke(monkeypatch):
    seen: dict = {}

    def fake_gemini(api_base, api_key, model, prompt, max_tokens):
        seen["base"] = api_base
        return "ok", 3, "gemini"

    monkeypatch.setattr(gateway_service, "_gemini_smoke", fake_gemini)
    status, latency, text = gateway_service._provider_dispatch(
        "google_ai_studio", "https://x.example", "k", "m", "p", 16,
    )
    assert (status, latency, text) == ("ok", 3, "gemini")
    assert seen["base"] == "https://x.example"


def test_gemini_smoke_strips_duplicated_v1beta_suffix(monkeypatch):
    captured: dict = {}

    def fake_post(url, pinned_ip, payload, headers, timeout_s):
        captured["url"] = url
        return {"candidates": []}

    monkeypatch.setattr(
        gateway_service,
        "resolve_external_url",
        lambda url, allowlist=None: (url, "93.184.216.34"),
    )
    monkeypatch.setattr(gateway_service, "_pinned_json_post", fake_post)

    gateway_service._gemini_smoke(
        "https://generativelanguage.googleapis.com/v1beta/",
        "test-key", "gemini-2.5-pro", "ping", 16,
    )
    assert captured["url"] == (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-2.5-pro:generateContent?key=test-key"
    )


# ---------------------------------------------------------------------------
# 6. SSRF 主机白名单合并（fake-ip 代理环境放行显式信任主机）
# ---------------------------------------------------------------------------


def test_ssrf_allowlist_merges_legacy_and_extra_envs(monkeypatch):
    monkeypatch.delenv("WANWEI_OPENAI_COMPATIBLE_HOST_ALLOWLIST", raising=False)
    monkeypatch.delenv("WANWEI_SSRF_EXTRA_ALLOWED_HOSTS", raising=False)
    assert gateway_service.local_llama_allowlist() is None

    monkeypatch.setenv("WANWEI_SSRF_EXTRA_ALLOWED_HOSTS", "token.sensenova.cn, api.example.cn")
    assert gateway_service.local_llama_allowlist() == ["token.sensenova.cn", "api.example.cn"]

    # 历史名与推荐名并存时合并去重（单源实现在 security.ssrf：推荐名先、
    # 历史名后；顺序无语义，成员判定为精确主机集合）
    monkeypatch.setenv("WANWEI_OPENAI_COMPATIBLE_HOST_ALLOWLIST", "api.example.cn , ollama.local")
    assert gateway_service.local_llama_allowlist() == [
        "token.sensenova.cn", "api.example.cn", "ollama.local",
    ]


# ---------------------------------------------------------------------------
# 7. 推理模型的 reasoning_content 回退（避免「成功但空回复」）
# ---------------------------------------------------------------------------


def test_openai_compatible_smoke_falls_back_to_reasoning_content(monkeypatch):
    """deepseek-r*/v* 等推理模型可能只产出 reasoning_content；content 为空时
    如实回退推理文本，而不是返回 ok + 空字符串。"""

    def fake_post(url, pinned_ip, payload, headers, timeout_s):
        return {
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "",
                    "reasoning_content": "这是推理文本，真正的输出在这里。",
                },
                "finish_reason": "length",
            }],
        }

    monkeypatch.setattr(
        gateway_service,
        "resolve_external_url",
        lambda url, allowlist=None: (url, "93.184.216.34"),
    )
    monkeypatch.setattr(gateway_service, "_pinned_json_post", fake_post)

    status, latency, preview = gateway_service._openai_compatible_smoke(
        "https://llm.example/v1", "k", "deepseek-v4-flash", "hi", 64,
    )
    assert status == "ok"
    assert "真正的输出在这里" in preview


def test_put_config_accepts_host_in_global_ssrf_allowlist(monkeypatch):
    """写入校验与连接路径同源：白名单内的自定义 base_url 能落库。

    用回环字面量而非真实域名：不依赖 DNS（CI/离线机行为一致），且能精确
    验证「同一主机，白名单开→收、关→拒」的翻转语义。
    """
    from backend.app.platform_api import providers as providers_mod

    monkeypatch.setenv("WANWEI_SSRF_EXTRA_ALLOWED_HOSTS", "127.0.0.1")
    body = providers_mod.ConfigIn(
        api_key="sk-x", base_url="http://127.0.0.1:8000/v1",
        model="m", enabled=False,
    )
    cfg = providers_mod.put_config("custom_endpoint", body)
    assert cfg["base_url"] == "http://127.0.0.1:8000/v1"


def test_put_config_still_rejects_hosts_outside_allowlist(monkeypatch):
    """白名单关闭时，回环主机对 custom 类 provider 仍维持写入即拒。

    回环地址由 SSRF denylist 直接拦截，不经 DNS，任何环境行为一致。
    """
    from fastapi import HTTPException

    from backend.app.platform_api import providers as providers_mod

    monkeypatch.delenv("WANWEI_SSRF_EXTRA_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("WANWEI_OPENAI_COMPATIBLE_HOST_ALLOWLIST", raising=False)
    body = providers_mod.ConfigIn(
        api_key="sk-x", base_url="http://127.0.0.1:8000/v1",
        model="m", enabled=False,
    )
    try:
        providers_mod.put_config("custom_endpoint", body)
        raised = False
    except HTTPException as exc:
        raised = exc.status_code == 422
    assert raised, "非白名单的内网地址必须维持写入即拒"
