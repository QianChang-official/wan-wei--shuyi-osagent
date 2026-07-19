"""
PAD three-dimensional affect state machine.

Pleasure–Arousal–Dominance (PAD) values are clamped to [0, 1].
Every state mutation is logged to the affect_events table.
"""

import json
import uuid
from dataclasses import dataclass, asdict

from ..db import transaction
from ..utils.datetime_utils import utc_now_iso_compact


@dataclass
class AffectState:
    pleasure: float = 0.5
    arousal: float = 0.4
    dominance: float = 0.5
    current_mood: str = "calm"
    mood_intensity: float = 0.3

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Trigger rules: trigger_name → (ΔP, ΔA, ΔD, target_mood)
# ---------------------------------------------------------------------------
_TRIGGER_MAP = {
    "user_thank": (0.15, -0.05, 0.10, "happy"),
    "user_complaint": (-0.20, 0.15, -0.10, None),   # mood resolved dynamically
    "task_success": (0.10, 0.05, 0.15, "satisfied"),
    "task_failure": (-0.15, 0.20, -0.15, "frustrated"),
    "user_joy": (0.20, 0.10, 0.00, "excited"),
    "user_sorrow": (-0.10, -0.05, -0.05, "empathetic"),
}


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def _resolve_mood(trigger: str, pleasure: float, arousal: float, dominance: float) -> str:
    """Map PAD coordinates to a mood label."""
    if trigger == "user_complaint":
        return "anxious" if arousal > 0.6 else "sad"

    # Fallback PAD-based heuristics for unlisted triggers
    if pleasure > 0.7 and arousal > 0.6:
        return "excited"
    if pleasure > 0.6 and arousal <= 0.5:
        return "happy"
    if pleasure < 0.3 and arousal > 0.6:
        return "frustrated"
    if pleasure < 0.3 and arousal <= 0.5:
        return "sad"
    if pleasure >= 0.3 and pleasure <= 0.7 and arousal > 0.6:
        return "anxious"
    if dominance > 0.7 and pleasure >= 0.5:
        return "satisfied"
    if pleasure >= 0.4 and pleasure <= 0.6 and arousal >= 0.3 and arousal <= 0.6:
        return "calm"
    return "neutral"


def _load_affect(conn, soul_id: str) -> AffectState:
    """Load the current affect state on *conn*; seed defaults if absent.

    03-#10 兼容：种子 INSERT 加 WHERE EXISTS 守卫——soul_persona 不存在的
    幽灵 soul 不再产生 affect_state 孤儿行（FOREIGN KEY 已启用），仅返回
    内存默认值。
    """
    row = conn.execute(
        "SELECT pleasure, arousal, dominance, current_mood, mood_intensity "
        "FROM affect_state WHERE soul_id=?",
        (soul_id,),
    ).fetchone()

    if row:
        return AffectState(
            pleasure=row["pleasure"],
            arousal=row["arousal"],
            dominance=row["dominance"],
            current_mood=row["current_mood"],
            mood_intensity=row["mood_intensity"],
        )

    # Seed default — normally init_db already inserts soul_default, but
    # standalone modules may run against a fresh DB.
    ts = utc_now_iso_compact()
    default = AffectState()
    conn.execute(
        "INSERT OR IGNORE INTO affect_state(soul_id, pleasure, arousal, dominance, "
        "current_mood, mood_intensity, updated_at) "
        "SELECT ?,?,?,?,?,?,? WHERE EXISTS (SELECT 1 FROM soul_persona WHERE soul_id=?)",
        (soul_id, default.pleasure, default.arousal, default.dominance,
         default.current_mood, default.mood_intensity, ts, soul_id),
    )
    return default


def load_affect(soul_id: str) -> AffectState:
    """Load the current affect state for a soul.  If absent, seed defaults."""
    with transaction() as conn:
        return _load_affect(conn, soul_id)


def _save_affect(conn, soul_id: str, state: AffectState) -> None:
    """Persist an AffectState on the caller's connection/transaction."""
    ts = utc_now_iso_compact()
    conn.execute(
        """
        INSERT INTO affect_state(soul_id, pleasure, arousal, dominance,
                                 current_mood, mood_intensity, updated_at)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(soul_id) DO UPDATE SET
            pleasure=excluded.pleasure,
            arousal=excluded.arousal,
            dominance=excluded.dominance,
            current_mood=excluded.current_mood,
            mood_intensity=excluded.mood_intensity,
            updated_at=excluded.updated_at
        """,
        (soul_id, _clamp(state.pleasure), _clamp(state.arousal), _clamp(state.dominance),
         state.current_mood, _clamp(state.mood_intensity), ts),
    )


def save_affect(soul_id: str, state: AffectState) -> None:
    """Persist an AffectState to the affect_state table."""
    with transaction() as conn:
        _save_affect(conn, soul_id, state)


def _log_event(
    soul_id: str,
    emotion: str,
    state: AffectState,
    intensity: float,
    trigger: str | None = None,
    bound_capsule_ids: list[str] | None = None,
    conn=None,
) -> None:
    """Write a row to affect_events.

    ``conn`` 传入时在调用方事务内写入（03-#17：transition 的 load→save→log
    收进单个事务）；缺省自建事务，保持既有独立调用语义。
    """
    event_id = "aevt_" + uuid.uuid4().hex[:12]
    ts = utc_now_iso_compact()
    sql = """
        INSERT INTO affect_events(
            event_id, soul_id, emotion, pleasure, arousal, dominance,
            intensity, trigger, bound_capsule_ids, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
        """
    params = (
        event_id,
        soul_id,
        emotion,
        _clamp(state.pleasure),
        _clamp(state.arousal),
        _clamp(state.dominance),
        _clamp(intensity),
        trigger,
        json.dumps(bound_capsule_ids or []),
        ts,
    )
    if conn is not None:
        conn.execute(sql, params)
        return
    with transaction() as wconn:
        wconn.execute(sql, params)


def transition(soul_id: str, trigger: str, intensity: float = 1.0) -> AffectState:
    """
    Apply a trigger to the current affect state and return the new state.

    Rules are hard-coded in _TRIGGER_MAP.  Unknown triggers leave the state
    unchanged but still log a zero-delta event.  All PAD values are clamped
    to [0, 1].

    03-#17: load→save→log 收进单个 transaction()。此前三步独立事务，任何
    一步失败都会留下半提交状态（如 state 已改但事件缺失），且并发请求间
    的读-改-写互相覆盖；现在同一连接同一事务内完成，整体提交或整体回滚。
    """
    with transaction() as conn:
        state = _load_affect(conn, soul_id)
        rule = _TRIGGER_MAP.get(trigger)

        if rule is None:
            _log_event(soul_id, state.current_mood, state, 0.0, trigger=trigger, conn=conn)
            return state

        dP, dA, dD, forced_mood = rule
        state.pleasure = _clamp(state.pleasure + dP * intensity)
        state.arousal = _clamp(state.arousal + dA * intensity)
        state.dominance = _clamp(state.dominance + dD * intensity)

        # Mood resolution
        if forced_mood is not None:
            state.current_mood = forced_mood
        else:
            state.current_mood = _resolve_mood(trigger, state.pleasure, state.arousal, state.dominance)

        state.mood_intensity = _clamp(state.mood_intensity + 0.1 * intensity)

        _save_affect(conn, soul_id, state)
        _log_event(soul_id, state.current_mood, state, intensity, trigger=trigger, conn=conn)
        return state
