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

"""视觉回看：对已归档的视觉资产做区域检查与像素采样。

算法移植自 VISTA（https://github.com/joshhhhhan/VISTA,
src/vista/core/session.py 的 ``_inspection_view`` / ``_pixel_readout_view``），
并按本项目语义做了三处适配：

1. 坐标系：VISTA 面向固定 1024x1024 显示面，本项目的归档图片尺寸任意，
   region 坐标直接取**源图像素坐标**，校验范围为该图实际宽高；
2. 调色板：VISTA 的符号调色板挂在会话上跨调用累积，本项目 API 无会话态，
   调色板按**单次调用**构建，响应自带完整 palette 即可自解释；
3. 存储：帧来自 ``memory_visual_assets`` BLOB 而不是 frames_dir 文件。

回看是只读操作：不触碰胶囊状态、不记 usage（检索记账有自己的
60 秒时间窗口径，回看不算一次召回）。
"""

from __future__ import annotations

import base64
import io
from typing import Any

from .store import read_asset_bytes

#: 与 VISTA 对齐的调用上限。
MAX_INSPECTION_VIEWS = 16
MAX_INSPECTION_LABEL_CHARS = 128
MAX_INSPECTION_QUESTION_CHARS = 1024
MAX_PIXEL_READOUT_VIEWS = 64
MAX_PIXEL_READOUT_SAMPLES = 4096

#: 区域裁剪后的放大目标边长（最近邻、无平滑，对齐 VISTA）。
DEFAULT_DISPLAY_SIZE = 1024

PIXEL_READOUT_SYMBOLS = (
    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_"
)


class InspectionError(ValueError):
    """回看请求非法（越界区域、未知资产等）。路由层映射为 422/404。"""


def _parse_region(value: Any, width: int, height: int) -> tuple[int, int, int, int]:
    """region 缺省为全图；坐标必须在源图范围内。"""
    if value is None:
        return 0, 0, width, height
    if not isinstance(value, dict) or set(value) != {"x", "y", "width", "height"}:
        raise InspectionError("invalid region")
    x, y, w, h = value["x"], value["y"], value["width"], value["height"]
    if any(type(item) is not int for item in (x, y, w, h)):
        raise InspectionError("invalid region")
    if x < 0 or y < 0 or w < 1 or h < 1 or x + w > width or y + h > height:
        raise InspectionError("region out of bounds")
    return x, y, w, h


def _load_asset(asset_id: str) -> dict[str, Any]:
    asset = read_asset_bytes(asset_id)
    if asset is None:
        raise InspectionError(f"asset not found: {asset_id}")
    return asset


def _validate_view_common(view: Any, index: int) -> dict[str, Any]:
    if (
        not isinstance(view, dict)
        or not isinstance(view.get("label"), str)
        or not view["label"].strip()
        or len(view["label"]) > MAX_INSPECTION_LABEL_CHARS
        or not isinstance(view.get("asset_id"), str)
        or not view["asset_id"]
        or set(view) - {"label", "asset_id", "region", "rows", "columns"}
    ):
        raise InspectionError(f"view {index}: invalid selection")
    return view


