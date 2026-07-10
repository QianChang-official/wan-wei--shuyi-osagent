"""Native Kylin SDK protocol and fallback lifecycle tests."""

from pathlib import Path
import subprocess

import pytest

from backend.app.kylin_sdk import native
from backend.app.memory_runtime import capsule_store as cs
from backend.app.memory_runtime import retrieval as rt
from backend.app.memory_runtime import vector_index as vi


class _FakeNativeAdapter:
    collection = "wanwei_memory_capsules"

    def __init__(self, *, available=True):
        self.available = available
        self.upserts: list[tuple[int, str, str]] = []
        self.deleted: list[int] = []
        self.search_hits: list[dict] = []

    def availability(self):
        return {"available": self.available, "reason": None if self.available else "bridge_not_installed"}

    def upsert(self, *, vector_id, capsule_id, text):
        self.upserts.append((vector_id, capsule_id, text))
        return {"ok": True, "vector_id": vector_id, "dimension": 768, "model": "kylin-test-model"}

    def search(self, *, text, top_k):
        return {"ok": True, "hits": self.search_hits[:top_k], "dimension": 768, "model": "kylin-test-model"}

    def delete(self, *, vector_id):
        self.deleted.append(vector_id)
        return {"ok": True, "vector_id": vector_id, "deleted": True}


def _write(text):
    return cs.write_capsule(memory_class="knowledge", content={"text": text})


def test_bridge_uses_stdin_json_and_parses_its_protocol_envelope(monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["input"] = kwargs["input"]
        return subprocess.CompletedProcess(args, 0, f"sdk-log\n{native.RESPONSE_PREFIX}{{\"ok\":true,\"hits\":[]}}\n", "")

    monkeypatch.setattr(native.subprocess, "run", fake_run)
    sdk = native.KylinNativeSdk(
        native.NativeSdkConfig(
            bridge_path=Path("/opt/kylin/bridge"),
            collection="wanwei_memory_capsules",
            app_id="wanwei-test",
            embedding_model=None,
            vector_db_path=Path("/var/lib/wanwei/vector.db"),
            timeout_seconds=3,
            mode="auto",
        )
    )

    result = sdk.search(text="不出现在命令行中", top_k=3)

    assert result["hits"] == []
    assert captured["args"] == [str(Path("/opt/kylin/bridge"))]
    assert "不出现在命令行中" in captured["input"]
    assert "不出现在命令行中" not in " ".join(captured["args"])


def test_bridge_rejects_unsuccessful_native_response(monkeypatch):
    monkeypatch.setattr(
        native.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(
            args, 0, f'{native.RESPONSE_PREFIX}{{"ok":false,"error":"hidden"}}\n', ""
        ),
    )
    sdk = native.KylinNativeSdk(
        native.NativeSdkConfig(Path("/opt/kylin/bridge"), "collection", "app", None, Path("/var/lib/wanwei/vector.db"), 3, "auto")
    )

    with pytest.raises(native.KylinNativeSdkError):
        sdk.search(text="query", top_k=3)


def test_status_exposes_model_only_after_a_successful_probe(monkeypatch):
    monkeypatch.setattr(
        native.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(
            args,
            0,
            f'{native.RESPONSE_PREFIX}{{"ok":true,"capabilities":{{"embedding":true,"vector_database":true}},"model":"kylin-test-model","dimension":768}}\n',
            "",
        ),
    )
    sdk = native.KylinNativeSdk(
        native.NativeSdkConfig(Path("/opt/kylin/bridge"), "collection", "app", None, Path("/var/lib/wanwei/vector.db"), 3, "auto")
    )

    assert sdk.status() == {
        "backend": "kylin_native",
        "available": True,
        "reason": None,
        "bridge_path": str(Path("/opt/kylin/bridge")),
        "capabilities": {"embedding": True, "vector_database": True},
        "model": "kylin-test-model",
        "dimension": 768,
    }


def test_bridge_rejects_ambiguous_protocol_output(monkeypatch):
    payload = f'{native.RESPONSE_PREFIX}{{"ok":true,"hits":[]}}\n'
    monkeypatch.setattr(
        native.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0, payload + payload, ""),
    )
    sdk = native.KylinNativeSdk(
        native.NativeSdkConfig(Path("/opt/kylin/bridge"), "collection", "app", None, Path("/var/lib/wanwei/vector.db"), 3, "auto")
    )

    with pytest.raises(native.KylinNativeSdkError):
        sdk.search(text="query", top_k=3)


