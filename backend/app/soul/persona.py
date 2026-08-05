"""Persona CRUD for soul_persona and affect_state."""

import json
import sqlite3
import uuid
from typing import Any

from ..db import get_conn, transaction
from ..utils.datetime_utils import utc_now_iso_compact
from .ownership import SoulAccessDenied, configured_actor_id


class PersonaStoreError(RuntimeError):
    """persona 写库失败。03-#6：不再把异常吞掉后返回旧值/sid 假成功，
    由调用方（API 层）转换为显式错误响应。"""


class PersonaPolicyViolation(ValueError):
    """A prompt-facing persona update was rejected by the policy gate."""

    def __init__(self, field: str, policy: dict[str, Any]) -> None:
        super().__init__(f"persona field {field!r} violates the memory policy")
        self.field = field
        self.policy_result = str(policy["policy_result"])
        self.risk_tags = list(policy.get("risk_tags", []))
        self.sensitivity_level = policy.get("sensitivity_level")


_PROMPT_FIELDS = ("name", "core_traits", "voice", "soul_values", "self_narrative")


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


def _persona_field_text(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return "\n".join(str(item) for item in value if item is not None)
    return "" if value is None else str(value)


def _evaluate_persona_text(field: str, text: str) -> None:
    if not text:
        return

    from ..memory_runtime.policy_gate import evaluate_policy

    policy = evaluate_policy(
        text=text,
        source_type="persona_update",
        write_intent="explicit",
        affects_future_behavior=True,
        source_trust="normal",
        memory_class="context",
    )
    if policy["policy_result"] in {"quarantine", "reject"}:
        raise PersonaPolicyViolation(field, policy)


def _validate_prompt_fields(fields: dict[str, Any]) -> None:
    changed_prompt_fields: list[str] = []
    for field in _PROMPT_FIELDS:
        if field not in fields:
            continue
        text = _persona_field_text(fields[field])
        _evaluate_persona_text(field, text)
        if text:
            changed_prompt_fields.append(f"{field}: {text}")

    # A payload can be split across two otherwise-benign persona fields just
    # as it can be split across memories. Check the complete update as well.
    if len(changed_prompt_fields) > 1:
        _evaluate_persona_text("persona_fields", "\n".join(changed_prompt_fields))


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
    """Update allowed persona fields and bump updated_at.

    All five prompt-facing fields are checked separately and as one assembled
    update before serialization. This closes both direct and split-field
    injection paths while leaving affect baselines independent.
    """
    allowed = {
        "name", "core_traits", "voice", "soul_values",
        "self_narrative", "baseline_pleasure", "baseline_arousal", "baseline_dominance",
    }
    accepted_fields = {key: value for key, value in fields.items() if key in allowed}
    if not accepted_fields:
        return get_persona(soul_id) or {}

    _validate_prompt_fields(accepted_fields)

    updates = {}
    for k, v in accepted_fields.items():
        if k in {"core_traits", "soul_values"}:
            updates[k] = _dumps(list(v or []))
        elif k in {"baseline_pleasure", "baseline_arousal", "baseline_dominance"}:
            updates[k] = _clamp01(v)
        else:
            updates[k] = v

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


def create_persona(soul_id: str | None = None, *, owner_id: str | None = None) -> str:
    """Create a new soul persona and its affect_state row."""
    sid = soul_id or ("soul_" + uuid.uuid4().hex[:12])
    resolved_owner_id = owner_id or configured_actor_id()
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
                    soul_id, owner_id, name, core_traits, voice, soul_values,
                    self_narrative, baseline_pleasure, baseline_arousal,
                    baseline_dominance, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    sid, resolved_owner_id, defaults["name"], defaults["core_traits"], defaults["voice"],
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
        # Idempotency is owner-scoped.  Treating any existing soul_id as a
        # successful create would let a second principal attach to that Soul.
        row = get_conn().execute(
            "SELECT owner_id FROM soul_persona WHERE soul_id=?",
            (sid,),
        ).fetchone()
        if row is not None and row["owner_id"] == resolved_owner_id:
            return sid
        if row is not None:
            raise SoulAccessDenied(sid) from exc
        raise PersonaStoreError(f"create_persona conflict for soul_id={sid!r}") from exc
    except Exception as exc:
        # 03-#6：不再一律返回 sid 假成功（行可能并未落库），显式抛错。
        raise PersonaStoreError(f"create_persona failed for soul_id={sid!r}") from exc

    return sid
