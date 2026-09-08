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

"""
SSRF regression tests for model gateway and external URL validation.
No live network calls; local loopback / cloud metadata URLs are rejected at validation.

Security hotspot review (v0.9.6.1): all IP literals in this file are intentional
SSRF test vectors; hardcoded by design (NOSONAR). They exercise the denylist in
backend/app/security/ssrf.py and must NOT be made configurable or weakened.
"""
import ipaddress

import pytest
from ..security import ssrf
from ..security.ssrf import SSRFError, resolve_external_url, validate_external_url
from ..model_gateway.schemas import ModelGatewayTestIn
from ..model_gateway import service as gateway_service
from ..model_gateway.service import run_provider_test


def test_blocks_loopback_ipv4():
    with pytest.raises(SSRFError):
        validate_external_url("http://127.0.0.1:8084/v1")  # NOSONAR (intentional SSRF test vector)


def test_blocks_ipv6_embedded_ipv4_transition_formats():
    """IPv6 过渡格式内嵌 IPv4（NAT64/6to4/compatible）必须按内嵌 IPv4 比对黑名单。

    这些地址校验时看似公网 IPv6，连接时被解包为内嵌 IPv4，可绕过全部
    IPv4 黑名单直连回环/内网。
    """
    vectors = [
        "http://[::ffff:127.0.0.1]/v1",      # IPv4-mapped（既有行为，防回归）
        "http://[64:ff9b::127.0.0.1]/v1",    # NAT64 (RFC 6052)
        "http://[::7f00:1]/v1",              # IPv4-compatible
        "http://[2002:7f00:1::]/v1",         # 6to4 → 127.0.0.1
        "http://[64:ff9b::a9fe:1]/v1",       # NAT64 → 169.254.0.1 (链路本地)
        "http://[2002:ac10:fe01::]/v1",      # 6to4 → 172.16.254.1 (私网)
        "http://[64:ff9b:1::7f00:1]/v1",     # 本地-use NAT64 (RFC 8215) → 127.0.0.1
        "http://[::ffff:0:7f00:1]/v1",       # IPv4-translated (RFC 2765/6145)
    ]  # NOSONAR (intentional SSRF test vectors)
    for url in vectors:
        with pytest.raises(SSRFError):
            validate_external_url(url)


def test_normalise_ip_extracts_embedded_ipv4():
    from ..security.ssrf import _normalise_ip

    assert _normalise_ip(ipaddress.ip_address("::ffff:127.0.0.1")) == ipaddress.ip_address("127.0.0.1")
    assert _normalise_ip(ipaddress.ip_address("64:ff9b::7f00:1")) == ipaddress.ip_address("127.0.0.1")
    assert _normalise_ip(ipaddress.ip_address("2002:7f00:1::")) == ipaddress.ip_address("127.0.0.1")
    assert _normalise_ip(ipaddress.ip_address("::7f00:1")) == ipaddress.ip_address("127.0.0.1")
    # 未内嵌 IPv4 的普通 IPv6 不受影响；未指定地址 :: 不解包
    v6 = ipaddress.ip_address("2606:4700:4700::1111")
    assert _normalise_ip(v6) == v6
    assert _normalise_ip(ipaddress.ip_address("::")) == ipaddress.ip_address("::")


def test_blocks_localhost():
    with pytest.raises(SSRFError):
        validate_external_url("http://localhost:8084/v1")


def test_blocks_cloud_metadata():
    with pytest.raises(SSRFError):
        validate_external_url("http://169.254.169.254/latest/meta-data/")  # NOSONAR (intentional SSRF test vector)


def test_blocks_private_ipv4():
    for url in ["http://10.0.0.1/x", "http://192.168.1.1/x", "http://172.16.0.1/x"]:  # NOSONAR (intentional SSRF test vectors)
        with pytest.raises(SSRFError):
            validate_external_url(url)




def test_blocks_rfc2544_benchmark_ipv4():
    with pytest.raises(SSRFError):
        validate_external_url("http://198.18.0.1/v1")  # NOSONAR (intentional SSRF test vector)


def test_resolve_external_url_pins_validated_ip(monkeypatch):
    calls = []

    def fake_getaddrinfo(host, port):
        calls.append((host, port))
        return [(None, None, None, None, ("203.0.113.10", 0))]

    monkeypatch.setattr(ssrf.socket, "getaddrinfo", fake_getaddrinfo)
    url, pinned_ip = resolve_external_url("https://api.example.test/v1")
    assert url == "https://api.example.test/v1"
    assert pinned_ip == "203.0.113.10"
    assert calls == [("api.example.test", None)]


