"""Issue #38 FIX-16/17/22/23/24 regression coverage."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import anyio
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
for _path in (str(_PROJECT_ROOT), str(_PROJECT_ROOT / "backend")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from app.platform_api import automation  # noqa: E402
from backend.app.affect import emotion_memory  # noqa: E402
from backend.app.affect.state_machine import AffectState  # noqa: E402
from backend.app.db import get_conn, transaction  # noqa: E402
from backend.app.model_gateway import service as gateway_service  # noqa: E402
from backend.app.model_gateway.schemas import ModelGatewayTestIn  # noqa: E402
from backend.app.retrieval import service as legacy_retrieval  # noqa: E402


@pytest.fixture(autouse=True)
def clean_smoke_runtime():
    def shutdown_loaded_runtimes():
        seen: set[int] = set()
        for module_name in (
            "app.model_gateway.service",
            "backend.app.model_gateway.service",
        ):
            service = sys.modules.get(module_name)
            if service is None or id(service) in seen:
                continue
            seen.add(id(service))
            service.shutdown_smoke_executor()

    # The suite deliberately exercises both supported import roots. Clear a
    # runtime created by either identity so the lifecycle assertion measures
    # only the application instance under test.
    shutdown_loaded_runtimes()
    yield
    shutdown_loaded_runtimes()


@pytest.fixture
def automation_client(tmp_path, monkeypatch):
    monkeypatch.setenv("WANWEI_PLATFORM_DIR", str(tmp_path / "platform"))
    automation._schedule_state.clear()
    app = FastAPI()
    app.include_router(automation.router)
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    client.close()
    automation._schedule_state.clear()


def _step(step_type: str, config: dict) -> dict:
    return {
        "id": f"step-{step_type}",
        "type": step_type,
        "name": step_type,
        "config": config,
        "on_error": "stop",
    }


def test_flow_count_gate_is_atomic_at_creation_boundary(automation_client, monkeypatch):
    monkeypatch.setattr(automation, "MAX_FLOW_COUNT", 1)

    first = automation_client.post("/automation/flows", json={"name": "first"})
    second = automation_client.post("/automation/flows", json={"name": "second"})

    assert first.status_code == 201
    assert second.status_code == 409
    assert "上限" in second.text
    assert len(automation._flows.all()) == 1


def test_concurrent_flow_creates_cannot_cross_count_limit(automation_client, monkeypatch):
    monkeypatch.setattr(automation, "MAX_FLOW_COUNT", 1)
    start = threading.Barrier(2)

    def create(flow_id: str) -> int:
        start.wait(timeout=2)
        try:
            automation._store_new_flow(flow_id, {"id": flow_id, "name": flow_id})
            return 201
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as callers:
        statuses = sorted(callers.map(create, ("flow-a", "flow-b")))

    assert statuses == [201, 409]
    assert len(automation._flows.all()) == 1


def test_concurrent_flow_partial_updates_are_not_lost(monkeypatch):
    flow_id = "flow-concurrent-update"
    initial = {
        "id": flow_id,
        "name": "before",
        "desc": "before",
        "trigger": "manual",
        "cron": None,
        "steps": [],
        "enabled": True,
        "created_at": "2026-08-04T00:00:00+08:00",
        "updated_at": "2026-08-04T00:00:00+08:00",
        "ai_editable": True,
    }

    class ConcurrentFlowStore:
        def __init__(self):
            self.data = {flow_id: initial}
            self.lock = threading.RLock()
            self.legacy_get_barrier = threading.Barrier(2)

        def get(self, key):
            with self.lock:
                value = dict(self.data[key])
            # This deterministically exposes the old get/merge/set race while
            # the mutate-based implementation never enters this legacy path.
            self.legacy_get_barrier.wait(timeout=2)
            return value

        def set(self, key, value):
            with self.lock:
                self.data[key] = value

        def mutate(self, fn):
            with self.lock:
                return fn(self.data)

    store = ConcurrentFlowStore()
    monkeypatch.setattr(automation, "_flows", store)

    with ThreadPoolExecutor(max_workers=2) as callers:
        futures = [
            callers.submit(
                automation.update_flow,
                flow_id,
                automation.FlowPatch(name="renamed"),
            ),
            callers.submit(
                automation.update_flow,
                flow_id,
                automation.FlowPatch(desc="preserved"),
            ),
        ]
        for future in futures:
            future.result(timeout=5)

    assert store.data[flow_id]["name"] == "renamed"
    assert store.data[flow_id]["desc"] == "preserved"


def test_flow_rejects_more_than_bounded_step_count(automation_client):
    steps = [_step("agent", {"task": f"task-{index}"}) for index in range(automation.MAX_STEPS_PER_FLOW + 1)]

    response = automation_client.post("/automation/flows", json={"name": "too-many", "steps": steps})

    assert response.status_code == 422
    assert automation._flows.all() == {}


@pytest.mark.parametrize(
    ("step_type", "config"),
    [
        ("agent", {"task": 123}),
        ("shell", {"command": "echo ok", "url": "https://unexpected.example"}),
        ("http", {"method": "TRACE", "url": "https://example.com"}),
        ("memory", {"op": "delete", "key": "x"}),
        ("condition", {"expr": ["not", "text"]}),
    ],
)
def test_step_type_config_schema_rejects_wrong_or_extra_fields(automation_client, step_type, config):
    response = automation_client.post(
        "/automation/flows",
        json={"name": "invalid-config", "steps": [_step(step_type, config)]},
    )

    assert response.status_code == 422
    assert automation._flows.all() == {}


def test_step_type_config_schema_accepts_and_normalizes_known_fields(automation_client):
    steps = [
        _step("agent", {"task": "summarize"}),
        _step("shell", {"command": "echo ok"}),
        _step("http", {"method": "get", "url": "https://example.com", "desc": "fetch"}),
        _step("memory", {"op": "WRITE", "key": "summary", "desc": "store"}),
        _step("condition", {"expr": "result != ''", "desc": "non-empty"}),
    ]

    response = automation_client.post("/automation/flows", json={"name": "valid-config", "steps": steps})

    assert response.status_code == 201, response.text
    stored = response.json()["steps"]
    assert stored[2]["config"]["method"] == "GET"
    assert stored[3]["config"]["op"] == "write"


def test_ai_apply_cannot_bypass_step_config_schema(automation_client):
    created = automation_client.post("/automation/flows", json={"name": "base"}).json()
    proposal = {
        "name": "base",
        "steps": [_step("shell", {"command": "echo ok", "unexpected": True})],
    }

    response = automation_client.post(
        f"/automation/flows/{created['id']}/ai-apply",
        json={"proposed_flow": proposal},
    )

    assert response.status_code == 422
    assert automation._flows.get(created["id"])["steps"] == []


def test_non_step_patch_preserves_legacy_step_config(automation_client):
    flow_id = "flow-legacy-shell"
    legacy_steps = [_step("shell", {"cmd": "echo legacy"})]
    automation._flows.set(
        flow_id,
        {
            "id": flow_id,
            "name": "legacy",
            "desc": "",
            "trigger": "manual",
            "cron": None,
            "steps": legacy_steps,
            "enabled": True,
            "created_at": "2026-08-04T00:00:00+08:00",
            "updated_at": "2026-08-04T00:00:00+08:00",
            "ai_editable": True,
        },
    )

    toggled = automation_client.put(
        f"/automation/flows/{flow_id}",
        json={"enabled": False},
    )
    assert toggled.status_code == 200, toggled.text
    assert toggled.json()["steps"] == legacy_steps
    assert automation._flows.get(flow_id)["steps"] == legacy_steps

    null_steps = automation_client.put(
        f"/automation/flows/{flow_id}",
        json={"name": "legacy-renamed", "steps": None},
    )
    assert null_steps.status_code == 200, null_steps.text
    assert null_steps.json()["steps"] == legacy_steps

    explicit_legacy_steps = automation_client.put(
        f"/automation/flows/{flow_id}",
        json={"steps": legacy_steps},
    )
    assert explicit_legacy_steps.status_code == 422
    assert automation._flows.get(flow_id)["steps"] == legacy_steps


def test_cron_input_and_recalculation_are_bounded():
    with pytest.raises(ValueError, match="最长"):
        automation._validate_cron_expr("0" * (automation.MAX_CRON_EXPRESSION_LENGTH + 1))
    crowded_minute = ",".join(["0"] * (automation._MAX_CRON_FIELD_SEGMENTS + 1))
    with pytest.raises(ValueError, match="片段"):
        automation._validate_cron_expr(f"{crowded_minute} * * * *")

    automation._parsed_cron.cache_clear()
    now = datetime.fromisoformat("2026-08-04T12:00:30+08:00")
    first, _ = automation._next_cron_dt("* * * * *", now)
    second, _ = automation._next_cron_dt("* * * * *", now)

    assert first == second == datetime.fromisoformat("2026-08-04T12:01:00+08:00")
    assert automation._parsed_cron.cache_info().hits == 1
    assert automation._parsed_cron.cache_info().maxsize == 256


def test_real_execution_requires_explicit_authorized_gear(monkeypatch):
    monkeypatch.delenv("WANWEI_DEVICE_GEAR_ENABLED", raising=False)

    automation._enforce_real_execution_gear("shell", "sandbox")
    with pytest.raises(PermissionError, match="显式选择"):
        automation._enforce_real_execution_gear("shell", "human_review")
    with pytest.raises(PermissionError, match="未获授权"):
        automation._enforce_real_execution_gear("shell", "device")


def _configured_provider() -> dict:
    return {
        "provider": "custom",
        "api_base": "https://model.example/v1",
        "api_key": "",
        "api_key_encrypted": None,
        "model": "test-model",
        "enabled": True,
        "notes": "",
    }


def test_real_smoke_runs_on_dedicated_worker(monkeypatch):
    caller_thread = threading.current_thread().name
    observed: dict[str, str] = {}
    monkeypatch.setattr(gateway_service, "_get_config", lambda _provider: _configured_provider())

    def fake_smoke(*_args):
        observed["thread"] = threading.current_thread().name
        return "ok", 3, "ready"

    monkeypatch.setattr(gateway_service, "_openai_compatible_smoke", fake_smoke)

    result = gateway_service.run_provider_test(ModelGatewayTestIn(provider="custom", dry_run=False))

    assert result.status == "ok"
    assert observed["thread"].startswith("model-gateway-smoke")
    assert observed["thread"] != caller_thread


def test_async_smoke_does_not_starve_the_only_anyio_worker(monkeypatch):
    smoke_started = threading.Event()
    release_smoke = threading.Event()
    monkeypatch.setattr(gateway_service, "_get_config", lambda _provider: _configured_provider())

    def blocking_smoke(*_args):
        smoke_started.set()
        if not release_smoke.wait(timeout=5):
            raise TimeoutError("test did not release smoke worker")
        return "ok", 3, "ready"

    monkeypatch.setattr(gateway_service, "_openai_compatible_smoke", blocking_smoke)

    @asynccontextmanager
    async def lifespan(_app):
        limiter = anyio.to_thread.current_default_thread_limiter()
        previous_tokens = limiter.total_tokens
        limiter.total_tokens = 1
        gateway_service.start_smoke_executor()
        try:
            yield
        finally:
            limiter.total_tokens = previous_tokens
            gateway_service.shutdown_smoke_executor()

    app = FastAPI(lifespan=lifespan)

    @app.post("/smoke")
    async def smoke_route():
        request = ModelGatewayTestIn(provider="custom", dry_run=False)
        return await gateway_service.run_provider_test_async(request)

    @app.get("/probe")
    def synchronous_probe():
        return {"status": "ready"}

    with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as callers:
        smoke_response = callers.submit(client.post, "/smoke")
        assert smoke_started.wait(timeout=2)
        probe_response = callers.submit(client.get, "/probe")
        try:
            probe = probe_response.result(timeout=1)
        finally:
            release_smoke.set()
        smoke = smoke_response.result(timeout=5)

    assert probe.status_code == 200
    assert probe.json() == {"status": "ready"}
    assert smoke.status_code == 200
    assert smoke.json()["status"] == "ok"


def test_chat_completion_does_not_starve_the_only_anyio_worker(monkeypatch):
    """The async soul-chat model wait must stay outside AnyIO's worker pool."""
    from backend.app import app_runtime

    smoke_started = threading.Event()
    release_smoke = threading.Event()
    monkeypatch.setenv("WANWEI_OPENAI_COMPATIBLE_BASE", "https://model.example/v1")
    monkeypatch.setenv("WANWEI_OPENAI_COMPATIBLE_MODEL", "chat-model")

    def blocking_smoke(*_args):
        smoke_started.set()
        if not release_smoke.wait(timeout=5):
            raise TimeoutError("test did not release chat worker")
        return "ok", 3, "ready"

    monkeypatch.setattr(gateway_service, "_openai_compatible_smoke", blocking_smoke)

    @asynccontextmanager
    async def lifespan(_app):
        limiter = anyio.to_thread.current_default_thread_limiter()
        previous_tokens = limiter.total_tokens
        limiter.total_tokens = 1
        gateway_service.start_smoke_executor()
        try:
            yield
        finally:
            limiter.total_tokens = previous_tokens
            gateway_service.shutdown_smoke_executor()

    app = FastAPI(lifespan=lifespan)

    @app.post("/chat")
    async def chat_route():
        return await app_runtime._chat_complete_async(
            [{"role": "user", "content": "hello"}],
        )

    @app.get("/probe")
    def synchronous_probe():
        return {"status": "ready"}

    with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as callers:
        chat_response = callers.submit(client.post, "/chat")
        assert smoke_started.wait(timeout=2)
        probe_response = callers.submit(client.get, "/probe")
        try:
            probe = probe_response.result(timeout=1)
        finally:
            release_smoke.set()
        chat = chat_response.result(timeout=5)

    assert probe.status_code == 200
    assert probe.json() == {"status": "ready"}
    assert chat.status_code == 200
    assert chat.json()["status"] == "ok"


