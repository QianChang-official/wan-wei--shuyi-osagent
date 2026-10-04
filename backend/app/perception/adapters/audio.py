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

"""语音对话适配器：WAV 解析 → 能量法 VAD 切分 → 可选 ASR 转写。

分层与依赖策略（与 local_embedding 同一诚实口径）：
- **VAD 自研零依赖**：短时能量 + 迟滞门限（ onset/offset 双门限，
  电子电路施密特触发器思路），对 16bit PCM 单声道 WAV 直接可用；
  silero-vad（MIT）/ sherpa-onnx（Apache-2.0）可作为可选增强后端，
  懒加载、缺席即回退能量法，不报错不假装。
- **ASR 可选**：sherpa-onnx 懒加载，模型目录由
  ``WANWEI_ASR_MODEL_DIR`` 指定；缺席时转写为 None，语音段时长/能量等
  元数据照常入库——功能降级但管道不断。
"""

from __future__ import annotations

import io
import logging
import math
import os
import wave
from dataclasses import dataclass
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

#: VAD 帧长（毫秒）与门限：onset 高于高门限进入语音段，offset 低于
#: 低门限且持续 hangover 帧后才出段——双门限迟滞防抖，避免呼吸/唇齿音
#: 把一句话切成碎片。
FRAME_MS = 30
ONSET_RMS_DB = -42.0
OFFSET_RMS_DB = -50.0
HANGOVER_FRAMES = 8          # 240ms 连续低能量才判语音结束
MIN_SPEECH_FRAMES = 3        # 短于 90ms 的段视为噪声丢弃
MAX_AUDIO_BYTES = 32 * 1024 * 1024


class AudioValidationError(ValueError):
    """音频输入未通过校验。路由层映射 422。"""


@dataclass(frozen=True)
class SpeechSegment:
    start_ms: int
    end_ms: int
    rms_db: float          # 段内平均能量
    pcm: bytes             # 段原始 PCM（16bit mono）
    transcript: str | None  # ASR 缺席时为 None（诚实降级）


def _to_mono_16bit(pcm: bytes, channels: int, width: int) -> bytes:
    """归一化为 16bit 单声道 PCM（numpy 实现，audioop 已在 py3.13 移除）。

    WAV PCM 的 8bit 是无符号、16/32bit 是有符号——量化格式差异在此收敛。
    """
    if width == 2:
        samples = np.frombuffer(pcm, dtype="<i2")
    elif width == 1:
        samples = ((np.frombuffer(pcm, dtype=np.uint8).astype(np.int32) - 128) << 8)
    elif width == 4:
        samples = (np.frombuffer(pcm, dtype="<i4") >> 16)
    else:
        raise AudioValidationError(f"unsupported sample width: {width}")
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return np.clip(samples, -32768, 32767).astype("<i2").tobytes()


def parse_wav(data: bytes) -> tuple[bytes, int, int]:
    """解析 WAV → (16bit 单声道 PCM bytes, sample_rate, 2)。

    多声道先混成单声道；8/32bit 量化先线性转换。只接受 PCM/LPCM，
    压缩格式（μ-law 等）直接拒绝——感知层不做通用转码器。
    """
    if len(data) > MAX_AUDIO_BYTES:
        raise AudioValidationError(f"audio exceeds {MAX_AUDIO_BYTES} bytes")
    try:
        with wave.open(io.BytesIO(data)) as wav:
            channels, width, rate = (
                wav.getnchannels(), wav.getsampwidth(), wav.getframerate()
            )
            pcm = wav.readframes(wav.getnframes())
            comptype = wav.getcomptype()
    except (wave.Error, EOFError) as exc:
        raise AudioValidationError(f"undecodable wav: {exc}") from exc
    if comptype != "NONE":
        raise AudioValidationError(f"compressed wav unsupported: {comptype}")
    pcm = _to_mono_16bit(pcm, channels, width)
    if not pcm:
        raise AudioValidationError("empty audio")
    return pcm, rate, 2


