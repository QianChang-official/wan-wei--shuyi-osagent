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

"""AWS Bedrock SigV4 真实调用 + OAuth 设备授权状态机回归测试。

A. AWS Bedrock SigV4（model_gateway/service.py）
 1. 离线签名正确性：对齐 AWS 官方 SigV4 测试向量（get-vanilla / post-vanilla，
    取自 AWS General Reference 的 sigv4 test suite，Apache-2.0；凭据
    AKIDEXAMPLE / wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY 为官方公开示例值）；
 2. invoke 请求构造：monkeypatch ``_pinned_json_post``，断言 Authorization /
    X-Amz-Date / x-amz-content-sha256 头与 Llama(prompt)/Nova(messages)
    两类请求体，且 SECRET 绝不出现在任何上线产物中；
 3. 凭据格式错误：not_configured 语义，绝不半签，异常消息不回显凭据。

B. OAuth 设备授权（RFC 8628）状态机（platform_api/providers.py）
 - authorize/token 端点用本地 TestClient 子应用替代（monkeypatch
   ``_pinned_oauth_post`` 注入传输层），覆盖：成功授权落盘加密令牌 /
   pending→success / slow_down 间隔递增 / expired_token / 缺 client_id 诚实
   501 / 官方端点未核实的 501（qwen_oauth）/ 无 begin 时拒绝伪造 authorized。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from backend.app.model_gateway import service as gateway_service
from backend.app.model_gateway.schemas import ModelGatewayTestIn
from backend.app.platform_api import providers as providers_mod
from backend.app.security import encryption


FAKE_ACCESS_TOKEN = "gho_FAKE_TOKEN_NOT_REAL_1234567890"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """隔离 JsonStore('providers') / SQLite DB / 本地端点与 OAuth env。"""
    monkeypatch.setenv("WANWEI_PLATFORM_DIR", str(tmp_path / "platform"))
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.delenv("WANWEI_OPENAI_COMPATIBLE_BASE", raising=False)
    monkeypatch.delenv("WANWEI_OPENAI_COMPATIBLE_MODEL", raising=False)
    for pid in ("GITHUB_COPILOT", "GOOGLE_VERTEX", "QWEN_OAUTH", "AWS_BEDROCK"):
        monkeypatch.delenv(f"WANWEI_OAUTH_CLIENT_ID_{pid}", raising=False)
        monkeypatch.delenv(f"WANWEI_OAUTH_CLIENT_SECRET_{pid}", raising=False)


@pytest.fixture(autouse=True)
def _smoke_cleanup():
    yield
    gateway_service.shutdown_smoke_executor()


# ---------------------------------------------------------------------------
# A. Bedrock SigV4 —— 离线签名正确性（AWS 官方向量）
# ---------------------------------------------------------------------------

# 常量来源：AWS General Reference «SigV4 Test Suite»（公开示例凭据与固定时间戳）
_SIGV4_AK = "AKIDEXAMPLE"
_SIGV4_SK = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"
_AMZ_DATE = "20150830T123600Z"
_EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

_GET_VANILLA_AUTHZ = (
    "AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20150830/us-east-1/service/aws4_request, "
    "SignedHeaders=host;x-amz-date, "
    "Signature=5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31"
)
_POST_VANILLA_SIGNATURE = (
    "5da7c1a2acd57cee7505fc6676e4e544621c30862966e37dddb68e92efbe5d6b"
)


def test_sigv4_matches_official_get_vanilla_vector():
    authz = gateway_service._sigv4_authorization(
        method="GET",
        canonical_uri="/",
        canonical_query="",
        header_pairs=[
            ("host", "example.amazonaws.com"),
            ("x-amz-date", _AMZ_DATE),
        ],
        payload_hash=_EMPTY_SHA256,
        amz_date=_AMZ_DATE,
        access_key=_SIGV4_AK,
        secret_key=_SIGV4_SK,
        region="us-east-1",
        service="service",
    )
    assert authz == _GET_VANILLA_AUTHZ


def test_sigv4_matches_official_post_vanilla_vector():
    authz = gateway_service._sigv4_authorization(
        method="POST",
        canonical_uri="/",
        canonical_query="",
        header_pairs=[
            ("host", "example.amazonaws.com"),
            ("x-amz-date", _AMZ_DATE),
        ],
        payload_hash=_EMPTY_SHA256,
        amz_date=_AMZ_DATE,
        access_key=_SIGV4_AK,
        secret_key=_SIGV4_SK,
        region="us-east-1",
        service="service",
    )
    assert authz.startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/")
    assert authz.endswith(f"Signature={_POST_VANILLA_SIGNATURE}")


def test_bedrock_credential_parse_errors_are_explicit_and_silent():
    secret_marker = "TOPSECRETVALUE-DO-NOT-ECHO"
    with pytest.raises(gateway_service._BedrockConfigError) as exc:
        gateway_service._parse_bedrock_credentials("ONLY-ONE-SEGMENT")
    assert "ACCESS_KEY_ID|SECRET_ACCESS_KEY" in str(exc.value)

    for bad in ("", "|secret", f"AKIDTEST|{secret_marker}|extra", "AKIDTEST|"):
        with pytest.raises(gateway_service._BedrockConfigError):
            gateway_service._parse_bedrock_credentials(bad)

    # 异常消息绝不回显凭据内容
    try:
        gateway_service._parse_bedrock_credentials(f"AKIDTEST|{secret_marker}|x")
    except gateway_service._BedrockConfigError as exc:
        assert secret_marker not in str(exc)


def test_bedrock_region_extracted_from_api_base():
    assert (
        gateway_service._bedrock_region_from_base(
            "https://bedrock-runtime.us-east-1.amazonaws.com"
        )
        == "us-east-1"
    )
    assert (
        gateway_service._bedrock_region_from_base(
            "https://bedrock-runtime.cn-north-1.amazonaws.com.cn/"
        )
        == "cn-north-1"
    )
    with pytest.raises(gateway_service._BedrockConfigError):
        gateway_service._bedrock_region_from_base("https://api.deepseek.com")


def test_provider_dispatch_routes_aws_bedrock(monkeypatch):
    seen: dict = {}

    def fake_bedrock(api_base, api_key, model, prompt, max_tokens):
        seen.update(base=api_base, key=api_key, model=model)
        return "ok", 1, "pong"

    monkeypatch.setattr(gateway_service, "_bedrock_smoke", fake_bedrock)
    status, latency, text = gateway_service._provider_dispatch(
        "aws_bedrock", "https://bedrock-runtime.us-east-1.amazonaws.com",
        "AK|SK", "amazon.nova-pro-v1:0", "hi", 16,
    )
    assert (status, latency, text) == ("ok", 1, "pong")
    assert seen["base"] == "https://bedrock-runtime.us-east-1.amazonaws.com"


# ---------------------------------------------------------------------------
# A. Bedrock SigV4 —— invoke 请求构造（monkeypatch pinned 通道）
# ---------------------------------------------------------------------------


def _capture_pinned_post(monkeypatch, response: dict):
    captured: dict = {}

    def fake_post(url, pinned_ip, payload, headers, timeout_s):
        captured.update(
            url=url, pinned_ip=pinned_ip, payload=payload,
            headers=headers, timeout=timeout_s,
        )
        return response

    monkeypatch.setattr(gateway_service, "_pinned_json_post", fake_post)
    monkeypatch.setattr(
        gateway_service,
        "resolve_external_url",
        lambda url, allowlist=None: (url, "203.0.113.10"),
    )
    return captured


def _expected_sigv4_headers(captured: dict) -> dict:
    """用纯签名器按捕获到的请求重放一遍，校验线上 Authorization 一致。"""
    payload_hash = hashlib.sha256(
        json.dumps(captured["payload"]).encode("utf-8")
    ).hexdigest()
    parsed = gateway_service.urlparse(captured["url"])
    header_pairs = sorted([
        ("content-type", "application/json"),
        ("host", gateway_service._host_header(parsed)),
        ("x-amz-content-sha256", payload_hash),
        ("x-amz-date", captured["headers"]["X-Amz-Date"]),
    ])
    access_key, secret_key = captured["credentials"]
    return {
        "Authorization": gateway_service._sigv4_authorization(
            method="POST",
            canonical_uri=parsed.path or "/",
            canonical_query="",
            header_pairs=header_pairs,
            payload_hash=payload_hash,
            amz_date=captured["headers"]["X-Amz-Date"],
            access_key=access_key,
            secret_key=secret_key,
            region=captured["region"],
            service="bedrock",
        ),
        "x-amz-content-sha256": payload_hash,
    }


def test_invoke_llama_builds_prompt_body_with_sigv4_headers(monkeypatch):
    creds = ("AKIDTEST", "SECRETVALUE-MUST-NOT-LEAK")
    captured = _capture_pinned_post(
        monkeypatch,
        {"generation": "llama replies", "generation_token_count": 5},
    )
    status, latency_ms, preview = gateway_service._bedrock_smoke(
        "https://bedrock-runtime.us-east-1.amazonaws.com",
        f"{creds[0]}|{creds[1]}",
        "meta.llama3-3-70b-instruct-v1:0",
        "ping",
        16,
    )

    assert status == "ok"
    assert latency_ms >= 0
    assert preview == "llama replies"
    # URL：模型 ID 的冒号必须被编码进 /model/{id}/invoke
    assert captured["url"] == (
        "https://bedrock-runtime.us-east-1.amazonaws.com"
        "/model/meta.llama3-3-70b-instruct-v1%3A0/invoke"
    )
    assert captured["payload"] == {
        "prompt": "ping",
        "temperature": 0.2,
        "max_gen_len": 16,
    }
    headers = captured["headers"]
    assert re.fullmatch(r"\d{8}T\d{6}Z", headers["X-Amz-Date"])
    # 必需三件套：Authorization / X-Amz-Date / x-amz-content-sha256
    assert re.fullmatch(
        r"AWS4-HMAC-SHA256 Credential=AKIDTEST/\d{8}/us-east-1/bedrock/aws4_request, "
        r"SignedHeaders=content-type;host;x-amz-content-sha256;x-amz-date, "
        r"Signature=[0-9a-f]{64}",
        headers["Authorization"],
    )
    expected = _expected_sigv4_headers({**captured, "credentials": creds, "region": "us-east-1"})
    assert headers["Authorization"] == expected["Authorization"]
    assert headers["x-amz-content-sha256"] == expected["x-amz-content-sha256"]

    # 诚实红线：SECRET 绝不出现在任何上线产物（URL/头/payload）中
    wire = json.dumps(
        {
            "url": captured["url"],
            "payload": captured["payload"],
            "headers": captured["headers"],
        }
    )
    assert "SECRETVALUE-MUST-NOT-LEAK" not in wire


def test_invoke_nova_builds_messages_body_and_parses_output(monkeypatch):
    creds = ("AKIDNOVA", "NOVASECRET-DO-NOT-ECHO")
    captured = _capture_pinned_post(
        monkeypatch,
        {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [{"text": "nova says hi"}],
                },
            },
            "stopReason": "end_turn",
        },
    )
    status, _latency, preview = gateway_service._bedrock_smoke(
        "https://bedrock-runtime.us-west-2.amazonaws.com",
        f"{creds[0]}|{creds[1]}",
        "amazon.nova-pro-v1:0",
        "hello nova",
        999,  # 超上限应被夹到 256
    )

    assert status == "ok"
    assert preview == "nova says hi"
    assert captured["url"] == (
        "https://bedrock-runtime.us-west-2.amazonaws.com/model/amazon.nova-pro-v1%3A0/invoke"
    )
    assert captured["payload"]["schemaVersion"] == "messages-v1"
    assert captured["payload"]["messages"] == [
        {"role": "user", "content": [{"text": "hello nova"}]},
    ]
    assert captured["payload"]["inferenceConfig"] == {"max_new_tokens": 256}
    assert re.fullmatch(
        r"AWS4-HMAC-SHA256 Credential=AKIDNOVA/\d{8}/us-west-2/bedrock/aws4_request.*",
        captured["headers"]["Authorization"],
    )
    assert "NOVASECRET-DO-NOT-ECHO" not in json.dumps(captured["headers"])
    assert "NOVASECRET-DO-NOT-ECHO" not in captured["url"]


def test_invoke_unsupported_model_family_refuses_without_network(monkeypatch):
    def forbidden(*_args, **_kwargs):  # pragma: no cover - 被调用即失败
        raise AssertionError("unsupported 家族不得发起网络请求")

    monkeypatch.setattr(gateway_service, "_pinned_json_post", forbidden)
    monkeypatch.setattr(
        gateway_service,
        "resolve_external_url",
        lambda url, allowlist=None: (url, "203.0.113.10"),
    )
    with pytest.raises(ValueError) as exc:
        gateway_service._bedrock_smoke(
            "https://bedrock-runtime.us-east-1.amazonaws.com",
            "AKIDTEST|SECRETTEST",
            "anthropic.claude-sonnet-4-5",
            "hi",
            16,
        )
    assert "unsupported_model_format" in str(exc.value)


def test_run_provider_test_maps_bad_credentials_to_not_configured(monkeypatch):
    """格式不对 → not_configured 语义，且绝不发起半签名的网络请求。"""

    def forbidden(*_args, **_kwargs):  # pragma: no cover - 被调用即失败
        raise AssertionError("凭据格式错误时不得发出网络请求")

    monkeypatch.setattr(gateway_service, "_pinned_json_post", forbidden)
    gateway_service.upsert_config(
        provider="aws_bedrock",
        api_base="https://bedrock-runtime.us-east-1.amazonaws.com",
        api_key="only-one-segment",
        model="amazon.nova-pro-v1:0",
        enabled=True,
        notes="",
    )
    out = gateway_service.run_provider_test(
        ModelGatewayTestIn(provider="aws_bedrock", dry_run=False),
    )
    assert out.status == "not_configured"
    assert "凭据格式错误" in out.message
    assert "only-one-segment" not in out.message  # 不回显凭据内容


def test_gateway_catalog_lists_aws_bedrock_with_credential_notes():
    # list_providers 返回 model_dump 后的 dict 视图（非 pydantic 实例），用下标访问
    items = {p["provider"]: p for p in gateway_service.list_providers()["items"]}
    entry = items["aws_bedrock"]
    assert entry["api_base"] == "https://bedrock-runtime.us-east-1.amazonaws.com"
    assert entry["status"] == "configuration_required"
    assert "ACCESS_KEY_ID|SECRET_ACCESS_KEY" in entry["notes"]
    # 未配置时不再误报 not_implemented（目录默认 enabled=False → not_configured）
    prepared = gateway_service._prepare_provider_test(
        ModelGatewayTestIn(provider="aws_bedrock", dry_run=False),
    )
    assert prepared.status == "not_configured"


# ---------------------------------------------------------------------------
# B. OAuth 设备授权 —— 本地子应用替代真实供应商端点
# ---------------------------------------------------------------------------


def _make_fake_oauth_app(scenario: dict) -> FastAPI:
    app = FastAPI()

    @app.post("/login/device/code")
    async def device_code(request: Request):
        form = await request.form()
        scenario.setdefault("begin_forms", []).append(dict(form))
        if scenario.get("begin_error"):
            return JSONResponse({"error": scenario["begin_error"]}, status_code=400)
        return JSONResponse({
            "device_code": "DEV-CODE-123",
            "user_code": "ABCD-1234",
            "verification_uri": "https://github.com/login/device",
            "verification_uri_complete":
                "https://github.com/login/device?user_code=ABCD-1234",
            "expires_in": 900,
            "interval": 5,
        })

    @app.post("/login/oauth/access_token")
    async def access_token(request: Request):
        form = await request.form()
        scenario.setdefault("token_forms", []).append(dict(form))
        steps = scenario.setdefault("steps", ["success"])
        step = steps.pop(0) if steps else "success"
        bodies = {
            "authorization_pending": {"error": "authorization_pending"},
            "slow_down": {"error": "slow_down"},
            "expired_token": {"error": "expired_token"},
            "access_denied": {"error": "access_denied"},
            "success": {
                "access_token": FAKE_ACCESS_TOKEN,
                "token_type": "bearer",
                "scope": "",
            },
        }
        return JSONResponse(bodies[step])

    return app


@pytest.fixture
def oauth_harness(monkeypatch):
    """注入「假供应商」传输层：SSRF 解析与 pinned POST 全部落到本地子应用。"""

    def _install(scenario: dict) -> TestClient:
        from urllib.parse import urlsplit as _split

        fake_client = TestClient(_make_fake_oauth_app(scenario))

        def fake_pinned_post(url, pinned_ip, form):
            resp = fake_client.post(_split(url).path, data=form)
            try:
                data = resp.json()
            except ValueError:
                data = {}
            return resp.status_code, data

        monkeypatch.setattr(providers_mod, "_pinned_oauth_post", fake_pinned_post)
        monkeypatch.setattr(
            providers_mod,
            "resolve_external_url",
            lambda url, allowlist=None: (url, "203.0.113.77"),
        )
        sub_app = FastAPI()
        sub_app.include_router(providers_mod.router)
        return TestClient(sub_app)

    return _install


def _seed_oauth_client(pid: str = "github_copilot", client_id: str | None = "cid-test-1234", **record_extra):
    record: dict = {"enabled": False, "updated_at": "2026-01-01T00:00:00Z"}
    extra = record_extra.pop("extra", {})
    if client_id is not None:
        extra = {**extra, "client_id": client_id}
    if extra:
        record["extra"] = extra
    record.update(record_extra)
    providers_mod._store.set(pid, record)


def test_catalog_declares_device_auth_metadata():
    gh = providers_mod._CATALOG_BY_ID["github_copilot"]["device_auth"]
    assert gh["authorize_url"] == "https://github.com/login/device/code"
    assert gh["token_url"] == "https://github.com/login/oauth/access_token"
    gv = providers_mod._CATALOG_BY_ID["google_vertex"]["device_auth"]
    assert gv["authorize_url"] == "https://oauth2.googleapis.com/device/code"
    assert gv["token_url"] == "https://oauth2.googleapis.com/token"
    assert gv["scope"] == "https://www.googleapis.com/auth/cloud-platform"
    # DashScope 未公布官方设备授权端点 → 如实留空
    assert providers_mod._CATALOG_BY_ID["qwen_oauth"]["device_auth"] is None


def test_begin_without_client_id_is_honest_501(oauth_harness):
    scenario: dict = {}
    client = oauth_harness(scenario)
    r = client.post("/providers/auth/github_copilot/begin")
    assert r.status_code == 501, r.text
    detail = r.json()["detail"]
    assert "缺少 client_id 配置" in detail
    assert "WANWEI_OAUTH_CLIENT_ID_GITHUB_COPILOT" in detail
    # 诚实红线：一个字的假链接都不能有
    assert "verification_uri" not in r.text
    assert "user_code" not in r.text
    assert "wanwei.local" not in r.text
    # 且根本没有发起过网络请求
    assert scenario.get("begin_forms") is None


def test_begin_with_client_id_hits_real_endpoint_and_stores_pending(oauth_harness):
    scenario: dict = {}
    client = oauth_harness(scenario)
    _seed_oauth_client("github_copilot", client_id="cid-test-1234")
    before = time.time()
    r = client.post("/providers/auth/github_copilot/begin")
    assert r.status_code == 200, r.text
    body = r.json()
    # 返回的是供应商真实的 verification_uri / user_code，不是伪造死链
    assert body["verification_uri"] == "https://github.com/login/device"
    assert body["verification_uri_complete"].endswith("user_code=ABCD-1234")
    assert body["user_code"] == "ABCD-1234"
    assert body["status"] == "pending"
    assert body["expires_in"] == 900
    # 发出的请求带上了 client_id（GitHub scope 为空则不发送该参数）
    assert scenario["begin_forms"] == [{"client_id": "cid-test-1234"}]
    # pending 态进入 JsonStore('_oauth_pending')，含完整四元组
    pending = providers_mod._store.get("_oauth_pending") or {}
    state = pending.get("github_copilot")
    assert isinstance(state, dict)
    assert state["device_code"] == "DEV-CODE-123"
    assert state["user_code"] == "ABCD-1234"
    assert state["interval"] == 5
    assert state["expires_at"] > before


def test_begin_reads_client_id_from_env_when_extra_absent(oauth_harness, monkeypatch):
    scenario: dict = {}
    client = oauth_harness(scenario)
    monkeypatch.setenv("WANWEI_OAUTH_CLIENT_ID_GITHUB_COPILOT", "cid-from-env")
    _seed_oauth_client("github_copilot", client_id=None)
    r = client.post("/providers/auth/github_copilot/begin")
    assert r.status_code == 200, r.text
    assert scenario["begin_forms"] == [{"client_id": "cid-from-env"}]


def test_poll_pending_then_success_encrypts_token_and_clears_pending(oauth_harness):
    scenario: dict = {"steps": ["authorization_pending", "success"]}
    client = oauth_harness(scenario)
    _seed_oauth_client("github_copilot")
    assert client.post("/providers/auth/github_copilot/begin").status_code == 200

    first = client.post("/providers/auth/github_copilot/poll")
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "authorization_pending"

    granted = client.post("/providers/auth/github_copilot/poll")
    assert granted.status_code == 200, granted.text
    assert granted.json() == {
        "pid": "github_copilot",
        "status": "authorized",
        "configured": True,
    }

    # token 请求符合 RFC 8628 设备码授予形态
    assert len(scenario["token_forms"]) == 2
    grant_form = scenario["token_forms"][1]
    assert grant_form["grant_type"] == "urn:ietf:params:oauth:grant-type:device_code"
    assert grant_form["device_code"] == "DEV-CODE-123"
    assert grant_form["client_id"] == "cid-test-1234"

    # 令牌 Fernet 加密落盘，可解密回原值；pending 已清理
    record = providers_mod._store.get("github_copilot")
    assert encryption.decrypt(record["api_key_encrypted"]) == FAKE_ACCESS_TOKEN
    assert record["extra"]["authorized_via"] == "oauth_device"
    assert record["extra"]["authorized_at"]
    pending = providers_mod._store.get("_oauth_pending") or {}
    assert "github_copilot" not in pending

    # 诚实红线：明文令牌绝不出现在响应或落盘文件里
    assert FAKE_ACCESS_TOKEN not in granted.text
    store_path = os.environ["WANWEI_PLATFORM_DIR"] + "/platform_providers.json"
    with open(store_path, "rb") as fh:
        assert FAKE_ACCESS_TOKEN.encode("utf-8") not in fh.read()


def test_poll_slow_down_extends_interval(oauth_harness):
    scenario: dict = {"steps": ["slow_down", "slow_down"]}
    client = oauth_harness(scenario)
    _seed_oauth_client("github_copilot")
    assert client.post("/providers/auth/github_copilot/begin").status_code == 200

    first = client.post("/providers/auth/github_copilot/poll")
    assert first.json() == {
        "pid": "github_copilot", "status": "slow_down", "interval": 10,
    }
    second = client.post("/providers/auth/github_copilot/poll")
    assert second.json() == {
        "pid": "github_copilot", "status": "slow_down", "interval": 15,
    }
    # 持久化的额外间隔同步增长（后续轮询尊重 slow_down）
    state = (providers_mod._store.get("_oauth_pending") or {})["github_copilot"]
    assert state["slow_down_extra"] == 10
    assert scenario["steps"] == []  # 两次轮询确实到达了供应商端点


def test_poll_expired_token_clears_pending(oauth_harness):
    scenario: dict = {"steps": ["expired_token"]}
    client = oauth_harness(scenario)
    _seed_oauth_client("github_copilot")
    assert client.post("/providers/auth/github_copilot/begin").status_code == 200

    r = client.post("/providers/auth/github_copilot/poll")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "expired"
    pending = providers_mod._store.get("_oauth_pending") or {}
    assert "github_copilot" not in pending


def test_poll_denied_clears_pending(oauth_harness):
    scenario: dict = {"steps": ["access_denied"]}
    client = oauth_harness(scenario)
    _seed_oauth_client("github_copilot")
    assert client.post("/providers/auth/github_copilot/begin").status_code == 200

    r = client.post("/providers/auth/github_copilot/poll")
    assert r.json()["status"] == "denied"
    pending = providers_mod._store.get("_oauth_pending") or {}
    assert "github_copilot" not in pending


def test_poll_without_begin_returns_conflict_never_fabricates(oauth_harness):
    client = oauth_harness({})
    _seed_oauth_client("github_copilot")
    r = client.post("/providers/auth/github_copilot/poll")
    assert r.status_code == 409, r.text
    assert "begin" in r.json()["detail"]


def test_local_expires_at_expiry_is_cleaned_up(oauth_harness):
    """pending 本地过期：poll 直接判 expired 并清理；begin 会顺手清掉陈旧条目。"""
    scenario: dict = {}
    client = oauth_harness(scenario)
    _seed_oauth_client("github_copilot")
    providers_mod._store.set("_oauth_pending", {
        # seed 必须落在被轮询的 pid 键下，否则 poll 走 409「无 begin」分支
        "github_copilot": {
            "device_code": "OLD", "user_code": "OLD-CODE",
            "verification_uri": "https://example.com/d",
            "interval": 5, "expires_at": time.time() - 10,
        },
    })
    r = client.post("/providers/auth/github_copilot/poll")
    assert r.json()["status"] == "expired"

    assert client.post("/providers/auth/github_copilot/begin").status_code == 200
    pending = providers_mod._store.get("_oauth_pending") or {}
    assert set(pending.keys()) == {"github_copilot"}  # stale 条目已被清理


def test_qwen_oauth_endpoints_stay_501_until_official_endpoint_verified(oauth_harness):
    client = oauth_harness({})
    _seed_oauth_client("qwen_oauth", client_id="cid-qwen")
    begin = client.post("/providers/auth/qwen_oauth/begin")
    poll = client.post("/providers/auth/qwen_oauth/poll")
    assert begin.status_code == 501, begin.text
    assert poll.status_code == 501, poll.text
    assert "待核实" in begin.json()["detail"]
    # 即使配置了 client_id 也绝不伪造设备码流程
    assert "verification_uri" not in begin.text


def test_non_oauth_provider_still_rejected_400(oauth_harness):
    client = oauth_harness({})
    r = client.post("/providers/auth/deepseek/begin")
    assert r.status_code == 400
    r = client.post("/providers/auth/deepseek/poll")
    assert r.status_code == 400


def test_google_scope_param_sent_for_google_vertex(oauth_harness, monkeypatch):
    scenario: dict = {}
    client = oauth_harness(scenario)
    meta = providers_mod._CATALOG_BY_ID["google_vertex"]
    # 把 authorize_url 换成本地子应用的路径（传输层已被替换，路径即端点）
    monkeypatch.setitem(meta["device_auth"], "authorize_url", "/login/device/code")
    _seed_oauth_client("google_vertex", client_id="cid-gcp")
    r = client.post("/providers/auth/google_vertex/begin")
    assert r.status_code == 200, r.text
    assert scenario["begin_forms"][0]["scope"] == (
        "https://www.googleapis.com/auth/cloud-platform"
    )


# ---------------------------------------------------------------------------
# B/C. 对话选择边界：OAuth-only 不参与；aws_bedrock 凭据就绪后参与
# ---------------------------------------------------------------------------


def test_get_active_provider_skips_oauth_only_even_after_authorization():
    _seed_oauth_client(
        "github_copilot",
        client_id=None,
        api_key_encrypted=encryption.encrypt(FAKE_ACCESS_TOKEN),
        enabled=True,
    )
    # 维持现状：OAuth-only 的令牌即使已存成 api_key_encrypted，也不参与对话自动选择
    assert providers_mod.get_active_provider() is None


def test_get_active_provider_selects_enabled_bedrock_with_pipe_credentials():
    providers_mod._store.set("aws_bedrock", {
        "enabled": True,
        "api_key_encrypted": encryption.encrypt("AKIDCHAT|SECRETCHAT"),
        "updated_at": "2026-01-01T00:00:00Z",
    })
    active = providers_mod.get_active_provider()
    assert active is not None
    assert active["pid"] == "aws_bedrock"
    assert active["base_url"] == "https://bedrock-runtime.us-east-1.amazonaws.com"
    assert active["api_key"] == "AKIDCHAT|SECRETCHAT"


def test_chat_path_routes_bedrock_through_dispatch(monkeypatch):
    from backend.app import app_runtime

    providers_mod._store.set("aws_bedrock", {
        "enabled": True,
        "api_key_encrypted": encryption.encrypt("AKIDCHAT|SECRETCHAT"),
        "updated_at": "2026-01-01T00:00:00Z",
    })
    observed: dict = {}

    def fake_dispatch(provider, api_base, api_key, model, prompt, max_tokens):
        observed.update(provider=provider, key=api_key)
        return "ok", 9, "bedrock-reply"

    # conftest 双路径使 ``app.model_gateway.service`` 与 ``backend.app...`` 是
    # 不同模块对象；对 sys.modules 中所有同名拷贝统一打补丁
    # （写法同 test_agents_gateway_chain.py）。
    patched = 0
    for name, mod in list(sys.modules.items()):
        if name.endswith("model_gateway.service") and mod is not None:
            monkeypatch.setattr(mod, "_provider_dispatch", fake_dispatch)
            patched += 1
    assert patched >= 1
    out = app_runtime._chat_complete([{"role": "user", "content": "你好"}])
    assert out["status"] == "ok"
    assert out["provider"] == "aws_bedrock"
    assert out["content"] == "bedrock-reply"
    assert observed["key"] == "AKIDCHAT|SECRETCHAT"