def test_chat_complete_sync_uses_dedicated_worker(monkeypatch):
    """Legacy synchronous callers retain the bounded worker isolation."""
    from backend.app import app_runtime

    caller_thread = threading.current_thread().name
    observed: dict[str, str] = {}
    monkeypatch.setenv("WANWEI_OPENAI_COMPATIBLE_BASE", "https://model.example/v1")
    monkeypatch.setenv("WANWEI_OPENAI_COMPATIBLE_MODEL", "chat-model")

    def fake_smoke(*_args):
        observed["thread"] = threading.current_thread().name
        return "ok", 3, "ready"

    monkeypatch.setattr(gateway_service, "_openai_compatible_smoke", fake_smoke)

    result = app_runtime._chat_complete([{"role": "user", "content": "hello"}])

    assert result["status"] == "ok"
    assert observed["thread"].startswith("model-gateway-smoke")
    assert observed["thread"] != caller_thread


def test_real_smoke_rejects_when_bounded_queue_is_full(monkeypatch):
    gateway_service.start_smoke_executor()
    full_gate = threading.BoundedSemaphore(1)
    assert full_gate.acquire(blocking=False)
    monkeypatch.setattr(gateway_service, "_SMOKE_QUEUE_SLOTS", full_gate)
    monkeypatch.setattr(gateway_service, "_get_config", lambda _provider: _configured_provider())

    result = gateway_service.run_provider_test(ModelGatewayTestIn(provider="custom", dry_run=False))

    assert result.status == "busy"
    assert "queue is full" in result.message
    full_gate.release()


