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

"""B5 知识舱：内置知识库（SQLite FTS5 全文检索）。

契约（前后端已钉死）：
- 文档 CRUD：GET/POST /knowledge/docs，GET/PUT/DELETE /knowledge/docs/{did}
  字段：id, title, body, tags[], source('manual'|'web'|'chat'|'file'),
        uri?, created_at, updated_at, pinned
  列表默认 body 只回前 200 字符预览（body_truncated 标注是否截断），
  full=true 返回全文；单篇 GET 始终返回全文。
- 检索：GET /knowledge/search?q=&limit= → FTS5 命中
  [{id,title,snippet(<b> 高亮),score}]；q 为空返回最新 20 条。
  FTS 不可用时回退 LIKE 并标注 engine='like'。
- 批量导入：POST /knowledge/import {items:[...]} → {imported, skipped}
  坏条目（校验失败/存储层错误）计入 skipped，不中断整批。
- 统计：GET /knowledge/stats → {total, by_source, by_tag_top10, recent7d}

存储说明：复用 app.db 的线程本地连接；独立表 kb_docs / kb_fts，
不与记忆胶囊等既有表混用。FTS5 缺失（极少见的精简 SQLite 构建）时
全模块自动降级为 LIKE 检索，接口形状保持不变。

双轨现状（审计 06-#11 诚实标注，不做合并重构）：本模块的 kb_fts 与老
``app.memory_runtime``/``main.py`` 侧的 ``memory_fts`` 检索体系双轨并行、
零数据互通；本模块只服务平台知识舱 CRUD/检索，不与胶囊/记忆运行时互相
索引或同步。

时间基准（审计 06-#12 统一）：全模块 UTC aware datetime，
ISO8601 秒级带 ``Z`` 序列化（与 memory_center.py 同一口径）。
"""
from __future__ import annotations

import html
import json
import logging
import re
import sqlite3
import uuid
from datetime import timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, ValidationError

from ..db import get_conn, transaction
from .guards import audit_safe
from ..soul.ownership import actor_id_for_request, configured_actor_id
from ..utils.cjk_text import cjk_space as _cjk_space, query_atoms
from ..utils.datetime_utils import utc_now, utc_now_iso_compact

logger = logging.getLogger(__name__)


def _require_knowledge_owner(request: Request) -> None:
    """Keep legacy shared knowledge storage behind the configured local actor."""
    owner_id = actor_id_for_request(request)
    if owner_id not in {'anonymous', configured_actor_id()}:
        raise HTTPException(status_code=404, detail={'error': 'not_found'})


router = APIRouter(
    prefix='/knowledge',
    tags=['knowledge'],
    dependencies=[Depends(_require_knowledge_owner)],
)

SOURCES = ('manual', 'web', 'chat', 'file')
_IMPORT_CAP = 500
MAX_KNOWLEDGE_BODY_CHARS = 100_000
MAX_KNOWLEDGE_TITLE_CHARS = 500
# LIKE 兜底通路的扫描硬预算（issue #136）：FTS 异常/0 命中时的全表扫封顶。
_LIKE_SCAN_CAP = 2000

# ---------------------------------------------------------------------------
# 建表与 FTS5 可用性探测（模块导入时执行一次）
# ---------------------------------------------------------------------------

_FTS_OK = False


def _now() -> str:
    """UTC aware 当前时间 → ISO8601 秒级带 Z（与 memory_center 统一基准）。"""
    return utc_now_iso_compact()


# CJK 逐字插空格：unicode61 按 Unicode 词边界分词，连续中文整段会成单 token，
# 导致 MATCH 检索中文子串永远 0 命中。入库前对 CJK 逐字插空格，让每个汉字独立成 token。
# 实现已上提到 app.utils.cjk_text（issue #119/#133：知识库与记忆底座共用同一套
# 分词实现，避免同一规则两处各写一份、修一处漏一处）；此处保留 _cjk_space 别名
# 供本模块既有调用点使用。


