"""
Emotion–memory binding layer.

Attaches affect metadata to memory capsules and tunes emotional weight
for retrieval prioritisation.
"""

import json

from ..db import get_conn
from ..utils.datetime_utils import utc_now_iso_compact
from .state_machine import AffectState


def bind_emotion_to_capsule(
    capsule_id: str,
    soul_id: str,
    affect: AffectState,
) -> None:
    """
    Write or merge affective metadata into a memory_capsules_v2 row.

    The affective_metadata JSON column is updated with the current PAD state
    and a timestamp.  Existing keys are preserved unless overwritten.
    """
    conn = get_conn()
    row = conn.execute(
        "SELECT affective_metadata FROM memory_capsules_v2 WHERE capsule_id=?",
        (capsule_id,),
    ).fetchone()

    metadata = {}
    if row and row["affective_metadata"]:
        try:
            metadata = json.loads(row["affective_metadata"])
        except json.JSONDecodeError:
            metadata = {}

    ts = utc_now_iso_compact()
    metadata.update({
        "soul_id": soul_id,
        "pleasure": affect.pleasure,
        "arousal": affect.arousal,
        "dominance": affect.dominance,
        "current_mood": affect.current_mood,
        "mood_intensity": affect.mood_intensity,
        "bound_at": ts,
    })

    conn.execute(
        "UPDATE memory_capsules_v2 SET affective_metadata=?, updated_at=? WHERE capsule_id=?",
        (json.dumps(metadata, ensure_ascii=False), ts, capsule_id),
    )
    conn.commit()


def apply_emotional_weight(capsule_id: str, weight: float) -> None:
    """
    Set the emotional_weight column on a memory capsule.

    Weight is clamped to [0, 1] and persisted alongside an updated_at stamp.
    """
    conn = get_conn()
    clamped = max(0.0, min(1.0, weight))
    ts = utc_now_iso_compact()
    conn.execute(
        "UPDATE memory_capsules_v2 SET emotional_weight=?, updated_at=? WHERE capsule_id=?",
        (clamped, ts, capsule_id),
    )
    conn.commit()