def test_real_smoke_pool_enforces_worker_and_queue_capacity(monkeypatch):
    capacity = gateway_service._SMOKE_WORKER_COUNT + gateway_service._SMOKE_QUEUE_CAPACITY
    gateway_service.start_smoke_executor()

    class TrackingGate:
        def __init__(self):
            self._semaphore = threading.BoundedSemaphore(capacity)
            self._lock = threading.Lock()
            self.acquired = 0
            self.all_acquired = threading.Event()

        def acquire(self, blocking=False):
            admitted = self._semaphore.acquire(blocking=blocking)
            if admitted:
                with self._lock:
                    self.acquired += 1
                    if self.acquired == capacity:
                        self.all_acquired.set()
            return admitted

        def release(self):
            self._semaphore.release()

    gate = TrackingGate()
    release_workers = threading.Event()
    workers_started = threading.Event()
    active_lock = threading.Lock()
    active = 0
    peak_active = 0
    monkeypatch.setattr(gateway_service, "_SMOKE_QUEUE_SLOTS", gate)
    monkeypatch.setattr(gateway_service, "_get_config", lambda _provider: _configured_provider())

    def blocking_smoke(*_args):
        nonlocal active, peak_active
        with active_lock:
            active += 1
            peak_active = max(peak_active, active)
            if active == gateway_service._SMOKE_WORKER_COUNT:
                workers_started.set()
        try:
            if not release_workers.wait(timeout=5):
                raise TimeoutError("test did not release smoke workers")
            return "ok", 4, "ready"
        finally:
            with active_lock:
                active -= 1

    monkeypatch.setattr(gateway_service, "_openai_compatible_smoke", blocking_smoke)
    request = ModelGatewayTestIn(provider="custom", dry_run=False)

    def run_async_request():
        return asyncio.run(gateway_service.run_provider_test_async(request))

    with ThreadPoolExecutor(max_workers=capacity + 1) as callers:
        admitted = [callers.submit(run_async_request) for _ in range(capacity)]
        assert gate.all_acquired.wait(timeout=2)
        assert workers_started.wait(timeout=2)
        rejected = callers.submit(run_async_request).result(timeout=2)
        assert rejected.status == "busy"
        assert peak_active == gateway_service._SMOKE_WORKER_COUNT
        release_workers.set()
        assert [future.result(timeout=5).status for future in admitted] == ["ok"] * capacity


