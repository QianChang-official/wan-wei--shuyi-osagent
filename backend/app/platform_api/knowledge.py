"""B5 知识舱：内置知识库（SQLite FTS5 全文检索）。

契约（前后端已钉死）：
- 文档 CRUD：GET/POST /knowledge/docs，GET/PUT/DELETE /knowledge/docs/{did}
  字段：id, title, body, tags[], source('manual'|'web'|'chat'|'file'),
        uri?, created_at, updated_at, pinned
- 检索：GET /knowledge/search?q=&limit= → FTS5 命中
  [{id,title,snippet(<b> 高亮),score}]；q 为空返回最新 20 条。
  FTS 不可用时回退 LIKE 并标注 engine='like'。
- 批量导入：POST /knowledge/import {items:[...]} → {imported, skipped}
- 统计：GET /knowledge/stats → {total, by_source, by_tag_top10, recent7d}

存储说明：复用 app.db 的线程本地连接；独立表 kb_docs / kb_fts，
不与记忆胶囊等既有表混用。FTS5 缺失（极少见的精简 SQLite 构建）时
全模块自动降级为 LIKE 检索，接口形状保持不变。
"""
from __future__ import annotations

import html
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.db import get_conn

router = APIRouter(prefix='/knowledge', tags=['knowledge'])

SOURCES = ('manual', 'web', 'chat', 'file')
_IMPORT_CAP = 500

# ---------------------------------------------------------------------------
# 建表与 FTS5 可用性探测（模块导入时执行一次）
# ---------------------------------------------------------------------------

