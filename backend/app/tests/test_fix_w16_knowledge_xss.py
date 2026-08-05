"""FIX-19：knowledge search 的文本契约与 snippet XSS 回归测试。

`title` 是 API 文本数据，必须与 CRUD 路径一样保留原值；它在 Vue
文本插值处由渲染器进行上下文编码。`snippet` 是唯一携带系统生成
`<b>` 高亮标记的 HTML 字段，因此必须转义存储内容并仅保留高亮标记。
"""

import pytest


@pytest.fixture()
def kb_with_untrusted_html(isolated_db):
    """通过正常写入路径创建同时进入 kb_docs 和 FTS 索引的文档。"""
    from backend.app.platform_api import knowledge

    knowledge._ensure_kb_schema()
    doc = knowledge._insert_doc(
        knowledge.DocCreate(
            title="<script>alert('XSS')</script>恶意标题",
            body="unique_snippet_marker <img src=x onerror=alert(1)> 可见文本",
        )
    )
    return knowledge, doc


def _find_fixture_item(result, doc):
    return next(item for item in result["items"] if item["id"] == doc["id"])


def test_latest_path_preserves_canonical_title(kb_with_untrusted_html):
    knowledge, doc = kb_with_untrusted_html
    result = knowledge.search_docs(q="", limit=10)

    assert result["engine"] == "latest"
    assert _find_fixture_item(result, doc)["title"] == doc["title"]


def test_fts_path_preserves_title_and_sanitizes_snippet(kb_with_untrusted_html):
    knowledge, doc = kb_with_untrusted_html
    assert knowledge._FTS_OK is True, "本回归需要实际进入 FTS5 分支"

    result = knowledge.search_docs(q="unique_snippet_marker", limit=10)
    assert result["engine"] == "fts5"
    item = _find_fixture_item(result, doc)

    assert item["title"] == doc["title"]
    assert "<img" not in item["snippet"]
    assert "&lt;img" in item["snippet"]
    assert "<b>" in item["snippet"]


def test_like_path_preserves_title_and_sanitizes_snippet(
    kb_with_untrusted_html,
    monkeypatch,
):
    knowledge, doc = kb_with_untrusted_html
    monkeypatch.setattr(knowledge, "_FTS_OK", False)

    result = knowledge.search_docs(q="unique_snippet_marker", limit=10)
    assert result["engine"] == "like"
    item = _find_fixture_item(result, doc)

    assert item["title"] == doc["title"]
    assert "<img" not in item["snippet"]
    assert "&lt;img" in item["snippet"]
    assert "<b>unique_snippet_marker</b>" in item["snippet"]


def test_fts_highlight_preserved_while_raw_html_is_escaped(kb_with_untrusted_html):
    """高亮标记必须保留，紧邻的原始 HTML 必须转义。"""
    knowledge, _doc = kb_with_untrusted_html
    sanitized = knowledge._sanitize_fts_snippet(
        "<b>Python</b><script>alert(1)</script>"
    )

    assert sanitized == (
        "<b>Python</b>&lt;script&gt;alert(1)&lt;/script&gt;"
    )
