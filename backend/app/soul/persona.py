"""Persona CRUD for soul_persona and affect_state."""

import json
import sqlite3
import uuid
from typing import Any

from ..db import get_conn, transaction
from ..utils.datetime_utils import utc_now_iso_compact


class PersonaStoreError(RuntimeError):
    """persona 写库失败。03-#6：不再把异常吞掉后返回旧值/sid 假成功，
    由调用方（API 层）转换为显式错误响应。"""


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
        # 03-#11: 0.0 是合法 baseline，只有 NULL 才回退默认值
        "baseline_pleasure": _clamp01(row["baseline_pleasure"] if row["baseline_pleasure"] is not None else 0.5),
        "baseline_arousal": _clamp01(row["baseline_arousal"] if row["baseline_arousal"] is not None else 0.5),
        "baseline_dominance": _clamp01(row["baseline_dominance"] if row["baseline_dominance"] is not None else 0.5),
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
        with transaction() as conn:
            conn.execute(
                f"UPDATE soul_persona SET {cols} WHERE soul_id=?",
                values,
            )
    except Exception as exc:
        # transaction() 已 rollback。03-#6：不再返回旧值假成功，显式抛错由
        # API 层转成 5xx，调用方能感知写入真实失败。
        raise PersonaStoreError(f"update_persona failed for soul_id={soul_id!r}") from exc

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
        with transaction() as conn:
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
    except sqlite3.IntegrityError as exc:
        # transaction() 已 rollback。幂等语义仅限「soul_id 确实已存在」：
        # 核验持久化行仍在才返回 sid；否则属于真实冲突/坏数据，显式抛错。
        if get_persona(sid) is not None:
            return sid
        raise PersonaStoreError(f"create_persona conflict for soul_id={sid!r}") from exc
    except Exception as exc:
        # 03-#6：不再一律返回 sid 假成功（行可能并未落库），显式抛错。
        raise PersonaStoreError(f"create_persona failed for soul_id={sid!r}") from exc

    return sid
