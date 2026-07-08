"""
SSRF regression tests for model gateway and external URL validation.
No live network calls; local loopback / cloud metadata URLs are rejected at validation.

Security hotspot review (v0.9.6.1): all IP literals in this file are intentional
SSRF test vectors; hardcoded by design (NOSONAR). They exercise the denylist in
backend/app/security/ssrf.py and must NOT be made configurable or weakened.
"""
import pytest
from ..security.ssrf import SSRFError, validate_external_url
from ..model_gateway.schemas import ModelGatewayTestIn
from ..model_gateway.service import run_provider_test


def test_blocks_loopback_ipv4():
    with pytest.raises(SSRFError):
        validate_external_url("http://127.0.0.1:8084/v1")  # NOSONAR (intentional SSRF test vector)


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


def test_blocks_ipv6_loopback():
    with pytest.raises(SSRFError):
        validate_external_url("http://[::1]/v1")


def test_allows_public_https():
    assert validate_external_url("https://api.anthropic.com/v1").startswith("https://")


def test_model_gateway_dry_run_does_not_require_network():
    out = run_provider_test(ModelGatewayTestIn(provider="openai_compatible", dry_run=True))
    assert out.status == "ok"


def test_model_gateway_real_smoke_rejects_blocked_provider():
    # local_mock is not allowed real smoke; should not make network call
    out = run_provider_test(ModelGatewayTestIn(provider="local_mock", dry_run=False))
    assert out.status == "blocked_in_alpha"