def test_async_deadline_cancels_future_and_callback_releases_once(monkeypatch):
    class CountingGate:
        def __init__(self):
            self.acquire_calls = 0
            self.release_calls = 0

        def acquire(self, blocking=False):
            assert blocking is False
            self.acquire_calls += 1
            return True

        def release(self):
            self.release_calls += 1

    class TrackingFuture(Future):
        def __init__(self):
            super().__init__()
            self.cancel_calls = 0

        def cancel(self):
            self.cancel_calls += 1
            return super().cancel()

    class FakeExecutor:
        def __init__(self, future):
            self.future = future

        def submit(self, *_args, **_kwargs):
            return self.future

        def shutdown(self, *, wait, cancel_futures):
            assert wait is True
            assert cancel_futures is True

    gate = CountingGate()
    future = TrackingFuture()
    with gateway_service._SMOKE_RUNTIME_LOCK:
        gateway_service._SMOKE_EXECUTOR = FakeExecutor(future)
        gateway_service._SMOKE_QUEUE_SLOTS = gate
    monkeypatch.setattr(gateway_service, "_SMOKE_RESULT_TIMEOUT_S", 0.01)

    with pytest.raises(gateway_service._SmokeDeadlineExceeded):
        asyncio.run(
            gateway_service._run_smoke_in_dedicated_pool_async(
                "test-provider",
                "https://model.example/v1",
                "",
                "test-model",
                "ping",
                16,
            )
        )

    assert gate.acquire_calls == 1
    # asyncio.wrap_future propagates cancellation back to its concurrent
    # future, so the explicit deadline cancellation may be repeated safely.
    assert future.cancel_calls >= 1
    assert gate.release_calls == 1