def init_knowledge_schema(conn=None) -> None:
    """为当前数据库初始化知识库表与 FTS5 索引；可被 init_db 与运行时按需调用。"""
    global _FTS_OK
    if conn is None:
        conn = get_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS kb_docs (
            id         TEXT PRIMARY KEY,
            title      TEXT NOT NULL,
            body       TEXT NOT NULL,
            tags       TEXT NOT NULL DEFAULT '[]',
            source     TEXT NOT NULL DEFAULT 'manual',
            uri        TEXT,
            pinned     INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        'CREATE INDEX IF NOT EXISTS idx_kb_docs_updated ON kb_docs(pinned DESC, updated_at DESC)'
    )
    # FTS 分词方案版本标记表（CJK 逐字插空格 = v2）
    conn.execute(
        'CREATE TABLE IF NOT EXISTS _kb_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)'
    )
    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS kb_fts USING fts5(
                doc_id UNINDEXED, title, body, tags,
                tokenize = 'unicode61 remove_diacritics 0'
            )
            """
        )
        # 空 MATCH 探测一次，确认 fts5 真正可用而非仅语法通过
        conn.execute("SELECT count(*) FROM kb_fts WHERE kb_fts MATCH '\"__probe__\"'").fetchone()
        _FTS_OK = True
    except Exception as exc:  # noqa: BLE001 —— FTS5 缺失时降级 LIKE
        logger.warning('kb FTS5 不可用，检索降级为 LIKE：%r', exc)
        _FTS_OK = False

    # 分词方案升级（v1=纯 unicode61，v2=CJK 逐字插空格）：版本不匹配则重建 kb_fts
    if _FTS_OK:
        row = conn.execute("SELECT value FROM _kb_meta WHERE key = 'fts_schema_version'").fetchone()
        current = int(row['value']) if row else 1
        if current < 2:
            try:
                conn.execute('DROP TABLE IF EXISTS kb_fts')
                conn.execute(
                    """
                    CREATE VIRTUAL TABLE kb_fts USING fts5(
                        doc_id UNINDEXED, title, body, tags,
                        tokenize = 'unicode61 remove_diacritics 0'
                    )
                    """
                )
                for r in conn.execute('SELECT id, title, body, tags FROM kb_docs').fetchall():
                    tags_json = r['tags']
                    try:
                        tags_list = json.loads(tags_json or '[]')
                        tags_str = ' '.join(tags_list) if isinstance(tags_list, list) else str(tags_list)
                    except Exception:  # noqa: BLE001
                        tags_str = str(tags_json)
                    conn.execute(
                        'INSERT INTO kb_fts (doc_id, title, body, tags) VALUES (?, ?, ?, ?)',
                        (r['id'], _cjk_space(r['title']), _cjk_space(r['body']), _cjk_space(tags_str)),
                    )
                conn.execute(
                    "INSERT OR REPLACE INTO _kb_meta (key, value) VALUES ('fts_schema_version', '2')"
                )
                logger.warning('kb FTS5 分词方案升级至 v2（CJK 逐字插空格），已重建索引')
            except Exception as exc:  # noqa: BLE001
                logger.warning('kb FTS5 重建失败，本进程仍按 v2 写入：%r', exc)
                # 重建失败时不降级 _FTS_OK——后续写入仍尝试 v2，下次启动会再重建
    conn.commit()


def _ensure_kb_schema() -> None:
    """按需在测试/DB 切换场景下为当前连接重建知识库表。"""
    conn = get_conn()
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='kb_docs'"
    ).fetchone():
        return
    init_knowledge_schema(conn)


init_knowledge_schema()


# ---------------------------------------------------------------------------
# 行 <-> API 文档
# ---------------------------------------------------------------------------


def _row_to_doc(row: Any) -> dict:
    try:
        tags = json.loads(row['tags'] or '[]')
        if not isinstance(tags, list):
            tags = []
    except Exception:  # noqa: BLE001
        tags = []
    return {
        'id': row['id'],
        'title': row['title'],
        'body': row['body'],
        'tags': [str(t) for t in tags],
        'source': row['source'],
        'uri': row['uri'],
        'created_at': row['created_at'],
        'updated_at': row['updated_at'],
        'pinned': bool(row['pinned']),
    }


def _get_row(did: str) -> Optional[Any]:
    return get_conn().execute('SELECT * FROM kb_docs WHERE id = ?', (did,)).fetchone()


def _fts_upsert(conn: Any, doc: dict) -> None:
    if not _FTS_OK:
        return
    conn.execute('DELETE FROM kb_fts WHERE doc_id = ?', (doc['id'],))
    conn.execute(
        'INSERT INTO kb_fts (doc_id, title, body, tags) VALUES (?, ?, ?, ?)',
        (
            doc['id'],
            _cjk_space(doc['title']),
            _cjk_space(doc['body']),
            _cjk_space(' '.join(doc['tags'])),
        ),
    )


def _fts_delete(conn: Any, did: str) -> None:
    if not _FTS_OK:
        return
    conn.execute('DELETE FROM kb_fts WHERE doc_id = ?', (did,))


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class DocCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=MAX_KNOWLEDGE_TITLE_CHARS)
    body: str = Field(..., min_length=1, max_length=MAX_KNOWLEDGE_BODY_CHARS)
    tags: list[str] = Field(default_factory=list)
    source: str = 'manual'
    uri: Optional[str] = None
    pinned: bool = False


class DocUpdate(BaseModel):
    title: Optional[str] = Field(
        default=None, min_length=1, max_length=MAX_KNOWLEDGE_TITLE_CHARS
    )
    body: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=MAX_KNOWLEDGE_BODY_CHARS,
    )
    tags: Optional[list[str]] = None
    source: Optional[str] = None
    uri: Optional[str] = None
    pinned: Optional[bool] = None


class ImportItem(BaseModel):
    # issue #136：导入条目与单条创建共用同一组长宽约束（此前 ImportItem 无
    # max_length，虽然 import_docs 内部转 DocCreate 时会校验，但 schema 层
    # 不设上限意味着坏条目只能整批 200 后逐条 skipped，契约不可见）。
    title: Optional[str] = Field(
        default=None, min_length=1, max_length=MAX_KNOWLEDGE_TITLE_CHARS
    )
    body: Optional[str] = Field(
        default=None, min_length=1, max_length=MAX_KNOWLEDGE_BODY_CHARS
    )
    tags: list[str] = Field(default_factory=list)
    source: str = 'manual'
    uri: Optional[str] = None


class ImportPayload(BaseModel):
    # 使用宽松 dict 接收，让处理函数内部逐条校验并跳过坏条目
    items: list[dict[str, Any]] = Field(default_factory=list)


def _check_source(source: str) -> str:
    if source not in SOURCES:
        raise HTTPException(
            status_code=422,
            detail=f"source 必须是 {list(SOURCES)} 之一，收到：{source!r}",
        )
    return source


def _clean_tags(tags: list[str]) -> list[str]:
    seen: list[str] = []
    for t in tags:
        t = str(t).strip()
        if t and t not in seen:
            seen.append(t)
    return seen[:32]


def _insert_doc(payload: DocCreate) -> dict:
    now = _now()
    doc = {
        'id': f'kd_{uuid.uuid4().hex[:16]}',
        'title': payload.title.strip(),
        'body': payload.body,
        'tags': _clean_tags(payload.tags),
        'source': _check_source(payload.source),
        'uri': payload.uri,
        'pinned': payload.pinned,
        'created_at': now,
        'updated_at': now,
    }
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO kb_docs (id, title, body, tags, source, uri, pinned, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                doc['id'], doc['title'], doc['body'], json.dumps(doc['tags'], ensure_ascii=False),
                doc['source'], doc['uri'], int(doc['pinned']), now, now,
            ),
        )
        _fts_upsert(conn, doc)
    audit_safe('knowledge_doc_created', {'doc_id': doc['id'], 'title': doc['title'], 'source': doc['source']})
    return doc


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


# 列表接口 body 预览字符上限（06-#10）：full=true 时返回全文
_LIST_BODY_PREVIEW_CHARS = 200


@router.get('/docs')
def list_docs(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    source: Optional[str] = None,
    full: bool = Query(default=False),
) -> dict:
    """文档列表。

    默认每条的 ``body`` 只回前 ``_LIST_BODY_PREVIEW_CHARS`` 字符预览，
    并以 ``body_truncated`` 标注是否截断，避免一次拉回数百篇全文；
    传 ``full=true`` 返回完整 body。响应字段全集不变，向后兼容。
    """
    _ensure_kb_schema()
    conn = get_conn()
    where, args = '', []
    if source:
        where, args = 'WHERE source = ?', [source]
    total = conn.execute(f'SELECT count(*) AS c FROM kb_docs {where}', args).fetchone()['c']
    rows = conn.execute(
        f'SELECT * FROM kb_docs {where} ORDER BY pinned DESC, updated_at DESC LIMIT ? OFFSET ?',
        (*args, limit, offset),
    ).fetchall()
    items = []
    for r in rows:
        doc = _row_to_doc(r)
        if not full and len(doc['body']) > _LIST_BODY_PREVIEW_CHARS:
            doc['body'] = doc['body'][:_LIST_BODY_PREVIEW_CHARS]
            doc['body_truncated'] = True
        else:
            doc['body_truncated'] = False
        items.append(doc)
    return {'items': items, 'total': total, 'limit': limit, 'offset': offset}


@router.post('/docs', status_code=201)
def create_doc(payload: DocCreate) -> dict:
    _ensure_kb_schema()
    return _insert_doc(payload)


@router.get('/docs/{did}')
def get_doc(did: str) -> dict:
    _ensure_kb_schema()
    row = _get_row(did)
    if row is None:
        raise HTTPException(status_code=404, detail=f'知识文档不存在：{did}')
    return _row_to_doc(row)


@router.put('/docs/{did}')
def update_doc(did: str, payload: DocUpdate) -> dict:
    _ensure_kb_schema()
    row = _get_row(did)
    if row is None:
        raise HTTPException(status_code=404, detail=f'知识文档不存在：{did}')
    doc = _row_to_doc(row)
    if payload.title is not None:
        doc['title'] = payload.title.strip()
    if payload.body is not None:
        doc['body'] = payload.body
    if payload.tags is not None:
        doc['tags'] = _clean_tags(payload.tags)
    if payload.source is not None:
        doc['source'] = _check_source(payload.source)
    if payload.uri is not None:
        doc['uri'] = payload.uri
    if payload.pinned is not None:
        doc['pinned'] = payload.pinned
    doc['updated_at'] = _now()

    with transaction() as conn:
        conn.execute(
            """
            UPDATE kb_docs
            SET title = ?, body = ?, tags = ?, source = ?, uri = ?, pinned = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                doc['title'], doc['body'], json.dumps(doc['tags'], ensure_ascii=False),
                doc['source'], doc['uri'], int(doc['pinned']), doc['updated_at'], did,
            ),
        )
        _fts_upsert(conn, doc)
    return doc


