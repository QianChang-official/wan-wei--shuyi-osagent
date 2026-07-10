from __future__ import annotations

import importlib
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.operations.backup import create_backup, restore_backup, validate_database, verify_backup
from backend.app.operations.observability import MetricsRegistry, request_id
from backend.app.security.rate_limit import resolve_client_ip


def _client(tmp_path: Path) -> TestClient:
    os.environ["WANWEI_API_KEY"] = "test-key"
    os.environ["WANWEI_MEMORY_DB"] = str(tmp_path / "memory.db")
    os.environ.pop("WANWEI_PRODUCTION", None)
    import backend.app.main as main_mod
    importlib.reload(main_mod)
    return TestClient(main_mod.app, raise_server_exceptions=False)


def test_health_probes_request_id_and_metrics(tmp_path):
    client = _client(tmp_path)
    live = client.get("/health/live", headers={"X-Request-ID": "delivery-test"})
    assert live.status_code == 200
    assert live.headers["X-Request-ID"] == "delivery-test"
    assert "app;dur=" in live.headers["Server-Timing"]
    assert client.get("/health/ready").json()["status"] == "ready"
    assert client.get("/metrics").status_code == 401
    metrics = client.get("/metrics", headers={"X-API-Key": "test-key"})
    assert metrics.status_code == 200
    assert "wanwei_http_requests_total" in metrics.text
    assert "wanwei_build_info" in metrics.text


def test_request_id_validation():
    assert request_id("valid-request_123") == "valid-request_123"
    assert request_id("bad request").startswith("req_")
    assert request_id("x" * 129).startswith("req_")


def test_metrics_registry_uses_bounded_route_labels():
    registry = MetricsRegistry()
    registry.begin()
    registry.finish("GET", "/workflow/runs/{run_id}", 200, 0.25)
    rendered = registry.render("test")
    assert '/workflow/runs/{run_id}' in rendered
    assert "0.250000" in rendered


def test_forwarded_ip_requires_trusted_proxy():
    assert resolve_client_ip("10.0.0.2", "203.0.113.7", "") == "10.0.0.2"
    assert resolve_client_ip("10.0.0.2", "203.0.113.7", "10.0.0.0/24") == "203.0.113.7"
    assert resolve_client_ip("10.1.0.2", "203.0.113.7", "10.0.0.0/24") == "10.1.0.2"
    assert resolve_client_ip("10.0.0.2", "not-an-ip", "10.0.0.0/24") == "10.0.0.2"
    assert (
        resolve_client_ip(
            "10.0.0.2",
            "198.51.100.8, 203.0.113.7",
            "10.0.0.0/24,203.0.113.0/24",
        )
        == "198.51.100.8"
    )
    assert (
        resolve_client_ip(
            "10.0.0.2",
            "192.0.2.123, 198.51.100.8",
            "10.0.0.0/24",
        )
        == "198.51.100.8"
    )
    assert resolve_client_ip("10.0.0.2", "203.0.113.7", "10.0.0.0/24,203.0.113.0/24") == "10.0.0.2"


def test_verified_backup_and_restore_round_trip(tmp_path, monkeypatch):
    database = tmp_path / "live.db"
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(database))
    from backend.app.db import close_all, get_conn
    from backend.app.init_db import main as init_db

    close_all()
    init_db()
    conn = get_conn()
    conn.execute(
        "INSERT INTO audit_logs VALUES (?, ?, ?, ?)",
        ("audit_original", "test", json.dumps({"value": "original"}), "2026-07-10T00:00:00Z"),
    )
    conn.commit()

    result = create_backup(tmp_path / "backups")
    backup = Path(result["backup"])
    assert backup.exists()
    assert Path(result["manifest"]).exists()
    assert validate_database(backup)["quick_check"] == "ok"
    assert verify_backup(backup)["manifest"] == "verified"

    conn.execute("DELETE FROM audit_logs")
    conn.commit()
    close_all()
    restored = restore_backup(backup, force=True)
    assert restored["status"] == "restored"
    row = get_conn().execute("SELECT audit_id FROM audit_logs").fetchone()
    assert row[0] == "audit_original"


def test_restore_requires_explicit_force(tmp_path):
    with pytest.raises(RuntimeError, match="force=True"):
        restore_backup(tmp_path / "missing.db")


def test_restore_requires_backup_manifest(tmp_path, monkeypatch):
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(source))
    from backend.app.db import close_all
    from backend.app.init_db import main as init_db

    close_all()
    init_db()
    close_all()
    with pytest.raises(RuntimeError, match="manifest is required"):
        restore_backup(source, target=target, force=True)


def test_backup_manifest_detects_tampering(tmp_path, monkeypatch):
    database = tmp_path / "live.db"
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(database))
    from backend.app.db import close_all
    from backend.app.init_db import main as init_db

    close_all()
    init_db()
    backup = Path(create_backup(tmp_path / "backups")["backup"])
    manifest_path = backup.with_suffix(".db.manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RuntimeError, match="checksum"):
        verify_backup(backup)


def test_restore_preserves_corrupt_target_for_forensics(tmp_path, monkeypatch):
    source = tmp_path / "source.db"
    target = tmp_path / "corrupt.db"
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(source))
    from backend.app.db import close_all
    from backend.app.init_db import main as init_db

    close_all()
    init_db()
    backup = Path(create_backup(tmp_path / "backups")["backup"])
    close_all()
    target.write_bytes(b"not a sqlite database")
    restored = restore_backup(backup, target=target, force=True)
    assert restored["safety_backup_kind"] == "raw"
    assert Path(restored["safety_backup"]).read_bytes() == b"not a sqlite database"
    assert validate_database(target)["quick_check"] == "ok"
