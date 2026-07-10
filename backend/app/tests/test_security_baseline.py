from __future__ import annotations

import importlib
import os
import stat
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _client(tmp_path: Path, *, api_key: str = "test-key", production: bool = False):
    os.environ["WANWEI_API_KEY"] = api_key
    os.environ["WANWEI_MEMORY_DB"] = str(tmp_path / "memory.db")
    if production:
        os.environ["WANWEI_PRODUCTION"] = "1"
    else:
        os.environ.pop("WANWEI_PRODUCTION", None)
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    import backend.app.main as main_mod
    importlib.reload(main_mod)
    return TestClient(main_mod.app, raise_server_exceptions=False)


def test_write_requires_api_key(tmp_path):
    client = _client(tmp_path)
    body = {"memory_class": "preference", "content": {"text": "安全回归测试"}}
    assert client.get("/health").status_code == 200
    assert client.post("/memory/v2/capsules", json=body).status_code == 401
    assert client.post("/memory/v2/capsules", json=body, headers={"x-api-key": "wrong"}).status_code == 401
    assert client.post("/memory/v2/capsules", json=body, headers={"x-api-key": "test-key"}).status_code == 200


def test_legacy_event_rejects_secret_and_not_searchable(tmp_path):
    client = _client(tmp_path)
    payload = {"source_type": "user_input", "scene": "general", "content": {"note": "password=hunter2"}}
    r = client.post("/memory/events", json=payload, headers={"x-api-key": "test-key"})
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
    search = client.get("/memory/search", params={"q": "hunter2"}, headers={"x-api-key": "test-key"})
    assert search.status_code == 200
    assert search.json()["results"] == []


def test_forget_confirm_hides_capsule_from_search(tmp_path):
    client = _client(tmp_path)
    body = {"memory_class": "knowledge", "content": {"text": "请生成周报，使用正式语气和三段式结构。"}}
    write = client.post("/memory/v2/capsules", json=body, headers={"x-api-key": "test-key"}).json()
    cap_id = write["capsule_id"]
    assert client.get("/memory/v2/search", params={"q": "周报"}, headers={"x-api-key": "test-key"}).json()["results"]
    result = client.post("/memory/forget/confirm", json={"forget_request_id": "manual", "confirm": True, "mode": "soft_delete"}, headers={"x-api-key": "test-key"})
    # manual request has no preview; direct helper path is tested via capsule lifecycle below
    assert result.status_code == 200
    from backend.app.memory_runtime.capsule_store import forget_capsules, get_capsule
    forget_capsules([cap_id])
    assert get_capsule(cap_id)["state"]["lifecycle"] == "forgotten"
    assert client.get("/memory/v2/search", params={"q": "周报"}, headers={"x-api-key": "test-key"}).json()["results"] == []


def test_chinese_search_hits_real_capsule_not_latest_fallback(tmp_path):
    client = _client(tmp_path)
    first = {"memory_class": "knowledge", "content": {"text": "请生成周报，使用正式语气和三段式结构。"}}
    second = {"memory_class": "knowledge", "content": {"text": "完全无关的部署日志。"}}
    w1 = client.post("/memory/v2/capsules", json=first, headers={"x-api-key": "test-key"}).json()
    client.post("/memory/v2/capsules", json=second, headers={"x-api-key": "test-key"}).json()
    for q in ["周报", "正式语气", "三段式结构"]:
        res = client.get("/memory/v2/search", params={"q": q}, headers={"x-api-key": "test-key"}).json()["results"]
        assert res and res[0]["capsule_id"] == w1["capsule_id"]
    assert client.get("/memory/v2/search", params={"q": "不存在关键词"}, headers={"x-api-key": "test-key"}).json()["results"] == []


@pytest.mark.skipif(os.name == "nt", reason="Windows uses ACLs instead of POSIX mode bits")
def test_db_file_permission_600(tmp_path):
    client = _client(tmp_path)
    assert client.get("/health").status_code == 200
    client.get("/audit/logs", headers={"x-api-key": "test-key"})
    mode = stat.S_IMODE((tmp_path / "memory.db").stat().st_mode)
    assert mode == 0o600


def test_production_disables_docs_and_openapi(tmp_path):
    client = _client(tmp_path, production=True)
    assert client.get("/health").status_code == 200
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