@router.delete('/docs/{did}')
def delete_doc(did: str) -> dict:
    _ensure_kb_schema()
    if _get_row(did) is None:
        raise HTTPException(status_code=404, detail=f'知识文档不存在：{did}')
    with transaction() as conn:
        conn.execute('DELETE FROM kb_docs WHERE id = ?', (did,))
        _fts_delete(conn, did)
    audit_safe('knowledge_doc_deleted', {'doc_id': did})
    return {'deleted': True, 'id': did}


# ---------------------------------------------------------------------------
# 检索（FTS5 优先，LIKE 兜底）
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r'[\w一-鿿]+', re.UNICODE)


def _fts_query(q: str) -> str:
    """把用户输入清洗成安全的 FTS5 MATCH 表达式。

    配合入库侧的 _cjk_space：CJK 逐字拆分后 OR 连接，命中中文子串。
    例如「兼容性」拆成「兼」「容」「性」三个 atom，body「兼容问题」
    含「兼」「容」即命中；bm25 排序使包含更多查询字的文档靠前。

    issue #133：混排 token（"Windows麒麟"）此前只保留 CJK 部分、ASCII 段
    被整段丢弃（if cjk/elif 分支永远走不到 elif）——现改用共享的
    ``query_atoms``，同一 token 内 CJK 逐字 + 非 CJK 连续片段各自成 atom，
    两个语种都参与匹配。
    """
    atoms = query_atoms(q)
    if not atoms:
        return ''
    # 限制 atom 总数，避免超长 MATCH 表达式（query_atoms 已封顶 48）
    quoted = [f'"{a}"' for a in atoms if a and '"' not in a and a not in ('AND', 'OR', 'NOT')]
    return ' OR '.join(quoted)


