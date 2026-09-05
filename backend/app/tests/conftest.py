"""
共享测试夹具 (v0.9.6)

提供隔离的临时数据库，避免测试之间互相污染。
每个使用 fresh_db 的测试都会获得一个全新的 SQLite 文件。
"""

import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

import pytest


@pytest.fixture
def seed_identity():
    """Explicitly provision a key after the test initializes its database.

    This opt-in fixture does not initialize a DB or replace authentication.
    Duplicate keys deliberately fail SQL constraints.
    """
    from backend.app.db import transaction
    from backend.app.security.auth import _api_key_hash
    from backend.app.utils.datetime_utils import utc_now_iso_compact

    def seed(api_key, *, identity_id=None, is_active=True):
        identity_id = identity_id or "id_" + uuid.uuid4().hex[:16]
        with transaction() as conn:
            conn.execute(
                "INSERT INTO identity(identity_id, api_key_hash, created_at, is_active) "
                "VALUES (?,?,?,?)",
                (identity_id, _api_key_hash(api_key), utc_now_iso_compact(), int(is_active)),
            )
        return identity_id

    return seed


def _shutdown_loaded_smoke_executor() -> None:
    """Close every import alias of the process-global model gateway runtime."""
    services = {
        id(module): module
        for name, module in tuple(sys.modules.items())
        if name.endswith(".model_gateway.service") and module is not None
    }
    for service in services.values():
        shutdown = getattr(service, "shutdown_smoke_executor", None)
        if callable(shutdown):
            shutdown()


@pytest.fixture(autouse=True)
def _cleanup_model_gateway_runtime():
    """Prevent process-global model smoke workers from crossing test boundaries."""
    _shutdown_loaded_smoke_executor()
    try:
        yield
    finally:
        # Tests reload this module in place, so resolve it again after the test
        # instead of retaining a possibly obsolete runtime reference.
        _shutdown_loaded_smoke_executor()


@pytest.fixture(autouse=True)
def _close_cached_connections():
    """Release thread-local cached SQLite handles after every test.

    v0.9.6 T3 introduced per-thread connection reuse. Tests that swap
    WANWEI_MEMORY_DB and unlink temp files (persistence/security suites use
    their own fixtures) would otherwise leave the cached handle open, causing
    ResourceWarnings and cross-test file-handle leakage. This autouse teardown
    closes cached connections uniformly, regardless of which DB fixture a test
    uses.
    """
    yield
    try:
        from backend.app.db import close_all
        close_all()
    except Exception:
        pass


@pytest.fixture
def isolated_db():
    """为单个测试提供隔离的临时数据库。

    通过 WANWEI_MEMORY_DB 环境变量指向临时文件，
    并在测试结束后清理。恢复原始环境变量值。
    """
    prev = os.environ.get("WANWEI_MEMORY_DB")
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    os.environ["WANWEI_MEMORY_DB"] = db_path

    # Drop any cached connection pointing at a previous DB path so this test
    # opens a fresh handle against its isolated file (v0.9.6 T3 connection reuse).
    from backend.app.db import close_all
    close_all()

    # 初始化 runtime schema
    from backend.app.init_db import main as init_db
    init_db()

    yield db_path

    # Release the cached handle before unlinking so the temp file can be removed
    # cleanly and no ResourceWarning is raised for an unclosed connection.
    close_all()
    if prev is None:
        os.environ.pop("WANWEI_MEMORY_DB", None)
    else:
        os.environ["WANWEI_MEMORY_DB"] = prev
    # D6: Windows 下句柄释放有延迟，重试几次；仍失败则忽略
    # （临时文件，OS 最终会清理，不阻断测试结果）
    for attempt in range(5):
        try:
            Path(db_path).unlink(missing_ok=True)
            break
        except PermissionError:
            if attempt < 4:
                time.sleep(0.1)