_FTS_OK = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _init_schema() -> None:
    global _FTS_OK
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
    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS kb_fts USING fts5(
                doc_id UNINDEXED, title, body, tags,
                tokenize = 'unicode61'
            )
            """
        )
        # 空 MATCH 探测一次，确认 fts5 真正可用而非仅语法通过
        conn.execute("SELECT count(*) FROM kb_fts WHERE kb_fts MATCH '\"__probe__\"'").fetchone()
        _FTS_OK = True
    except Exception as exc:  # noqa: BLE001 —— FTS5 缺失时降级 LIKE
        print(f'[knowledge] FTS5 不可用，检索降级为 LIKE：{exc!r}')
        _FTS_OK = False
    conn.commit()


_init_schema()


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
        (doc['id'], doc['title'], doc['body'], ' '.join(doc['tags'])),
    )


def _fts_delete(conn: Any, did: str) -> None:
    if not _FTS_OK:
        return
    conn.execute('DELETE FROM kb_fts WHERE doc_id = ?', (did,))


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class DocCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    body: str = Field(..., min_length=1)
    tags: list[str] = Field(default_factory=list)
    source: str = 'manual'
    uri: Optional[str] = None
    pinned: bool = False


class DocUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=500)
    body: Optional[str] = Field(default=None, min_length=1)
    tags: Optional[list[str]] = None
    source: Optional[str] = None
    uri: Optional[str] = None
    pinned: Optional[bool] = None


class ImportItem(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    source: str = 'manual'
    uri: Optional[str] = None


class ImportPayload(BaseModel):
    items: list[ImportItem] = Field(default_factory=list)


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
    conn = get_conn()
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
    conn.commit()
    return doc


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.get('/docs')
def list_docs(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    source: Optional[str] = None,
) -> dict:
    conn = get_conn()
    where, args = '', []
    if source:
        where, args = 'WHERE source = ?', [source]
    total = conn.execute(f'SELECT count(*) AS c FROM kb_docs {where}', args).fetchone()['c']
    rows = conn.execute(
        f'SELECT * FROM kb_docs {where} ORDER BY pinned DESC, updated_at DESC LIMIT ? OFFSET ?',
        (*args, limit, offset),
    ).fetchall()
    return {'items': [_row_to_doc(r) for r in rows], 'total': total, 'limit': limit, 'offset': offset}


@router.post('/docs', status_code=201)
def create_doc(payload: DocCreate) -> dict:
    return _insert_doc(payload)


@router.get('/docs/{did}')
def get_doc(did: str) -> dict:
    row = _get_row(did)
    if row is None:
        raise HTTPException(status_code=404, detail=f'知识文档不存在：{did}')
    return _row_to_doc(row)


@router.put('/docs/{did}')
def update_doc(did: str, payload: DocUpdate) -> dict:
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

    conn = get_conn()
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
    conn.commit()
    return doc


@router.delete('/docs/{did}')
def delete_doc(did: str) -> dict:
    if _get_row(did) is None:
        raise HTTPException(status_code=404, detail=f'知识文档不存在：{did}')
    conn = get_conn()
    conn.execute('DELETE FROM kb_docs WHERE id = ?', (did,))
    _fts_delete(conn, did)
    conn.commit()
    return {'deleted': True, 'id': did}


# ---------------------------------------------------------------------------
# 检索（FTS5 优先，LIKE 兜底）
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r'[\w一-鿿]+', re.UNICODE)


def _fts_query(q: str) -> str:
    """把用户输入清洗成安全的 FTS5 MATCH 表达式（逐词加引号，OR 连接）。"""
    tokens = _TOKEN_RE.findall(q)
    return ' OR '.join(f'"{t}"' for t in tokens[:12])


def _like_snippet(body: str, q: str, width: int = 120) -> str:
    tokens = _TOKEN_RE.findall(q)
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


@router.get('/search')
def search_docs(
    q: str = Query(default=''),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
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
                    SELECT doc_id, title,
                           snippet(kb_fts, 2, '<b>', '</b>', '…', 24) AS snip,
                           bm25(kb_fts) AS rank
                    FROM kb_fts
                    WHERE kb_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (fts_q, limit),
                ).fetchall()
                items = [
                    {
                        'id': r['doc_id'], 'title': r['title'],
                        'snippet': r['snip'] or '',
                        'score': round(-float(r['rank']), 6),
                    }
                    for r in rows
                ]
                return {'q': q, 'engine': 'fts5', 'items': items}
            except Exception as exc:  # noqa: BLE001 —— 异常查询降级 LIKE
                print(f'[knowledge] FTS 查询失败，降级 LIKE：{exc!r}')

    tokens = _TOKEN_RE.findall(q)
    if not tokens:
        return {'q': q, 'engine': 'like', 'items': []}
    clause = ' OR '.join(['(title LIKE ? OR body LIKE ? OR tags LIKE ?)'] * len(tokens[:6]))
    args: list[str] = []
    for t in tokens[:6]:
        like = f'%{t}%'
        args.extend([like, like, like])
    rows = conn.execute(
        f'SELECT * FROM kb_docs WHERE {clause} ORDER BY pinned DESC, updated_at DESC LIMIT ?',
        (*args, limit),
    ).fetchall()
    items = [
        {
            'id': r['id'], 'title': r['title'],
            'snippet': _like_snippet(r['body'], q),
            'score': 1.0,
        }
        for r in rows
    ]
    return {'q': q, 'engine': 'like', 'items': items}


# ---------------------------------------------------------------------------
# 批量导入 / 统计
# ---------------------------------------------------------------------------


@router.post('/import')
def import_docs(payload: ImportPayload) -> dict:
    imported, skipped = 0, 0
    for item in payload.items[:_IMPORT_CAP]:
        if not item.title or not item.title.strip() or not item.body or not item.body.strip():
            skipped += 1
            continue
        try:
            _insert_doc(DocCreate(
                title=item.title, body=item.body, tags=item.tags,
                source=item.source, uri=item.uri,
            ))
            imported += 1
        except HTTPException:
            skipped += 1
    overflow = max(0, len(payload.items) - _IMPORT_CAP)
    return {'imported': imported, 'skipped': skipped + overflow}


@router.get('/stats')
def knowledge_stats() -> dict:
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

    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec='seconds')
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
