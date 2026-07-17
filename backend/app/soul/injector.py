"""Soul injection prompt builder and soul state aggregator."""

import json
from typing import Any

from ..db import get_conn
from ..utils.datetime_utils import utc_now_iso_compact


def _loads(text: str | None, default: Any = None) -> Any:
    if text is None:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _now() -> str:
    return utc_now_iso_compact()


def _get_affect(soul_id: str) -> dict:
    """Read affect_state; return safe defaults on error."""
    try:
        row = get_conn().execute(
            """SELECT pleasure, arousal, dominance, current_mood, mood_intensity, updated_at
               FROM affect_state WHERE soul_id=?""",
            (soul_id,),
        ).fetchone()
    except Exception:
        return {
            "pleasure": 0.5,
            "arousal": 0.4,
            "dominance": 0.5,
            "current_mood": "calm",
            "mood_intensity": 0.3,
            "updated_at": None,
        }

    if row is None:
        return {
            "pleasure": 0.5,
            "arousal": 0.4,
            "dominance": 0.5,
            "current_mood": "calm",
            "mood_intensity": 0.3,
            "updated_at": None,
        }

    return {
        "pleasure": _clamp01(row["pleasure"] or 0.5),
        "arousal": _clamp01(row["arousal"] or 0.4),
        "dominance": _clamp01(row["dominance"] or 0.5),
        "current_mood": row["current_mood"] or "calm",
        "mood_intensity": _clamp01(row["mood_intensity"] or 0.3),
        "updated_at": row["updated_at"],
    }


def _get_core_memories(soul_id: str, limit: int = 10) -> list[dict]:
    """Fetch top-N capsules by importance_score for this soul."""
    try:
        rows = get_conn().execute(
            """SELECT capsule_id, content, state
               FROM memory_capsules_v2
               WHERE json_extract(state, '$.importance_score') IS NOT NULL
               ORDER BY json_extract(state, '$.importance_score') DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    except Exception:
        return []

    memories = []
    for row in rows:
        state = _loads(row["state"], {})
        content = _loads(row["content"], {})
        text = content.get("text") or content.get("summary") or str(content)[:200]
        memories.append({
            "capsule_id": row["capsule_id"],
            "text": text,
            "importance_score": _clamp01(state.get("importance_score", 0.0)),
        })
    return memories


def build_injection_prompt(soul_id: str) -> str:
    """Assemble the soul injection prompt string for a given soul."""
    try:
        row = get_conn().execute(
            """SELECT name, core_traits, voice, soul_values, self_narrative
               FROM soul_persona WHERE soul_id=?""",
            (soul_id,),
        ).fetchone()
    except Exception:
        row = None

    if row is None:
        return ""

    name = row["name"] or "枢忆"
    core_traits = _loads(row["core_traits"], [])
    voice = row["voice"] or ""
    soul_values = _loads(row["soul_values"], [])
    self_narrative = row["self_narrative"] or ""

    affect = _get_affect(soul_id)
    mood = affect["current_mood"]
    pleasure = affect["pleasure"]
    arousal = affect["arousal"]

    core_memories = _get_core_memories(soul_id, limit=10)
    memory_parts = []
    for mem in core_memories:
        memory_parts.append(f"• {mem['text']}")
    memories_text = "\n".join(memory_parts) if memory_parts else "（暂无核心记忆）"

    traits_text = "、".join(core_traits) if core_traits else ""
    values_text = "、".join(soul_values) if soul_values else ""

    lines = [
        f"你是{name}。",
        f"你当前的心情是{mood}（愉悦度{pleasure:.2f}/激活度{arousal:.2f}）。",
    ]
    if traits_text:
        lines.append(f"你的核心特质：{traits_text}。")
    if values_text:
        lines.append(f"你的灵魂价值观：{values_text}。")
    if voice:
        lines.append(f"你的表达风格：{voice}。")
    if self_narrative:
        lines.append(f"自我叙述：{self_narrative}")
    lines.append("你记得：")
    lines.append(memories_text)

    return "\n".join(lines)


def get_soul_state(soul_id: str) -> dict:
    """Return full soul state: persona + affect + core memories summary."""
    try:
        row = get_conn().execute(
            """SELECT name, core_traits, voice, soul_values, self_narrative,
                      baseline_pleasure, baseline_arousal, baseline_dominance
               FROM soul_persona WHERE soul_id=?""",
            (soul_id,),
        ).fetchone()
    except Exception:
        row = None

    if row is None:
        return {
            "soul_id": soul_id,
            "persona": None,
            "affect": _get_affect(soul_id),
            "core_memories": [],
        }

    persona = {
        "name": row["name"],
        "core_traits": _loads(row["core_traits"], []),
        "voice": row["voice"],
        "soul_values": _loads(row["soul_values"], []),
        "self_narrative": row["self_narrative"],
        "baseline_pleasure": _clamp01(row["baseline_pleasure"] or 0.5),
        "baseline_arousal": _clamp01(row["baseline_arousal"] or 0.5),
        "baseline_dominance": _clamp01(row["baseline_dominance"] or 0.5),
    }

    affect = _get_affect(soul_id)
    core_memories = _get_core_memories(soul_id, limit=10)

    return {
        "soul_id": soul_id,
        "persona": persona,
        "affect": affect,
        "core_memories": core_memories,
    }
