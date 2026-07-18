"""
Affect decay daemon.

Slowly pulls PAD values back toward the soul's baseline personality traits
and attenuates mood_intensity over time.  Intended to run as a background
thread inside the FastAPI lifespan.
"""

import threading
import time

from ..db import get_conn
from ..utils.datetime_utils import utc_now_iso_compact
from .state_machine import AffectState, save_affect, _clamp


def decay_affect(soul_id: str) -> AffectState:
    """
    Execute a single decay step for *one* soul.

    Algorithm:
        pleasure    += (baseline_p - pleasure)    * 0.15
        arousal     += (baseline_a - arousal)     * 0.20
        mood_intensity *= 0.85

    Returns the updated AffectState.
    """
    conn = get_conn()

    # Load baseline from soul_persona
    baseline = conn.execute(
        "SELECT baseline_pleasure, baseline_arousal, baseline_dominance "
        "FROM soul_persona WHERE soul_id=?",
        (soul_id,),
    ).fetchone()

    if baseline is None:
        # Soul does not exist — nothing to decay
        return AffectState()

    baseline_p = baseline["baseline_pleasure"] or 0.6
    baseline_a = baseline["baseline_arousal"] or 0.4
    baseline_d = baseline["baseline_dominance"] or 0.5

    # Load current affect
    row = conn.execute(
        "SELECT pleasure, arousal, dominance, current_mood, mood_intensity "
        "FROM affect_state WHERE soul_id=?",
        (soul_id,),
    ).fetchone()

    if row is None:
        # Seed default state
        ts = utc_now_iso_compact()
        state = AffectState(
            pleasure=baseline_p, arousal=baseline_a, dominance=baseline_d
        )
        conn.execute(
            "INSERT INTO affect_state(soul_id, pleasure, arousal, dominance, "
            "current_mood, mood_intensity, updated_at) VALUES (?,?,?,?,?,?,?)",
            (soul_id, state.pleasure, state.arousal, state.dominance,
             state.current_mood, state.mood_intensity, ts),
        )
        conn.commit()
        return state

    pleasure = row["pleasure"]
    arousal = row["arousal"]
    dominance = row["dominance"]
    mood_intensity = row["mood_intensity"]

    # Decay toward baseline
    pleasure = _clamp(pleasure + (baseline_p - pleasure) * 0.15)
    arousal = _clamp(arousal + (baseline_a - arousal) * 0.20)
    dominance = _clamp(dominance + (baseline_d - dominance) * 0.15)
    mood_intensity = _clamp(mood_intensity * 0.85)

    # Mood drifts toward calm as intensity fades
    current_mood = row["current_mood"]
    if mood_intensity < 0.15 and current_mood not in ("calm", "neutral"):
        current_mood = "calm"

    state = AffectState(
        pleasure=pleasure,
        arousal=arousal,
        dominance=dominance,
        current_mood=current_mood,
        mood_intensity=mood_intensity,
    )
    save_affect(soul_id, state)
    return state


def _decay_all_souls() -> None:
    """Decay every soul that has an affect_state row."""
    conn = get_conn()
    rows = conn.execute("SELECT soul_id FROM affect_state").fetchall()
    for row in rows:
        try:
            decay_affect(row["soul_id"])
        except Exception:
            # Never let one soul's decay kill the daemon
            pass


def run_decay_daemon(interval_seconds: int = 1800, stop_event: threading.Event | None = None) -> None:
    """
    Blocking decay loop.  Call from a daemon thread.

    Example (inside FastAPI lifespan):
        stop = threading.Event()
        t = threading.Thread(target=lambda: run_decay_daemon(1800, stop), daemon=True)
        t.start()
        ...
        stop.set()
    """
    stop_event = stop_event or threading.Event()
    while not stop_event.is_set():
        stop_event.wait(timeout=interval_seconds)
        if stop_event.is_set():
            break
        try:
            _decay_all_souls()
        except Exception:
            # Log failure silently; the daemon must survive DB hiccups.
            pass
