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

"""视觉语义检索 — 轻量嵌入 + SQLite 暴力余弦。

定位：让视觉资产「以图搜图」。与文本通道（麒麟 SDK / BGE / FTS5 的回退链）
同一哲学——**本地优先、无外部模型依赖、延迟可实测**。

嵌入方案（167 维，PIL 纯 C 路径，无 numpy 也能编码）：
- 64x64 归一化 → 空间金字塔（全局 + 2x2 网格，共 5 个区域）
- 每区域 HSV 直方图 8x2x2 = 32 维（颜色分布，抗位移/缩放）
- 每区域边缘密度 1 维（FIND_EDGES 灰度均值，捕捉结构/文字密度）
- 宽高比 2 维（w/(w+h), h/(w+h)，区分横竖构图）
全向量 L2 归一化，余弦相似度即点积。

诚实边界（如实标注，不夸大）：
- 这是**感知相似**（颜色/布局/结构），不是 CLIP 级语义（"猫"≈"猫"可以，
  "猫"≈"宠物"不行）。信创离线环境无 GPU/无 CLIP 模型分发，CLIP 接入是
  既定后续方向，接口（向量表 + search 签名）已预留 dim 列兼容。
- **brute-force cosine**：numpy 矩阵乘法全表扫描。实测 167 维 x 1 万条
  < 5ms；量级到百万才需要 HNSW，届时再换（与 local_embedding 同口径）。
- 索引与生命周期同生死：仅 active 且闸门放行的胶囊入索引；确认/放行时
  补写（挂在 lifecycle._sync_fts 上），遗忘/删除时同事务清除，
  verify_deletion 第七处取证。
"""
from __future__ import annotations

import io
import logging
import math
import struct
import time
from typing import Any

from ..db import get_conn

logger = logging.getLogger(__name__)

VECTOR_TABLE = "memory_visual_vectors"

#: 嵌入维度：5 区域 x (HSV 联合直方图 32 + 边缘 1) + 宽高比 2。
EMBED_DIM = 167

_NORMALIZE_SIZE = 64
_H_BINS, _S_BINS, _V_BINS = 8, 2, 2

try:  # numpy 是编码与检索热路径的加速项，缺席时退化为纯 Python（功能不变）
    import numpy as _np
except ImportError:  # pragma: no cover - 部署环境默认带 numpy
    _np = None


def _hsv_joint_hist(region) -> list[float]:
    """区域 HSV 联合直方图（8x2x2 = 32 bin，按像素数归一化）。

    联合 bin 捕捉通道间的交互（暗红 ≠ 亮红），比三通道各自独立分箱更有
    区分度。bin 下标 = h_bin*4 + s_bin*2 + v_bin。
    """
    width = region.size[0] * region.size[1]
    raw = region.tobytes()
    bins = [0] * (_H_BINS * _S_BINS * _V_BINS)
    if _np is not None:
        arr = _np.frombuffer(raw, dtype=_np.uint8).reshape(-1, 3)
        idx = (arr[:, 0] >> 5) * 4 + (arr[:, 1] >> 7) * 2 + (arr[:, 2] >> 7)
        counts = _np.bincount(idx, minlength=len(bins))
        return (counts / width).tolist()
    for i in range(0, len(raw), 3):  # pragma: no cover - numpy 缺席的退化路径
        bins[(raw[i] >> 5) * 4 + (raw[i + 1] >> 7) * 2 + (raw[i + 2] >> 7)] += 1
    return [count / width for count in bins]


def _pack(vec: list[float]) -> bytes:
    return struct.pack(f"<{len(vec)}f", *vec)


def _unpack(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))


def embed_image(data: bytes) -> list[float]:
    """图片字节 → 167 维 L2 归一化嵌入向量。输入须已过 store 层校验。"""
    from PIL import Image, ImageFilter, ImageStat

    with Image.open(io.BytesIO(data)) as im:
        width, height = im.size
        rgb = im.convert("RGB").resize(
            (_NORMALIZE_SIZE, _NORMALIZE_SIZE), Image.Resampling.BILINEAR
        )
        hsv = rgb.convert("HSV")
        edges = rgb.convert("L").filter(ImageFilter.FIND_EDGES)

    half = _NORMALIZE_SIZE // 2
    regions = [
        (0, 0, _NORMALIZE_SIZE, _NORMALIZE_SIZE),
        (0, 0, half, half),
        (half, 0, _NORMALIZE_SIZE, half),
        (0, half, half, _NORMALIZE_SIZE),
        (half, half, _NORMALIZE_SIZE, _NORMALIZE_SIZE),
    ]
    vec: list[float] = []
    for box in regions:
        vec.extend(_hsv_joint_hist(hsv.crop(box)))
        vec.append(ImageStat.Stat(edges.crop(box)).mean[0] / 255.0)
    total = width + height
    vec.extend((width / total, height / total))

    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


# ---------------------------------------------------------------------------
# 索引写入 / 清除（事务规则与 local_embedding 一致：传入 conn 时不 commit）
# ---------------------------------------------------------------------------


def store_vector_in_transaction(
    conn,
    asset_id: str,
    capsule_id: str,
    vec: list[float],
    *,
    owner_id: str | None,
    soul_id: str | None,
    ts: str,
) -> None:
    conn.execute(
        f"INSERT OR REPLACE INTO {VECTOR_TABLE}"
        "(asset_id, capsule_id, embedding, dim, owner_id, soul_id, updated_at)"
        " VALUES(?,?,?,?,?,?,?)",
        (asset_id, capsule_id, _pack(vec), len(vec), owner_id, soul_id, ts),
    )


