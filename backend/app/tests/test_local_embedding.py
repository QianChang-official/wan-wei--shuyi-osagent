"""本地向量语义通道测试 — BGE-small-zh + SQLite brute-force cosine。

覆盖两个面:
1. **通道关闭**(默认 CI 环境,无模型):available()=False,search 返回 None,
   检索回退 FTS,写入不受影响 — 这是部署默认形态,必须零副作用。
2. **通道开启**(本机有模型目录时):真实语义召回 — 无共同词的 query 命中
   语义相近记忆;删除后向量同步消失。

模型测试用 pytest.mark.skipif 门控:无 WANWEI_LOCAL_EMBED_DIR 时跳过,
保证 CI(无 95MB 模型)不挂。
"""
from __future__ import annotations

import os

import pytest

from backend.app.memory_runtime import local_embedding as le

MODEL_DIR = os.environ.get("WANWEI_LOCAL_EMBED_DIR", "")
HAS_MODEL = bool(MODEL_DIR) and os.path.isdir(MODEL_DIR)


@pytest.fixture(autouse=True)
def _reset_model_cache(monkeypatch):
    """每个测试重置模型单例缓存,避免跨测试污染。"""
    monkeypatch.setattr(le, "_model", None)
    monkeypatch.setattr(le, "_model_tried", False)
    yield


# ---------------------------------------------------------------------------
# 通道关闭(默认形态,CI 必跑)
# ---------------------------------------------------------------------------


def test_unavailable_without_model_dir(isolated_db, monkeypatch):
    """未配置模型目录 → 通道关闭,search 返回 None(调用方回退 FTS)。"""
    monkeypatch.delenv("WANWEI_LOCAL_EMBED_DIR", raising=False)
    assert le.available() is False
    assert le.search("任意查询") is None


def test_embed_and_store_noop_when_unavailable(isolated_db, monkeypatch):
    """通道关闭时写入路径静默跳过,不建表不报错。"""
    monkeypatch.delenv("WANWEI_LOCAL_EMBED_DIR", raising=False)
    assert le.embed_and_store("cap_x", "任意内容", ts="2026-09-01T00:00:00Z") is False


def test_delete_vector_safe_when_no_table(isolated_db):
    """表不存在时删除不报错(幂等)。"""
    le.delete_vector("cap_nonexistent")  # 不应抛异常


def test_retrieval_falls_back_to_fts_when_channel_off(isolated_db, monkeypatch):
    """端到端:通道关闭时,检索走 FTS,语义无关 query 用词面命中。"""
    monkeypatch.delenv("WANWEI_LOCAL_EMBED_DIR", raising=False)
    from backend.app.memory_runtime.capsule_store import write_capsule
    from backend.app.memory_runtime.retrieval import search_capsules_with_status

    write_capsule(memory_class="preference", content={"text": "用户喜欢喝美式咖啡"})
    results, status = search_capsules_with_status("美式咖啡", top_k=3)
    assert len(results) >= 1
    # 通道关闭时 backend 不得声称 local_embedding
    assert status["backend"] != "local_embedding"


# ---------------------------------------------------------------------------
# 通道开启(需本机模型;CI 无模型时 skip)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_MODEL, reason="无本地模型目录(WANWEI_LOCAL_EMBED_DIR 未设置)")
def test_semantic_recall_without_shared_words(isolated_db):
    """核心能力:无共同词的 query 命中语义相近记忆(FTS 做不到的事)。"""
    from backend.app.memory_runtime.capsule_store import write_capsule
    from backend.app.memory_runtime.retrieval import search_capsules_with_status

    write_capsule(memory_class="preference", content={"text": "用户喜欢喝美式咖啡,不加糖"})
    write_capsule(memory_class="knowledge", content={"text": "项目使用 FastAPI 加 SQLite"})
    write_capsule(memory_class="preference", content={"text": "用户对花生过敏"})

    # 「提神的饮品」与三条记忆都无共同词
    results, status = search_capsules_with_status("来点提神的饮品推荐", top_k=3)
    assert status["backend"] == "local_embedding"
    assert results, "语义通道应有候选"
    assert "美式咖啡" in str(results[0]["content"])


@pytest.mark.skipif(not HAS_MODEL, reason="无本地模型目录")
def test_delete_removes_local_vector(isolated_db):
    """删除后本地向量同步消失,语义检索不再召回。"""
    from backend.app.memory_runtime.capsule_store import write_capsule, forget_capsules

    r = write_capsule(memory_class="preference", content={"text": "用户喜欢喝美式咖啡"})
    cid = r["capsule_id"]
    assert le.search("咖啡") is not None

    forget_capsules([cid], mode="hard_delete")
    hits = le.search("咖啡")
    remaining = [] if hits is None else [h for h in hits if h[0] == cid]
    assert remaining == []


@pytest.mark.skipif(not HAS_MODEL, reason="无本地模型目录")
def test_embed_latency_within_budget(isolated_db):
    """写入编码延迟实测:单次 embed 应远低于 500ms 检索预算。"""
    import time

    from backend.app.memory_runtime.capsule_store import write_capsule

    t0 = time.monotonic()
    write_capsule(memory_class="preference", content={"text": "延迟测试:用户偏好记录"})
    elapsed_ms = (time.monotonic() - t0) * 1000
    # 整条写入(含 policy gate + FTS + 本地向量编码)应远小于 500ms
    assert elapsed_ms < 500, f"写入总耗时 {elapsed_ms:.0f}ms 超预算"