def inspect_views(
    *,
    question: str,
    views: list[dict[str, Any]],
    display_size: int = DEFAULT_DISPLAY_SIZE,
) -> dict[str, Any]:
    """回看一个或多个归档视觉资产，可选矩形区域，裁剪后最近邻放大。

    返回 ``views`` 元数据（请求序）+ ``images``（base64 PNG，与 views 对齐）。
    """
    if (
        not isinstance(question, str)
        or not question.strip()
        or len(question) > MAX_INSPECTION_QUESTION_CHARS
    ):
        raise InspectionError("invalid question")
    if not isinstance(views, list) or not 1 <= len(views) <= MAX_INSPECTION_VIEWS:
        raise InspectionError(
            f"views must contain 1..{MAX_INSPECTION_VIEWS} selections"
        )
    if type(display_size) is not int or display_size < 1:
        raise InspectionError("display_size must be a positive integer")

    from PIL import Image

    metadata_views: list[dict[str, Any]] = []
    images: list[dict[str, Any]] = []
    for index, view in enumerate(views, start=1):
        view = _validate_view_common(view, index)
        asset = _load_asset(view["asset_id"])
        x, y, w, h = _parse_region(
            view.get("region"), asset["width"], asset["height"]
        )
        try:
            with Image.open(io.BytesIO(asset["data"])) as archived:
                visual = archived.convert("RGB").crop((x, y, x + w, y + h))
            longest_side = max(w, h)
            rendered = (w * display_size // longest_side,
                        h * display_size // longest_side)
            if rendered != visual.size:
                visual = visual.resize(rendered, Image.Resampling.NEAREST)
            output = io.BytesIO()
            visual.save(output, format="PNG")
        except InspectionError:
            raise
        except Exception as exc:
            raise InspectionError(
                f"view {index}: archived visual could not be rendered"
            ) from exc
        metadata_views.append({
            "index": index,
            "label": view["label"],
            "asset_id": view["asset_id"],
            "capsule_id": asset["capsule_id"],
            "sha256": asset["sha256"],
            "region": {"x": x, "y": y, "width": w, "height": h},
            "image_size": {"width": visual.width, "height": visual.height},
        })
        images.append({
            "mime_type": "image/png",
            "data": base64.b64encode(output.getvalue()).decode("ascii"),
        })
    return {
        "visual_kind": "inspection",
        "question": question.strip(),
        "view_count": len(metadata_views),
        "views": metadata_views,
        "images": images,
    }


def read_pixels(
    *,
    question: str,
    views: list[dict[str, Any]],
) -> dict[str, Any]:
    """等分网格中心采样：region 划为 rows x columns，取每格中心像素。

    返回一个 RGB 符号调色板 + 每个视图的紧凑行字符串（VISTA 同款编码），
    模型无需视觉通道也能对颜色做精确比对。只测量，不解释。
    """
    if (
        not isinstance(question, str)
        or not question.strip()
        or len(question) > MAX_INSPECTION_QUESTION_CHARS
    ):
        raise InspectionError("invalid question")
    if not isinstance(views, list) or not 1 <= len(views) <= MAX_PIXEL_READOUT_VIEWS:
        raise InspectionError(
            f"views must contain 1..{MAX_PIXEL_READOUT_VIEWS} selections"
        )

    from PIL import Image

    sampled: list[tuple[dict[str, Any], list[list[tuple[int, int, int]]]]] = []
    total_samples = 0
    for index, view in enumerate(views, start=1):
        view = _validate_view_common(view, index)
        rows, columns = view.get("rows"), view.get("columns")
        asset = _load_asset(view["asset_id"])
        if (
            type(rows) is not int
            or type(columns) is not int
            or not 1 <= rows <= asset["height"]
            or not 1 <= columns <= asset["width"]
        ):
            raise InspectionError(f"view {index}: invalid sample dimensions")
        x, y, w, h = _parse_region(
            view.get("region"), asset["width"], asset["height"]
        )
        total_samples += rows * columns
        if total_samples > MAX_PIXEL_READOUT_SAMPLES:
            raise InspectionError(
                f"at most {MAX_PIXEL_READOUT_SAMPLES} samples per call"
            )
        sample_x = [x + ((2 * c + 1) * w) // (2 * columns) for c in range(columns)]
        sample_y = [y + ((2 * r + 1) * h) // (2 * rows) for r in range(rows)]
        try:
            with Image.open(io.BytesIO(asset["data"])) as archived:
                pixels = archived.convert("RGB").load()
                samples = [[pixels[sx, sy] for sx in sample_x] for sy in sample_y]
        except Exception as exc:
            raise InspectionError(
                f"view {index}: archived visual could not be sampled"
            ) from exc
        sampled.append(
            (
                {
                    "index": index,
                    "label": view["label"],
                    "asset_id": view["asset_id"],
                    "capsule_id": asset["capsule_id"],
                    "sha256": asset["sha256"],
                    "region": {"x": x, "y": y, "width": w, "height": h},
                    "rows": rows,
                    "columns": columns,
                },
                samples,
            )
        )

    # 单次调用内构建调色板：颜色 → 符号，响应自带映射即可独立解读。
    colors = {color for _, rows_ in sampled for row in rows_ for color in row}
    if len(colors) > len(PIXEL_READOUT_SYMBOLS):
        raise InspectionError("pixel readout color limit reached")
    symbol_by_color = {
        color: PIXEL_READOUT_SYMBOLS[i] for i, color in enumerate(sorted(colors))
    }
    palette = {
        symbol: f"#{color[0]:02X}{color[1]:02X}{color[2]:02X}"
        for color, symbol in symbol_by_color.items()
    }
    metadata_views = []
    for metadata, samples in sampled:
        metadata["samples"] = [
            "".join(symbol_by_color[color] for color in row) for row in samples
        ]
        metadata_views.append(metadata)
    return {
        "visual_kind": "pixel_readout",
        "question": question.strip(),
        "sampling": "equal-bin-centers",
        "palette": palette,
        "sample_count": total_samples,
        "view_count": len(metadata_views),
        "views": metadata_views,
    }
