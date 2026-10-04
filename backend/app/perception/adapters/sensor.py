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

"""传感器连接适配器：串口帧协议解析 + 阈值/突变检测。

电子电路侧约定（与下位机固件对齐的最小协议）：

    帧格式：  0xAA 0x55 | len(1B) | type(1B) | channel(1B) | value(4B float32 LE)
              | crc16(2B LE, CRC-16/CCITT-FALSE, 覆盖 len..value)
    读数帧 type=0x01；心跳 type=0x00；告警 type=0x02（下位机本地已判越限）。

解析器是**字节流状态机**（feed 任意切片，粘包/半包/噪声自动重同步），
不是「读一整帧」的理想化假设——串口数据天然粘包断包。

阈值检测用**迟滞比较器**（施密特触发）：越上限报警后要跌破「上限-回差」
才恢复，消除读数在阈值附近抖动导致的报警振荡——这是比较器电路里
正反馈回差的软件对应物。

传输层可插拔：pyserial（BSD-3）懒加载可选；测试/回放用内存字节流。
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any

SYNC = b"\xaa\x55"
FRAME_TYPES = {0x00: "heartbeat", 0x01: "reading", 0x02: "alarm"}
MAX_PAYLOAD_LEN = 16


class SensorProtocolError(ValueError):
    """协议级错误（长度/类型非法）。CRC 错误不算——噪声帧丢弃重同步即可。"""


def crc16_ccitt(data: bytes, *, init: int = 0xFFFF) -> int:
    """CRC-16/CCITT-FALSE（多项式 0x1021，初值 0xFFFF，不反射）。"""
    crc = init
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def encode_reading(channel: int, value: float, frame_type: int = 0x01) -> bytes:
    """打包一帧（供测试与下位机固件参考实现使用）。

    len = 其后 body 的字节数（type 1 + channel 1 + value 4 = 6），
    CRC 覆盖 len+body（与解析器严格同口径）。
    """
    if not 0 <= channel <= 255 or frame_type not in FRAME_TYPES:
        raise SensorProtocolError("invalid channel or frame type")
    body = bytes([frame_type, channel]) + struct.pack("<f", value)
    head = SYNC + bytes([len(body)])
    return head + body + struct.pack("<H", crc16_ccitt(head[2:] + body))


@dataclass(frozen=True)
class SensorFrame:
    frame_type: str
    channel: int
    value: float


class FrameParser:
    """字节流 → 帧。粘包/断包/噪声自动重同步。

    状态机：SYNC0 → SYNC1 → BODY(len+payload) → CRC。任何一步校验失败
    都退回重新找同步头，且只逐字节滑窗——不错过噪声中嵌套的真同步头。
    """

    def __init__(self) -> None:
        self._buf = bytearray()
        self.crc_errors = 0

    def feed(self, data: bytes) -> list[SensorFrame]:
        self._buf.extend(data)
        frames: list[SensorFrame] = []
        while True:
            frame = self._try_pop()
            if frame is None:
                return frames
            frames.append(frame)

    def _try_pop(self) -> SensorFrame | None:
        buf = self._buf
        # 找同步头；找不到就丢弃到只剩最后一个字节（可能是半个 0xAA）。
        while len(buf) >= 2 and bytes(buf[:2]) != SYNC:
            del buf[0]
        if len(buf) < 2:
            return None
        if len(buf) < 3:
            return None
        body_len = buf[2]
        if body_len < 3 or body_len > MAX_PAYLOAD_LEN:
            # 长度非法 → 这个「同步头」是噪声，滑过一个字节重找。
            del buf[0]
            return self._try_pop()
        frame_end = 3 + body_len + 2
        if len(buf) < frame_end:
            return None  # 半包，等更多字节
        covered = bytes(buf[2:3 + body_len])          # len + body
        body = bytes(buf[3:3 + body_len])
        expected_crc = struct.unpack("<H", bytes(buf[3 + body_len:frame_end]))[0]
        if crc16_ccitt(covered) != expected_crc:
            self.crc_errors += 1
            del buf[0]  # CRC 错 → 同步头是噪声或传输出错，滑窗重同步
            return self._try_pop()
        del buf[:frame_end]
        frame_type, channel = body[0], body[1]
        if frame_type not in FRAME_TYPES:
            raise SensorProtocolError(f"unknown frame type: {frame_type:#x}")
        value = struct.unpack("<f", body[2:6])[0] if body_len >= 6 else 0.0
        return SensorFrame(FRAME_TYPES[frame_type], channel, value)


@dataclass
class HysteresisAlarm:
    """迟滞比较器（施密特触发）：channel → (high, low, state)。

    报警条件 value > high；恢复条件 value < high - hysteresis。
    两者之间维持原状态——回差消除阈值抖动振荡。
    """

    high: float
    hysteresis: float = 1.0
    active: bool = False

    def update(self, value: float) -> str | None:
        """返回 'triggered' / 'recovered' / None（状态不变）。"""
        if not self.active and value > self.high:
            self.active = True
            return "triggered"
        if self.active and value < self.high - self.hysteresis:
            self.active = False
            return "recovered"
        return None


@dataclass
class SensorWatcher:
    """通道级读数监视：迟滞报警 + 突变检测。

    突变：|value - EMA| > spike_factor × EMA 标准差估计（简化指数估计，
    不存历史窗口——传感器可能上千 Hz，内存口径必须恒定）。
    """

    ema_alpha: float = 0.2
    spike_factor: float = 3.0
    _ema: dict[int, float] = field(default_factory=dict)
    _var: dict[int, float] = field(default_factory=dict)
    _alarms: dict[int, HysteresisAlarm] = field(default_factory=dict)

    def set_alarm(self, channel: int, *, high: float, hysteresis: float = 1.0) -> None:
        self._alarms[channel] = HysteresisAlarm(high, hysteresis)

    def observe(self, frame: SensorFrame) -> list[dict[str, Any]]:
        """吃一个读数帧，吐出零或多个事件（报警触发/恢复/突变）。"""
        if frame.frame_type != "reading":
            return []
        channel, value = frame.channel, frame.value
        events: list[dict[str, Any]] = []

        ema = self._ema.get(channel, value)
        var = self._var.get(channel, 0.0)
        deviation = abs(value - ema)
        sigma = var ** 0.5
        if channel in self._ema and deviation > self.spike_factor * max(sigma, 1e-6):
            events.append({
                "kind": "spike", "channel": channel, "value": value,
                "ema": round(ema, 4), "deviation": round(deviation, 4),
            })
        self._ema[channel] = ema + self.ema_alpha * (value - ema)
        self._var[channel] = var + self.ema_alpha * ((value - ema) ** 2 - var)

        alarm = self._alarms.get(channel)
        if alarm is not None:
            transition = alarm.update(value)
            if transition:
                events.append({
                    "kind": f"alarm_{transition}", "channel": channel,
                    "value": value, "threshold_high": alarm.high,
                })
        return events
