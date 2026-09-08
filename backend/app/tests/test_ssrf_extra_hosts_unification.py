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

"""SSRF 全局白名单单源化 + 推理模型空回复修复的回归测试。

背景（2026-08-24 SenseNova 接入实测）：fake-ip DNS 代理把公网域名解析到
198.18.0.0/15 被 pinned-IP 防护拦截；推理模型只产出 reasoning_content /
thinking / thought 部件时得到「成功但空回复」。修复要求全仓外呼路径统一：

1. ``security.ssrf.extra_allowed_hosts()`` 是唯一解析入口；
2. 所有真实外呼路径合并同一白名单：模型网关三原生通路、providers 写入/
   本地探测/OAuth 设备流、automation http 步骤、MCP 远程传输、系统服务
   下载/转写；
3. 三家协议的空输出回退语义：openai reasoning_content / anthropic
   thinking 块 / gemini thought 部件。
"""

from __future__ import annotations

import pytest

from backend.app.model_gateway import service as gateway_service
from backend.app.security.ssrf import extra_allowed_hosts


@pytest.fixture(autouse=True)
def _clean_allowlist_env(monkeypatch):
    monkeypatch.delenv("WANWEI_SSRF_EXTRA_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("WANWEI_OPENAI_COMPATIBLE_HOST_ALLOWLIST", raising=False)


# ---------------------------------------------------------------------------
# 1. 单源解析
# ---------------------------------------------------------------------------


def test_extra_allowed_hosts_merges_and_dedupes(monkeypatch):
    assert extra_allowed_hosts() == []
    monkeypatch.setenv("WANWEI_SSRF_EXTRA_ALLOWED_HOSTS", "a.example.cn, b.example.cn")
    monkeypatch.setenv("WANWEI_OPENAI_COMPATIBLE_HOST_ALLOWLIST", "b.example.cn, c.example.cn")
    assert extra_allowed_hosts() == ["a.example.cn", "b.example.cn", "c.example.cn"]


def test_gateway_allowlist_delegates_to_ssrf_source(monkeypatch):
    monkeypatch.setenv("WANWEI_SSRF_EXTRA_ALLOWED_HOSTS", "token.sensenova.cn")
    assert gateway_service.local_llama_allowlist() == ["token.sensenova.cn"]


# ---------------------------------------------------------------------------
# 2. 各外呼路径统一消费同一白名单（monkeypatch 捕获 allowlist 实参）
# ---------------------------------------------------------------------------


def _capture_resolve(monkeypatch, module, pinned_ip="203.0.113.9") -> dict:
    captured: dict = {}

    def fake_resolve(url, *, allowlist=None):
        captured["url"] = url
        captured["allowlist"] = allowlist
        return url, pinned_ip

    monkeypatch.setattr(module, "resolve_external_url", fake_resolve)
    return captured


def test_providers_oauth_form_post_passes_global_allowlist(monkeypatch):
    from backend.app.platform_api import providers as providers_mod

    monkeypatch.setenv("WANWEI_SSRF_EXTRA_ALLOWED_HOSTS", "github.com")
    captured = _capture_resolve(monkeypatch, providers_mod)
    monkeypatch.setattr(
        providers_mod, "_pinned_form_post",
        lambda url, ip, form, headers: (200, {"access_token": "x"}),
        raising=False,
    )
    # _oauth_form_post 内部再调 _pinned_form_post 同名包装；直接驱动并断言
    try:
        providers_mod._oauth_form_post(
            "https://github.com/login/oauth/access_token",
            {"grant_type": "x"}, purpose="unit",
        )
    except Exception:  # noqa: BLE001 —— 后续网络步骤失败不影响本断言
        pass
    assert captured["allowlist"] == ["github.com"]


def test_automation_http_step_passes_global_allowlist(monkeypatch):
    from backend.app.platform_api import automation as automation_mod

    monkeypatch.setenv("WANWEI_SSRF_EXTRA_ALLOWED_HOSTS", "httpbin.example.org")

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def request(self, *a, **kw):
            import types
            resp = types.SimpleNamespace(status_code=200, text="ok")
            return resp

    monkeypatch.setattr(automation_mod.httpx, "Client", FakeClient)
    captured = _capture_resolve(monkeypatch, automation_mod)
    automation_mod._pinned_http_request("GET", "https://httpbin.example.org/get")
    assert captured["allowlist"] == ["httpbin.example.org"]


def test_mcp_host_allowlist_merges_global_source(monkeypatch):
    from backend.app.platform_api import mcp_hub as mcp_hub_mod

    monkeypatch.setenv("WANWEI_MCP_HTTP_HOST_ALLOWLIST", "mcp.internal.example")
    monkeypatch.setenv("WANWEI_SSRF_EXTRA_ALLOWED_HOSTS", "mcp.cloud.example")
    merged = mcp_hub_mod._http_host_allowlist()
    assert merged == ["mcp.internal.example", "mcp.cloud.example"]

    # 未配置 MCP 专属 env 时，全局白名单仍然生效
    monkeypatch.delenv("WANWEI_MCP_HTTP_HOST_ALLOWLIST", raising=False)
    assert mcp_hub_mod._http_host_allowlist() == ["mcp.cloud.example"]


def test_system_svc_download_and_asr_pass_global_allowlist(monkeypatch):
    from backend.app.platform_api import _system_svc_runtime as svc

    monkeypatch.setenv("WANWEI_SSRF_EXTRA_ALLOWED_HOSTS", "mirror.example.cn")
    captured_dl = _capture_resolve(monkeypatch, svc)

    # 下载线程体：resolve 后立即抛错即可，无需走完整下载流程
    class StopEarly(Exception):
        pass

    monkeypatch.setattr(
        svc, "_download_filename",
        lambda *_a: (_ for _ in ()).throw(StopEarly()),
    )
    try:
        svc._real_download_worker("dl_test", "https://mirror.example.cn/img.img", "", __import__("threading").Event())
    except StopEarly:
        pass
    except Exception:  # noqa: BLE001 —— 其它异常同样说明已过 resolve 点
        pass
    assert captured_dl.get("allowlist") == ["mirror.example.cn"]

    captured_asr = _capture_resolve(monkeypatch, svc)

    def fake_pinned_target(url, ip):
        raise StopEarly()

    monkeypatch.setattr(svc, "_pinned_target", fake_pinned_target)
    monkeypatch.setattr(svc, "_asr_settings", lambda: {
        "base_url": "https://mirror.example.cn/v1", "api_key": "k", "model": "whisper-1",
    })
    try:
        svc._transcribe_audio(b"RIFFxxxxWAVEfmt ", "t.wav", "audio/wav")
    except StopEarly:
        pass
    except Exception:  # noqa: BLE001
        pass
    assert captured_asr.get("allowlist") == ["mirror.example.cn"]


# ---------------------------------------------------------------------------
# 3. 推理模型空回复回退（三家协议）
# ---------------------------------------------------------------------------


def _stub_network(monkeypatch, payload: dict):
    monkeypatch.setattr(
        gateway_service,
        "resolve_external_url",
        lambda url, allowlist=None: (url, "203.0.113.9"),
    )
    monkeypatch.setattr(gateway_service, "_pinned_json_post", lambda *a, **kw: payload)


def test_anthropic_smoke_falls_back_to_thinking_blocks(monkeypatch):
    _stub_network(monkeypatch, {
        "content": [
            {"type": "thinking", "thinking": "思考过程……"},
        ],
    })
    status, _ms, preview = gateway_service._anthropic_smoke(
        "https://api.anthropic.com", "k", "claude-sonnet-4-5", "hi", 64,
    )
    assert status == "ok"
    assert "思考过程" in preview


def test_gemini_smoke_prefers_output_over_thought_parts(monkeypatch):
    _stub_network(monkeypatch, {
        "candidates": [{"content": {"parts": [
            {"text": "思考片段", "thought": True},
            {"text": "正式回答"},
        ]}}],
    })
    status, _ms, preview = gateway_service._gemini_smoke(
        "https://generativelanguage.googleapis.com", "k", "gemini-2.5-pro", "hi", 64,
    )
    assert status == "ok"
    assert preview == "正式回答"


def test_gemini_smoke_falls_back_to_thought_parts_when_no_output(monkeypatch):
    _stub_network(monkeypatch, {
        "candidates": [{"content": {"parts": [
            {"text": "只有思考", "thought": True},
        ]}}],
    })
    status, _ms, preview = gateway_service._gemini_smoke(
        "https://generativelanguage.googleapis.com", "k", "gemini-2.5-pro", "hi", 64,
    )
    assert status == "ok"
    assert "只有思考" in preview
