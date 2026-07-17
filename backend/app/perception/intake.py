import json
import logging
import re
import uuid
from typing import Any

from ..db import get_conn
from ..memory_runtime.capsule_store import write_capsule
from ..utils.datetime_utils import utc_now_iso_compact

logger = logging.getLogger(__name__)


def now() -> str:
    return utc_now_iso_compact()


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def loads(text: str, default: Any = None) -> Any:
    if text is None:
        return default
    return json.loads(text)


def _detect_emotion(content: str) -> str:
    """内联简单正则情绪检测，避免循环导入."""
    text = content.lower()
    if any(k in text for k in ("开心", "高兴", "快乐", "兴奋", "激动", "惊喜", "喜悦", "愉快")):
        return "joy"
    if any(k in text for k in ("难过", "伤心", "悲伤", "沮丧", "失望", "痛苦", "哭", "泪")):
        return "sadness"
    if any(k in text for k in ("生气", "愤怒", "恼火", "烦躁", "火大", "怒", "讨厌", "恨")):
        return "anger"
    if any(k in text for k in ("害怕", "恐惧", "担心", "焦虑", "不安", "紧张", "慌")):
        return "fear"
    if any(k in text for k in ("感谢", "谢谢", "感激", "谢了", "多谢")):
        return "gratitude"
    return "neutral"


def _classify_intent(content: str) -> str:
    """简单意图分类规则."""
    text = content.lower()
    if any(k in text for k in ("感谢", "谢谢", "感激", "谢了", "多谢")):
        return "gratitude"
    if any(k in text for k in ("差", "糟", "不好", "讨厌", "不满", "失望", "烦", "垃圾", "废物", "烂")):
        return "complaint"
    if any(k in text for k in ("为什么", "怎么", "什么", "如何", "是否", "请问", "吗", "？", "?")):
        return "question"
    if any(k in text for k in ("我感觉", "我觉得", "我很", "我心情", "今天心情", "心情", "情绪")):
        return "share_emotion"
    return "neutral"


def _emotion_delta(emotion: str) -> dict[str, float]:
    """根据检测到的情绪返回对 affect_state 的增量."""
    deltas = {
        "joy": {"pleasure": 0.1, "arousal": 0.05, "dominance": 0.0},
        "gratitude": {"pleasure": 0.08, "arousal": 0.02, "dominance": 0.0},
        "sadness": {"pleasure": -0.1, "arousal": -0.05, "dominance": -0.05},
        "anger": {"pleasure": -0.15, "arousal": 0.1, "dominance": 0.05},
        "fear": {"pleasure": -0.1, "arousal": 0.08, "dominance": -0.1},
        "neutral": {"pleasure": 0.0, "arousal": 0.0, "dominance": 0.0},
    }
    return deltas.get(emotion, deltas["neutral"])


def _mood_for_emotion(emotion: str) -> str:
    mapping = {
        "joy": "happy",
        "gratitude": "content",
        "sadness": "sad",
        "anger": "irritated",
        "fear": "anxious",
        "neutral": "calm",
    }
    return mapping.get(emotion, "calm")


def _clamp(value: float, min_val: float = 0.0, max_val: float = 1.0) -> float:
    return max(min_val, min(value, max_val))


def extract_entities(text: str) -> list[str]:
    """简单实体抽取: 正则匹配连续的中文名词短语（至少2个字符）."""
    matches = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    seen: set[str] = set()
    result: list[str] = []
    for m in matches:
        if m not in seen:
            seen.add(m)
            result.append(m)
    return result


