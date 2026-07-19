import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path


def _default_data_dir() -> Path:
    configured = os.environ.get("WANWEI_DATA_DIR")
    if configured:
        return Path(configured)

    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "wanwei-shuyi"

    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home) / "wanwei-shuyi"
    return Path.home() / ".local" / "share" / "wanwei-shuyi"


# 03-#20: mkdir/exists/chmod 三个 syscall 按路径 once 化，不再随每次
# get_conn 重复执行。就绪集合登记在 _prepared_paths，close_all() 时随连接
# 缓存一并失效——测试在 close_all 后更换/删除 DB 文件，下一次访问会重新
# prepare，语义与旧版「每次调用都 prepare」对齐。
_prepared_paths: set[str] = set()


def _db_path() -> Path:
    # Allow tests / arena runner to point at an isolated DB via env.
    env = os.environ.get("WANWEI_MEMORY_DB")
    if env:
        p = Path(env)
    else:
        p = _default_data_dir() / "memory.db"
    key = str(p)
    with _registry_lock:
        prepared = key in _prepared_paths
    if not prepared:
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.touch(mode=0o600)
        else:
            try:
                p.chmod(0o600)
            except PermissionError:
                pass
        with _registry_lock:
            _prepared_paths.add(key)
    return p


def database_path() -> Path:
    return _db_path()


# v0.9.6 (T3): thread-local connection reuse.
#
# Rationale / boundaries:
# - FastAPI runs sync endpoints in a worker threadpool, so each thread gets its
#   own cached connection. `check_same_thread=False` is used only so shutdown
#   can close idle handles created by worker threads; normal queries never share
#   a connection across threads.
# - Tests swap the DB file via WANWEI_MEMORY_DB between cases, so the cache is
#   keyed by resolved path; a path change transparently opens a fresh handle.
# - WAL is enabled for better concurrent read/write behaviour. For a local
#   SQLite file the raw connect() cost is sub-millisecond, so reuse is a modest
#   correctness/concurrency improvement, not a headline latency win. The
#   perf report records the measured before/after honestly.
_local = threading.local()
_registry_lock = threading.Lock()
_connections: dict[int, sqlite3.Connection] = {}
_generation = 0


def _configure(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    # WAL: concurrent readers do not block a writer; survives across connections
    # (stored in the DB header). synchronous=NORMAL is the WAL-safe fast setting.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    # Avoid spurious "database is locked" under threadpool concurrency.
    conn.execute("PRAGMA busy_timeout=5000")
    # 03-#10: 启用外键约束（soul_persona → affect_state/dream_lock 等 5 处
    # FOREIGN KEY 此前空转）。PRAGMA 为连接级设置，每个新建连接都要执行。
    conn.execute("PRAGMA foreign_keys=ON")


def get_conn():
    global _generation

    path = str(_db_path())
    with _registry_lock:
        local_generation = getattr(_local, "generation", -1)
        if local_generation != _generation:
            _local.conns = {}
            _local.generation = _generation

        cache = _local.conns
        conn = cache.get(path)
        if conn is None:
            conn = sqlite3.connect(path, check_same_thread=False)
            _configure(conn)
            cache[path] = conn
            _connections[id(conn)] = conn
        return conn


@contextmanager
def transaction():
    """事务上下文：成功时 commit，异常时 rollback。

    线程本地连接复用场景下，所有写路径必须用此上下文包裹。否则一旦 DML 抛
    异常，sqlite3 模块隐式开启的事务会悬挂在连接上，污染同线程后续请求——
    下一个 commit 可能把上一个请求的部分写入提交（脏数据跨请求泄漏），或
    后续查询读到未提交的中间状态。

    用法::

        with transaction() as conn:
            conn.execute("INSERT ...", (...))
            conn.execute("INSERT ...", (...))
        # 正常退出自动 commit；异常自动 rollback 并向上抛出
    """
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def close_all() -> None:
    """Close and invalidate cached connections from every worker thread.

    Tests swap WANWEI_MEMORY_DB and unlink temp DB files between cases; calling
    this on teardown releases the cached handle so the file can be removed
    cleanly and no ResourceWarning is raised for an unclosed connection.
    """
    global _generation

    with _registry_lock:
        connections = list(_connections.values())
        _connections.clear()
        _generation += 1
        _local.conns = {}
        _local.generation = _generation
        # 路径级 prepare 缓存随连接代际一并失效：测试可能在 teardown 删除
        # DB 文件后以相同路径重建，下一次 get_conn 必须重新 mkdir/touch。
        _prepared_paths.clear()

    for conn in connections:
        try:
            conn.close()
        except Exception:
            pass
