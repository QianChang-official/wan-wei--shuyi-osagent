import os
import sqlite3
import threading
from pathlib import Path


def _db_path() -> Path:
    # Allow tests / arena runner to point at an isolated DB via env.
    env = os.environ.get("WANWEI_MEMORY_DB")
    if env:
        p = Path(env)
    else:
        p = Path.home() / ".local/share/wanwei-shuyi/memory.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.touch(mode=0o600)
    else:
        try:
            p.chmod(0o600)
        except PermissionError:
            pass
    return p


# v0.9.6 (T3): thread-local connection reuse.
#
# Rationale / boundaries:
# - FastAPI runs sync endpoints in a worker threadpool, so a single shared
#   connection would raise sqlite3 `check_same_thread` errors. We therefore
#   cache one connection *per thread* (threading.local), never crossing threads.
# - Tests swap the DB file via WANWEI_MEMORY_DB between cases, so the cache is
#   keyed by resolved path; a path change transparently opens a fresh handle.
# - WAL is enabled for better concurrent read/write behaviour. For a local
#   SQLite file the raw connect() cost is sub-millisecond, so reuse is a modest
#   correctness/concurrency improvement, not a headline latency win. The
#   perf report records the measured before/after honestly.
_local = threading.local()


def _configure(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    # WAL: concurrent readers do not block a writer; survives across connections
    # (stored in the DB header). synchronous=NORMAL is the WAL-safe fast setting.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    # Avoid spurious "database is locked" under threadpool concurrency.
    conn.execute("PRAGMA busy_timeout=5000")


def get_conn():
    path = str(_db_path())
    cache = getattr(_local, "conns", None)
    if cache is None:
        cache = {}
        _local.conns = cache
    conn = cache.get(path)
    if conn is None:
        conn = sqlite3.connect(path)
        _configure(conn)
        cache[path] = conn
    return conn


def close_all() -> None:
    """Close and drop all cached connections for the current thread.

    Tests swap WANWEI_MEMORY_DB and unlink temp DB files between cases; calling
    this on teardown releases the cached handle so the file can be removed
    cleanly and no ResourceWarning is raised for an unclosed connection.
    """
    cache = getattr(_local, "conns", None)
    if not cache:
        return
    for conn in cache.values():
        try:
            conn.close()
        except Exception:
            pass
    cache.clear()
