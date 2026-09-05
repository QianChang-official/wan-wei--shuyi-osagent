from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..db import verify_db_identity
from ..platform_api import failed_modules, loaded_modules


def readiness_report(frontend_paths: tuple[Path, ...]) -> dict:
    checks: dict[str, dict[str, Any]] = {}
    # issue #213:readiness 的 database 检查不能只用缓存连接的 SELECT 1——
    # DB 文件被移走后,缓存连接仍指向已 unlink 的 inode,SELECT 1 永远通过
    # (假绿);而 sqlite3.connect 对缺失路径会自动创建空文件,同样假绿。
    # 改用身份校验:路径存在 + inode 与 prepare 时一致 + 全新只读连接能
    # 看到非空 schema。
    identity = verify_db_identity()
    if identity["status"] == "ok":
        checks["database"] = {"status": "ok", "detail": "identity+schema"}
    else:
        checks["database"] = {
            "status": "failed",
            "detail": identity["detail"],
        }

    # Only enforce static-assets readiness in production; CI/test may run
    # without a built frontend.
    if os.environ.get("WANWEI_PRODUCTION"):
        frontend_ready = any(path.exists() for path in frontend_paths)
        checks["console"] = {
            "status": "ok" if frontend_ready else "failed",
            "detail": "static_assets",
        }
    else:
        checks["console"] = {"status": "ok", "detail": "static_assets_optional"}

    modules = loaded_modules()
    failed = failed_modules()
    platform_detail = f"loaded_modules={','.join(modules) if modules else 'none'}"
    if failed:
        platform_detail += f";failed_modules={','.join(sorted(failed))}"
    checks["platform_api"] = {
        "status": "ok" if modules and not failed else "failed",
        "detail": platform_detail,
    }
    if failed:
        checks["platform_api"]["failed_modules"] = sorted(failed)

    ready = all(check["status"] == "ok" for check in checks.values())
    return {"status": "ready" if ready else "not_ready", "checks": checks}