def test_worker_network_timeout_is_not_misreported_as_pool_deadline(monkeypatch):
    monkeypatch.setattr(gateway_service, "_get_config", lambda _provider: _configured_provider())

    def network_timeout(*_args):
        raise TimeoutError("socket timed out")

    monkeypatch.setattr(gateway_service, "_openai_compatible_smoke", network_timeout)

    result = asyncio.run(
        gateway_service.run_provider_test_async(
            ModelGatewayTestIn(provider="custom", dry_run=False)
        )
    )

    assert result.status == "error"
    assert "smoke failed: socket timed out" in result.message
    assert "isolated worker deadline" not in result.message


def test_app_lifespan_restarts_and_fully_shuts_down_smoke_executor(
    isolated_db,
    tmp_path,
    monkeypatch,
):
    from backend.app import app_runtime

    monkeypatch.setenv("WANWEI_PLATFORM_DIR", str(tmp_path / "platform"))
    monkeypatch.setattr(gateway_service, "_get_config", lambda _provider: _configured_provider())
    monkeypatch.setattr(
        gateway_service,
        "_openai_compatible_smoke",
        lambda *_args: ("ok", 2, "ready"),
    )
    executors = []
    request_headers = {"X-API-Key": app_runtime.get_api_key()}

    for _ in range(2):
        with TestClient(app_runtime.app) as client:
            response = client.post(
                "/model-gateway/test",
                json={"provider": "custom", "dry_run": False},
                headers=request_headers,
            )
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "ok"
            assert gateway_service._SMOKE_EXECUTOR is not None
            executors.append(gateway_service._SMOKE_EXECUTOR)

        assert gateway_service._SMOKE_EXECUTOR is None
        assert gateway_service._SMOKE_QUEUE_SLOTS is None
        assert not [
            thread.name
            for thread in threading.enumerate()
            if thread.name.startswith("model-gateway-smoke")
        ]

    assert executors[0] is not executors[1]


