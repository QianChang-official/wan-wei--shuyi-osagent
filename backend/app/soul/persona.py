"""Persona CRUD for soul_persona and affect_state."""

import json
import uuid
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


def get_persona(soul_id: str) -> dict | None:
    """Read soul persona from soul_persona; return None if missing."""
    try:
        row = get_conn().execute(
            """SELECT soul_id, name, core_traits, voice, soul_values,
                      self_narrative, baseline_pleasure, baseline_arousal,
                      baseline_dominance, created_at, updated_at
               FROM soul_persona WHERE soul_id=?""",
            (soul_id,),
        ).fetchone()
    except Exception:
        return None

    if row is None:
        return None

    return {
        "soul_id": row["soul_id"],
        "name": row["name"],
        "core_traits": _loads(row["core_traits"], []),
        "voice": row["voice"],
        "soul_values": _loads(row["soul_values"], []),
        "self_narrative": row["self_narrative"],
        "baseline_pleasure": _clamp01(row["baseline_pleasure"] or 0.5),
        "baseline_arousal": _clamp01(row["baseline_arousal"] or 0.5),
        "baseline_dominance": _clamp01(row["baseline_dominance"] or 0.5),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def update_persona(soul_id: str, **fields) -> dict:
    """Update allowed persona fields and bump updated_at."""
    allowed = {
        "name", "core_traits", "voice", "soul_values",
        "self_narrative", "baseline_pleasure", "baseline_arousal", "baseline_dominance",
    }
    updates = {}
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k in {"core_traits", "soul_values"}:
            updates[k] = _dumps(v)
        elif k in {"baseline_pleasure", "baseline_arousal", "baseline_dominance"}:
            updates[k] = _clamp01(v)
        else:
            updates[k] = v

    if not updates:
        return get_persona(soul_id) or {}

    updates["updated_at"] = _now()
    cols = ", ".join(f"{k}=?" for k in updates)
    values = list(updates.values()) + [soul_id]

    try:
        get_conn().execute(
            f"UPDATE soul_persona SET {cols} WHERE soul_id=?",
            values,
        ).connection.commit()
    except Exception:
        return get_persona(soul_id) or {}

    return get_persona(soul_id) or {}


def create_persona(soul_id: str | None = None) -> str:
    """Create a new soul persona and its affect_state row."""
    sid = soul_id or ("soul_" + uuid.uuid4().hex[:12])
    ts = _now()
    defaults = {
        "name": "枢忆",
        "core_traits": _dumps(["严谨", "有温度", "会自省"]),
        "voice": "专业但不冷漠，偶尔幽默",
        "soul_values": _dumps(["诚实", "成长", "守护用户"]),
        "self_narrative": "我是枢忆，一个有记忆和情感的AI助手，我在持续学习和成长。",
        "baseline_pleasure": 0.6,
        "baseline_arousal": 0.4,
        "baseline_dominance": 0.5,
        "created_at": ts,
        "updated_at": ts,
    }

    try:
        conn = get_conn()
        conn.execute(
            """INSERT INTO soul_persona(
                soul_id, name, core_traits, voice, soul_values,
                self_narrative, baseline_pleasure, baseline_arousal,
                baseline_dominance, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                sid, defaults["name"], defaults["core_traits"], defaults["voice"],
                defaults["soul_values"], defaults["self_narrative"],
                defaults["baseline_pleasure"], defaults["baseline_arousal"],
                defaults["baseline_dominance"], ts, ts,
            ),
        )
        conn.execute(
            """INSERT INTO affect_state(
                soul_id, pleasure, arousal, dominance, current_mood, mood_intensity, updated_at
            ) VALUES (?,?,?,?,?,?,?)""",
            (sid, 0.5, 0.4, 0.5, "calm", 0.3, ts),
        )
        conn.commit()
    except Exception:
        # Idempotent: if row exists, return existing id
        return sid

    return sid
