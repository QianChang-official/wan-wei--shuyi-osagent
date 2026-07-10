"""
T2 core-module unit tests — retrieval.py

覆盖检索逻辑：CJK 分词、FTS/substring 混合检索、上下文过滤、usage_count 更新。
这些行为测试在 T4 (N+1 batch 优化) 之后必须继续通过 —— 作为重构安全网。

v0.9.6 stability-perf-baseline
"""

from backend.app.memory_runtime import retrieval as rt
from backend.app.memory_runtime import capsule_store as cs


def _write(text):
    return cs.write_capsule(memory_class="knowledge", content={"text": text})


# ---------------------------------------------------------------------------
# helpers: _has_cjk / _zh_terms / _match_query
# ---------------------------------------------------------------------------

def test_has_cjk():
    assert rt._has_cjk("周报") is True
    assert rt._has_cjk("weekly report") is False


def test_zh_terms_bigram_expansion():
    # 3+ char CJK => original + bigrams
    terms = rt._zh_terms("三段式结构")
    assert "三段式结构" in terms
    assert "三段" in terms  # bigram present
    # deduped
    assert len(terms) == len(set(terms))


def test_zh_terms_empty():
    assert rt._zh_terms("") == []
    assert rt._zh_terms('  "  ') == []


def test_zh_terms_short_cjk_no_bigram():
    # < 3 chars => no bigram expansion, just the token
    terms = rt._zh_terms("周报")
    assert terms == ["周报"]


def test_match_query_or_join():
    assert rt._match_query("a b c") == '"a" OR "b" OR "c"'
    assert rt._match_query("") == ""


# ---------------------------------------------------------------------------
# search_capsules — behavior
# ---------------------------------------------------------------------------

def test_search_finds_chinese_capsule(isolated_db):
    _write("周报应使用正式语气和三段式结构")
    _write("完全无关的英文内容 about cats")
    results = rt.search_capsules("周报", top_k=5)
    assert len(results) >= 1
    assert any("周报" in cs.dumps(r["content"]) for r in results)


def test_search_no_match_returns_empty(isolated_db):
    _write("周报应使用正式语气")
    # keyword that does not exist => must NOT fallback to latest
    results = rt.search_capsules("量子色动力学专用术语xyz", top_k=5)
    assert results == []


def test_search_respects_top_k(isolated_db):
    for i in range(10):
        _write(f"周报模板版本 {i} 正式语气")
    results = rt.search_capsules("周报", top_k=3)
    assert len(results) <= 3


def test_search_increments_usage_count(isolated_db):
    res = _write("三段式结构周报偏好")
    rt.search_capsules("三段式结构", top_k=5)
    got = cs.get_capsule(res["capsule_id"])
    assert got["state"]["usage_count"] >= 1
    assert got["state"]["last_accessed_at"] is not None


def test_search_excludes_rejected(isolated_db):
    _write("token: abcdef1234567890abcdef")  # rejected, not in FTS
    results = rt.search_capsules("token", top_k=5)
    # rejected capsule must not be retrievable
    assert results == []


def test_search_sets_retrieval_score(isolated_db):
    _write("正式语气周报三段式")
    results = rt.search_capsules("周报", top_k=5)
    assert len(results) >= 1
    for r in results:
        assert "retrieval_score" in r
        assert 0.0 <= r["retrieval_score"] <= 1.0


def test_search_english_fts(isolated_db):
    _write("weekly report formal tone three part")
    results = rt.search_capsules("weekly", top_k=5)
    assert len(results) >= 1


def test_search_hyphenated_phrase(isolated_db):
    written = _write("deployment marker wanwei-smoke-12345")
    results = rt.search_capsules("wanwei-smoke-12345", top_k=5)
    assert results
    assert results[0]["capsule_id"] == written["capsule_id"]
