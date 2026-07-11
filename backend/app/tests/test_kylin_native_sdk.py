"""Native Kylin SDK protocol and fallback lifecycle tests."""

import json
from pathlib import Path
import sqlite3
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

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


def _reset_vector_generation_migration(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_schema_migrations(
            name TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "DELETE FROM memory_schema_migrations WHERE name='vector_generation_fencing_v1'"
    )
    conn.commit()


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


def test_collection_change_fails_closed_without_orphaning_old_vector(isolated_db, monkeypatch):
    adapter = _FakeNativeAdapter()
    monkeypatch.setattr(vi, "get_native_sdk", lambda: adapter)
    written = _write("collection 迁移必须显式治理")
    vector_id = written["native_index"]["vector_id"]
    adapter.collection = "new_collection"

    result = vi.index_capsule(
        capsule_id=written["capsule_id"],
        content={"text": "collection 迁移必须显式治理"},
        index_refs={},
    )
    row = vi.get_conn().execute(
        "SELECT vector_id,collection_name,status FROM memory_vector_refs WHERE capsule_id=?",
        (written["capsule_id"],),
    ).fetchone()

    assert result == {
        "backend": "fts_fallback",
        "indexed": False,
        "reason": "native_collection_mismatch",
    }
    assert dict(row) == {
        "vector_id": vector_id,
        "collection_name": "wanwei_memory_capsules",
        "status": "indexed",
    }
    assert len(adapter.upserts) == 1


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
    assert status["native_index"] == {"eligible": 1, "indexed": 0, "failed": 0, "pending": 1, "delete_pending": 0}
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
    assert reindex["index"] == {"eligible": 1, "indexed": 1, "failed": 0, "pending": 0, "delete_pending": 0}
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
    assert reindex["index"] == {"eligible": 1, "indexed": 0, "failed": 1, "pending": 0, "delete_pending": 0}
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
    assert status["native_index"] == {"eligible": 2, "indexed": 1, "failed": 1, "pending": 0, "delete_pending": 0}
    by_id = {item["capsule_id"]: item for item in results}
    assert by_id[healthy["capsule_id"]]["retrieval_backend"] == "kylin_native"
    assert by_id[failed["capsule_id"]]["retrieval_backend"] == "fts_fallback"
    assert by_id[failed["capsule_id"]]["retrieval_fallback_reason"] == "native_index_failed_capsule"


def test_failed_vector_fallback_does_not_enumerate_collection_wide_ids(isolated_db, monkeypatch):
    adapter = _FakeNativeAdapter()
    monkeypatch.setattr(vi, "get_native_sdk", lambda: adapter)
    native_upsert = adapter.upsert

    def selectively_fail(*, vector_id, capsule_id, text):
        if "boundedfallback" in text:
            raise native.KylinNativeSdkError("vendor rejected this one Capsule")
        return native_upsert(vector_id=vector_id, capsule_id=capsule_id, text=text)

    adapter.upsert = selectively_fail
    failed = _write("boundedfallback must remain searchable")
    monkeypatch.setattr(
        vi,
        "failed_vector_capsule_ids",
        lambda _collection: (_ for _ in ()).throw(AssertionError("unbounded failed-ID enumeration")),
    )

    results, status = rt.search_capsules_with_status("boundedfallback", top_k=3)

    assert status["backend"] == "kylin_native"
    assert [item["capsule_id"] for item in results] == [failed["capsule_id"]]


def test_reindex_endpoint_queues_a_bounded_native_task(isolated_db, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.app import main as main_module

    adapter = _FakeNativeAdapter()
    monkeypatch.delenv("WANWEI_PRODUCTION", raising=False)
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


def test_forget_keeps_vector_pending_when_vendor_reports_not_deleted(isolated_db, monkeypatch):
    adapter = _FakeNativeAdapter()
    monkeypatch.setattr(vi, "get_native_sdk", lambda: adapter)
    written = _write("厂商未确认删除时必须保持待处理")
    vector_id = written["native_index"]["vector_id"]
    adapter.delete = lambda **_kwargs: {"ok": True, "vector_id": vector_id, "deleted": False}

    result = cs.forget_capsules([written["capsule_id"]])

    assert result["native_vector"] == {
        "backend": "kylin_native",
        "deleted_vector_ids": [],
        "pending_vector_ids": [vector_id],
    }
    assert vi.native_index_coverage(adapter.collection)["delete_pending"] == 1


@pytest.mark.parametrize("initial_status", ["allocated", "index_failed"])
def test_forget_deletes_uncertain_native_vector_states(isolated_db, monkeypatch, initial_status):
    adapter = _FakeNativeAdapter(available=False)
    monkeypatch.setattr(vi, "get_native_sdk", lambda: adapter)
    written = _write(f"{initial_status} 状态也可能已写入厂商向量库")
    conn = vi.get_conn()
    timestamp = vi.utc_now_iso_compact()
    cursor = conn.execute(
        """
        INSERT INTO memory_vector_refs(
            capsule_id,provider,collection_name,status,attempt_generation,created_at,updated_at
        ) VALUES (?,?,?,?,?,?,?)
        """,
        (written["capsule_id"], vi.PROVIDER, adapter.collection, initial_status, 1, timestamp, timestamp),
    )
    conn.commit()
    vector_id = int(cursor.lastrowid)
    adapter.available = True

    result = cs.forget_capsules([written["capsule_id"]])

    assert result["native_vector"] == {
        "backend": "kylin_native",
        "deleted_vector_ids": [vector_id],
        "pending_vector_ids": [],
    }
    assert adapter.deleted == [vector_id]


def test_concurrent_forget_prevents_late_upsert_from_reactivating_vector(isolated_db, monkeypatch):
    adapter = _FakeNativeAdapter()
    monkeypatch.setattr(vi, "get_native_sdk", lambda: adapter)
    entered_upsert = threading.Event()
    release_upsert = threading.Event()
    native_upsert = adapter.upsert

    def blocked_upsert(**kwargs):
        response = native_upsert(**kwargs)
        entered_upsert.set()
        assert release_upsert.wait(timeout=5)
        return response

    adapter.upsert = blocked_upsert
    result_holder = {}

    def write_in_background():
        result_holder["write"] = _write("并发遗忘不能被晚到的向量写入复活")

    writer = threading.Thread(target=write_in_background)
    writer.start()
    assert entered_upsert.wait(timeout=5)
    conn = vi.get_conn()
    row = conn.execute(
        "SELECT capsule_id,vector_id,status FROM memory_vector_refs",
    ).fetchone()
    assert row["status"] == "indexing"

    forgotten = cs.forget_capsules([row["capsule_id"]])
    release_upsert.set()
    writer.join(timeout=5)

    assert not writer.is_alive()
    assert forgotten["deleted_capsule_ids"] == [row["capsule_id"]]
    assert result_holder["write"]["native_index"] == {
        "backend": "fts_fallback",
        "indexed": False,
        "reason": "capsule_forgotten_during_index",
    }
    assert conn.execute(
        "SELECT status FROM memory_vector_refs WHERE vector_id=?", (row["vector_id"],)
    ).fetchone()["status"] == "deleted"
    assert adapter.deleted.count(row["vector_id"]) == 2
    assert vi.native_index_coverage(adapter.collection)["eligible"] == 0


def test_stale_indexing_worker_cannot_delete_replacement_vector(isolated_db, monkeypatch):
    adapter = _FakeNativeAdapter()
    monkeypatch.setattr(vi, "get_native_sdk", lambda: adapter)
    entered_old_upsert = threading.Event()
    release_old_upsert = threading.Event()
    native_vectors: set[int] = set()
    upsert_count = 0
    upsert_lock = threading.Lock()

    def fenced_upsert(*, vector_id, capsule_id, text):
        nonlocal upsert_count
        with upsert_lock:
            upsert_count += 1
            current_count = upsert_count
        native_vectors.add(vector_id)
        if current_count == 1:
            entered_old_upsert.set()
            assert release_old_upsert.wait(timeout=5)
        return {"ok": True, "vector_id": vector_id, "dimension": 768, "model": "kylin-test-model"}

    def tracked_delete(*, vector_id):
        adapter.deleted.append(vector_id)
        native_vectors.discard(vector_id)
        return {"ok": True, "vector_id": vector_id, "deleted": True}

    adapter.upsert = fenced_upsert
    adapter.delete = tracked_delete
    writer_result = {}

    def old_writer():
        writer_result["old"] = _write("过期 worker 不能删除接管 worker 的向量")

    writer = threading.Thread(target=old_writer)
    writer.start()
    assert entered_old_upsert.wait(timeout=5)
    conn = vi.get_conn()
    old_ref = conn.execute(
        "SELECT capsule_id,vector_id,attempt_generation FROM memory_vector_refs",
    ).fetchone()
    conn.execute(
        "UPDATE memory_vector_refs SET updated_at='2000-01-01T00:00:00Z' WHERE capsule_id=?",
        (old_ref["capsule_id"],),
    ).connection.commit()

    replacement = vi._index_capsule_with_adapter(
        adapter=adapter,
        capsule_id=old_ref["capsule_id"],
        content={"text": "过期 worker 不能删除接管 worker 的向量"},
        index_refs={"fts_ref": old_ref["capsule_id"], "vector_ref": None},
    )
    new_ref = conn.execute(
        "SELECT vector_id,status,attempt_generation FROM memory_vector_refs WHERE capsule_id=?",
        (old_ref["capsule_id"],),
    ).fetchone()
    assert replacement["indexed"] is True
    assert new_ref["vector_id"] != old_ref["vector_id"]
    assert new_ref["attempt_generation"] == old_ref["attempt_generation"] + 1
    assert native_vectors == {old_ref["vector_id"], new_ref["vector_id"]}

    release_old_upsert.set()
    writer.join(timeout=5)

    assert not writer.is_alive()
    assert writer_result["old"]["native_index"]["reason"] == "native_index_lease_lost"
    assert conn.execute(
        "SELECT status FROM memory_vector_refs WHERE capsule_id=?", (old_ref["capsule_id"],)
    ).fetchone()["status"] == "indexed"
    assert native_vectors == {new_ref["vector_id"]}
    assert adapter.deleted == [old_ref["vector_id"]]
    tombstone = conn.execute(
        "SELECT status FROM memory_vector_tombstones WHERE vector_id=?",
        (old_ref["vector_id"],),
    ).fetchone()
    assert tombstone["status"] == "deleted"


def test_delete_sweeper_recovers_late_upsert_after_process_crash(isolated_db, monkeypatch):
    class SimulatedProcessCrash(BaseException):
        pass

    adapter = _FakeNativeAdapter()
    monkeypatch.setattr(vi, "get_native_sdk", lambda: adapter)
    entered_upsert = threading.Event()
    release_upsert = threading.Event()
    native_vectors: set[int] = set()
    writer_crashed = threading.Event()

    def late_upsert(*, vector_id, capsule_id, text):
        adapter.upserts.append((vector_id, capsule_id, text))
        entered_upsert.set()
        assert release_upsert.wait(timeout=5)
        native_vectors.add(vector_id)
        return {"ok": True, "vector_id": vector_id, "dimension": 768, "model": "kylin-test-model"}

    def tracked_delete(*, vector_id):
        adapter.deleted.append(vector_id)
        native_vectors.discard(vector_id)
        return {"ok": True, "vector_id": vector_id, "deleted": True}

    adapter.upsert = late_upsert
    adapter.delete = tracked_delete
    monkeypatch.setattr(
        vi,
        "_publish_indexed_if_active",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(SimulatedProcessCrash()),
    )

    def write_until_crash():
        try:
            _write("进程崩溃后永久 tombstone 必须清理晚到向量")
        except SimulatedProcessCrash:
            writer_crashed.set()

    writer = threading.Thread(target=write_until_crash)
    writer.start()
    assert entered_upsert.wait(timeout=5)
    row = vi.get_conn().execute(
        "SELECT capsule_id,vector_id,status FROM memory_vector_refs",
    ).fetchone()
    assert row["status"] == "indexing"

    forgotten = cs.forget_capsules([row["capsule_id"]])
    assert forgotten["native_vector"]["deleted_vector_ids"] == [row["vector_id"]]
    assert native_vectors == set()

    release_upsert.set()
    writer.join(timeout=5)
    assert not writer.is_alive()
    assert writer_crashed.is_set()
    assert native_vectors == {row["vector_id"]}
    assert vi.get_conn().execute(
        "SELECT status FROM memory_vector_refs WHERE vector_id=?", (row["vector_id"],)
    ).fetchone()["status"] == "deleted"

    vi.get_conn().execute(
        "UPDATE memory_vector_tombstones SET checked_at='2000-01-01T00:00:00Z' WHERE vector_id=?",
        (row["vector_id"],),
    ).connection.commit()

    swept = vi.sweep_pending_vector_deletes(limit=10, adapter=adapter)

    assert swept == {
        "attempted": 1,
        "deleted_vector_ids": [row["vector_id"]],
        "pending_vector_ids": [],
    }
    assert native_vectors == set()
    assert adapter.deleted.count(row["vector_id"]) == 2


def test_delete_sweeper_retries_a_failed_deleted_tombstone(isolated_db, monkeypatch):
    adapter = _FakeNativeAdapter(available=False)
    monkeypatch.setattr(vi, "get_native_sdk", lambda: adapter)
    written = _write("不确定索引状态的 tombstone 必须持续复核")
    conn = vi.get_conn()
    timestamp = vi.utc_now_iso_compact()
    vector_id = vi._allocate_vector_id_in_transaction(conn, timestamp)
    conn.execute(
        """
        INSERT INTO memory_vector_refs(
            vector_id,capsule_id,provider,collection_name,status,
            attempt_generation,created_at,updated_at
        ) VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            vector_id,
            written["capsule_id"],
            vi.PROVIDER,
            adapter.collection,
            "index_failed",
            1,
            timestamp,
            timestamp,
        ),
    ).connection.commit()
    adapter.available = True
    assert cs.forget_capsules([written["capsule_id"]])["native_vector"]["deleted_vector_ids"] == [vector_id]
    adapter.delete = lambda **_kwargs: {"ok": True, "vector_id": vector_id, "deleted": False}
    vi.get_conn().execute(
        "UPDATE memory_vector_tombstones SET checked_at='2000-01-01T00:00:00Z' WHERE vector_id=?",
        (vector_id,),
    ).connection.commit()

    swept = vi.sweep_pending_vector_deletes(limit=10, adapter=adapter)

    assert swept == {
        "attempted": 1,
        "deleted_vector_ids": [],
        "pending_vector_ids": [vector_id],
    }
    assert vi.get_conn().execute(
        "SELECT status FROM memory_vector_refs WHERE vector_id=?", (vector_id,)
    ).fetchone()["status"] == "delete_pending"


def test_recent_deleted_tombstone_waits_before_terminal_verification(isolated_db):
    adapter = _FakeNativeAdapter()
    conn = vi.get_conn()
    timestamp = vi.utc_now_iso_compact()
    conn.execute(
        """
        INSERT INTO memory_vector_tombstones(
            provider,collection_name,vector_id,status,checked_at,created_at,updated_at
        ) VALUES (?,?,?,'deleted',?,?,?)
        """,
        (vi.PROVIDER, adapter.collection, 7001, timestamp, timestamp, timestamp),
    )
    conn.commit()

    swept = vi.sweep_pending_vector_deletes(limit=10, adapter=adapter)

    assert swept == {"attempted": 0, "deleted_vector_ids": [], "pending_vector_ids": []}
    assert adapter.deleted == []


def test_aged_deleted_tombstone_is_verified_once_then_terminal(isolated_db):
    adapter = _FakeNativeAdapter()
    conn = vi.get_conn()
    old_timestamp = "2000-01-01T00:00:00Z"
    conn.execute(
        """
        INSERT INTO memory_vector_tombstones(
            provider,collection_name,vector_id,status,checked_at,created_at,updated_at
        ) VALUES (?,?,?,'deleted',?,?,?)
        """,
        (vi.PROVIDER, adapter.collection, 7002, old_timestamp, old_timestamp, old_timestamp),
    )
    conn.commit()

    first = vi.sweep_pending_vector_deletes(limit=10, adapter=adapter)
    second = vi.sweep_pending_vector_deletes(limit=10, adapter=adapter)

    assert first == {"attempted": 1, "deleted_vector_ids": [7002], "pending_vector_ids": []}
    assert second == {"attempted": 0, "deleted_vector_ids": [], "pending_vector_ids": []}
    assert adapter.deleted == [7002]
    assert conn.execute(
        "SELECT status FROM memory_vector_tombstones WHERE vector_id=7002"
    ).fetchone()["status"] == "verified_deleted"
    assert conn.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE event_type='kylin_sdk_vector_delete_sweep'"
    ).fetchone()[0] == 1


def test_aged_tombstone_verification_uses_compare_and_swap_claim(isolated_db, monkeypatch):
    adapter = _FakeNativeAdapter()
    conn = vi.get_conn()
    old_timestamp = "2000-01-01T00:00:00Z"
    conn.execute(
        """
        INSERT INTO memory_vector_tombstones(
            provider,collection_name,vector_id,status,checked_at,created_at,updated_at
        ) VALUES (?,?,?,'deleted',?,?,?)
        """,
        (vi.PROVIDER, adapter.collection, 7003, old_timestamp, old_timestamp, old_timestamp),
    )
    conn.commit()
    monkeypatch.setattr(
        vi,
        "_claim_deleted_tombstone_verification",
        lambda _vector_id, _collection, _checked_at: False,
    )

    swept = vi.sweep_pending_vector_deletes(limit=10, adapter=adapter)

    assert swept == {"attempted": 0, "deleted_vector_ids": [], "pending_vector_ids": []}
    assert adapter.deleted == []


def test_deleted_tombstone_claim_is_single_winner(isolated_db):
    adapter = _FakeNativeAdapter()
    conn = vi.get_conn()
    old_timestamp = "2000-01-01T00:00:00Z"
    conn.execute(
        """
        INSERT INTO memory_vector_tombstones(
            provider,collection_name,vector_id,status,checked_at,created_at,updated_at
        ) VALUES (?,?,?,'deleted',?,?,?)
        """,
        (vi.PROVIDER, adapter.collection, 7004, old_timestamp, old_timestamp, old_timestamp),
    )
    conn.commit()

    first = vi._claim_deleted_tombstone_verification(7004, adapter.collection, old_timestamp)
    second = vi._claim_deleted_tombstone_verification(7004, adapter.collection, old_timestamp)

    assert first is True
    assert second is False


def test_aged_verification_is_not_starved_by_pending_backlog(isolated_db):
    adapter = _FakeNativeAdapter()
    conn = vi.get_conn()
    now_timestamp = vi.utc_now_iso_compact()
    for vector_id in (7101, 7102):
        conn.execute(
            """
            INSERT INTO memory_vector_tombstones(
                provider,collection_name,vector_id,status,checked_at,created_at,updated_at
            ) VALUES (?,?,?,'delete_pending',NULL,?,?)
            """,
            (vi.PROVIDER, adapter.collection, vector_id, now_timestamp, now_timestamp),
        )
    conn.execute(
        """
        INSERT INTO memory_vector_tombstones(
            provider,collection_name,vector_id,status,checked_at,created_at,updated_at
        ) VALUES (?,?,?,'deleted',?,?,?)
        """,
        (vi.PROVIDER, adapter.collection, 7103, "2000-01-01T00:00:00Z", "2000-01-01T00:00:00Z", "2000-01-01T00:00:00Z"),
    )
    conn.commit()

    def delete_with_persistent_failures(*, vector_id):
        adapter.deleted.append(vector_id)
        return {"ok": True, "vector_id": vector_id, "deleted": vector_id == 7103}

    adapter.delete = delete_with_persistent_failures

    swept = vi.sweep_pending_vector_deletes(limit=2, adapter=adapter)

    assert 7103 in swept["deleted_vector_ids"]
    assert conn.execute(
        "SELECT status FROM memory_vector_tombstones WHERE vector_id=7103"
    ).fetchone()["status"] == "verified_deleted"


def test_forget_replay_retries_pending_tombstone_even_when_ref_was_deleted(isolated_db, monkeypatch):
    adapter = _FakeNativeAdapter()
    monkeypatch.setattr(vi, "get_native_sdk", lambda: adapter)
    written = _write("ref 已删除但 tombstone 待删时重放必须继续清理")
    vector_id = written["native_index"]["vector_id"]
    timestamp = vi.utc_now_iso_compact()
    vi._record_vector_tombstone(vector_id, adapter.collection)
    conn = vi.get_conn()
    conn.execute(
        "UPDATE memory_vector_refs SET status='deleted',updated_at=? WHERE vector_id=?",
        (timestamp, vector_id),
    ).connection.commit()

    result = vi.remove_vectors([written["capsule_id"]])

    assert result == {
        "backend": "kylin_native",
        "deleted_vector_ids": [vector_id],
        "pending_vector_ids": [],
    }
    assert adapter.deleted == [vector_id]
    assert conn.execute(
        "SELECT status FROM memory_vector_tombstones WHERE vector_id=?",
        (vector_id,),
    ).fetchone()["status"] == "deleted"


def test_delete_sweeper_recovers_pending_without_ticket_replay(isolated_db, monkeypatch):
    adapter = _FakeNativeAdapter()
    monkeypatch.setattr(vi, "get_native_sdk", lambda: adapter)
    written = _write("客户端不重放时后台仍要清理待删向量")
    vector_id = written["native_index"]["vector_id"]
    adapter.available = False

    result = cs.forget_capsules([written["capsule_id"]])
    assert result["native_vector"]["pending_vector_ids"] == [vector_id]
    adapter.available = True

    swept = vi.sweep_pending_vector_deletes(limit=10)

    assert swept == {
        "attempted": 1,
        "deleted_vector_ids": [vector_id],
        "pending_vector_ids": [],
    }
    assert adapter.deleted == [vector_id]
    assert vi.native_index_coverage(adapter.collection)["delete_pending"] == 0


def test_delete_sweeper_deduplicates_ref_and_tombstone(isolated_db, monkeypatch):
    adapter = _FakeNativeAdapter(available=False)
    monkeypatch.setattr(vi, "get_native_sdk", lambda: adapter)
    written = _write("引用和 tombstone 同时待删时只调用厂商一次")
    conn = vi.get_conn()
    timestamp = vi.utc_now_iso_compact()
    vector_id = vi._allocate_vector_id_in_transaction(conn, timestamp)
    conn.execute(
        """
        INSERT INTO memory_vector_refs(
            vector_id,capsule_id,provider,collection_name,status,
            attempt_generation,created_at,updated_at
        ) VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            vector_id,
            written["capsule_id"],
            vi.PROVIDER,
            adapter.collection,
            "indexing",
            1,
            timestamp,
            timestamp,
        ),
    ).connection.commit()
    adapter.available = True
    assert cs.forget_capsules([written["capsule_id"]])["native_vector"]["deleted_vector_ids"] == [vector_id]
    conn.execute(
        "UPDATE memory_vector_refs SET status='delete_pending' WHERE vector_id=?",
        (vector_id,),
    ).connection.commit()
    adapter.deleted.clear()

    swept = vi.sweep_pending_vector_deletes(limit=10, adapter=adapter)

    assert swept["attempted"] == 1
    assert swept["deleted_vector_ids"] == [vector_id]
    assert adapter.deleted == [vector_id]


def test_legacy_deleted_ref_migrates_to_retryable_tombstone(isolated_db, monkeypatch):
    from backend.app.init_db import main as init_db

    adapter = _FakeNativeAdapter()
    monkeypatch.setattr(vi, "get_native_sdk", lambda: adapter)
    written = _write("升级前 deleted ref 的 late upsert 必须可恢复")
    vector_id = written["native_index"]["vector_id"]
    conn = vi.get_conn()
    conn.execute(
        """
        UPDATE memory_vector_refs
        SET status='deleted',attempt_generation=0
        WHERE vector_id=?
        """,
        (vector_id,),
    )
    conn.execute(
        "DELETE FROM memory_vector_tombstones WHERE provider=? AND vector_id=?",
        (vi.PROVIDER, vector_id),
    )
    _reset_vector_generation_migration(conn)
    conn.commit()

    init_db()

    tombstone = conn.execute(
        """
        SELECT status FROM memory_vector_tombstones
        WHERE provider=? AND collection_name=? AND vector_id=?
        """,
        (vi.PROVIDER, adapter.collection, vector_id),
    ).fetchone()
    assert tombstone["status"] == "delete_pending"
    assert vi.sweep_pending_vector_deletes(limit=10, adapter=adapter) == {
        "attempted": 1,
        "deleted_vector_ids": [vector_id],
        "pending_vector_ids": [],
    }
    assert adapter.deleted == [vector_id]


@pytest.mark.parametrize("legacy_status", ["allocated", "indexing", "index_failed"])
def test_legacy_uncertain_ref_is_fenced_to_a_new_id(isolated_db, monkeypatch, legacy_status):
    from backend.app.init_db import main as init_db

    adapter = _FakeNativeAdapter()
    monkeypatch.setattr(vi, "get_native_sdk", lambda: adapter)
    conn = vi.get_conn()
    written = _write(f"升级前 {legacy_status} 引用必须更换原生 ID")
    old_vector_id = written["native_index"]["vector_id"]
    conn.execute(
        """
        UPDATE memory_vector_refs
        SET status=?,attempt_generation=0
        WHERE vector_id=?
        """,
        (legacy_status, old_vector_id),
    )
    conn.execute(
        "DELETE FROM memory_vector_tombstones WHERE provider=? AND vector_id=?",
        (vi.PROVIDER, old_vector_id),
    )
    _reset_vector_generation_migration(conn)
    conn.commit()

    init_db()

    ref = conn.execute(
        "SELECT vector_id,status,attempt_generation FROM memory_vector_refs WHERE capsule_id=?",
        (written["capsule_id"],),
    ).fetchone()
    assert ref["vector_id"] > old_vector_id
    assert ref["status"] == "allocated"
    assert ref["attempt_generation"] == 0
    tombstone = conn.execute(
        """
        SELECT status FROM memory_vector_tombstones
        WHERE provider=? AND vector_id=?
        """,
        (vi.PROVIDER, old_vector_id),
    ).fetchone()
    assert tombstone["status"] == "delete_pending"


def test_vector_generation_migration_serializes_legacy_schema(tmp_path):
    from backend.app.init_db import migrate_legacy_vector_refs

    db_path = tmp_path / "legacy-vector-migration.db"
    setup = sqlite3.connect(db_path)
    setup.executescript(
        """
        CREATE TABLE memory_vector_refs(
            vector_id INTEGER PRIMARY KEY AUTOINCREMENT,
            capsule_id TEXT NOT NULL UNIQUE,
            provider TEXT NOT NULL,
            collection_name TEXT NOT NULL,
            model_name TEXT,
            dimension INTEGER,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE memory_vector_id_allocations(
            vector_id INTEGER PRIMARY KEY AUTOINCREMENT,
            allocated_at TEXT NOT NULL
        );
        CREATE TABLE memory_vector_tombstones(
            provider TEXT NOT NULL,
            collection_name TEXT NOT NULL,
            vector_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            checked_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(provider, collection_name, vector_id)
        );
        CREATE TABLE memory_schema_migrations(
            name TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        );
        INSERT INTO memory_vector_refs(
            capsule_id,provider,collection_name,status,created_at,updated_at
        ) VALUES ('cap_legacy','kylin_native_sdk','wanwei_memory_capsules','allocated','2000-01-01','2000-01-01');
        """
    )
    setup.close()
    start = threading.Barrier(2)

    def run_migration():
        conn = sqlite3.connect(db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            start.wait(timeout=5)
            return migrate_legacy_vector_refs(conn)
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result(timeout=10) for future in [pool.submit(run_migration), pool.submit(run_migration)]]

    check = sqlite3.connect(db_path)
    try:
        columns = {row[1] for row in check.execute("PRAGMA table_info(memory_vector_refs)")}
        marker_count = check.execute(
            "SELECT COUNT(*) FROM memory_schema_migrations WHERE name=?",
            ("vector_generation_fencing_v1",),
        ).fetchone()[0]
    finally:
        check.close()

    assert sorted(results) == [False, True]
    assert "attempt_generation" in columns
    assert marker_count == 1


def test_vector_generation_migration_is_not_replayed_after_success(isolated_db, monkeypatch):
    from backend.app.init_db import main as init_db

    adapter = _FakeNativeAdapter()
    monkeypatch.setattr(vi, "get_native_sdk", lambda: adapter)
    written = _write("generation migration marker test")
    vector_id = written["native_index"]["vector_id"]
    conn = vi.get_conn()
    conn.execute(
        "UPDATE memory_vector_refs SET status='deleted',attempt_generation=0 WHERE vector_id=?",
        (vector_id,),
    )
    conn.execute(
        "DELETE FROM memory_vector_tombstones WHERE provider=? AND vector_id=?",
        (vi.PROVIDER, vector_id),
    )
    _reset_vector_generation_migration(conn)

    init_db()
    statements = []
    conn.set_trace_callback(statements.append)
    try:
        init_db()
    finally:
        conn.set_trace_callback(None)

    assert conn.execute(
        "SELECT 1 FROM memory_schema_migrations WHERE name='vector_generation_fencing_v1'"
    ).fetchone()
    assert not any("FROM memory_vector_refs" in statement for statement in statements)


def test_other_collection_backlog_cannot_starve_current_collection(isolated_db, monkeypatch):
    adapter = _FakeNativeAdapter()
    monkeypatch.setattr(vi, "get_native_sdk", lambda: adapter)
    conn = vi.get_conn()
    timestamp = "2000-01-01T00:00:00Z"
    for vector_id in range(100, 125):
        conn.execute(
            """
            INSERT INTO memory_vector_tombstones(
                provider,collection_name,vector_id,status,checked_at,created_at,updated_at
            ) VALUES (?,?,?,'delete_pending',NULL,?,?)
            """,
            (vi.PROVIDER, "old_collection", vector_id, timestamp, timestamp),
        )
    current_vector_id = 999
    conn.execute(
        """
        INSERT INTO memory_vector_tombstones(
            provider,collection_name,vector_id,status,checked_at,created_at,updated_at
        ) VALUES (?,?,?,'delete_pending',NULL,?,?)
        """,
        (vi.PROVIDER, adapter.collection, current_vector_id, timestamp, timestamp),
    )
    conn.commit()

    swept = vi.sweep_pending_vector_deletes(limit=25, adapter=adapter)

    assert swept == {
        "attempted": 1,
        "deleted_vector_ids": [current_vector_id],
        "pending_vector_ids": [],
    }
    assert adapter.deleted == [current_vector_id]
    assert conn.execute(
        """
        SELECT COUNT(*) FROM memory_vector_tombstones
        WHERE collection_name='old_collection' AND status='delete_pending'
        """
    ).fetchone()[0] == 25


def test_tombstone_status_update_is_scoped_to_collection(isolated_db, monkeypatch):
    adapter = _FakeNativeAdapter()
    monkeypatch.setattr(vi, "get_native_sdk", lambda: adapter)
    conn = vi.get_conn()
    timestamp = vi.utc_now_iso_compact()
    vector_id = 77
    for collection_name in (adapter.collection, "other_collection"):
        conn.execute(
            """
            INSERT INTO memory_vector_tombstones(
                provider,collection_name,vector_id,status,checked_at,created_at,updated_at
            ) VALUES (?,?,?,'delete_pending',NULL,?,?)
            """,
            (vi.PROVIDER, collection_name, vector_id, timestamp, timestamp),
        )
    conn.commit()

    swept = vi.sweep_pending_vector_deletes(limit=10, adapter=adapter)

    assert swept["deleted_vector_ids"] == [vector_id]
    statuses = {
        row["collection_name"]: row["status"]
        for row in conn.execute(
            """
            SELECT collection_name,status FROM memory_vector_tombstones
            WHERE provider=? AND vector_id=?
            """,
            (vi.PROVIDER, vector_id),
        ).fetchall()
    }
    assert statuses == {
        adapter.collection: "deleted",
        "other_collection": "delete_pending",
    }


def test_lifespan_sweeper_recovers_pending_without_an_api_request(isolated_db, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.app import main as main_module

    adapter = _FakeNativeAdapter()
    monkeypatch.delenv("WANWEI_PRODUCTION", raising=False)
    monkeypatch.setenv("WANWEI_API_KEY", "sweeper-startup-test-key")
    monkeypatch.setattr(vi, "get_native_sdk", lambda: adapter)
    written = _write("服务重启后自动清理待删向量")
    vector_id = written["native_index"]["vector_id"]
    vi.get_conn().execute(
        "UPDATE memory_vector_refs SET status='delete_pending' WHERE vector_id=?", (vector_id,)
    ).connection.commit()

    with TestClient(main_module.app):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status = vi.get_conn().execute(
                "SELECT status FROM memory_vector_refs WHERE vector_id=?", (vector_id,)
            ).fetchone()["status"]
            if status == "deleted":
                break
            time.sleep(0.01)

    assert status == "deleted"
    assert adapter.deleted == [vector_id]


def test_partial_multi_vector_delete_accumulates_completed_ids(isolated_db, monkeypatch):
    adapter = _FakeNativeAdapter()
    monkeypatch.setattr(vi, "get_native_sdk", lambda: adapter)
    first = _write("多向量部分删除中的第一条")
    second = _write("多向量部分删除中的第二条")
    first_vector = first["native_index"]["vector_id"]
    second_vector = second["native_index"]["vector_id"]
    second_attempts = 0

    def partial_delete(*, vector_id):
        nonlocal second_attempts
        if vector_id == second_vector:
            second_attempts += 1
            return {"ok": True, "vector_id": vector_id, "deleted": second_attempts > 1}
        return {"ok": True, "vector_id": vector_id, "deleted": True}

    adapter.delete = partial_delete

    initial = cs.forget_capsules([first["capsule_id"], second["capsule_id"]])
    retried = cs.forget_capsules([first["capsule_id"], second["capsule_id"]])

    assert initial["native_vector"] == {
        "backend": "kylin_native",
        "deleted_vector_ids": [first_vector],
        "pending_vector_ids": [second_vector],
    }
    assert retried["native_vector"] == {
        "backend": "kylin_native",
        "deleted_vector_ids": [first_vector, second_vector],
        "pending_vector_ids": [],
    }


def test_forget_retries_a_pending_vendor_delete(isolated_db, monkeypatch):
    adapter = _FakeNativeAdapter()
    monkeypatch.setattr(vi, "get_native_sdk", lambda: adapter)
    written = _write("厂商恢复后重试待删除向量")
    vector_id = written["native_index"]["vector_id"]
    attempts = 0

    def delete_after_recovery(**_kwargs):
        nonlocal attempts
        attempts += 1
        return {"ok": True, "vector_id": vector_id, "deleted": attempts > 1}

    adapter.delete = delete_after_recovery

    first = cs.forget_capsules([written["capsule_id"]])
    second = cs.forget_capsules([written["capsule_id"]])

    assert first["native_vector"]["pending_vector_ids"] == [vector_id]
    assert second["native_vector"]["deleted_vector_ids"] == [vector_id]
    assert second["native_vector"]["pending_vector_ids"] == []
    assert attempts == 2
    assert vi.native_index_coverage(adapter.collection)["delete_pending"] == 0


def test_forget_never_deletes_same_id_from_a_different_collection(isolated_db, monkeypatch):
    adapter = _FakeNativeAdapter()
    monkeypatch.setattr(vi, "get_native_sdk", lambda: adapter)
    written = _write("切换 collection 后不能误删同号向量")
    vector_id = written["native_index"]["vector_id"]
    original_collection = adapter.collection
    adapter.collection = "different_collection"

    pending = cs.forget_capsules([written["capsule_id"]])

    assert pending["native_vector"]["deleted_vector_ids"] == []
    assert pending["native_vector"]["pending_vector_ids"] == [vector_id]
    assert adapter.deleted == []
    assert vi.native_index_coverage(adapter.collection)["delete_pending"] == 1

    adapter.collection = original_collection
    retried = cs.forget_capsules([written["capsule_id"]])

    assert retried["native_vector"]["deleted_vector_ids"] == [vector_id]
    assert adapter.deleted == [vector_id]


def test_forget_does_not_report_unknown_native_delete_as_complete(isolated_db, monkeypatch):
    adapter = _FakeNativeAdapter()
    monkeypatch.setattr(vi, "get_native_sdk", lambda: adapter)
    written = _write("未知删除错误不能伪装成功")
    monkeypatch.setattr(vi, "remove_vectors", lambda _ids: (_ for _ in ()).throw(RuntimeError("unexpected")))

    result = cs.forget_capsules([written["capsule_id"]])

    assert result["native_vector"] == {
        "backend": "fts_fallback",
        "deleted_vector_ids": [],
        "pending_vector_ids": [written["native_index"]["vector_id"]],
        "reason": "native_delete_status_unknown",
    }


def test_forget_api_returns_native_vector_deletion(isolated_db, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.app import main as main_module

    adapter = _FakeNativeAdapter()
    monkeypatch.delenv("WANWEI_PRODUCTION", raising=False)
    monkeypatch.setenv("WANWEI_API_KEY", "forget-native-test-key")
    monkeypatch.setattr(vi, "get_native_sdk", lambda: adapter)
    written = _write("需要通过预览确认后从原生向量索引删除")
    vector_id = written["native_index"]["vector_id"]
    adapter.search_hits = [{"vector_id": vector_id, "score": 0.9}]

    with TestClient(main_module.app) as client:
        headers = {"X-API-Key": "forget-native-test-key"}
        preview = client.post(
            "/memory/forget/preview",
            json={"instruction": "删除这条原生索引记忆"},
            headers=headers,
        ).json()
        response = client.post(
            "/memory/forget/confirm",
            json={"forget_request_id": preview["forget_request_id"], "capsule_ids": [written["capsule_id"]]},
            headers=headers,
        )

    assert response.status_code == 200
    assert response.json()["native_vector"] == {
        "backend": "kylin_native",
        "deleted_vector_ids": [vector_id],
        "pending_vector_ids": [],
    }
    assert adapter.deleted == [vector_id]


def test_forget_api_commits_local_state_before_retryable_native_delete(isolated_db, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.app import main as main_module
    from backend.app.db import get_conn

    adapter = _FakeNativeAdapter()
    monkeypatch.delenv("WANWEI_PRODUCTION", raising=False)
    monkeypatch.setenv("WANWEI_API_KEY", "forget-retry-test-key")
    monkeypatch.setattr(vi, "get_native_sdk", lambda: adapter)
    written = _write("本地遗忘提交后重试原生向量删除")
    vector_id = written["native_index"]["vector_id"]
    adapter.search_hits = [{"vector_id": vector_id, "score": 0.9}]
    actual_remove = vi.remove_vectors
    attempts = 0

    def fail_once(capsule_ids):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("injected post-commit SDK failure")
        return actual_remove(capsule_ids)

    monkeypatch.setattr(vi, "remove_vectors", fail_once)

    with TestClient(main_module.app) as client:
        headers = {"X-API-Key": "forget-retry-test-key"}
        preview = client.post(
            "/memory/forget/preview",
            json={"instruction": "重试原生向量删除"},
            headers=headers,
        ).json()
        payload = {"forget_request_id": preview["forget_request_id"], "capsule_ids": [written["capsule_id"]]}
        first = client.post("/memory/forget/confirm", json=payload, headers=headers)

        conn = get_conn()
        assert first.status_code == 200
        assert first.json()["native_vector"] == {
            "backend": "fts_fallback",
            "deleted_vector_ids": [],
            "pending_vector_ids": [vector_id],
            "reason": "native_delete_status_unknown",
        }
        assert conn.execute(
            "SELECT json_extract(state,'$.lifecycle') FROM memory_capsules_v2 WHERE capsule_id=?",
            (written["capsule_id"],),
        ).fetchone()[0] == "forgotten"
        assert conn.execute(
            "SELECT status FROM memory_vector_refs WHERE vector_id=?", (vector_id,)
        ).fetchone()["status"] == "delete_pending"
        assert conn.execute(
            "SELECT status FROM memory_forget_requests WHERE forget_request_id=?",
            (preview["forget_request_id"],),
        ).fetchone()["status"] == "completed"

        second = client.post("/memory/forget/confirm", json=payload, headers=headers)

    assert second.status_code == 200
    assert second.json()["native_vector"] == {
        "backend": "kylin_native",
        "deleted_vector_ids": [vector_id],
        "pending_vector_ids": [],
    }
    assert attempts == 2
    assert adapter.deleted == [vector_id]
    assert get_conn().execute("SELECT COUNT(*) FROM audit_logs WHERE event_type='forget_confirm'").fetchone()[0] == 1


def test_forget_replay_repairs_result_after_vendor_delete_then_ticket_write_failure(isolated_db, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.app import main as main_module
    from backend.app.db import get_conn

    adapter = _FakeNativeAdapter()
    monkeypatch.delenv("WANWEI_PRODUCTION", raising=False)
    monkeypatch.setenv("WANWEI_API_KEY", "forget-result-repair-key")
    monkeypatch.setattr(vi, "get_native_sdk", lambda: adapter)
    written = _write("向量已删但票据结果未写入时可以恢复")
    vector_id = written["native_index"]["vector_id"]
    adapter.search_hits = [{"vector_id": vector_id, "score": 0.9}]

    with TestClient(main_module.app, raise_server_exceptions=False) as client:
        headers = {"X-API-Key": "forget-result-repair-key"}
        preview = client.post(
            "/memory/forget/preview",
            json={"instruction": "票据结果未写入时恢复"},
            headers=headers,
        ).json()
        payload = {"forget_request_id": preview["forget_request_id"], "capsule_ids": [written["capsule_id"]]}
        actual_get_conn = main_module.get_conn

        class FailFinalResultUpdate:
            def __init__(self, connection):
                self.connection = connection
                self.completed_update_seen = False

            def execute(self, sql, parameters=()):
                normalized = " ".join(sql.split())
                if "SET status='completed', result=?" in normalized:
                    self.completed_update_seen = True
                elif self.completed_update_seen and "SET result=?, updated_at=?" in normalized:
                    raise RuntimeError("injected final ticket result write failure")
                return self.connection.execute(sql, parameters)

            def __getattr__(self, name):
                return getattr(self.connection, name)

        proxy = FailFinalResultUpdate(actual_get_conn())
        monkeypatch.setattr(main_module, "get_conn", lambda: proxy)
        first = client.post("/memory/forget/confirm", json=payload, headers=headers)
        monkeypatch.setattr(main_module, "get_conn", actual_get_conn)

        assert first.status_code == 500
        assert get_conn().execute(
            "SELECT status FROM memory_vector_refs WHERE vector_id=?", (vector_id,)
        ).fetchone()["status"] == "deleted"
        second = client.post("/memory/forget/confirm", json=payload, headers=headers)

    assert second.status_code == 200
    assert second.json()["native_vector"] == {
        "backend": "kylin_native",
        "deleted_vector_ids": [vector_id],
        "pending_vector_ids": [],
    }
    stored = json.loads(get_conn().execute(
        "SELECT result FROM memory_forget_requests WHERE forget_request_id=?", (preview["forget_request_id"],)
    ).fetchone()["result"])
    assert stored["native_vector"] == second.json()["native_vector"]


def test_concurrent_same_forget_confirmation_is_idempotent(isolated_db, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from fastapi.testclient import TestClient
    from backend.app import main as main_module

    adapter = _FakeNativeAdapter()
    monkeypatch.delenv("WANWEI_PRODUCTION", raising=False)
    monkeypatch.setenv("WANWEI_API_KEY", "forget-concurrent-key")
    monkeypatch.setattr(vi, "get_native_sdk", lambda: adapter)
    written = _write("并发相同确认必须得到相同完成结果")
    vector_id = written["native_index"]["vector_id"]
    adapter.search_hits = [{"vector_id": vector_id, "score": 0.9}]
    delete_barrier = threading.Barrier(2)

    def concurrent_delete(*, vector_id):
        delete_barrier.wait(timeout=5)
        return {"ok": True, "vector_id": vector_id, "deleted": True}

    adapter.delete = concurrent_delete

    with TestClient(main_module.app) as client:
        headers = {"X-API-Key": "forget-concurrent-key"}
        preview = client.post(
            "/memory/forget/preview",
            json={"instruction": "并发相同确认"},
            headers=headers,
        ).json()
        payload = {"forget_request_id": preview["forget_request_id"], "capsule_ids": [written["capsule_id"]]}
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(
                lambda _index: client.post("/memory/forget/confirm", json=payload, headers=headers),
                range(2),
            ))

    assert [response.status_code for response in responses] == [200, 200]
    assert responses[0].json() == responses[1].json()
    assert responses[0].json()["native_vector"] == {
        "backend": "kylin_native",
        "deleted_vector_ids": [vector_id],
        "pending_vector_ids": [],
    }
