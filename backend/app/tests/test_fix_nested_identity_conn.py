# Copyright (c) 2026 QianChang-official
#
# 宛委·枢忆 is licensed under Mulan PSL v2.
# You can use this software according to the terms and the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
# http://license.coscl.org.cn/MulanPSL2
#
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

"""持连接身份解析的确定性回归测试（forget_confirm 嵌套 get_conn 修复）。

机制：``db.get_conn()`` 在线程本地代际落后于全局 ``_generation`` 时，会关闭
本线程缓存的旧句柄。若身份解析函数（``configured_actor_id`` /
``actor_id_for_request``）在调用方已持有连接时内部再进 ``get_conn()``，另一
线程 ``close_all()`` 抬代际后，嵌套调用会关掉调用方仍在用的句柄，表现为
``sqlite3.ProgrammingError: Cannot operate on a closed database``。

本测试从另一线程抬一次代际，把「嵌套即关闭」变成确定性事件：修复后
helper 复用传入的连接，句柄保持可用；一旦回归为嵌套 ``get_conn()``，随后
的 ``SELECT 1`` 会立即在已关闭的句柄上抛错。比并发压力循环更强——不依赖
竞争窗口是否恰好命中。
"""

from concurrent.futures import ThreadPoolExecutor


class _StubRequest:
    """actor_id_for_request 只读取 .headers 的最小请求桩。"""

    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers


def _bump_generation_from_other_thread() -> None:
    """close_all() 只能由本线程安全关闭自己的句柄；跨线程调用只抬代际。

    抬完后，主测试线程缓存的连接仍在使用中，但其线程本地代际已过期——
    主线程下一次 get_conn() 会关掉它。这正是被测的嵌套触发条件。
    """
    from backend.app.db import close_all

    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(close_all).result()


def test_configured_actor_id_reuses_held_conn(isolated_db, monkeypatch):
    monkeypatch.setenv("WANWEI_API_KEY", "nested-conn-owner-key-0123456789abcdef")
    from backend.app.db import get_conn
    from backend.app.soul.ownership import configured_actor_id

    conn = get_conn()
    _bump_generation_from_other_thread()

    owner_id = configured_actor_id(conn=conn)
    assert owner_id
    # 若实现嵌套 get_conn()，此刻 conn 已被关闭，下一行抛 ProgrammingError。
    assert conn.execute("SELECT 1").fetchone() is not None


def test_actor_id_for_request_reuses_held_conn(isolated_db, monkeypatch):
    key = "nested-conn-owner-key-0123456789abcdef"
    monkeypatch.setenv("WANWEI_API_KEY", key)
    from backend.app.db import get_conn
    from backend.app.soul.ownership import actor_id_for_request

    conn = get_conn()
    _bump_generation_from_other_thread()

    # 无 header → configured_actor_id(conn=conn) 分支。
    assert actor_id_for_request(_StubRequest({}), conn=conn)
    assert conn.execute("SELECT 1").fetchone() is not None

    # 带 x-api-key → actor_id_from_api_key(provided, conn=conn) 分支
    # （含首次引导：独立写连接，不触碰调用方句柄）。
    assert actor_id_for_request(_StubRequest({"x-api-key": key}), conn=conn)
    assert conn.execute("SELECT 1").fetchone() is not None
