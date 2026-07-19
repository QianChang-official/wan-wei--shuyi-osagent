"""W04 厂商接入修复回归测试。

覆盖任务包四条：
1. 02-#11/04-#12：连通性测试 SSRF 防护（复用 app.security.ssrf.validate_external_url，
   本机回环地址显式豁免）。
2. 04-#13：OAuth stub 诚实化 —— begin/poll 不再返回伪造 verification_uri，
   未接入真实流程时如实 501。
3. 04-#14：_remove_config 读改写收成单锁。
4. 04-#15：catalog 准确性 —— id 键名冻结（跨 worker 契约 C），占位符如实标注。
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient


def _client(tmp_path, *, api_key: str = "test-key"):
    """构造隔离的 TestClient（与 test_platform_api_smoke.py 同一模式）。"""
    os.environ["WANWEI_API_KEY"] = api_key
    os.environ["WANWEI_MEMORY_DB"] = str(tmp_path / "memory.db")
    os.environ["WANWEI_PLATFORM_DIR"] = str(tmp_path / "platform")
    os.environ.pop("WANWEI_PRODUCTION", None)

    import importlib
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    import backend.app.init_db
    import backend.app.main as main_mod

    importlib.reload(main_mod)
    backend.app.init_db.main()
    return TestClient(main_mod.app, raise_server_exceptions=False)


_HEADERS = {"x-api-key": "test-key"}


def _put_base_url(client, pid: str, base_url: str) -> None:
    r = client.put(
        f"/platform/providers/configs/{pid}",
        json={"base_url": base_url},
        headers=_HEADERS,
    )
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# 1. 连通性测试 SSRF 防护
# ---------------------------------------------------------------------------


def test_put_config_blocks_cloud_metadata_address(tmp_path, monkeypatch):
    """保存 base_url 时即拦截云元数据地址，写入阶段 fail-closed。"""
    client = _client(tmp_path)

    def _forbidden(*args, **kwargs):  # pragma: no cover - 被调用即失败
        raise AssertionError("httpx.get 不应被调用（SSRF 应提前拦截）")

    monkeypatch.setattr(httpx, "get", _forbidden)
    r = client.put(
        "/platform/providers/configs/lm_studio",
        json={"base_url": "http://169.254.169.254/latest/meta-data"},
        headers=_HEADERS,
    )
    assert r.status_code == 422, r.text
    assert "SSRF" in r.json()["detail"]


def test_put_config_blocks_private_network_addresses(tmp_path, monkeypatch):
    """保存 base_url 时内网保留段一律拦截。"""
    client = _client(tmp_path)
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应发起网络请求")),
    )
    for url in ["http://192.168.1.1:8080/v1", "http://10.0.0.5/v1", "http://172.16.3.4/v1"]:
        r = client.put(
            "/platform/providers/configs/ollama_cloud",
            json={"base_url": url},
            headers=_HEADERS,
        )
        assert r.status_code == 422, (url, r.text)
        assert "SSRF" in r.json()["detail"], url


def test_put_config_rejects_non_http_scheme(tmp_path, monkeypatch):
    """保存 base_url 时协议白名单仅允许 http/https。"""
    client = _client(tmp_path)
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应发起网络请求")),
    )
    r = client.put(
        "/platform/providers/configs/lm_studio",
        json={"base_url": "file:///etc/passwd"},
        headers=_HEADERS,
    )
    assert r.status_code == 422, r.text
    assert "SSRF" in r.json()["detail"]


def test_probe_ssrf_still_blocks_malicious_base_url(tmp_path, monkeypatch):
    """探测端点的 SSRF 拦截仍生效（绕过写入校验直接写入脏数据）。"""
    client = _client(tmp_path)

    def _forbidden(*args, **kwargs):  # pragma: no cover - 被调用即失败
        raise AssertionError("httpx.get 不应被调用（SSRF 应提前拦截）")

    monkeypatch.setattr(httpx, "get", _forbidden)
    from backend.app.platform_api import providers as providers_mod

    providers_mod._store.set("lm_studio", {"base_url": "http://169.254.169.254/latest/meta-data"})  # noqa: SLF001
    r = client.post("/platform/providers/test", json={"pid": "lm_studio"}, headers=_HEADERS)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False
    assert "SSRF" in body["reason"]


def test_probe_allows_explicit_loopback_endpoint(tmp_path, monkeypatch):
    """用户显式配置的本机回环端点（Ollama/LM Studio）豁免，真实探测。"""
    client = _client(tmp_path)
    calls: list[str] = []

    def _fake_get(url, **kwargs):
        calls.append(url)
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(httpx, "get", _fake_get)
    _put_base_url(client, "ollama_cloud", "http://127.0.0.1:11434")
    r = client.post("/platform/providers/test", json={"pid": "ollama_cloud"}, headers=_HEADERS)
    body = r.json()
    assert body["ok"] is True, body
    assert body["mode"] == "live"
    assert body["status_code"] == 200
    assert calls == ["http://127.0.0.1:11434"]


def test_probe_allows_localhost_alias(tmp_path, monkeypatch):
    """localhost 别名同样豁免。"""
    client = _client(tmp_path)
    monkeypatch.setattr(httpx, "get", lambda url, **k: SimpleNamespace(status_code=404))
    _put_base_url(client, "lm_studio", "http://localhost:1234/v1")
    r = client.post("/platform/providers/test", json={"pid": "lm_studio"}, headers=_HEADERS)
    body = r.json()
    assert body["ok"] is True, body
    assert body["mode"] == "live"


def test_probe_default_catalog_loopback_still_works(tmp_path, monkeypatch):
    """未配置时目录默认的 127.0.0.1 端点照常探测（回归保护）。"""
    client = _client(tmp_path)
    monkeypatch.setattr(httpx, "get", lambda url, **k: SimpleNamespace(status_code=200))
    r = client.post("/platform/providers/test", json={"pid": "lm_studio"}, headers=_HEADERS)
    body = r.json()
    assert body["ok"] is True, body
    assert body["mode"] == "live"


# ---------------------------------------------------------------------------
# 2. OAuth stub 诚实化
# ---------------------------------------------------------------------------


def test_oauth_begin_returns_501_without_fake_link(tmp_path):
    """begin 不得再返回伪造 verification_uri / user_code，如实 501。"""
    client = _client(tmp_path)
    r = client.post("/platform/providers/auth/github_copilot/begin", headers=_HEADERS)
    assert r.status_code == 501, r.text
    assert "verification_uri" not in r.text
    assert "user_code" not in r.text
    assert "wanwei.local" not in r.text
    assert "API Key" in r.json()["detail"]


def test_oauth_poll_returns_501_without_key(tmp_path):
    """未配置密钥时 poll 同样如实 501，不再返回模拟 pending。"""
    client = _client(tmp_path)
    r = client.post("/platform/providers/auth/github_copilot/poll", headers=_HEADERS)
    assert r.status_code == 501, r.text


def test_oauth_poll_reports_authorized_when_key_configured(tmp_path):
    """已通过其他途径配置密钥的，poll 如实报告 authorized（真实状态）。"""
    client = _client(tmp_path)
    r = client.put(
        "/platform/providers/configs/github_copilot",
        json={"api_key": "gho_test_key_123456"},
        headers=_HEADERS,
    )
    assert r.status_code == 200, r.text
    r = client.post("/platform/providers/auth/github_copilot/poll", headers=_HEADERS)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "authorized"


def test_oauth_endpoints_reject_non_oauth_provider(tmp_path):
    """不支持 OAuth 的 provider 仍是 400（契约不变）。"""
    client = _client(tmp_path)
    r = client.post("/platform/providers/auth/deepseek/begin", headers=_HEADERS)
    assert r.status_code == 400, r.text
    r = client.post("/platform/providers/auth/deepseek/poll", headers=_HEADERS)
    assert r.status_code == 400, r.text


# ---------------------------------------------------------------------------
# 3. _remove_config 单锁
# ---------------------------------------------------------------------------


def test_remove_config_holds_lock_for_whole_read_modify_write(tmp_path):
    """持锁期间 _remove_config 必须整体阻塞 —— 证明读改写在同一把锁内。"""
    os.environ["WANWEI_PLATFORM_DIR"] = str(tmp_path / "platform")
    from backend.app.platform_api import providers as providers_mod

    providers_mod._store.set("victim", {"enabled": True})  # noqa: SLF001
    lock = providers_mod._store._lock  # noqa: SLF001

    done: list[bool] = []
    lock.acquire()
    try:
        t = threading.Thread(
            target=lambda: done.append(providers_mod._remove_config("victim")),  # noqa: SLF001
            daemon=True,
        )
        t.start()
        time.sleep(0.3)
        # 旧实现（两次获锁 + 无锁写）此时已完成；单锁实现必须仍在等待
        assert done == [], "读-改-写未收进同一把锁"
    finally:
        lock.release()
    t.join(timeout=5)
    assert done == [True]
    assert providers_mod._store.get("victim") is None  # noqa: SLF001


def test_remove_config_concurrent_put_delete_stress(tmp_path):
    """并发 put/delete 压测：不抛异常，落盘始终是合法 JSON，终态一致。"""
    os.environ["WANWEI_PLATFORM_DIR"] = str(tmp_path / "platform")
    from backend.app.platform_api import providers as providers_mod

    errors: list[BaseException] = []

    def _worker(tag: int) -> None:
        try:
            for i in range(30):
                providers_mod._store.set(f"k{tag}", {"i": i})  # noqa: SLF001
                providers_mod._remove_config(f"k{tag}")  # noqa: SLF001
                providers_mod._remove_config("ghost")  # 删除不存在的 key
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=_worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors, errors
    data = providers_mod._store.all()  # noqa: SLF001
    assert isinstance(data, dict)


def test_delete_config_endpoint_still_works(tmp_path):
    """DELETE 端点功能回归。"""
    client = _client(tmp_path)
    _put_base_url(client, "deepseek", "https://api.deepseek.com")
    r = client.delete("/platform/providers/configs/deepseek", headers=_HEADERS)
    assert r.status_code == 200, r.text
    assert r.json()["removed"] is True
    r = client.delete("/platform/providers/configs/deepseek", headers=_HEADERS)
    assert r.json()["removed"] is False


# ---------------------------------------------------------------------------
# 4. catalog 准确性（id 键名冻结 = 跨 worker 契约 C）
# ---------------------------------------------------------------------------

# 31 家 provider id 冻结清单：任何 id 改名都会打破前端 FALLBACK_CATALOG 对齐契约
_EXPECTED_IDS = [
    'openrouter', 'mixture_of_agents', 'novitaai', 'lm_studio', 'anthropic',
    'openai', 'qwen_cloud', 'xai_grok', 'xiaomi_mimo', 'tencent_tokenhub',
    'nvidia_nim', 'github_copilot', 'huggingface', 'google_ai_studio',
    'google_vertex', 'deepseek', 'zai', 'kimi_moonshot', 'stepfun', 'minimax',
    'ollama_cloud', 'arcee_ai', 'gmi_cloud', 'kilo_code', 'opencode',
    'aws_bedrock', 'azure_foundry', 'qwen_oauth', 'alibaba_coding_plan',
    'siliconflow', 'custom_endpoint',
]


def test_catalog_ids_frozen_and_unique(tmp_path):
    client = _client(tmp_path)
    r = client.get("/platform/providers/catalog", headers=_HEADERS)
    assert r.status_code == 200, r.text
    ids = [p["id"] for p in r.json()]
    assert len(ids) == len(set(ids)), "id 重复"
    assert ids == _EXPECTED_IDS, "id 键名或顺序被改动（违反跨 worker 契约 C）"


def test_catalog_verified_base_urls(tmp_path):
    """WebSearch 核实后的官方 base_url。"""
    client = _client(tmp_path)
    catalog = {p["id"]: p for p in client.get("/platform/providers/catalog", headers=_HEADERS).json()}
    assert catalog["xiaomi_mimo"]["base_url"] == "https://api.xiaomimimo.com/v1"
    assert catalog["kilo_code"]["base_url"] == "https://api.kilo.ai/api/gateway"
    assert catalog["arcee_ai"]["base_url"] == "https://api.arcee.ai/api/v1"
    assert catalog["alibaba_coding_plan"]["base_url"] == "https://coding.dashscope.aliyuncs.com/v1"
    assert catalog["gmi_cloud"]["base_url"] == "https://api.gmi-serving.com/v1"
    assert catalog["opencode"]["base_url"] == "https://opencode.ai/zen/v1"


def test_catalog_placeholders_marked(tmp_path):
    """含占位符的条目必须如实标注 placeholder: true。"""
    client = _client(tmp_path)
    catalog = client.get("/platform/providers/catalog", headers=_HEADERS).json()
    for p in catalog:
        if "YOUR_" in (p.get("base_url") or ""):
            assert p.get("placeholder") is True, f"{p['id']} 含占位符却未标注"
    azure = next(p for p in catalog if p["id"] == "azure_foundry")
    assert azure["placeholder"] is True
    assert "YOUR_RESOURCE" in azure["base_url"]