def test_production_requires_an_explicit_bridge_path(monkeypatch):
    monkeypatch.setenv("WANWEI_PRODUCTION", "1")
    monkeypatch.delenv("WANWEI_KYLIN_SDK_BRIDGE", raising=False)
    monkeypatch.setattr(native.shutil, "which", lambda _name: "/unexpected/bridge")

    assert native._resolve_bridge_path() is None
    sdk = native.KylinNativeSdk(
        native.NativeSdkConfig(None, "collection", "app", None, Path("/var/lib/wanwei/vector.db"), 3, "auto")
    )
    assert sdk.availability() == {"available": False, "reason": "bridge_path_required_in_production"}


def test_write_prefers_native_vector_index_when_bridge_is_available(isolated_db, monkeypatch):
    adapter = _FakeNativeAdapter()
    monkeypatch.setattr(vi, "get_native_sdk", lambda: adapter)

    written = _write("麒麟原生向量索引")
    stored = cs.get_capsule(written["capsule_id"])

    assert written["native_index"]["backend"] == "kylin_native"
    assert adapter.upserts and adapter.upserts[0][1] == written["capsule_id"]
    assert stored["index_refs"]["vector_ref"] == "kylin-native:1"
    assert stored["index_refs"]["vector_backend"]["model"] == "kylin-test-model"


def test_rejected_capsule_never_reaches_native_vector_index(isolated_db, monkeypatch):
    adapter = _FakeNativeAdapter()
    monkeypatch.setattr(vi, "get_native_sdk", lambda: adapter)

    written = _write("password: this-must-not-enter-the-vector-index")

    assert written["governance"]["policy_result"] == "reject"
    assert written["native_index"]["reason"] == "policy_not_indexable"
    assert adapter.upserts == []


def test_search_prefers_native_hits_and_keeps_governance_filter(isolated_db, monkeypatch):
    adapter = _FakeNativeAdapter()
    monkeypatch.setattr(vi, "get_native_sdk", lambda: adapter)
    written = _write("可由原生向量检索的 Capsule")
    vector_id = written["native_index"]["vector_id"]
    adapter.search_hits = [{"vector_id": vector_id, "score": 0.9}]

    results, status = rt.search_capsules_with_status("不依赖关键词的查询", top_k=3)

    assert status["backend"] == "kylin_native"
    assert [item["capsule_id"] for item in results] == [written["capsule_id"]]
    assert results[0]["retrieval_backend"] == "kylin_native"
    assert results[0]["vector_score"] == 0.9


def test_fts_is_the_fallback_when_native_bridge_is_missing(isolated_db, monkeypatch):
    monkeypatch.setattr(vi, "get_native_sdk", lambda: _FakeNativeAdapter(available=False))
    _write("FTS 后备检索仍可工作")

    results, status = rt.search_capsules_with_status("后备检索", top_k=3)

    assert status == {"backend": "fts_fallback", "fallback_reason": "bridge_not_installed"}
    assert results
    assert results[0]["retrieval_backend"] == "fts_fallback"


def test_legacy_capsules_use_fts_until_reindexed(isolated_db, monkeypatch):
    adapter = _FakeNativeAdapter(available=False)
    monkeypatch.setattr(vi, "get_native_sdk", lambda: adapter)
    written = _write("旧数据在迁移前仍然可以被 FTS 检索")
    adapter.available = True

    results, status = rt.search_capsules_with_status("迁移前", top_k=3)

    assert written["native_index"]["reason"] == "bridge_not_installed"
    assert status["backend"] == "fts_fallback"
    assert status["fallback_reason"] == "native_index_backfill_pending"
    assert status["native_index"] == {"eligible": 1, "indexed": 0, "failed": 0, "pending": 1}
    assert [item["capsule_id"] for item in results] == [written["capsule_id"]]


