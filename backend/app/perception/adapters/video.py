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

"""视频适配器：关键帧抽取 → 视觉胶囊序列。

不引 OpenCV：解码器可插拔（OpenCV 可选，Apache-2.0）；核心算法只面向
「帧序列」抽象——关键帧检测复用视觉记忆的 167 维嵌入
（``memory_visual.embedding.embed_image``）算相邻帧余弦距离，超阈值即
场景切换。感知层与记忆层共享同一套嵌入，视频关键帧天然可检索。

帧来源两路：
- ``frames``：调用方直接给 PNG 字节序列（测试/上游已解码的场景）；
- ``video_bytes``：本地视频文件，需 OpenCV（懒加载，缺席报 422 级错误，
  不假装能解码）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

#: 相邻帧余弦距离超过此值判定为场景切换（167 维感知嵌入实测口径：
#: 同色块静帧 ~0.00，换色 ~0.3+，构图大改 ~0.5+）。
SCENE_CHANGE_THRESHOLD = 0.18

#: 首帧恒为关键帧；相邻关键帧最小间隔（帧），避免镜头抖动连爆。
MIN_KEYFRAME_GAP = 3

MAX_FRAMES = 10000


class VideoValidationError(ValueError):
    """视频输入未通过校验。路由层映射 422。"""


@dataclass(frozen=True)
class KeyFrame:
    frame_index: int
    png_bytes: bytes
    distance: float        # 与上一关键帧的余弦距离（首帧为 1.0）


def detect_keyframes(
    frames: list[bytes],
    *,
    threshold: float = SCENE_CHANGE_THRESHOLD,
    min_gap: int = MIN_KEYFRAME_GAP,
) -> list[KeyFrame]:
    """帧序列（PNG 字节）→ 关键帧清单。

    算法：逐帧算感知嵌入，与**上一关键帧**（不是上一帧）比余弦距离——
    与上帧比会在渐变镜头（淡入淡出）里雪崩式连爆，与上一关键帧比
    才是「场景是否真的变了」。
    """
    from ...memory_visual.embedding import embed_image

    if not frames:
        raise VideoValidationError("empty frame sequence")
    if len(frames) > MAX_FRAMES:
        raise VideoValidationError(f"frame sequence exceeds {MAX_FRAMES}")

    keyframes: list[KeyFrame] = []
    last_vec: list[float] | None = None
    last_key_index = -MIN_KEYFRAME_GAP
    for index, png in enumerate(frames):
        vec = embed_image(png)
        if last_vec is None:
            distance = 1.0
        else:
            similarity = sum(a * b for a, b in zip(vec, last_vec))
            distance = 1.0 - similarity
        is_key = last_vec is None or (
            distance >= threshold and index - last_key_index >= min_gap
        )
        if is_key:
            keyframes.append(KeyFrame(index, png, round(distance, 6)))
            last_vec = vec
            last_key_index = index
    return keyframes


def _decode_with_cv2(video_bytes: bytes, *, sample_every: int = 15) -> list[bytes]:
    """OpenCV 解码视频字节 → 抽帧 PNG 序列。依赖缺席抛 VideoValidationError。"""
    try:
        import cv2  # noqa: F401  # cv2 即解码可用性探针；np 由 cv2 帧转换内部使用
    except ImportError as exc:
        raise VideoValidationError(
            "video decode requires opencv-python (not installed)"
        ) from exc
    import tempfile
    from pathlib import Path

    # OpenCV VideoCapture 只认文件路径，临时文件用完即删。
    tmp = Path(tempfile.mkstemp(suffix=".video")[1])
    try:
        tmp.write_bytes(video_bytes)
        capture = cv2.VideoCapture(str(tmp))
        if not capture.isOpened():
            raise VideoValidationError("undecodable video stream")
        frames: list[bytes] = []
        index = 0
        while len(frames) < MAX_FRAMES:
            ok, frame = capture.read()
            if not ok:
                break
            if index % sample_every == 0:
                ok, encoded = cv2.imencode(".png", frame)
                if ok:
                    frames.append(encoded.tobytes())
            index += 1
        capture.release()
    finally:
        tmp.unlink(missing_ok=True)
    if not frames:
        raise VideoValidationError("video yielded no frames")
    return frames


def process_video(
    *,
    video_bytes: bytes | None = None,
    frames: list[bytes] | None = None,
    threshold: float = SCENE_CHANGE_THRESHOLD,
    sample_every: int = 15,
) -> dict[str, Any]:
    """完整视频管道：解码（可选）→ 关键帧抽取。返回关键帧清单与统计。"""
    if frames is None:
        if video_bytes is None:
            raise VideoValidationError("video_bytes or frames is required")
        frames = _decode_with_cv2(video_bytes, sample_every=sample_every)
    keyframes = detect_keyframes(frames, threshold=threshold)
    return {
        "frame_count": len(frames),
        "keyframe_count": len(keyframes),
        "compression_ratio": round(len(keyframes) / len(frames), 4),
        "threshold": threshold,
        "keyframes": keyframes,
    }