def vad_split(
    pcm: bytes,
    rate: int,
    *,
    frame_ms: int = FRAME_MS,
    onset_db: float = ONSET_RMS_DB,
    offset_db: float = OFFSET_RMS_DB,
    hangover: int = HANGOVER_FRAMES,
) -> list[tuple[int, int, bytes, float]]:
    """能量法 VAD：返回 [(start_ms, end_ms, pcm_segment, avg_rms_db)]。

    施密特触发器式迟滞：能量升破 onset_db 进入语音段，跌破 offset_db
    后还要连续 hangover 帧才出段。无双门限的单门限方案会在一句话内部
    的气口处反复断句。
    """
    frame_len = rate * frame_ms // 1000 * 2  # 16bit mono → 每帧字节数
    if frame_len < 2:
        raise AudioValidationError(f"sample rate too low: {rate}")
    frames = [
        pcm[i:i + frame_len] for i in range(0, len(pcm) - frame_len + 1, frame_len)
    ]
    if not frames:
        return []
    # 逐帧能量（numpy 向量化）：int16 → float，RMS 转 dBFS。
    samples = np.frombuffer(b"".join(frames), dtype="<i2").astype(np.float64)
    samples = samples[: len(frames) * (frame_len // 2)].reshape(len(frames), -1)
    frame_db = 20.0 * np.log10(
        np.maximum(np.sqrt((samples**2).mean(axis=1)), 1.0) / 32768.0
    )

    segments: list[tuple[int, int, bytes, float]] = []
    in_speech = False
    seg_start = 0
    quiet_run = 0
    seg_energies: list[float] = []

    for idx, _frame in enumerate(frames):
        db = float(frame_db[idx])
        if not in_speech:
            if db >= onset_db:
                in_speech = True
                seg_start = idx
                quiet_run = 0
                seg_energies = [db]
        else:
            seg_energies.append(db)
            if db < offset_db:
                quiet_run += 1
                if quiet_run >= hangover:
                    seg_end = idx - hangover + 1
                    if seg_end - seg_start >= MIN_SPEECH_FRAMES:
                        # hangover 窗口内的静音帧不计入段能量均值；
                        # 段长不足 hangover 时退回整段均值（分子分母须一致）。
                        speech_energies = (
                            seg_energies[:-hangover]
                            if len(seg_energies) > hangover
                            else seg_energies
                        )
                        segments.append((
                            seg_start * frame_ms,
                            seg_end * frame_ms,
                            b"".join(frames[seg_start:seg_end]),
                            sum(speech_energies) / len(speech_energies),
                        ))
                    in_speech = False
                    quiet_run = 0
                    seg_energies = []
            else:
                quiet_run = 0
    if in_speech and len(frames) - seg_start >= MIN_SPEECH_FRAMES:
        segments.append((
            seg_start * frame_ms,
            len(frames) * frame_ms,
            b"".join(frames[seg_start:]),
            sum(seg_energies) / len(seg_energies),
        ))
    return segments


def _log10(x: float) -> float:
    return math.log10(x)


_asr_model = None
_asr_tried = False


def _get_asr():
    """懒加载 sherpa-onnx 识别器。依赖或模型目录缺席即返回 None。"""
    global _asr_model, _asr_tried
    if _asr_model is not None or _asr_tried:
        return _asr_model
    _asr_tried = True
    model_dir = os.environ.get("WANWEI_ASR_MODEL_DIR", "").strip()
    if not model_dir:
        logger.info("asr disabled: WANWEI_ASR_MODEL_DIR not set")
        return None
    try:
        import sherpa_onnx

        _asr_model = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=os.path.join(model_dir, "encoder.onnx"),
            decoder=os.path.join(model_dir, "decoder.onnx"),
            joiner=os.path.join(model_dir, "joiner.onnx"),
            tokens=os.path.join(model_dir, "tokens.txt"),
            num_threads=2,
        )
        logger.info("asr loaded from %s", model_dir)
    except ImportError:
        logger.info("asr disabled: sherpa-onnx not installed")
        return None
    except Exception as exc:
        logger.warning("asr load failed: %s", exc)
        return None
    return _asr_model


def asr_available() -> bool:
    return _get_asr() is not None


def transcribe_segment(pcm: bytes, rate: int) -> str | None:
    """ASR 转写一段语音。通道不可用返回 None（调用方降级处理）。"""
    recognizer = _get_asr()
    if recognizer is None:
        return None
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    stream = recognizer.create_stream()
    stream.accept_waveform(rate, samples)
    recognizer.decode_stream(stream)
    text = (stream.result.text or "").strip()
    return text or None


def process_audio(data: bytes, *, transcribe: bool = True) -> dict[str, Any]:
    """完整语音管道：解析 → VAD 切分 →（可选）转写。返回段落清单。"""
    pcm, rate, _width = parse_wav(data)
    raw_segments = vad_split(pcm, rate)
    segments = [
        SpeechSegment(
            start_ms=start,
            end_ms=end,
            rms_db=round(avg_db, 2),
            pcm=seg_pcm,
            transcript=transcribe_segment(seg_pcm, rate) if transcribe else None,
        )
        for start, end, seg_pcm, avg_db in raw_segments
    ]
    return {
        "sample_rate": rate,
        "duration_ms": len(pcm) // 2 * 1000 // rate,
        "segment_count": len(segments),
        "asr": "sherpa-onnx" if asr_available() else "unavailable",
        "segments": segments,
    }