def test_reindex_migrates_legacy_capsules_to_native_search(isolated_db, monkeypatch):
    adapter = _FakeNativeAdapter(available=False)
    monkeypatch.setattr(vi, "get_native_sdk", lambda: adapter)
    written = _write("旧 Capsule 可以批量迁移到麒麟原生索引")
    adapter.available = True

    reindex = vi.sync_pending_vectors(limit=25)
    vector_id = adapter.upserts[0][0]
    adapter.search_hits = [{"vector_id": vector_id, "score": 0.8}]
    results, status = rt.search_capsules_with_status("批量迁移", top_k=3)

    assert reindex["backend"] == "kylin_native"
    assert reindex["attempted"] == 1
    assert reindex["indexed"] == 1
    assert reindex["index"] == {"eligible": 1, "indexed": 1, "failed": 0, "pending": 0}
    assert status["backend"] == "kylin_native"
    assert [item["capsule_id"] for item in results] == [written["capsule_id"]]


def test_reindex_reports_fallback_when_a_native_upsert_fails(isolated_db, monkeypatch):
    adapter = _FakeNativeAdapter(available=False)
    monkeypatch.setattr(vi, "get_native_sdk", lambda: adapter)
    _write("迁移失败时必须保留 FTS 后备状态")
    adapter.available = True

    def fail_upsert(**_kwargs):
        raise native.KylinNativeSdkError("native unavailable")

    adapter.upsert = fail_upsert
    reindex = vi.sync_pending_vectors(limit=25)

    assert reindex["backend"] == "fts_fallback"
    assert reindex["failed"] == 1
    assert reindex["reason"] == "native_reindex_failed"
    assert reindex["index"] == {"eligible": 1, "indexed": 0, "failed": 1, "pending": 0}
    assert vi.sync_pending_vectors(limit=25)["attempted"] == 0


def test_failed_vector_uses_narrow_fts_fallback_without_disabling_native_search(isolated_db, monkeypatch):
    adapter = _FakeNativeAdapter()
    monkeypatch.setattr(vi, "get_native_sdk", lambda: adapter)
    healthy = _write("native healthy record")
    native_upsert = adapter.upsert

    def selectively_fail(*, vector_id, capsule_id, text):
        if "fallbackneedle" in text:
            raise native.KylinNativeSdkError("vendor rejected this one Capsule")
        return native_upsert(vector_id=vector_id, capsule_id=capsule_id, text=text)

    adapter.upsert = selectively_fail
    failed = _write("unindexable fallbackneedle record")
    adapter.search_hits = [{"vector_id": healthy["native_index"]["vector_id"], "score": 0.8}]

    results, status = rt.search_capsules_with_status("fallbackneedle", top_k=3)

    assert status["backend"] == "kylin_native"
    assert status["fallback_reason"] == "native_index_failed_capsules"
    assert status["native_index"] == {"eligible": 2, "indexed": 1, "failed": 1, "pending": 0}
    by_id = {item["capsule_id"]: item for item in results}
    assert by_id[healthy["capsule_id"]]["retrieval_backend"] == "kylin_native"
    assert by_id[failed["capsule_id"]]["retrieval_backend"] == "fts_fallback"
    assert by_id[failed["capsule_id"]]["retrieval_fallback_reason"] == "native_index_failed_capsule"


def test_reindex_endpoint_queues_a_bounded_native_task(isolated_db, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.app import main as main_module

    adapter = _FakeNativeAdapter()
    monkeypatch.setenv("WANWEI_API_KEY", "reindex-test-key")
    monkeypatch.setattr(main_module, "get_native_sdk", lambda: adapter)
    monkeypatch.setattr(vi, "get_native_sdk", lambda: adapter)

    with TestClient(main_module.app) as client:
        response = client.post(
            "/kylin/sdk/reindex?limit=10",
            headers={"X-API-Key": "reindex-test-key"},
        )

    assert response.status_code == 202
    assert response.json()["scheduled"] is True
    assert response.json()["limit"] == 10


def test_forget_deletes_native_vector_after_capsule_forget(isolated_db, monkeypatch):
    adapter = _FakeNativeAdapter()
    monkeypatch.setattr(vi, "get_native_sdk", lambda: adapter)
    written = _write("应同时从原生向量库删除")
    vector_id = written["native_index"]["vector_id"]

    result = cs.forget_capsules([written["capsule_id"]])

    assert result["native_vector"]["backend"] == "kylin_native"
    assert result["native_vector"]["deleted_vector_ids"] == [vector_id]
    assert adapter.deleted == [vector_id]