def _like_snippet(body: str, q: str, width: int = 120) -> str:
    # 与检索通路共用 query_atoms（issue #133/#136）：高亮词与实际 LIKE
    # 匹配词保持一致，混排 token 的两个语种部分都能被高亮。
    tokens = query_atoms(q) or _TOKEN_RE.findall(q)
    text = body.replace('\n', ' ')
    pos = -1
    for t in tokens:
        pos = text.lower().find(t.lower())
        if pos >= 0:
            break
    start = max(0, pos - width // 2) if pos >= 0 else 0
    window = text[start:start + width]
    escaped = html.escape(window)
    for t in tokens:
        if not t:
            continue
        escaped = re.sub(
            f'({re.escape(html.escape(t))})',
            r'<b>\1</b>',
            escaped,
            flags=re.IGNORECASE,
        )
    prefix = '…' if start > 0 else ''
    suffix = '…' if start + width < len(text) else ''
    return prefix + escaped + suffix


# PUA 占位符：先把 FTS 返回的 <b>/</b> 高亮标签抽离，再对正文整体做 HTML 转义，
# 最后还原高亮标签。这样即使正文中含 <script>/<img> 等标签，也不会注入到页面。
_HIGHLIGHT_START = '\uE000'
_HIGHLIGHT_END = '\uE001'

# CJK 字符（含 <b></b> 标签边界、CJK 标点）之间的多余空格——_cjk_space 入库的副作用，
# 在 snippet 还原后压缩掉，使展示文本回到「在麒麟系统上」而非「在 麒 麟 系 统 上」。
# \u3000-\u303f=CJK 符号和标点，\uff00-\uffef=全角形式（含，。！？等中文标点）。
_CJK_GAP_RE = re.compile(r'([\u4e00-\u9fff\u3400-\u4dbf\u3000-\u303f\uff00-\uffef<>/.])\s+([\u4e00-\u9fff\u3400-\u4dbf\u3000-\u303f\uff00-\uffef<>/.])')


def _compact_cjk_snippet(snip: str) -> str:
    """压缩 CJK 字符及 <b> 标签边界之间的多余空格（_cjk_space 副作用）。"""
    if not snip:
        return snip
    prev = None
    # 循环应用直到稳定（处理连续多空格 + 标签嵌套）
    while prev != snip:
        prev = snip
        snip = _CJK_GAP_RE.sub(r'\1\2', snip)
    return snip


def _sanitize_fts_snippet(snip: str) -> str:
    """Escape raw HTML in FTS snippet while preserving <b> highlight tags."""
    if not snip:
        return ''
    snip = snip.replace('<b>', _HIGHLIGHT_START).replace('</b>', _HIGHLIGHT_END)
    snip = html.escape(snip)
    snip = snip.replace(_HIGHLIGHT_START, '<b>').replace(_HIGHLIGHT_END, '</b>')
    return _compact_cjk_snippet(snip)


@router.get('/search')
def search_docs(
    q: str = Query(default=''),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    _ensure_kb_schema()
    conn = get_conn()
    q = (q or '').strip()

    if not q:
        rows = conn.execute(
            'SELECT * FROM kb_docs ORDER BY pinned DESC, updated_at DESC LIMIT ?', (limit,)
        ).fetchall()
        items = [
            {
                'id': r['id'], 'title': r['title'],
                'snippet': '', 'score': 0.0,
                'source': r['source'], 'pinned': bool(r['pinned']),
                'updated_at': r['updated_at'],
            }
            for r in rows
        ]
        return {'q': '', 'engine': 'latest', 'items': items}

    if _FTS_OK:
        fts_q = _fts_query(q)
        if fts_q:
            try:
                rows = conn.execute(
                    """
                    SELECT kb_fts.doc_id, kb_docs.title,
                           snippet(kb_fts, 2, '<b>', '</b>', '…', 24) AS snip,
                           bm25(kb_fts) AS rank
                    FROM kb_fts
                    JOIN kb_docs ON kb_docs.id = kb_fts.doc_id
                    WHERE kb_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (fts_q, limit),
                ).fetchall()
                if rows:
                    items = [
                        {
                            'id': r['doc_id'],
                            # API 字段保持原始文本语义；HTML 输出编码属于渲染端职责。
                            # 联表读取规范标题，避免返回 FTS 索引中的 CJK 插空格副本。
                            'title': r['title'],
                            'snippet': _sanitize_fts_snippet(r['snip'] or ''),
                            'score': round(-float(r['rank']), 6),
                        }
                        for r in rows
                    ]
                    return {'q': q, 'engine': 'fts5', 'items': items}
                # FTS 未命中时继续走 LIKE 兜底，提升 CJK/未分词短语的召回
            except Exception as exc:  # noqa: BLE001 —— 异常查询降级 LIKE
                logger.warning('kb FTS 查询失败，降级 LIKE：%r', exc)

    # LIKE 兜底（issue #136）：扫描必须有硬预算。
    # 旧实现 ``SELECT * WHERE … LIKE … ORDER BY pinned DESC, updated_at DESC``
    # 的 LIMIT 只封顶输出不封顶扫描——FTS 异常或 0 命中（中文查询常态，见
    # #133）都会走到这里，等于一次无界全表扫 + 全量排序。现在：
    #   1. 匹配行先在子查询里截到 _LIKE_SCAN_CAP（2000）行，排序只作用于截断集
    #   2. 截断发生时响应显式带 truncated: true（可观测）
    #   3. 切词与 FTS 用同一套 query_atoms，杜绝「FTS 与 LIKE 切分不一致」
    tokens = query_atoms(q)[:6]
    if not tokens:
        return {'q': q, 'engine': 'like', 'items': []}
    clause = ' OR '.join(['(title LIKE ? OR body LIKE ? OR tags LIKE ?)'] * len(tokens))
    args: list[str] = []
    for t in tokens:
        like = f'%{t}%'
        args.extend([like, like, like])
    matched = conn.execute(
        f'SELECT COUNT(*) FROM (SELECT 1 FROM kb_docs WHERE {clause} LIMIT ?)',
        (*args, _LIKE_SCAN_CAP + 1),
    ).fetchone()[0]
    truncated = bool(matched > _LIKE_SCAN_CAP)
    rows = conn.execute(
        f'SELECT * FROM (SELECT * FROM kb_docs WHERE {clause} LIMIT ?) '
        'ORDER BY pinned DESC, updated_at DESC LIMIT ?',
        (*args, _LIKE_SCAN_CAP, limit),
    ).fetchall()
    items = [
        {
            'id': r['id'],
            'title': r['title'],
            'snippet': _like_snippet(r['body'], q),
            # 没有相关性证据时不给分数（issue #136）：LIKE 命中与 bm25 分数
            # 不可比，旧实现恒写 1.0 会让前端把两类结果渲染成同等置信度。
            'score': None,
        }
        for r in rows
    ]
    response: dict = {'q': q, 'engine': 'like', 'items': items}
    if truncated:
        response['truncated'] = True
        response['note'] = f'LIKE 匹配超过 {_LIKE_SCAN_CAP} 行，结果基于截断集排序'
    return response


# ---------------------------------------------------------------------------
# 批量导入 / 统计
# ---------------------------------------------------------------------------


@router.post('/import')
def import_docs(payload: ImportPayload) -> dict:
    _ensure_kb_schema()
    imported, skipped = 0, 0
    for raw in payload.items[:_IMPORT_CAP]:
        # 先尝试把原始 dict 校验为 ImportItem，失败即跳过
        try:
            item = ImportItem.model_validate(raw)
        except ValidationError:
            skipped += 1
            continue
        if not item.title or not item.title.strip() or not item.body or not item.body.strip():
            skipped += 1
            continue
        try:
            _insert_doc(DocCreate(
                title=item.title, body=item.body, tags=item.tags,
                source=item.source, uri=item.uri,
            ))
            imported += 1
        except (HTTPException, ValidationError, ValueError, sqlite3.Error):
            # 坏条目（如 title 超 500 字触发 DocCreate 校验、source 非法、
            # 单条存储层错误）计入 skipped，不中断整批（06-#8）
            skipped += 1
    overflow = max(0, len(payload.items) - _IMPORT_CAP)
    return {'imported': imported, 'skipped': skipped + overflow}


@router.get('/stats')
def knowledge_stats() -> dict:
    _ensure_kb_schema()
    conn = get_conn()
    total = conn.execute('SELECT count(*) AS c FROM kb_docs').fetchone()['c']

    by_source: dict[str, int] = {}
    for r in conn.execute('SELECT source, count(*) AS c FROM kb_docs GROUP BY source').fetchall():
        by_source[r['source']] = r['c']

    tag_counts: dict[str, int] = {}
    for r in conn.execute('SELECT tags FROM kb_docs').fetchall():
        try:
            tags = json.loads(r['tags'] or '[]')
        except Exception:  # noqa: BLE001
            continue
        if isinstance(tags, list):
            for t in tags:
                t = str(t).strip()
                if t:
                    tag_counts[t] = tag_counts.get(t, 0) + 1
    by_tag_top10 = [
        {'tag': t, 'count': c}
        for t, c in sorted(tag_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    ]

    cutoff = (
        (utc_now() - timedelta(days=7))
        .replace(microsecond=0)
        .isoformat()
        .replace('+00:00', 'Z')
    )
    recent7d = conn.execute(
        'SELECT count(*) AS c FROM kb_docs WHERE created_at >= ?', (cutoff,)
    ).fetchone()['c']

    return {
        'total': total,
        'by_source': by_source,
        'by_tag_top10': by_tag_top10,
        'recent7d': recent7d,
        'engine': 'fts5' if _FTS_OK else 'like',
    }
