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

"""Public builds test the SDK boundary without access to private dependencies."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
from types import ModuleType

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.app.memory_runtime import sdk_adapter as adapter


@pytest.fixture
def configured_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(tmp_path / "legacy.db"))
    monkeypatch.setenv("WANWEI_PLATFORM_DIR", str(tmp_path / "platform"))
    monkeypatch.setenv("WANWEI_MEMORY_SDK_DB", str(tmp_path / "sdk.db"))
    monkeypatch.setenv("WANWEI_MEMORY_SDK_ENABLED", "1")
    return tmp_path


@pytest.fixture
def fake_sdk(monkeypatch):
    module = ModuleType("wanwei_affect_memory")
    module.API_VERSION = "1"
    module.SCHEMA_VERSION = 1
    module.__version__ = "0.1.0-test"
    module.created = []
    module.closed = []
    module.rows = {}

    class Engine:
        def __init__(self, path, *, owner_id, soul_id):
            self.scope = (owner_id, soul_id)
            module.created.append((Path(path), self.scope))

        def remember(self, content, **kwargs):
            cid = "cap_" + str(len(module.rows) + 1)
            cap = {
                "capsule_id": cid,
                "memory_class": kwargs["memory_class"],
                "content": deepcopy(content),
                "owner_id": self.scope[0],
                "provenance": {"owner_id": self.scope[0]},
                "governance": {"policy_result": "allow", "sensitivity_level": "S0"},
                "state": {"lifecycle": "active"},
            }
            module.rows[self.scope, cid] = cap
            return deepcopy(cap)

        def list(self, limit=50):
            return [deepcopy(row) for (scope, _), row in module.rows.items() if scope == self.scope][:limit]

        def get(self, cid):
            return deepcopy(module.rows.get((self.scope, cid)))

        def search_with_status(self, q, *, limit, high_risk):
            return {"hits": self.list(limit), "status": {"backend": "fts_fallback", "high_risk": high_risk}}

        def close(self):
            module.closed.append(self.scope)

    module.MemoryEngine = Engine
    monkeypatch.setitem(sys.modules, "wanwei_affect_memory", module)
    return module


def test_disabled_mode_does_not_import_private_sdk(monkeypatch):
    monkeypatch.setenv("WANWEI_MEMORY_SDK_ENABLED", "off")
    monkeypatch.setitem(sys.modules, "wanwei_affect_memory", None)
    assert adapter.load_configuration() is None
    adapter.validate_sdk_configuration()
    assert adapter.sdk_status()["enabled"] is False


@pytest.mark.parametrize("value", ["yes-please", "2", "auto"])
def test_unknown_opt_in_is_not_silent_fallback(monkeypatch, value):
    monkeypatch.setenv("WANWEI_MEMORY_SDK_ENABLED", value)
    with pytest.raises(adapter.SDKConfigurationError):
        adapter.load_configuration()


@pytest.mark.parametrize("path", ["", "relative.db"])
def test_sdk_needs_explicit_absolute_path(configured_paths, monkeypatch, path):
    monkeypatch.setenv("WANWEI_MEMORY_SDK_DB", path)
    with pytest.raises(adapter.SDKConfigurationError, match="separate absolute"):
        adapter.load_configuration()


def test_never_reuses_legacy_database(configured_paths, monkeypatch):
    monkeypatch.setenv("WANWEI_MEMORY_SDK_DB", str(configured_paths / "legacy.db"))
    with pytest.raises(adapter.SDKConfigurationError, match="legacy"):
        adapter.load_configuration()


def test_hardlink_to_legacy_database_is_rejected(configured_paths):
    legacy, other = configured_paths / "legacy.db", configured_paths / "sdk.db"
    legacy.write_bytes(b"do-not-touch")
    try:
        other.hardlink_to(legacy)
    except OSError:
        pytest.skip("filesystem cannot create a hard link")
    with pytest.raises(adapter.SDKConfigurationError, match="legacy"):
        adapter.load_configuration()
    assert legacy.read_bytes() == b"do-not-touch"


def test_enabled_missing_package_is_error(configured_paths, monkeypatch):
    monkeypatch.setitem(sys.modules, "wanwei_affect_memory", None)
    with pytest.raises(adapter.SDKConfigurationError, match="explicitly enabled"):
        adapter.validate_sdk_configuration()
    assert not (configured_paths / "sdk.db").exists()


@pytest.mark.parametrize("attribute,value", [("API_VERSION", "2"), ("SCHEMA_VERSION", 2), ("MemoryEngine", None)])
def test_incompatible_package_does_not_fallback(configured_paths, fake_sdk, attribute, value):
    setattr(fake_sdk, attribute, value)
    with pytest.raises(adapter.SDKConfigurationError, match="incompatible"):
        adapter.load_configuration()


def test_configuration_does_not_instantiate_engine(configured_paths, fake_sdk):
    configuration = adapter.load_configuration()
    assert configuration.path == configured_paths / "sdk.db"
    assert not fake_sdk.created
    assert not configuration.path.exists()


@pytest.fixture
def http(configured_paths, fake_sdk, monkeypatch, seed_identity):
    from backend.app.init_db import main as init_db
    from backend.app.security.auth import APIKeyMiddleware
    from backend.app.soul.ownership import configured_actor_id
    from backend.app.soul.persona import create_persona

    monkeypatch.setenv("WANWEI_API_KEY", "sdk-owner-a-key")
    monkeypatch.delenv("WANWEI_PRODUCTION", raising=False)
    monkeypatch.setenv("WANWEI_LOOPBACK_READ_EXEMPT", "0")
    init_db()
    owner_a = configured_actor_id()
    owner_b = seed_identity("sdk-owner-b-key")
    create_persona("sdk-soul-a", owner_id=owner_a)
    create_persona("sdk-soul-b", owner_id=owner_b)
    app = FastAPI()
    app.add_middleware(APIKeyMiddleware)
    app.include_router(adapter.router)
    with TestClient(app) as client:
        yield client, {"x-api-key": "sdk-owner-a-key"}, {"x-api-key": "sdk-owner-b-key"}, owner_a


def test_http_scope_and_response_redaction(http, fake_sdk):
    client, headers_a, headers_b, owner_a = http
    body = {"soul_id": "sdk-soul-a", "memory_class": "episodic", "content": {"text": "tea preference"}}
    created = client.post("/memory/sdk/capsules", json=body, headers=headers_a)
    assert created.status_code == 200, created.text
    capsule = created.json()
    assert "owner_id" not in capsule
    assert "owner_id" not in capsule["provenance"]
    assert fake_sdk.created[-1][1] == (owner_a, "sdk-soul-a")
    assert client.get("/memory/sdk/capsules", params={"soul_id": "sdk-soul-a"}, headers=headers_b).status_code == 404
    own_other = client.get("/memory/sdk/capsules", params={"soul_id": "sdk-soul-b"}, headers=headers_b)
    assert own_other.json() == {"items": []}
    cross = client.get("/memory/sdk/capsules/" + capsule["capsule_id"], params={"soul_id": "sdk-soul-b"}, headers=headers_b)
    assert cross.status_code == 404
    found = client.get("/memory/sdk/search", params={"q": "tea", "soul_id": "sdk-soul-a", "high_risk": True}, headers=headers_a)
    assert found.status_code == 200
    assert found.json()["results"][0]["capsule_id"] == capsule["capsule_id"]
    assert found.json()["retrieval"]["high_risk"] is True
    assert len(fake_sdk.closed) == len(fake_sdk.created)


def test_http_default_deny_and_strict_payload(http, monkeypatch):
    client, headers, _, _ = http
    assert client.get("/memory/sdk/status").status_code == 401
    body = {"memory_class": "episodic", "content": {"text": "test"}, "soul_id": "sdk-soul-a", "owner_id": "forged"}
    assert client.post("/memory/sdk/capsules", json=body, headers=headers).status_code == 422
    assert client.get("/memory/sdk/capsules", headers=headers).status_code == 422
    monkeypatch.setenv("WANWEI_MEMORY_SDK_ENABLED", "0")
    assert client.get("/memory/sdk/status", headers=headers).json()["enabled"] is False
    assert client.get("/memory/sdk/capsules", params={"soul_id": "sdk-soul-a"}, headers=headers).status_code == 404


def test_sdk_does_not_expose_one_step_http_forgetting(http):
    client, headers, _, _ = http
    assert client.post("/memory/sdk/forget", json={"capsule_ids": ["any"]}, headers=headers).status_code == 404


def test_new_router_registered_in_real_application():
    from backend.app.app_runtime import app
    paths = set(app.openapi()["paths"])
    assert {"/memory/sdk/status", "/memory/sdk/search", "/memory/v2/search"} <= paths


@pytest.mark.parametrize("backend", ["legacy", "sdk"])
def test_shared_memory_contract(isolated_db, tmp_path, backend):
    """Same public fixture; real SDK case is optional in credential-free public CI."""
    if backend == "sdk":
        sdk = pytest.importorskip("wanwei_affect_memory")
        with sdk.MemoryEngine(tmp_path / "sdk-contract.db", owner_id="owner-a", soul_id="soul-a") as engine:
            result = engine.remember({"text": "tea preference"}, memory_class="preference")
            assert result["governance"]["policy_result"] == "allow"
            assert result["state"]["lifecycle"] == "active"
            assert engine.search("tea")[0]["capsule_id"] == result["capsule_id"]
            engine.forget([result["capsule_id"]])
            assert engine.search("tea") == []
    else:
        from backend.app.memory_runtime.capsule_store import write_capsule, forget_capsules
        from backend.app.memory_runtime.retrieval import search_capsules
        result = write_capsule(content={"text": "tea preference"}, memory_class="preference", owner_id="owner-a", soul_id="soul-a")
        assert result["governance"]["policy_result"] == "allow"
        assert result["state"]["lifecycle"] == "active"
        hits = search_capsules("tea", owner_id="owner-a", soul_id="soul-a")
        assert hits[0]["capsule_id"] == result["capsule_id"]
        forget_capsules([result["capsule_id"]], owner_id="owner-a", soul_id="soul-a")
        assert search_capsules("tea", owner_id="owner-a", soul_id="soul-a") == []
