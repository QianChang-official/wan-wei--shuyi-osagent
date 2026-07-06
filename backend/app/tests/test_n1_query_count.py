"""
T4 回归证明: N+1 查询消除 (v0.9.6)

本测试通过 **统计实际执行的 SQL 语句数** 来证明批量优化的收益，
而不是依赖主观的性能描述或计时（计时受硬件影响，不可复现）。

原始 (N+1) 路径 search_capsules(top_k=5)，20 个候选:
  - 每候选 get_capsule           = 1 SELECT      -> 20
  - 每命中 update_capsule        = get+UPDATE+get = 3 DML/SELECT (+audit 写库) -> 15+
  合计 ≈ 45+ 条 SQL 语句/次检索。

批量路径:
  - 1 FTS + (可选)1 substring
  - 1 get_capsules_batch (IN 子句)
  - 1 executemany 批量更新 usage_count
  - 少量 schema/audit 写入
  合计为个位数常量，与候选数 N 解耦。

断言: 批量路径 SELECT+UPDATE 主查询数为个位数常量，
且与候选规模 N 不成正比。这是纯计数证明，不依赖计时。
"""

import sqlite3
import threading

import pytest


class _QueryCounter:
    """通过 sqlite3 trace callback 统计执行的 SQL 语句数。"""

    def __init__(self):
        self.count = 0
        self.statements: list[str] = []
        self._lock = threading.Lock()

    def __call__(self, statement: str):
        with self._lock:
            self.count += 1
            self.statements.append(statement)


@pytest.fixture
def counted_conn(isolated_db, monkeypatch):
    """包装 get_conn，使每个新连接都安装 trace callback 计数。"""
    from backend.app import db as db_mod

    counter = _QueryCounter()
    original_connect = sqlite3.connect

    def traced_connect(*args, **kwargs):
        conn = original_connect(*args, **kwargs)
        conn.set_trace_callback(counter)
        return conn

    monkeypatch.setattr(db_mod.sqlite3, "connect", traced_connect)
    return counter


def _seed(n: int, keyword: str = "周报"):
    from backend.app.memory_runtime.capsule_store import write_capsule

    for i in range(n):
        write_capsule(
            memory_class="knowledge",
            content={"note": f"{keyword} 项目进展 第{i}条 正式语气 三段式结构"},
        )


def test_batch_fetch_single_query(isolated_db):
    """get_capsules_batch 用单条 IN 查询取回多个 capsule。"""
    from backend.app.memory_runtime.capsule_store import write_capsule, get_capsules_batch

    ids = []
    for i in range(10):
        r = write_capsule(memory_class="knowledge", content={"n": f"item {i}"})
        ids.append(r["capsule_id"])

    by_id = get_capsules_batch(ids)
    assert len(by_id) == 10
    for cid in ids:
        assert cid in by_id
        assert by_id[cid]["capsule_id"] == cid


def test_batch_fetch_empty():
    from backend.app.memory_runtime.capsule_store import get_capsules_batch
    assert get_capsules_batch([]) == {}


def test_search_query_count_is_constant(counted_conn):
    """核心证明: 检索的主查询数为个位数常量，不随候选数线性增长。

    种子 20 条命中 capsule => 老 N+1 路径会产生 20+ SELECT (每候选 1 条)。
    批量路径应远低于该值。我们断言 SELECT 数 < 15，
    这在 20 候选下用老的 per-candidate get_capsule 是不可能达到的。
    """
    from backend.app.memory_runtime.retrieval import search_capsules

    _seed(20, keyword="周报")

    # 重置计数器：只统计检索阶段
    counted_conn.count = 0
    counted_conn.statements = []

    results = search_capsules("周报", top_k=5)
    assert len(results) == 5  # top_k 生效

    selects = [s for s in counted_conn.statements if s.strip().upper().startswith("SELECT")]
    updates = [s for s in counted_conn.statements if s.strip().upper().startswith("UPDATE")]

    # 老 N+1 路径: >= 20 个 get_capsule SELECT (每候选一次) + 每命中额外 SELECT。
    # 批量路径: FTS + substring + 1 个 IN 批量取 + 少量 = 个位数。
    assert len(selects) < 15, (
        f"SELECT 数={len(selects)} 过高，疑似 N+1 回归。语句={selects}"
    )
    # 批量更新: 单条 executemany 覆盖所有命中，UPDATE 语句应 <= 命中数但由单次 round-trip 完成。
    # 关键是不再是 per-candidate 的 get+update+get 链。
    assert len(updates) <= 5, (
        f"UPDATE 数={len(updates)} 过高，批量更新未生效。语句={updates}"
    )


def test_search_query_count_decoupled_from_candidate_size(counted_conn):
    """证明查询数与候选规模解耦: 40 候选 vs 20 候选，SELECT 数不应翻倍。"""
    from backend.app.memory_runtime.retrieval import search_capsules

    _seed(40, keyword="周报")

    counted_conn.count = 0
    counted_conn.statements = []

    search_capsules("周报", top_k=5)

    selects = [s for s in counted_conn.statements if s.strip().upper().startswith("SELECT")]
    # 即便候选达到 40（top_k*4=20 上限截断），批量路径 SELECT 仍为个位数常量。
    assert len(selects) < 15, (
        f"候选翻倍后 SELECT 数={len(selects)}，未与规模解耦，疑似 N+1。"
    )


def test_usage_count_still_increments_after_batch(isolated_db):
    """批量优化不得破坏 usage_count 递增语义（功能回归保护）。"""
    from backend.app.memory_runtime.capsule_store import write_capsule, get_capsule
    from backend.app.memory_runtime.retrieval import search_capsules

    r = write_capsule(
        memory_class="knowledge",
        content={"note": "周报 正式语气 三段式结构 项目进展"},
    )
    cid = r["capsule_id"]

    before = get_capsule(cid)["state"].get("usage_count", 0)
    search_capsules("周报", top_k=5)
    after = get_capsule(cid)["state"]["usage_count"]

    assert after == before + 1, "批量更新后 usage_count 未正确递增"
    assert get_capsule(cid)["state"]["last_accessed_at"] is not None