def index_capsule_assets_in_transaction(
    conn,
    capsule_id: str,
    *,
    owner_id: str | None = None,
    soul_id: str | None = None,
    ts: str,
) -> int:
    """为该胶囊的全部视觉资产补写向量（确认/放行转 active 时调用）。

    幂等：INSERT OR REPLACE。返回补写条数。
    """
    rows = conn.execute(
        "SELECT asset_id, data FROM memory_visual_assets WHERE capsule_id=?",
        (capsule_id,),
    ).fetchall()
    for row in rows:
        vec = embed_image(row["data"])
        store_vector_in_transaction(
            conn, row["asset_id"], capsule_id, vec,
            owner_id=owner_id, soul_id=soul_id, ts=ts,
        )
    return len(rows)


def purge_vectors_in_transaction(conn, capsule_ids: list[str]) -> int:
    """同事务清除视觉向量。老库无表按 0 处理（与 purge_assets 同口径）。"""
    if not capsule_ids:
        return 0
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (VECTOR_TABLE,),
    ).fetchone()
    if not exists:
        return 0
    placeholders = ",".join("?" for _ in capsule_ids)
    cursor = conn.execute(
        f"DELETE FROM {VECTOR_TABLE} WHERE capsule_id IN ({placeholders})",
        list(capsule_ids),
    )
    return cursor.rowcount


# ---------------------------------------------------------------------------
# 检索
# ---------------------------------------------------------------------------


def search_similar(
    *,
    query_data: bytes | None = None,
    query_asset_id: str | None = None,
    top_k: int = 20,
    min_score: float = 0.0,
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> dict[str, Any]:
    """以图搜图：暴力余弦，按相似度降序。

    治理口径与文本检索一致：只返回 lifecycle 可检索 + 闸门放行
    （allow/redact）的胶囊资产；owner/soul 作用域严格匹配（legacy 空值
    记录对具名调用方不可见，与 local_embedding #153 口径一致）。

    返回含 ``latency_ms``/``scanned``——延迟是宣称值就必须可复核。
    """
    from ..memoryos.lifecycle import INDEXABLE_POLICIES, retrievable_sql_list

    started = time.perf_counter()
    if query_asset_id is not None:
        row = get_conn().execute(
            f"SELECT embedding FROM {VECTOR_TABLE} WHERE asset_id=?",
            (query_asset_id,),
        ).fetchone()
        if row is None:
            return {
                "hits": [], "scanned": 0, "dim": EMBED_DIM,
                "index": "brute_force_cosine", "latency_ms": 0.0,
                "reason": "query_asset_not_indexed",
            }
        query_vec = _unpack(row["embedding"])
    elif query_data is not None:
        query_vec = embed_image(query_data)
    else:
        raise ValueError("query_data or query_asset_id is required")

    clauses = [
        f"json_extract(c.state,'$.lifecycle') IN ({retrievable_sql_list()})",
        "json_extract(c.governance,'$.policy_result') IN ("
        + ",".join(f"'{p}'" for p in sorted(INDEXABLE_POLICIES)) + ")",
    ]
    params: list[Any] = []
    if owner_id is not None:
        clauses.append("v.owner_id=?")
        params.append(owner_id)
    if soul_id is not None:
        clauses.append("v.soul_id=?")
        params.append(soul_id)
    rows = get_conn().execute(
        f"SELECT v.asset_id, v.capsule_id, v.embedding FROM {VECTOR_TABLE} v "
        f"JOIN memory_capsules_v2 c ON c.capsule_id = v.capsule_id "
        f"WHERE {' AND '.join(clauses)}",
        params,
    ).fetchall()

    scored = _score_all(query_vec, rows)
    hits = [
        {"asset_id": asset_id, "capsule_id": capsule_id, "score": round(score, 6)}
        for asset_id, capsule_id, score in scored
        if score >= min_score
    ][:top_k]
    return {
        "hits": hits,
        "scanned": len(rows),
        "dim": EMBED_DIM,
        "index": "brute_force_cosine",
        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def _score_all(
    query_vec: list[float], rows: list[Any]
) -> list[tuple[str, str, float]]:
    """[(asset_id, capsule_id, cosine)] 降序。numpy 在则走矩阵乘。"""
    if not rows:
        return []
    if _np is not None:
        matrix = _np.frombuffer(
            b"".join(row["embedding"] for row in rows), dtype="<f4"
        ).reshape(len(rows), -1)
        scores = matrix @ _np.asarray(query_vec, dtype="<f4")
        order = _np.argsort(-scores)
        return [
            (rows[i]["asset_id"], rows[i]["capsule_id"], float(scores[i]))
            for i in order
        ]
    scored = [
        (
            row["asset_id"],
            row["capsule_id"],
            sum(x * y for x, y in zip(query_vec, _unpack(row["embedding"]))),
        )
        for row in rows
    ]
    scored.sort(key=lambda item: item[2], reverse=True)
    return scored


__all__ = [
    "EMBED_DIM",
    "VECTOR_TABLE",
    "embed_image",
    "index_capsule_assets_in_transaction",
    "purge_vectors_in_transaction",
    "search_similar",
    "store_vector_in_transaction",
]