def test_openai_compatible_smoke_uses_pinned_ip(monkeypatch):
    captured = {}

    def fake_resolve(url, *, allowlist=None):
        return url, "203.0.113.10"

    def fake_post(url, pinned_ip, payload, headers, timeout_s):
        captured.update({"url": url, "pinned_ip": pinned_ip, "payload": payload, "timeout_s": timeout_s})
        return {"choices": [{"message": {"content": "pong"}}]}

    monkeypatch.setattr(gateway_service, "resolve_external_url", fake_resolve)
    monkeypatch.setattr(gateway_service, "_pinned_json_post", fake_post)
    status, _latency_ms, text = gateway_service._openai_compatible_smoke(
        "https://rebind.example.test/v1", "token", "model", "ping", 16,
    )
    assert status == "ok"
    assert text == "pong"
    assert captured["url"] == "https://rebind.example.test/v1/chat/completions"
    assert captured["pinned_ip"] == "203.0.113.10"


def _enable_fake_provider(monkeypatch):
    """让 run_provider_test 走到真实 smoke 调用：启用 db_config 形态的 provider。"""
    fake_config = {
        "provider": "openai_compatible",
        "api_base": "https://llm.example.test/v1",
        "api_key": "k",
        "api_key_encrypted": False,
        "model": "m1",
        "enabled": True,
        "notes": "",
    }
    monkeypatch.setattr(gateway_service, "_get_config", lambda _name: fake_config)
    monkeypatch.setattr(
        gateway_service, "resolve_external_url", lambda url, *, allowlist=None: (url, "203.0.113.9")
    )


def test_run_provider_test_handles_raw_socket_errors(monkeypatch):
    """原生网络异常（OSError 系：连接拒绝/超时/TLS）必须兜底为 status=error，
    不得冒泡成未处理异常（_pinned_json_post 走 http.client 后不再是 httpx 异常）。"""
    _enable_fake_provider(monkeypatch)

    def refused(*_args, **_kwargs):
        raise ConnectionRefusedError("connection refused")

    monkeypatch.setattr(gateway_service, "_pinned_json_post", refused)
    out = run_provider_test(ModelGatewayTestIn(provider="openai_compatible", dry_run=False))
    assert out.status == "error"
    assert "refused" in out.message


def test_run_provider_test_handles_http_client_errors(monkeypatch):
    """http.client.HTTPException 系（坏状态行/对端提前断连）同样兜底为 error。"""
    import http.client as _http_client

    _enable_fake_provider(monkeypatch)

    def bad_status(*_args, **_kwargs):
        raise _http_client.BadStatusLine("garbage response")

    monkeypatch.setattr(gateway_service, "_pinned_json_post", bad_status)
    out = run_provider_test(ModelGatewayTestIn(provider="openai_compatible", dry_run=False))
    assert out.status == "error"


def test_run_provider_test_handles_tls_errors(monkeypatch):
    """TLS 证书校验失败（ssl.SSLError 属 OSError）兜底为 error 而非 500。"""
    import ssl as _ssl

    _enable_fake_provider(monkeypatch)

    def cert_fail(*_args, **_kwargs):
        raise _ssl.SSLCertVerificationError("certificate verify failed")

    monkeypatch.setattr(gateway_service, "_pinned_json_post", cert_fail)
    out = run_provider_test(ModelGatewayTestIn(provider="openai_compatible", dry_run=False))
    assert out.status == "error"


def test_blocks_ipv6_loopback():
    with pytest.raises(SSRFError):
        validate_external_url("http://[::1]/v1")


def test_allows_public_https(monkeypatch):
    # The validation contract is independent of the test host's DNS policy.
    # Live resolution can be sinkholed to a blocked address in offline VMs.
    monkeypatch.setattr(ssrf, "_resolve_ips", lambda _host: ["203.0.113.20"])
    assert validate_external_url("https://api.anthropic.com/v1").startswith("https://")


def test_model_gateway_dry_run_does_not_require_network():
    out = run_provider_test(ModelGatewayTestIn(provider="openai_compatible", dry_run=True))
    assert out.status == "ok"


def test_model_gateway_real_smoke_rejects_unknown_provider():
    """未知 provider 的真实 smoke 必须被拒，且不得发起网络调用。

    issue #45 (4.1): 原载体 ``local_mock`` 是 mock provider，已随
    ``local://memoryops/mock-model`` 一并删除，故它现在如实返回
    ``not_found``。本测试的意图——"不在册的 provider 不得走真实链路"——
    不变，改用一个确定不存在的 provider 名承载。
    """
    out = run_provider_test(
        ModelGatewayTestIn(provider="definitely_not_a_provider", dry_run=False)
    )
    # 关键是被拒绝且不含成功语义，而非具体拒绝码。
    assert out.status in ("not_found", "blocked_in_alpha")
    assert out.status != "ok"
