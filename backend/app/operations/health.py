from __future__ import annotations

import sqlite3
from pathlib import Path

from ..db import get_conn


def readiness_report(frontend_paths: tuple[Path, ...]) -> dict:
    checks: dict[str, dict[str, str]] = {}
    try:
        row = get_conn().execute("SELECT 1").fetchone()
        checks["database"] = {
            "status": "ok" if row and row[0] == 1 else "failed",
            "detail": "sqlite_query",
        }
    except (sqlite3.Error, OSError) as exc:
        checks["database"] = {"status": "failed", "detail": type(exc).__name__}

    frontend_ready = any(path.exists() for path in frontend_paths)
    checks["console"] = {
        "status": "ok" if frontend_ready else "failed",
        "detail": "static_assets",
    }
    ready = all(check["status"] == "ok" for check in checks.values())
    return {"status": "ready" if ready else "not_ready", "checks": checks}