def test_emotion_binding_locks_before_read_and_preserves_concurrent_write(isolated_db, monkeypatch):
    capsule_id = "capsule-transaction-boundary"
    with transaction() as conn:
        conn.execute(
            "INSERT INTO memory_capsules_v2(capsule_id,affective_metadata,updated_at) VALUES (?,?,?)",
            (capsule_id, json.dumps({"existing": "value"}), "initial"),
        )

    load_entered = threading.Event()
    release_load = threading.Event()
    competing_writer_started = threading.Event()
    competing_writer_acquired = threading.Event()
    errors: list[BaseException] = []
    original_json_loads = json.loads

    def blocking_loads(value, *args, **kwargs):
        if threading.current_thread().name == "emotion-binder":
            load_entered.set()
            if not release_load.wait(timeout=5):
                raise TimeoutError("test did not release emotion metadata parse")
        return original_json_loads(value, *args, **kwargs)

    monkeypatch.setattr(emotion_memory.json, "loads", blocking_loads)

    def bind_emotion():
        try:
            emotion_memory.bind_emotion_to_capsule(capsule_id, "soul-a", AffectState(current_mood="focused"))
        except BaseException as exc:  # pragma: no cover - surfaced by assertion below
            errors.append(exc)

    def competing_write():
        try:
            competing_writer_started.set()
            with transaction(immediate=True) as conn:
                competing_writer_acquired.set()
                row = conn.execute(
                    "SELECT affective_metadata FROM memory_capsules_v2 WHERE capsule_id=?",
                    (capsule_id,),
                ).fetchone()
                metadata = original_json_loads(row["affective_metadata"])
                metadata["concurrent_marker"] = "preserved"
                conn.execute(
                    "UPDATE memory_capsules_v2 SET affective_metadata=? WHERE capsule_id=?",
                    (json.dumps(metadata), capsule_id),
                )
        except BaseException as exc:  # pragma: no cover - surfaced by assertion below
            errors.append(exc)

    binder = threading.Thread(target=bind_emotion, name="emotion-binder")
    writer = threading.Thread(target=competing_write, name="emotion-competing-writer")
    binder.start()
    assert load_entered.wait(timeout=2)
    writer.start()

    assert competing_writer_started.wait(timeout=2)
    assert not competing_writer_acquired.wait(timeout=0.2), "writer entered between emotion SELECT and UPDATE"
    release_load.set()
    binder.join(timeout=5)
    writer.join(timeout=5)

    assert not binder.is_alive() and not writer.is_alive()
    assert errors == []
    assert competing_writer_acquired.is_set()
    stored_row = get_conn().execute(
        "SELECT affective_metadata FROM memory_capsules_v2 WHERE capsule_id=?",
        (capsule_id,),
    ).fetchone()
    stored = json.loads(stored_row["affective_metadata"])
    assert stored["existing"] == "value"
    assert stored["current_mood"] == "focused"
    assert stored["concurrent_marker"] == "preserved"


def test_legacy_fts_fallback_logs_warning_without_query_text(monkeypatch, caplog):
    class BrokenConnection:
        def execute(self, *_args, **_kwargs):
            raise RuntimeError("FTS table unavailable")

    query = "private-query-must-not-enter-logs"
    monkeypatch.setattr(legacy_retrieval, "get_conn", BrokenConnection)

    with caplog.at_level(logging.WARNING, logger=legacy_retrieval.__name__):
        assert legacy_retrieval.search(query) == []

    assert "legacy FTS 检索失败" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "FTS table unavailable" not in caplog.text
    assert query not in caplog.text
