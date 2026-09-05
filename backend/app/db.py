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

#: DB 身份指纹（issue #213）：prepare 时记录 (st_dev, st_ino)。DB 文件被
#: 移走/替换后，缓存连接仍指向已 unlink 的 inode——读写「假成功」，数据
#: 进黑洞。指纹比对是唯一可靠的检测器（SELECT 1 永远通过：sqlite3.connect
#: 对缺失路径会自动创建空文件）。
_db_fingerprints: dict[str, tuple[int, int]] = {}


class DatabaseIdentityError(RuntimeError):
    """DB 文件身份校验失败：路径缺失或 inode 与 prepare 时不一致。

    典型触发：运行中 DB 文件被移走/删除/替换（误删、备份恢复失误、磁盘
    故障）。此时缓存连接写入的是已 unlink 的 inode——进程重启即永久丢失。
    抛此异常让写路径返回 5xx 并留下告警，绝不静默假成功。
    """


def verify_db_identity(path: str | None = None) -> dict:
    """校验 DB 文件身份与核心表存在性（readiness 消费，只读）。

    三级检查（issue #213 的 readiness 真实化）：
    1. 路径存在且 inode 与 prepare 时记录一致（文件未被移走/替换）；
    2. 用**全新短连接**打开该路径——缓存连接可能还挂在已 unlink 的旧
       inode 上，用它检查永远通过；
    3. 核心表存在（非 0 表的空壳库）+ SELECT 1。

    返回 ``{"status": "ok"|"failed", "detail": ...}``。
    """
    p = Path(path) if path else _db_path()
    key = str(p)
    try:
        st = os.stat(p)
    except OSError as exc:
        return {"status": "failed", "detail": f"db_file_missing:{type(exc).__name__}"}
    recorded = _db_fingerprints.get(key)
    if recorded is not None and (st.st_dev, st.st_ino) != recorded:
        return {
            "status": "failed",
            "detail": "db_file_replaced",
            "expected_inode": recorded[1],
            "actual_inode": st.st_ino,
        }
    try:
        # 普通短连接(非 mode=ro):WAL 库崩溃后遗留 -wal 内容且无 -shm 时,
        # 只读连接会因无法创建共享内存而误报失败;读写短连接可正常完成
        # WAL 恢复。路径存在性已由上面的 stat 保证,连接不会凭空建文件。
        conn = sqlite3.connect(key, timeout=5)
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if not tables:
                return {"status": "failed", "detail": "db_empty_schema"}
            conn.execute("SELECT 1").fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return {"status": "failed", "detail": f"sqlite:{type(exc).__name__}"}
    return {"status": "ok", "detail": "identity+schema"}


def assert_db_identity() -> None:
    """写路径快速校验（transaction() 每次调用）：一个 stat 的成本。

    文件缺失或 inode 变化 → :class:`DatabaseIdentityError`（→ 5xx）。
    文件还在且 inode 一致 → 通过（读旧 inode 的风险由 readiness 的
    全新连接检查兜底——本函数只拦截「写进黑洞」这一不可逆伤害）。
    """
    p = _db_path()
    key = str(p)
    try:
        st = os.stat(p)
    except OSError as exc:
        raise DatabaseIdentityError(
            f"数据库文件不存在（可能被移走/删除）: {key}; 写入已拒绝"
        ) from exc
    recorded = _db_fingerprints.get(key)
    if recorded is not None and (st.st_dev, st.st_ino) != recorded:
        raise DatabaseIdentityError(
            f"数据库文件已被替换: {key} inode {recorded[1]} → {st.st_ino}; "
            "写入已拒绝（旧连接指向的 inode 已失效）"
        )


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
        # issue #213:记录身份指纹,供写路径与 readiness 检测文件被移走/替换。
        try:
            st = os.stat(p)
            _db_fingerprints[key] = (st.st_dev, st.st_ino)
        except OSError:
            _db_fingerprints.pop(key, None)
        with _registry_lock:
            _prepared_paths.add(key)
    return p


def database_path() -> Path:
    return _db_path()


# v0.9.6 (T3): thread-local connection reuse.
#
# Rationale / boundaries:
# - FastAPI runs sync endpoints in a worker threadpool, so each thread gets its
#   own cached connection. A connection is only closed by its owner thread;
#   closing a handle from shutdown or test teardown while that thread is inside
#   SQLite can crash the interpreter instead of raising a Python exception.
#   `check_same_thread=False` is retained for compatibility, not as permission
#   to share connections between threads.
# - Tests swap the DB file via WANWEI_MEMORY_DB between cases, so the cache is
#   keyed by resolved path; a path change transparently opens a fresh handle.
# - WAL is enabled for better concurrent read/write behaviour. For a local
#   SQLite file the raw connect() cost is sub-millisecond, so reuse is a modest
#   correctness/concurrency improvement, not a headline latency win. The
#   perf report records the measured before/after honestly.
_local = threading.local()
_registry_lock = threading.Lock()
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


def _close_connections(connections: dict[str, sqlite3.Connection]) -> None:
    """Close connections owned by the calling thread."""
    for conn in connections.values():
        try:
            conn.close()
        except Exception:
            pass


def get_conn() -> sqlite3.Connection:
    global _generation

    path = str(_db_path())
    with _registry_lock:
        local_generation = getattr(_local, "generation", -1)
        if local_generation != _generation:
            stale_connections = getattr(_local, "conns", {})
            _local.conns = {}
            _local.generation = _generation
            # The generation may be advanced by another thread, but only this
            # owner thread may safely dispose of its cached SQLite handles.
            _close_connections(stale_connections)

        cache = _local.conns
        conn = cache.get(path)
        if conn is None:
            conn = sqlite3.connect(path, check_same_thread=False)
            _configure(conn)
            cache[path] = conn
        return conn


@contextmanager
def transaction(*, immediate: bool = False):
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

    ``immediate=True`` 在 yield 前执行 ``BEGIN IMMEDIATE``，用于必须从首个
    读取开始锁定写入快照的读-改-写流程。普通模式仍沿用 sqlite3 首个 DML
    隐式开启事务的既有行为。
    """
    conn = get_conn()
    try:
        # issue #213:写前校验 DB 身份——文件被移走/替换时缓存连接写进的
        # 是已 unlink 的 inode,SQLite 层面不报错、重启即丢。一个 stat 的
        # 成本换「绝不假成功」。校验失败抛 DatabaseIdentityError → 5xx。
        assert_db_identity()
        if immediate:
            conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def close_all() -> None:
    """Invalidate all caches and close this thread's cached connections.

    Tests swap WANWEI_MEMORY_DB and unlink temp DB files between cases; calling
    this on teardown releases handles owned by the test thread. Other threads
    keep any in-flight connection alive and close it themselves when they next
    call get_conn(). This ownership rule prevents native SQLite crashes caused
    by one thread closing a handle while another thread is executing a query.
    """
    global _generation

    with _registry_lock:
        local_connections = getattr(_local, "conns", {})
        _generation += 1
        _local.conns = {}
        _local.generation = _generation
        # 路径级 prepare 缓存随连接代际一并失效：测试可能在 teardown 删除
        # DB 文件后以相同路径重建，下一次 get_conn 必须重新 mkdir/touch。
        _prepared_paths.clear()
        # 身份指纹同样失效：同路径重建的文件是全新 inode（issue #213）。
        _db_fingerprints.clear()

    _close_connections(local_connections)
