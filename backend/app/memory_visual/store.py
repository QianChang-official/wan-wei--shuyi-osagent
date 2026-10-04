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

"""视觉资产存储层。

图片以**原始字节**存入 ``memory_visual_assets``（BLOB），主表胶囊只挂引用
（content.asset_sha256 / content.modality='visual'），文本检索走 caption。
这与 VISTA 的 Visual 契约一致：入库即校验「声明的维度/格式与字节一致」、
拒绝动图、锚定 sha256；派生资产（裁剪件、标注图）必须声明 derived_from。

治理口径：
- 写入走既有 ``write_capsule`` 策略闸门（caption 文本过 evaluate_policy），
  图片二进制本身的校验（格式/体积/像素弹）在本层完成，失败即 422 级别拒绝；
- 资产行与胶囊同生死：``forget_capsules_in_transaction`` 调
  ``purge_assets_in_transaction`` 同步清除，``verify_deletion`` 把本表列为
  第六处取证点。
"""

from __future__ import annotations

import hashlib
import io
import uuid
from typing import Any

from ..db import get_conn, transaction
from ..memory_runtime.capsule_store import dumps, init_runtime_schema, loads, now, write_capsule

#: 单张图片字节上限（8 MiB）。超出一律拒绝——记忆资产不是图床。
MAX_VISUAL_BYTES = 8 * 1024 * 1024

#: 单边像素上限。防御像素弹（DecompressionBomb）与无界内存占用。
MAX_VISUAL_DIMENSION = 4096

#: 与 VISTA 一致的媒体类型白名单。
ALLOWED_MIME_TYPES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})

#: 证据类别（对齐 VISTA EvidenceKind）：当前观察 / 历史归档 / 派生产物。
VISUAL_KINDS = frozenset({"current", "historical", "derived"})


class VisualValidationError(ValueError):
    """图片字节未通过入库校验。路由层映射为 422。"""


def _validate_visual_bytes(data: bytes) -> dict[str, Any]:
    """校验图片字节并提取清单（sha256/尺寸/格式）。

    校验项（与 VISTA ``Visual.__post_init__`` 对齐）：
    字节非空且不超限；PIL 可解码；尺寸在白名单内；媒体类型在白名单内；
    单帧（动图必须拆成逐帧观察分别入库，否则回看语义不清）。
    """
    if type(data) is not bytes or not data:
        raise VisualValidationError("visual bytes must be non-empty bytes")
    if len(data) > MAX_VISUAL_BYTES:
        raise VisualValidationError(
            f"visual exceeds {MAX_VISUAL_BYTES} bytes"
        )
    from PIL import Image

    # 本层自行解码校验，阈值明确，不依赖 Pillow 的全局炸弹告警默认值。
    Image.MAX_IMAGE_PIXELS = MAX_VISUAL_DIMENSION * MAX_VISUAL_DIMENSION
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            mime_type = Image.MIME.get(image.format or "")
            if getattr(image, "n_frames", 1) != 1:
                raise VisualValidationError(
                    "animated images must be supplied as single-frame observations"
                )
            image.verify()
    except VisualValidationError:
        raise
    except Exception as exc:  # PIL 解码异常族不统一，统一收敛为校验错误
        raise VisualValidationError(f"undecodable visual: {type(exc).__name__}") from exc
    if mime_type not in ALLOWED_MIME_TYPES:
        raise VisualValidationError(f"unsupported media type: {mime_type or 'unknown'}")
    if not (1 <= width <= MAX_VISUAL_DIMENSION and 1 <= height <= MAX_VISUAL_DIMENSION):
        raise VisualValidationError(
            f"dimensions {width}x{height} exceed {MAX_VISUAL_DIMENSION}"
        )
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "width": width,
        "height": height,
        "mime_type": mime_type,
        "bytes": len(data),
    }


def _validate_kind(kind: str, derived_from: list[str]) -> tuple[str, list[str]]:
    """派生契约（VISTA Observation 同款）：派生必须署名来源，非派生不得署名。"""
    if kind not in VISUAL_KINDS:
        raise VisualValidationError(f"unknown visual kind: {kind}")
    derived_from = [str(item) for item in derived_from]
    if kind == "derived" and not derived_from:
        raise VisualValidationError("derived visuals must name their source assets")
    if kind != "derived" and derived_from:
        raise VisualValidationError("non-derived visuals must not carry derived_from")
    return kind, derived_from


