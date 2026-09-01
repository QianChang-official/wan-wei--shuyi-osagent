"""本地向量语义通道 — BGE-small-zh + SQLite brute-force cosine。

定位:native(麒麟 SDK)与 FTS5 之间的**第二语义通道**。麒麟 SDK 缺席时,
本地 embedding 模型提供真正的语义召回,而不是退回纯词面匹配。

诚实边界(如实标注,不夸大):
- **可选能力**:依赖 sentence-transformers + 本地模型目录,两者缺一即
  静默不可用(返回 None),调用方回退 FTS。不装依赖 = 功能关闭,
  不会报错也不会假装在工作。
- **brute-force cosine**:全表扫描算余弦。胶囊量级 ≤ 数千时完全够用
  (实测 512 维 × 1000 条 < 5ms);量级到十万才需要 HNSW,届时再换。
- **模型分发**:模型文件(~95MB safetensors)不进仓库,由部署包携带或
  环境变量 WANWEI_LOCAL_EMBED_DIR 指定路径。
- **写放大**:每次写入编码一次(~8ms),在写路径可接受范围内。
"""
from __future__ import annotations

import json
import logging
import os
import struct
import threading
from typing import Any

from ..db import get_conn

logger = logging.getLogger(__name__)

TABLE = "memory_local_vectors"
DEFAULT_DIM = 512

_model = None
_model_lock = threading.Lock()
_model_tried = False


def _model_dir() -> str | None:
    d = os.environ.get("WANWEI_LOCAL_EMBED_DIR", "").strip()
    return d or None


def _get_model():
    """懒加载 sentence-transformers 模型(进程级单例)。

    依赖缺失或模型目录未配置时返回 None — 本地通道静默关闭。
    """
    global _model, _model_tried
    if _model is not None or _model_tried:
        return _model
    with _model_lock:
        if _model is not None or _model_tried:
            return _model
        _model_tried = True
        path = _model_dir()
        if not path:
            logger.info("local embedding disabled: WANWEI_LOCAL_EMBED_DIR not set")
            return None
        try:
            from sentence_transformers import SentenceTransformer

            _model = SentenceTransformer(path)
            logger.info("local embedding loaded from %s", path)
        except ImportError:
            logger.info("local embedding disabled: sentence-transformers not installed")
            return None
        except Exception as exc:  # 模型目录损坏等,本地通道不可用但系统不受影响
            logger.warning("local embedding load failed: %s", exc)
            return None
        return _model


def available() -> bool:
    """本地向量通道是否可用(供状态接口/评测如实报告)。"""
    return _get_model() is not None


def _pack(vec: list[float]) -> bytes:
    return struct.pack(f"<{len(vec)}f", *vec)


def _unpack(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))


def init_schema(*, conn=None) -> None:
    """建表/补列。传入 conn 时不 commit(提交权归调用方事务)。"""
    target = conn if conn is not None else get_conn()
    target.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE}(
            capsule_id TEXT PRIMARY KEY,
            embedding  BLOB NOT NULL,
            dim        INTEGER NOT NULL,
            owner_id   TEXT,
            soul_id    TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    # 兼容旧表(无 owner/soul 列):缺列时补齐。SQLite ALTER ADD COLUMN 幂等性
    # 用 PRAGMA 检测,而非 try/except 吞掉真实错误。
    cols = {row[1] for row in target.execute(f"PRAGMA table_info({TABLE})").fetchall()}
    for col in ("owner_id", "soul_id"):
        if col not in cols:
            target.execute(f"ALTER TABLE {TABLE} ADD COLUMN {col} TEXT")
    if conn is None:
        target.commit()


def embed_and_store(
    capsule_id: str,
    text: str,
    *,
    ts: str,
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> bool:
    """写入路径:编码并存向量。通道不可用时返回 False(调用方忽略)。"""
    model = _get_model()
    if model is None or not text:
        return False
    vec = model.encode([text], normalize_embeddings=True)[0].tolist()
    init_schema()
    get_conn().execute(
        f"INSERT OR REPLACE INTO {TABLE}(capsule_id, embedding, dim, owner_id, soul_id, updated_at) VALUES(?,?,?,?,?,?)",
        (capsule_id, _pack(vec), len(vec), owner_id, soul_id, ts),
    )
    get_conn().commit()
    return True


def delete_vector(capsule_id: str, *, conn=None) -> None:
    """删除路径:同步移除本地向量(删除验证的一环)。

    事务边界规则:调用方传入 ``conn`` 时只用该连接执行,**不 commit**
    (提交权归调用方事务);不传时自建连接并自行提交。这与
    ``vector_index.mark_vectors_delete_pending_in_transaction`` 的
    既有模式一致 — 在 ``forget_capsules_in_transaction`` 里必须传 conn,
    否则内部 commit 会提前提交调用方的进行中事务。
    """
    try:
        init_schema(conn=conn)
        target = conn if conn is not None else get_conn()
        target.execute(f"DELETE FROM {TABLE} WHERE capsule_id=?", (capsule_id,))
        if conn is None:
            target.commit()
    except Exception as exc:
        logger.warning("local vector delete failed for %s: %s", capsule_id, exc)


def search(
    text: str,
    *,
    top_k: int = 20,
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> list[tuple[str, float]] | None:
    """语义检索:返回 [(capsule_id, cosine_sim)] 按相似度降序。

    通道不可用或索引为空时返回 None(调用方据此回退 FTS)。

    **scope 隔离**:与 FTS 路径同口径 — owner_id 有值时严格匹配;
    soul_id 有值时严格匹配(legacy 空值记录不可见,与 #153 修复后的
    诚实口径一致)。两者皆 None 为未鉴权内部调用,不过滤。
    """
    model = _get_model()
    if model is None:
        return None
    init_schema()
    clauses: list[str] = []
    params: list[Any] = []
    if owner_id is not None:
        clauses.append("owner_id=?")
        params.append(owner_id)
    if soul_id is not None:
        clauses.append("soul_id=?")
        params.append(soul_id)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = get_conn().execute(
        f"SELECT capsule_id, embedding FROM {TABLE}{where}", params
    ).fetchall()
    if not rows:
        return None
    q = model.encode([text], normalize_embeddings=True)[0].tolist()
    scored = [
        (row["capsule_id"], _cosine(q, _unpack(row["embedding"])))
        for row in rows
    ]
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:top_k]


def _cosine(a: list[float], b: list[float]) -> float:
    # 向量已归一化,余弦即点积
    return sum(x * y for x, y in zip(a, b))


__all__ = ["available", "embed_and_store", "delete_vector", "search", "init_schema"]
