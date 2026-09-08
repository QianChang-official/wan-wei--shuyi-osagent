# Copyright (c) 2026 QianChang-official
#
# 宛委·枢忆 is licensed under Mulan PSL v2.
# You can use this software according to the terms of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
# http://license.coscl.org.cn/MulanPSL2
#
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

"""B1 回归测试：transaction() 上下文管理器保证异常时 rollback，不污染后续请求。

线程本地连接复用场景下，写路径异常如果不 rollback，悬挂事务会泄漏到同线程
后续请求——下一个 commit 可能提交上一个请求的部分写入（脏数据跨请求）。
"""

import queue
import threading

import pytest


def test_transaction_rollback_on_error(isolated_db):
    """异常时 transaction() 必须 rollback，悬挂事务不残留。"""
    from backend.app.db import get_conn, transaction

    # 建测试表并插入一条
    with transaction() as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS tx_probe (id INTEGER PRIMARY KEY, val TEXT)')
        conn.execute('INSERT INTO tx_probe (id, val) VALUES (1, ?)', ('first',))

    # 验证第一条写入成功
    row = get_conn().execute('SELECT val FROM tx_probe WHERE id=1').fetchone()
    assert row['val'] == 'first'

    # 触发写失败：主键冲突 → transaction() 必须 rollback
    with pytest.raises(Exception):
        with transaction() as conn:
            # 先插入一条新数据（这条不应被提交）
            conn.execute('INSERT INTO tx_probe (id, val) VALUES (2, ?)', ('should_rollback',))
            # 再插入主键冲突的（抛异常）
            conn.execute('INSERT INTO tx_probe (id, val) VALUES (1, ?)', ('conflict',))

    # 验证：悬挂事务已 rollback，id=2 没有被提交
    rows = get_conn().execute('SELECT id, val FROM tx_probe ORDER BY id').fetchall()
    assert len(rows) == 1
    assert rows[0]['id'] == 1
    assert rows[0]['val'] == 'first'

    # 后续请求不受悬挂事务影响，正常写入
    with transaction() as conn:
        conn.execute('INSERT INTO tx_probe (id, val) VALUES (3, ?)', ('after_rollback',))

    row = get_conn().execute('SELECT val FROM tx_probe WHERE id=3').fetchone()
    assert row['val'] == 'after_rollback'


def test_transaction_commit_on_success(isolated_db):
    """正常退出时 transaction() 必须 commit。"""
    from backend.app.db import get_conn, transaction

    with transaction() as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS tx_ok (id INTEGER PRIMARY KEY, val TEXT)')
        conn.execute('INSERT INTO tx_ok (id, val) VALUES (1, ?)', ('committed',))

    # 新连接（模拟后续请求）应能读到已提交数据
    row = get_conn().execute('SELECT val FROM tx_ok WHERE id=1').fetchone()
    assert row['val'] == 'committed'


def test_close_all_does_not_close_another_threads_connection(isolated_db):
    """Teardown must not close a connection while its owner is querying."""
    from backend.app.db import close_all, get_conn

    query_started = threading.Event()
    release_query = threading.Event()
    worker_results: queue.Queue[tuple[object, object]] = queue.Queue()

    def use_thread_owned_connection() -> None:
        try:
            original_connection = get_conn()
            original_connection.execute('CREATE TABLE thread_probe (value TEXT)')
            original_connection.execute(
                'INSERT INTO thread_probe (value) VALUES (?)',
                ('still_open',),
            )
            original_connection.commit()

            def pause_inside_sqlite(value: str) -> str:
                query_started.set()
                if not release_query.wait(timeout=5):
                    raise TimeoutError('main thread did not release worker query')
                return value

            original_connection.create_function('pause_inside_sqlite', 1, pause_inside_sqlite)
            value = original_connection.execute(
                'SELECT pause_inside_sqlite(value) AS value FROM thread_probe'
            ).fetchone()['value']

            replacement_connection = get_conn()
            worker_results.put((value, replacement_connection is original_connection))
        except BaseException as exc:
            worker_results.put((exc, None))

    worker = threading.Thread(target=use_thread_owned_connection)
    worker.start()
    assert query_started.wait(timeout=5), 'worker did not enter its SQLite query'

    close_all()
    release_query.set()
    worker.join(timeout=5)

    assert not worker.is_alive(), 'worker did not finish after cache invalidation'
    result, reused_stale_connection = worker_results.get_nowait()
    if isinstance(result, BaseException):
        raise result
    assert result == 'still_open'
    assert reused_stale_connection is False