def write_visual_capsule(
    *,
    data: bytes,
    caption: str,
    kind: str = "current",
    derived_from: list[str] | None = None,
    memory_class: str = "visual",
    source_type: str = "user_input",
    scene: str = "general",
    task_type: str = "planning",
    risk_class: str = "low",
    write_intent: str = "explicit",
    affects_future_behavior: bool = False,
    source_trust: str = "normal",
    provenance: dict[str, Any] | None = None,
    soul_id: str | None = None,
    owner_id: str | None = None,
) -> dict[str, Any]:
    """写入一条视觉记忆：策略闸门 + 胶囊主表 + 资产 BLOB + 账本，一次闭环。

    顺序说明：先 ``write_capsule``（出 capsule_id 与闸门裁决），再同事务落
    资产行 + ``visual_attach`` 账目。闸门 reject 时不落资产行（内容未入库，
    与文本写入的 reject 语义一致）。资产落库若意外失败，立即软删刚写入的
    胶囊，避免主表残留一条指向不存在资产的视觉记忆。
    """
    init_runtime_schema()
    manifest = _validate_visual_bytes(data)
    kind, derived_from = _validate_kind(kind, list(derived_from or ()))
    if not isinstance(caption, str) or not caption.strip():
        raise VisualValidationError("caption must be a non-empty string")
    if len(caption) > 4096:
        raise VisualValidationError("caption exceeds 4096 chars")
    for source_id in derived_from:
        if get_asset(source_id) is None:
            raise VisualValidationError(f"derived_from asset not found: {source_id}")

    result = write_capsule(
        memory_class=memory_class,
        content={
            "modality": "visual",
            "text": caption.strip(),
            "asset_sha256": manifest["sha256"],
            "width": manifest["width"],
            "height": manifest["height"],
            "mime_type": manifest["mime_type"],
            "visual_kind": kind,
        },
        source_type=source_type,
        scene=scene,
        task_type=task_type,
        risk_class=risk_class,
        write_intent=write_intent,
        affects_future_behavior=affects_future_behavior,
        source_trust=source_trust,
        provenance=provenance,
        soul_id=soul_id,
        owner_id=owner_id,
    )
    capsule_id = result["capsule_id"]
    if (result.get("governance") or {}).get("policy_result") == "reject":
        return {**result, "asset": None, "visual_manifest": manifest}

    asset_id = "vas_" + uuid.uuid4().hex[:12]
    created = now()
    # 仅 active（闸门放行）的视觉记忆进语义索引；candidate/quarantined 的
    # 索引补写挂在 lifecycle 的确认/放行路径上（与文本 FTS 同口径）。
    lifecycle_state = (result.get("state") or {}).get("lifecycle")
    vector = None
    if lifecycle_state == "active":
        from .embedding import embed_image

        vector = embed_image(data)
    try:
        from ..memoryos.governance import append_ledger_in_transaction

        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO memory_visual_assets (
                    asset_id, capsule_id, sha256, width, height, mime_type,
                    kind, derived_from, data, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    asset_id, capsule_id, manifest["sha256"], manifest["width"],
                    manifest["height"], manifest["mime_type"], kind,
                    dumps(derived_from), data, created,
                ),
            )
            if vector is not None:
                from .embedding import store_vector_in_transaction

                store_vector_in_transaction(
                    conn, asset_id, capsule_id, vector,
                    owner_id=owner_id, soul_id=soul_id, ts=created,
                )
            append_ledger_in_transaction(
                conn,
                op_type="visual_attach",
                capsule_id=capsule_id,
                actor="runtime",
                after_content=manifest["sha256"],
                after_state=(result.get("state") or {}).get("lifecycle"),
                reason=f"visual:{kind}:{manifest['mime_type']}",
                risk_class=risk_class,
                owner_id=owner_id,
                soul_id=soul_id,
            )
    except Exception:
        # 资产落库失败时胶囊已无意义，立即软删保持「胶囊⇔资产」一一对应。
        from ..memory_runtime.capsule_store import forget_capsules

        forget_capsules([capsule_id], mode="soft_delete", owner_id=owner_id, soul_id=soul_id)
        raise
    return {
        **result,
        "asset": {
            "asset_id": asset_id,
            "kind": kind,
            "derived_from": derived_from,
            **manifest,
        },
    }


def get_asset(asset_id: str) -> dict[str, Any] | None:
    """取资产行（含字节，derived_from 已解析为 list）。清单场景请用
    list_assets，别把 BLOB 拖出来。"""
    row = get_conn().execute(
        "SELECT * FROM memory_visual_assets WHERE asset_id=?",
        (asset_id,),
    ).fetchone()
    if not row:
        return None
    asset = dict(row)
    asset["derived_from"] = loads(asset["derived_from"], [])
    return asset


def read_asset_bytes(asset_id: str) -> dict[str, Any] | None:
    """取资产字节与清单，供 inspect/read_pixels 回看。"""
    return get_asset(asset_id)


def list_assets(capsule_id: str) -> list[dict[str, Any]]:
    """列出一个胶囊的全部视觉资产清单（不含字节）。"""
    rows = get_conn().execute(
        "SELECT asset_id, capsule_id, sha256, width, height, mime_type, kind, "
        "derived_from, length(data) AS bytes, created_at "
        "FROM memory_visual_assets WHERE capsule_id=? ORDER BY created_at",
        (capsule_id,),
    ).fetchall()
    return [
        {**dict(row), "derived_from": loads(row["derived_from"], [])}
        for row in rows
    ]


def purge_assets_in_transaction(conn, capsule_ids: list[str]) -> int:
    """在调用方事务内清除视觉资产及其语义向量（遗忘/删除闭环的一环）。

    老库可能没有这两张表（表由 init_db 创建），缺失时按 0 处理而不是炸掉
    整个删除事务——与 verify_deletion 的防御口径一致。
    """
    if not capsule_ids:
        return 0
    from .embedding import purge_vectors_in_transaction

    purge_vectors_in_transaction(conn, capsule_ids)
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='memory_visual_assets'"
    ).fetchone()
    if not exists:
        return 0
    placeholders = ",".join("?" for _ in capsule_ids)
    cursor = conn.execute(
        f"DELETE FROM memory_visual_assets WHERE capsule_id IN ({placeholders})",
        list(capsule_ids),
    )
    return cursor.rowcount
