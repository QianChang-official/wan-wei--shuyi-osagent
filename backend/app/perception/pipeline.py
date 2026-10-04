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

"""感知编排管道：适配器 → 归一化事件 → 状态机反馈 → 记忆写入。

四个模态共用同一条生命周期：
``begin → capturing → capture_done → understanding → understood →
responding → responded → idle``，任何一步故障走 ``fault → error →
recover → idle``。反馈事件随响应返回（drain），调用方/控制台可见
「感知正在做什么」。

治理口径：所有模态的记忆写入都过既有策略闸门（文本过 evaluate_policy，
图片过 store 层字节校验），感知层不发明第二条写入路径。传感器高频读数
**不逐条入记忆**——只有报警触发/恢复/突变等事件级信号才写入，
否则记忆库会被遥测流淹没（写入闸门拦的是内容，拦不住量级）。
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from ..memory_runtime.capsule_store import write_capsule
from ..memory_visual import store as visual_store
from .adapters import audio as audio_adapter
from .adapters import sensor as sensor_adapter
from .adapters import video as video_adapter
from .session import PerceptionSession

#: 进程级会话注册表（感知会话是运行时对象，不进 SQLite；
#: 需要跨进程持久的是记忆，不是会话）。
_sessions: dict[str, PerceptionSession] = {}
_sessions_lock = threading.Lock()

logger = logging.getLogger(__name__)

#: 单次传感器请求允许写入记忆的事件上限。 watcher 对异常流可能逐帧
#: 报警，没有上限时一次请求就能把记忆库灌满；超出部分如实计数返回，
#: 不静默丢弃也不中断解析（帧统计仍完整）。
MAX_SENSOR_EVENTS_PER_REQUEST = 64


def get_or_create_session(
    session_id: str | None = None,
    *,
    soul_id: str | None = None,
    owner_id: str | None = None,
) -> PerceptionSession:
    with _sessions_lock:
        if session_id and session_id in _sessions:
            return _sessions[session_id]
        session = PerceptionSession(session_id, soul_id=soul_id, owner_id=owner_id)
        _sessions[session.session_id] = session
        return session


def get_session(session_id: str) -> PerceptionSession | None:
    with _sessions_lock:
        return _sessions.get(session_id)


def _record_rollout(session: PerceptionSession, item_type: str, payload: dict) -> None:
    """执行轨迹落链（Codex rollout 思路）：感知动作全部可事后校验。

    轨迹失败**不得**反噬感知结果本身——审计辅助设施不该让主流程失败。
    但完全静默会让「链短一节」无从排查：异常降级为日志，链条缺口仍可被
    verify 发现，日志里也能对上原因。
    """
    try:
        from ..audit.rollout import append_rollout

        append_rollout(
            thread_id=f"perception:{session.session_id}",
            item_type=item_type,
            item=payload,
            owner_id=session.owner_id,
        )
    except Exception as exc:  # noqa: BLE001 - 审计设施故障不反噬主流程，但必须留痕
        logger.warning('[perception.pipeline] rollout 落链失败（%s）：%r', item_type, exc)


def _finish(session: PerceptionSession, result: dict[str, Any]) -> dict[str, Any]:
    """统一收尾：responding → idle，反馈事件随响应返回。"""
    if session.state == "understanding":
        session.fire("understood", detail="perception parsed")
    if session.state == "responding":
        session.fire("responded", detail="memory write complete")
    _record_rollout(session, "perception_completed", {
        "modality": result.get("modality"),
        "summary": {
            key: value for key, value in result.items()
            if key in {"modality", "frame_count", "frames_parsed", "duration_ms",
                       "asr", "compression_ratio"}
        },
    })
    result["session_id"] = session.session_id
    result["session_state"] = session.state
    result["feedback"] = session.drain_feedback()
    return result


def _fail(session: PerceptionSession, exc: Exception) -> dict[str, Any]:
    """故障闭环：fault → error → recover → idle，错误如实返回。"""
    try:
        session.fire("fault", detail=f"{type(exc).__name__}: {exc}")
        session.fire("recover", detail="auto-recover after fault")
    except Exception:  # 状态机自身故障不应掩盖原始错误
        pass
    _record_rollout(session, "perception_fault", {
        "error": type(exc).__name__,
        "reason": str(exc)[:400],
        "modality": getattr(exc, "modality", None),
    })
    return {
        "ok": False,
        "error": type(exc).__name__,
        "reason": str(exc),
        "session_id": session.session_id,
        "session_state": session.state,
        "feedback": session.drain_feedback(),
    }


def ingest_image(
    session: PerceptionSession,
    *,
    image_bytes: bytes,
    caption: str,
    soul_id: str | None = None,
    owner_id: str | None = None,
    kind: str = "current",
    derived_from: list[str] | None = None,
) -> dict[str, Any]:
    """图片感知：直接接入视觉记忆子系统（VISTA 无损视觉记忆）。"""
    try:
        session.fire("begin", detail="image ingest")
        session.fire("capture_done", meta={"bytes": len(image_bytes)})
        session.fire("understood", detail="visual capsule write")
        result = visual_store.write_visual_capsule(
            data=image_bytes, caption=caption, kind=kind,
            derived_from=derived_from, soul_id=soul_id, owner_id=owner_id,
            source_type="perception_image",
        )
        return _finish(session, {"ok": True, "modality": "image", "write": result})
    except Exception as exc:
        return _fail(session, exc)


def ingest_audio(
    session: PerceptionSession,
    *,
    wav_bytes: bytes,
    transcribe: bool = True,
    soul_id: str | None = None,
    owner_id: str | None = None,
) -> dict[str, Any]:
    """语音感知：VAD 切段 →（可选 ASR）→ 每段一条语音记忆。

    ASR 缺席时段落元数据（起止/能量/时长）照常入库，transcript 为 None——
    诚实降级，不编造转写文本。
    """
    try:
        session.fire("begin", detail="audio ingest")
        processed = audio_adapter.process_audio(wav_bytes, transcribe=transcribe)
        session.fire("capture_done", meta={
            "duration_ms": processed["duration_ms"],
            "segments": processed["segment_count"],
            "asr": processed["asr"],
        })
        written = []
        for seg in processed["segments"]:
            caption = (
                f"[语音 {seg.start_ms}-{seg.end_ms}ms] "
                + (seg.transcript or f"（未转写，能量 {seg.rms_db}dB）")
            )
            result = write_capsule(
                memory_class="episodic",
                content={
                    "modality": "audio",
                    "text": caption,
                    "start_ms": seg.start_ms,
                    "end_ms": seg.end_ms,
                    "rms_db": seg.rms_db,
                    "transcript": seg.transcript,
                    "asr": processed["asr"],
                },
                source_type="perception_audio",
                soul_id=soul_id,
                owner_id=owner_id,
            )
            written.append({
                "capsule_id": result["capsule_id"],
                "lifecycle": result["state"]["lifecycle"],
                "transcript": seg.transcript,
            })
        return _finish(session, {
            "ok": True, "modality": "audio",
            "duration_ms": processed["duration_ms"],
            "segments": written,
            "asr": processed["asr"],
        })
    except Exception as exc:
        return _fail(session, exc)


def ingest_video(
    session: PerceptionSession,
    *,
    frames: list[bytes] | None = None,
    video_bytes: bytes | None = None,
    caption: str = "视频关键帧",
    threshold: float = video_adapter.SCENE_CHANGE_THRESHOLD,
    soul_id: str | None = None,
    owner_id: str | None = None,
) -> dict[str, Any]:
    """视频感知：关键帧抽取 → 每帧一条视觉记忆（historical 归档观察）。

    关键帧之间以 derived_from 串链：第 N 帧派生自第 N-1 帧，
    回看任意一帧都能顺链重建场景演变。
    """
    try:
        session.fire("begin", detail="video ingest")
        processed = video_adapter.process_video(
            video_bytes=video_bytes, frames=frames, threshold=threshold
        )
        session.fire("capture_done", meta={
            "frames": processed["frame_count"],
            "keyframes": processed["keyframe_count"],
        })
        written = []
        previous_asset: str | None = None
        for keyframe in processed["keyframes"]:
            result = visual_store.write_visual_capsule(
                data=keyframe.png_bytes,
                caption=f"{caption}（第 {keyframe.frame_index} 帧，"
                        f"场景距离 {keyframe.distance}）",
                kind="derived" if previous_asset else "historical",
                derived_from=[previous_asset] if previous_asset else None,
                soul_id=soul_id,
                owner_id=owner_id,
                source_type="perception_video",
            )
            asset = result.get("asset") or {}
            previous_asset = asset.get("asset_id") or previous_asset
            written.append({
                "frame_index": keyframe.frame_index,
                "distance": keyframe.distance,
                "capsule_id": result["capsule_id"],
                "asset_id": asset.get("asset_id"),
            })
        return _finish(session, {
            "ok": True, "modality": "video",
            "frame_count": processed["frame_count"],
            "compression_ratio": processed["compression_ratio"],
            "keyframes": written,
        })
    except Exception as exc:
        return _fail(session, exc)


def ingest_sensor_stream(
    session: PerceptionSession,
    *,
    stream_bytes: bytes,
    watcher: sensor_adapter.SensorWatcher | None = None,
    soul_id: str | None = None,
    owner_id: str | None = None,
) -> dict[str, Any]:
    """传感器感知：帧解析 → 事件检测 → 事件级记忆（读数本体不入库）。

    返回全部解析帧数、丢弃的 CRC 错帧数、检出事件清单。
    """
    try:
        session.fire("begin", detail="sensor stream ingest")
        parser = sensor_adapter.FrameParser()
        frames = parser.feed(stream_bytes)
        watcher = watcher or sensor_adapter.SensorWatcher()
        session.fire("capture_done", meta={
            "frames": len(frames), "crc_errors": parser.crc_errors,
        })
        detected: list[dict[str, Any]] = []
        events_dropped = 0
        for frame in frames:
            for event in watcher.observe(frame):
                if len(detected) >= MAX_SENSOR_EVENTS_PER_REQUEST:
                    # 超出上限：事件计数但不入记忆、不进返回清单，
                    # 防止异常流把记忆库和响应体同时灌爆。
                    events_dropped += 1
                    continue
                detected.append(event)
                write_capsule(
                    memory_class="episodic",
                    content={
                        "modality": "sensor",
                        "text": (
                            f"[传感器 ch{event['channel']}] {event['kind']}"
                            f" 值={event['value']}"
                        ),
                        **event,
                    },
                    source_type="perception_sensor",
                    risk_class="medium" if event["kind"].startswith("alarm") else "low",
                    soul_id=soul_id,
                    owner_id=owner_id,
                )
        return _finish(session, {
            "ok": True, "modality": "sensor",
            "frames_parsed": len(frames),
            "crc_errors": parser.crc_errors,
            "events": detected,
            "events_dropped": events_dropped,
        })
    except Exception as exc:
        return _fail(session, exc)
