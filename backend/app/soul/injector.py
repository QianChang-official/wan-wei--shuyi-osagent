"""Soul injection prompt builder and soul state aggregator.

安全边界：本模块把核心记忆拼进模型「系统提示」（route_chat 以 system 角色注入），
是记忆重注入的最高危面。因此 _get_core_memories 的 SQL 过滤必须与
capsule_store.allowed_for_context 的治理判定保持同步——policy_result 白名单、
sensitivity_level(S3) 排除、lifecycle 白名单三者缺一不可。任何放宽此过滤的改动
（新增可检索状态、调整白名单）都须同步这两处，否则被 policy-gate 隔离的投毒/
提示注入记忆会绕过治理直接进入系统提示。见 test_mission_b 的隔离回归测试。
"""

import json
from typing import Any

from ..db import get_conn
from ..security.redaction import redact_capsule_for_output, redact_sensitive_text
from ..utils.datetime_utils import utc_now_iso_compact


_FILTERED_INJECTION_PROMPT = "你是枢忆。（系统提示因安全策略被过滤）"


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

    # 03-#11: 用 is None 判断代替 `row["x"] or 默认值`——0.0 是合法 PAD 值，
    # `or` 会把显式存储的 0.0 错误替换为默认值。
    return {
        "pleasure": _clamp01(row["pleasure"] if row["pleasure"] is not None else 0.5),
        "arousal": _clamp01(row["arousal"] if row["arousal"] is not None else 0.4),
        "dominance": _clamp01(row["dominance"] if row["dominance"] is not None else 0.5),
        "current_mood": row["current_mood"] if row["current_mood"] is not None else "calm",
        "mood_intensity": _clamp01(row["mood_intensity"] if row["mood_intensity"] is not None else 0.3),
        "updated_at": row["updated_at"],
    }


def _get_core_memories(soul_id: str, limit: int = 10) -> list[dict]:
    """Fetch top-N capsules by importance_score for this soul.

    按 provenance.soul_id 过滤，确保多 soul 场景记忆不互串。
    旧数据（provenance 不含 soul_id）作为回退返回，但排序靠后——
    新写入应在 provenance 中标记 soul_id（intake.py 已接入）。
    """
    try:
        owner_row = get_conn().execute(
            "SELECT owner_id FROM soul_persona WHERE soul_id=?",
            (soul_id,),
        ).fetchone()
        if owner_row is None or not owner_row["owner_id"]:
            return []
        owner_id = str(owner_row["owner_id"])
        rows = get_conn().execute(
            """SELECT capsule_id, content, state, governance
               FROM memory_capsules_v2
               WHERE json_extract(provenance, '$.owner_id') = ?
                 AND (json_extract(provenance, '$.soul_id') = ?
                       OR json_extract(provenance, '$.soul_id') IS NULL)
                 AND json_extract(state, '$.importance_score') IS NOT NULL
                 -- 治理隔离：与 capsule_store.allowed_for_context 对齐。
                 -- soul 注入会把记忆写入模型「系统提示」，是最高危的重注入面；
                 -- 若不做此过滤，被 policy-gate 判为 quarantine/require_confirmation
                 -- 的投毒/提示注入记忆（仍带 importance_score）会绕过治理直接进系统提示。
                 -- RETRIEVABLE_POLICY={allow,redact} / RETRIEVABLE_LIFECYCLE={active,reinforced,conflicted}
                 AND json_extract(governance, '$.policy_result') IN ('allow', 'redact')
                 AND (json_extract(governance, '$.sensitivity_level') IS NULL
                       OR json_extract(governance, '$.sensitivity_level') != 'S3')
                 AND json_extract(state, '$.lifecycle') IN ('active', 'reinforced', 'conflicted')
               ORDER BY CASE WHEN json_extract(provenance, '$.soul_id') = ? THEN 0 ELSE 1 END,
                        json_extract(state, '$.importance_score') DESC
               LIMIT ?""",
            (owner_id, soul_id, soul_id, limit),
        ).fetchall()
    except Exception:
        return []

    memories = []
    for row in rows:
        capsule = redact_capsule_for_output({
            "capsule_id": row["capsule_id"],
            "content": _loads(row["content"], {}),
            "state": _loads(row["state"], {}),
            "governance": _loads(row["governance"], {}),
        })
        state = capsule["state"]
        content = capsule["content"]
        governance = capsule["governance"]
        text = content.get("text") or content.get("summary") or str(content)[:200]
        policy_result = governance.get("policy_result", "allow")
        memories.append({
            "capsule_id": capsule["capsule_id"],
            "text": text,
            "importance_score": _clamp01(state.get("importance_score", 0.0)),
            "policy_result": policy_result,
        })
    return memories


def build_injection_prompt(soul_id: str) -> str:
    """Assemble the soul injection prompt string for a given soul.

    FIX-01/02（04-#09）：拼接后整体过闸，防拆分载荷绕过 + persona 零过滤。
    单条记忆/persona 字段可能各自合法，但拼接后整体可能是提示注入/投毒。
    在返回前对整体字符串跑 evaluate_policy，命中 quarantine/reject 即降级
    为占位文本，防止系统提示被污染。
    """
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
    memory_parts = [f"• {memory['text']}" for memory in core_memories]
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

    assembled = "\n".join(lines)

    # FIX-01/02: 拼接后整体过闸
    from backend.app.memory_runtime.policy_gate import evaluate_policy

    policy = evaluate_policy(
        text=assembled,
        source_type="system_injection",  # 系统提示注入面，高危
        write_intent="explicit",
        affects_future_behavior=True,  # 系统提示影响后续所有回复
        source_trust="normal",
        memory_class="context",
    )

    if policy["policy_result"] in ("quarantine", "reject"):
        # Never reuse persona data in the fallback: existing databases may
        # contain values written before the persona policy gate existed.
        return _FILTERED_INJECTION_PROMPT
    if policy["policy_result"] == "redact":
        return redact_sensitive_text(assembled)

    return assembled


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
        # 同 03-#11：baseline 允许显式 0.0，只有 NULL 才回退默认值
        "baseline_pleasure": _clamp01(row["baseline_pleasure"] if row["baseline_pleasure"] is not None else 0.5),
        "baseline_arousal": _clamp01(row["baseline_arousal"] if row["baseline_arousal"] is not None else 0.5),
        "baseline_dominance": _clamp01(row["baseline_dominance"] if row["baseline_dominance"] is not None else 0.5),
    }

    affect = _get_affect(soul_id)
    core_memories = _get_core_memories(soul_id, limit=10)

    return {
        "soul_id": soul_id,
        "persona": persona,
        "affect": affect,
        "core_memories": core_memories,
    }