def intake_perception(
    soul_id: str,
    role: str,
    content: str,
    used_capsule_ids: list[str] | None = None,
) -> dict:
    """每轮对话结束后调用，完成感知处理.

    职责:
    1. 提取情绪信号
    2. 意图分类
    3. 读取当前 affect_state 作为 affect_before
    4. 根据检测到的情绪更新 affect_state
    5. 将更新后的 affect_state 作为 affect_after
    6. 写入 conversation_turns 表
    7. 同时写入 memory_capsules_v2 (memory_class="working")
    """
    turn_id = "turn_" + uuid.uuid4().hex[:12]
    created = now()
    used_capsule_ids = used_capsule_ids or []

    try:
        # 1. 提取情绪信号
        emotion_detected = _detect_emotion(content)

        # 2. 意图分类
        intent_classified = _classify_intent(content)

        # 3. 读取当前 affect_state 作为 affect_before
        conn = get_conn()
        row = conn.execute(
            "SELECT pleasure, arousal, dominance, current_mood, mood_intensity "
            "FROM affect_state WHERE soul_id=?",
            (soul_id,),
        ).fetchone()

        if row:
            affect_before = {
                "pleasure": float(row["pleasure"]),
                "arousal": float(row["arousal"]),
                "dominance": float(row["dominance"]),
                "current_mood": row["current_mood"],
                "mood_intensity": float(row["mood_intensity"]),
            }
        else:
            affect_before = {
                "pleasure": 0.5,
                "arousal": 0.4,
                "dominance": 0.5,
                "current_mood": "calm",
                "mood_intensity": 0.3,
            }

        # 4. 根据检测到的情绪更新 affect_state
        delta = _emotion_delta(emotion_detected)
        affect_after = {
            "pleasure": _clamp(affect_before["pleasure"] + delta["pleasure"]),
            "arousal": _clamp(affect_before["arousal"] + delta["arousal"]),
            "dominance": _clamp(affect_before["dominance"] + delta["dominance"]),
            "current_mood": _mood_for_emotion(emotion_detected),
            "mood_intensity": _clamp(
                affect_before["mood_intensity"]
                + (abs(delta["pleasure"]) + abs(delta["arousal"])) / 2.0
            ),
        }

        try:
            conn.execute(
                """
                INSERT INTO affect_state(
                    soul_id, pleasure, arousal, dominance, current_mood, mood_intensity, updated_at
                ) VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(soul_id) DO UPDATE SET
                    pleasure=excluded.pleasure,
                    arousal=excluded.arousal,
                    dominance=excluded.dominance,
                    current_mood=excluded.current_mood,
                    mood_intensity=excluded.mood_intensity,
                    updated_at=excluded.updated_at
                """,
                (
                    soul_id,
                    affect_after["pleasure"],
                    affect_after["arousal"],
                    affect_after["dominance"],
                    affect_after["current_mood"],
                    affect_after["mood_intensity"],
                    created,
                ),
            )
            conn.commit()
        except Exception as e:
            logger.warning("affect_state update failed: %s", e)
            # 不阻断主流程

        # 6. 写入 conversation_turns 表
        try:
            conn.execute(
                """
                INSERT INTO conversation_turns(
                    turn_id, soul_id, role, content, emotion_detected, intent_classified,
                    capsules_used, affect_before, affect_after, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    turn_id,
                    soul_id,
                    role,
                    content,
                    emotion_detected,
                    intent_classified,
                    dumps(used_capsule_ids),
                    dumps(affect_before),
                    dumps(affect_after),
                    created,
                ),
            )
            conn.commit()
        except Exception as e:
            logger.warning("conversation_turns insert failed: %s", e)

        # 7. 同时写入 memory_capsules_v2 (memory_class="working")
        try:
            capsule_content = {
                "role": role,
                "content": content,
                "intent": intent_classified,
                "emotion": emotion_detected,
                "entities": extract_entities(content),
            }
            write_capsule(
                memory_class="working",
                content=capsule_content,
                source_type="conversation",
                scene="conversation",
                task_type="perception",
                risk_class="low",
            )
        except Exception as e:
            logger.warning("write_capsule failed: %s", e)

        return {
            "turn_id": turn_id,
            "emotion_detected": emotion_detected,
            "intent": intent_classified,
            "affect_before": affect_before,
            "affect_after": affect_after,
        }

    except Exception as e:
        logger.exception("intake_perception failed: %s", e)
        # 返回最小可用结果，不阻断主流程
        return {
            "turn_id": turn_id,
            "emotion_detected": "neutral",
            "intent": "neutral",
            "affect_before": {},
            "affect_after": {},
        }
