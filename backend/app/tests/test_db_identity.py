"""DB 身份指纹与 auth 注册门槛测试（issue #211 / #213 评审修复回归）。

#213 锁定行为：
1. DB 文件被移走/替换后,写路径抛 DatabaseIdentityError（绝不假成功）。
2. readiness 的 database 检查变红（此前 SELECT 1 对 unlinked inode 永远
   通过 = 假绿）。
3. 非空零表库启动 fail-fast;全新空库/旧版库照常初始化（不误伤）。

#211 锁定行为：
4. 陌生 key 不落 identity 表（不再自助开户成永久凭据）。
5. owner key（配置来源）首次使用照常完成身份引导——个人单 key 零变化。
6. 轮换后的 key 解析到同一 identity,旧 key 鉴权被拒。
7. 实际绑定地址/端口取进程参数（--host/--port）优先于环境变量声明。
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest

from backend.app import db as dbmod
from backend.app.db import DatabaseIdentityError, transaction
from backend.app.init_db import main as init_db


def _tamper_fingerprint(path: str, dev_ino: tuple[int, int]) -> None:
    """直接改写记录的指纹,跨平台模拟「prepare 后文件被替换」。"""
    dbmod._db_fingerprints[path] = dev_ino


# ---------------------------------------------------------------------------
# #213: 写路径身份校验
# ---------------------------------------------------------------------------

def test_write_rejected_when_db_replaced(isolated_db):
    """文件 inode 与 prepare 时不一致 → 写入拒绝（数据不再进黑洞）。"""
    path = str(dbmod.database_path())
    # 模拟文件被替换:记录的指纹指向一个不存在的 inode。
    _tamper_fingerprint(path, (0, 999_999_999))
    with pytest.raises(DatabaseIdentityError, match="替换"):
        with transaction() as conn:
            conn.execute("SELECT 1")


def test_write_rejected_when_db_missing(isolated_db):
    """路径缺失(被移走)→ 写入拒绝。

    Windows 句柄锁使「连接打开时移走文件」不可行;用「先移走、再恢复
    prepare 状态」模拟同等现场(get_conn 会对缺失路径自动建空文件,
    其 inode 必然与 prepare 期指纹不同——Linux 上 mv 后的真实行为一致)。
    """
    path = str(dbmod.database_path())
    recorded = dbmod._db_fingerprints.get(path)
    real_path = Path(path)
    hidden = real_path.with_suffix(".hidden")
    dbmod.close_all()
    os.replace(real_path, hidden)
    try:
        # 恢复 prepare 状态:模拟「文件在 prepare 之后才消失」。
        dbmod._prepared_paths.add(path)
        dbmod._db_fingerprints[path] = recorded
        with pytest.raises(DatabaseIdentityError):
            with transaction() as conn:
                conn.execute("SELECT 1")
    finally:
        dbmod.close_all()
        os.replace(hidden, real_path)
        dbmod._prepared_paths.discard(path)
        dbmod._db_fingerprints.pop(path, None)


def test_write_ok_when_identity_intact(isolated_db):
    """正常路径不误伤:指纹一致时事务照常工作。"""
    with transaction() as conn:
        conn.execute("SELECT 1").fetchone()


# ---------------------------------------------------------------------------
# #213: readiness 真实化
# ---------------------------------------------------------------------------

def test_readiness_fails_when_db_replaced(isolated_db):
    from backend.app.operations.health import readiness_report

    path = str(dbmod.database_path())
    _tamper_fingerprint(path, (0, 999_999_999))
    report = readiness_report((Path("/nonexistent"),))
    assert report["checks"]["database"]["status"] == "failed"
    assert report["checks"]["database"]["detail"] == "db_file_replaced"
    assert report["status"] != "ready"


def test_readiness_ok_when_healthy(isolated_db):
    from backend.app.operations.health import readiness_report

    report = readiness_report((Path("/nonexistent"),))
    assert report["checks"]["database"]["status"] == "ok"


# ---------------------------------------------------------------------------
# #213: 启动 fail-fast(外来库)与不误伤(全新/旧版库)
# ---------------------------------------------------------------------------

def test_foreign_db_fail_fast(tmp_path, monkeypatch):
    """非空但零表的文件 → 拒绝静默重建。"""
    import sqlite3

    foreign = tmp_path / "foreign.db"
    conn = sqlite3.connect(foreign)
    conn.execute("CREATE TABLE tmp_marker(x)")  # 触发真实文件写入
    conn.execute("DROP TABLE tmp_marker")       # 剩下合法 SQLite 文件,零表
    conn.commit()
    conn.close()
    assert foreign.stat().st_size > 0
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(foreign))
    dbmod.close_all()
    with pytest.raises(RuntimeError, match="不含任何表"):
        init_db()


def test_corrupt_db_fail_fast(tmp_path, monkeypatch):
    """非 SQLite 内容的文件 → 同样拒绝启动(损坏现场不静默重建)。"""
    corrupt = tmp_path / "corrupt.db"
    corrupt.write_bytes(b"SQLite format 3\x00" + b"\x00" * 96)
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(corrupt))
    dbmod.close_all()
    with pytest.raises(RuntimeError, match="无法解析"):
        init_db()


def test_fresh_empty_db_initializes(tmp_path, monkeypatch):
    """0 字节全新文件 → 正常初始化(fail-fast 不误伤全新安装)。"""
    fresh = tmp_path / "fresh.db"
    fresh.touch()
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(fresh))
    dbmod.close_all()
    init_db()  # 不抛即通过
    from backend.app.db import get_conn

    assert get_conn().execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
    ).fetchone()[0] > 0


def test_legacy_db_migrates_not_fail_fast(tmp_path, monkeypatch):
    """有旧版表的库 → 走迁移,不被 fail-fast 拦截。"""
    import sqlite3

    legacy = tmp_path / "legacy.db"
    conn = sqlite3.connect(legacy)
    # 与 init_db 的 legacy v0.2 DDL 同构(缺列会让迁移期 CREATE INDEX 失败,
    # 那是夹具问题不是被测行为)。
    conn.execute(
        "CREATE TABLE memory_events(event_id TEXT PRIMARY KEY, source_type TEXT,"
        " scene TEXT, content TEXT, quality_score REAL, sensitivity_level TEXT,"
        " trust_score REAL, created_at TEXT, soul_id TEXT, owner_id TEXT)"
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(legacy))
    dbmod.close_all()
    init_db()  # 有表 → 不抛


# ---------------------------------------------------------------------------
# #211: identity 注册门槛
# ---------------------------------------------------------------------------

def test_stranger_key_not_registered(isolated_db, monkeypatch):
    from backend.app.security import auth

    monkeypatch.setenv("WANWEI_API_KEY", "owner-key-abcdef1234567890abcdef1234567890")
    before = dbmod.get_conn().execute("SELECT COUNT(*) FROM identity").fetchone()[0]
    stranger = "stranger-key-000000000000000000000000000000"
    for _ in range(2):
        assert auth.actor_id_from_api_key(stranger) == auth._derive_legacy_owner_id(stranger)
        assert auth._verify_api_key(stranger) is False
    after = dbmod.get_conn().execute("SELECT COUNT(*) FROM identity").fetchone()[0]
    assert before == after  # 陌生 key 不落库
    # 鉴权同样被拒
    assert auth._verify_api_key(stranger) is False


@pytest.mark.parametrize("key_state", ["active", "inactive", "stranger"])
def test_identity_read_fastpath_preserves_caller_transaction(
    isolated_db, monkeypatch, seed_identity, key_state
):
    from backend.app.security import auth

    monkeypatch.setenv("WANWEI_API_KEY", "configured-fastpath-owner")
    key = "fastpath-test-key"
    expected = (
        auth._derive_legacy_owner_id(key)
        if key_state == "stranger"
        else seed_identity(key, is_active=key_state == "active")
    )
    marker = seed_identity("pending-marker-key")
    conn = dbmod.get_conn()
    conn.execute("UPDATE identity SET display_name='pending' WHERE identity_id=?", (marker,))
    statements = []
    conn.set_trace_callback(statements.append)

    def unexpected_connect(*args, **kwargs):
        pytest.fail("identity read fastpath opened a new SQLite connection")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(sqlite3, "connect", unexpected_connect)
            for _ in range(3):
                assert auth._identity_table_ready()
                assert auth.actor_id_from_api_key(key) == expected
            assert conn.in_transaction
            assert all(sql.lstrip().upper().startswith("SELECT ") for sql in statements)
            assert conn.execute(
                "SELECT display_name FROM identity WHERE identity_id=?", (marker,)
            ).fetchone()[0] == "pending"
    finally:
        conn.set_trace_callback(None)
        conn.rollback()
    assert conn.execute(
        "SELECT display_name FROM identity WHERE identity_id=?", (marker,)
    ).fetchone()[0] is None


@pytest.mark.parametrize("fail_insert", [False, True])
def test_owner_bootstrap_uses_independent_transaction(isolated_db, monkeypatch, fail_insert):
    from backend.app.security import auth

    owner = "independent-bootstrap-owner"
    monkeypatch.setenv("WANWEI_API_KEY", owner)
    conn = dbmod.get_conn()
    if fail_insert:
        conn.execute(
            "CREATE TRIGGER fail_bootstrap AFTER INSERT ON identity "
            "BEGIN SELECT RAISE(FAIL, 'injected bootstrap failure'); END"
        )
        conn.commit()
    # Preserve the caller's read snapshot across an independent commit or rollback.
    conn.execute("BEGIN")
    before = conn.execute("SELECT COUNT(*) FROM identity").fetchone()[0]
    try:
        if fail_insert:
            with pytest.raises(sqlite3.IntegrityError, match="injected bootstrap failure"):
                auth.actor_id_from_api_key(owner)
        else:
            identity = auth.actor_id_from_api_key(owner)
            assert identity.startswith("id_")
        assert conn.in_transaction
        assert conn.execute("SELECT COUNT(*) FROM identity").fetchone()[0] == before
    finally:
        conn.rollback()
    row = conn.execute(
        "SELECT identity_id FROM identity WHERE api_key_hash=?", (auth._api_key_hash(owner),)
    ).fetchone()
    if fail_insert:
        assert row is None
        conn.execute("DROP TRIGGER fail_bootstrap")
        conn.commit()
        assert auth.actor_id_from_api_key(owner).startswith("id_")
    else:
        assert row["identity_id"] == identity


def test_owner_key_bootstraps_identity(isolated_db, monkeypatch):
    from backend.app.security import auth

    owner = "owner-key-abcdef1234567890abcdef1234567890"
    monkeypatch.setenv("WANWEI_API_KEY", owner)
    # 清空 identity,从零验证 owner 引导注册。
    dbmod.get_conn().execute("DELETE FROM identity")
    dbmod.get_conn().commit()
    identity = auth.actor_id_from_api_key(owner)
    assert identity.startswith("id_")
    row = dbmod.get_conn().execute(
        "SELECT identity_id, is_active FROM identity WHERE api_key_hash=?",
        (auth._api_key_hash(owner),),
    ).fetchone()
    assert row is not None and row["identity_id"] == identity and row["is_active"] == 1
    assert auth._verify_api_key(owner) is True


def test_rotated_key_keeps_identity(isolated_db, monkeypatch):
    from backend.app.security import auth

    old_key = "old-key-abcdef1234567890abcdef1234567890"
    new_key = "new-key-abcdef1234567890abcdef1234567890"
    monkeypatch.setenv("WANWEI_API_KEY", old_key)
    original = auth.actor_id_from_api_key(old_key)
    rotated = auth.rotate_api_key(old_key, new_key)
    assert rotated == original  # 同一 identity
    # 旧 key 鉴权被拒;新 key 通过
    assert auth._verify_api_key(old_key) is False
    assert auth._verify_api_key(new_key) is True


# ---------------------------------------------------------------------------
# #211: 实际绑定地址/端口的事实来源
# ---------------------------------------------------------------------------

def test_argv_host_beats_env(monkeypatch):
    from backend.app.security import auth

    monkeypatch.setenv("WANWEI_HOST", "127.0.0.1")
    # nosec B104 —— 测试夹具字符串(验证 0.0.0.0 不被误判回环),非真实绑定。
    monkeypatch.setattr(sys, "argv", ["uvicorn", "--host", "0.0.0.0", "app:app"])  # nosec B104
    assert auth._effective_bind_host() == "0.0.0.0"  # nosec B104
    assert auth._is_loopback_bound() is False  # 0.0.0.0 不再误判回环


def test_argv_host_equals_form(monkeypatch):
    from backend.app.security import auth

    monkeypatch.setattr(sys, "argv", ["uvicorn", "--host=::1", "app:app"])
    assert auth._effective_bind_host() == "::1"


def test_env_host_when_no_argv(monkeypatch):
    from backend.app.security import auth

    monkeypatch.delenv("WANWEI_HOST", raising=False)
    monkeypatch.setattr(sys, "argv", ["python", "-m", "pytest"])
    assert auth._effective_bind_host() == "127.0.0.1"  # 默认回环
    monkeypatch.setenv("WANWEI_HOST", "192.168.1.5")
    assert auth._effective_bind_host() == "192.168.1.5"


def test_port_from_argv_beats_env(monkeypatch):
    from backend.app.security import auth

    monkeypatch.delenv("WANWEI_PORT", raising=False)
    monkeypatch.setattr(sys, "argv", ["uvicorn", "--port", "8000", "app:app"])
    assert auth._effective_port() == "8000"
    allowlist = auth._loopback_origin_allowlist()
    assert "http://127.0.0.1:8000" in allowlist  # 与实际监听一致
    monkeypatch.setenv("WANWEI_PORT", "8010")
    assert auth._effective_port() == "8000"  # argv 优先
