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

"""感知事件归一化模型。

借鉴 AstrBot（AGPL-3.0，仅借鉴架构思想、不引用任何代码）的
「适配器 → 归一化事件 → 流水线」分层：四类采集适配器（语音/图片/视频/
传感器）产出**同一种** PerceptionEvent，下游状态机与写入闸门只面向
这一份契约，不感知具体模态。

事件本身不落库 payload 本体——图片/视频帧的字节归 memory_visual 管，
音频转写文本归胶囊管，这里只留**引用与元数据**，与「记忆存在 ⇔ 有账目」
的治理闭环保持单一事实源。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

Modality = Literal["audio", "image", "video", "sensor", "text"]

#: 单次事件的元数据上限，防止传感器高频上报把事件表当日志炸。
MAX_META_BYTES = 4096

VALID_MODALITIES = frozenset({"audio", "image", "video", "sensor", "text"})


@dataclass(frozen=True)
class PerceptionEvent:
    """一次感知输入的归一化表示。

    ``payload_ref`` 是指向本体存储的不透明引用（asset_id / capsule_id /
    传感器通道号），不是字节本身；``meta`` 放采样率、帧号、阈值等结构化
    上下文。kind 区分原始观察与派生产物（视频关键帧派生自视频流）。
    """

    modality: Modality
    session_id: str
    payload_ref: str | None = None
    kind: Literal["observation", "derived"] = "observation"
    meta: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: "pev_" + uuid.uuid4().hex[:12])
    created_at: str = ""

    def __post_init__(self) -> None:
        if self.modality not in VALID_MODALITIES:
            raise ValueError(f"unknown modality: {self.modality}")
        if not self.session_id:
            raise ValueError("perception event needs a session_id")
        import json

        if len(json.dumps(self.meta, ensure_ascii=False)) > MAX_META_BYTES:
            raise ValueError("perception event meta exceeds size limit")

    def manifest(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "modality": self.modality,
            "session_id": self.session_id,
            "payload_ref": self.payload_ref,
            "kind": self.kind,
            "meta": self.meta,
            "created_at": self.created_at,
        }
