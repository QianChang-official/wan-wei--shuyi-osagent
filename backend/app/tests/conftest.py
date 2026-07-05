"""
共享测试夹具 (v0.9.6)

提供隔离的临时数据库，避免测试之间互相污染。
每个使用 fresh_db 的测试都会获得一个全新的 SQLite 文件。
"""

import os
import tempfile
from pathlib import Path

import pytest


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
    if Path(db_path).exists():
        Path(db_path).unlink()
