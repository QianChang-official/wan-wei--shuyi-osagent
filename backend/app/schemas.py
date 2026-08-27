from datetime import datetime, timezone
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Any, Literal

class MemoryEventIn(BaseModel):
    source_type: str
    scene: str='general'
    content: dict[str, Any]
    soul_id: str | None = Field(default=None, min_length=1, max_length=128)

class ForgetPreviewIn(BaseModel):
    instruction: str
    scope: Literal['current_user']='current_user'
    soul_id: str | None = Field(default=None, min_length=1, max_length=128)

class ForgetConfirmIn(BaseModel):
    forget_request_id: str
    confirm: bool=True
    mode: Literal['cascade', 'soft_delete', 'hard_delete']='cascade'
    capsule_ids: list[str] = Field(default_factory=list, max_length=50)
    event_ids: list[str] = Field(default_factory=list, max_length=50)

class CapsuleWriteIn(BaseModel):
    memory_class: str
    content: dict[str, Any]
    source_type: str = 'user_input'
    scene: str = 'general'
    task_type: str = 'planning'
    risk_class: str = 'low'
    write_intent: str = 'explicit'
    affects_future_behavior: bool = False
    source_trust: str = 'normal'
    provenance: dict[str, Any] | None = None
    # Explicit temporal/source fields keep the public contract usable without
    # requiring callers to construct an opaque provenance blob. They are
    # projected into provenance/state by the capsule store.
    valid_from: str | None = Field(default=None, min_length=1, max_length=64)
    valid_until: str | None = Field(default=None, min_length=1, max_length=64)
    episode_id: str | None = Field(default=None, min_length=1, max_length=128)
    source_ids: list[str] = Field(default_factory=list, max_length=50)
    evidence_ids: list[str] = Field(default_factory=list, max_length=50)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    production_context: dict[str, Any] | None = None
    alignment_metadata: dict[str, Any] | None = None
    relation_edges: list[dict[str, Any]] | None = None
    soul_id: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("valid_from", "valid_until")
    @classmethod
    def _validate_timestamp(cls, value: str | None) -> str | None:
        if value is None:
            return None
        candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            datetime.fromisoformat(candidate)
        except ValueError as exc:
            raise ValueError("must be an ISO-8601 timestamp") from exc
        return value

    @field_validator("source_ids", "evidence_ids")
    @classmethod
    def _validate_provenance_ids(cls, values: list[str]) -> list[str]:
        for value in values:
            if not isinstance(value, str) or not value.strip() or len(value) > 128:
                raise ValueError("provenance ids must be non-empty strings <= 128 chars")
        return values

    @staticmethod
    def _parse_timestamp(value: str) -> datetime:
        candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(candidate)
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)

    @model_validator(mode="after")
    def _validate_validity_window(self):
        if self.valid_from and self.valid_until:
            start = self._parse_timestamp(self.valid_from)
            end = self._parse_timestamp(self.valid_until)
            if end < start:
                raise ValueError("valid_until must be greater than or equal to valid_from")
        return self

class CommandLoopIn(BaseModel):
    goal: str
    scene: str = 'general'
    top_k: int = Field(default=5, ge=1, le=50)
    soul_id: str | None = Field(default=None, min_length=1, max_length=128)

class ReflectionIn(BaseModel):
    task_id: str
    goal_achieved: bool = True
    memory_used: list[str] = Field(default_factory=list)
    helpful_memories: list[str] = Field(default_factory=list)
    misleading_memories: list[str] = Field(default_factory=list)
    new_preferences: list[dict[str, Any]] = Field(default_factory=list)
    new_knowledge: list[dict[str, Any]] = Field(default_factory=list)
    new_risks: list[dict[str, Any]] = Field(default_factory=list)
    soul_id: str | None = Field(default=None, min_length=1, max_length=128)

# v0.11 Soul Awakening schemas
class SoulConnectIn(BaseModel):
    soul_id: str | None = None

class SoulChatIn(BaseModel):
    soul_id: str
    messages: list[dict[str, Any]]
    model: str = "default"
    # Optional explicit provider selection.  ``default`` preserves the
    # existing client contract while allowing the configured cockpit provider
    # to be selected without sending credentials through the UI.
    provider: str = "default"

class SoulPersonaUpdateIn(BaseModel):
    name: str | None = None
    core_traits: list[str] | None = None
    voice: str | None = None
    soul_values: list[str] | None = None
    self_narrative: str | None = None

class SoulDreamIn(BaseModel):
    soul_id: str
    task_id: str
    goal_achieved: bool = True
    memory_used: list[str] = Field(default_factory=list)
    helpful_memories: list[str] = Field(default_factory=list)
    misleading_memories: list[str] = Field(default_factory=list)
    new_preferences: list[dict[str, Any]] = Field(default_factory=list)
    new_knowledge: list[dict[str, Any]] = Field(default_factory=list)
    new_risks: list[dict[str, Any]] = Field(default_factory=list)

# v0.12 Memory tier management schemas (#56)
class TierTransitionIn(BaseModel):
    capsule_id: str = Field(min_length=1, max_length=64)
    to_tier: Literal['working', 'short_term', 'medium_term', 'long_term']
    reason: str = Field(default='manual', max_length=256)
    soul_id: str | None = Field(default=None, min_length=1, max_length=128)

class TierAutoFlowIn(BaseModel):
    soul_id: str | None = Field(default=None, min_length=1, max_length=128)
    limit: int = Field(default=500, ge=1, le=5000)

# v0.13 MemoryOS 治理层 schemas（规范来源: AI优化/MemoryOS-*.md）
#
# to_state 用 Literal 而不是自由字符串：非法状态名在 Pydantic 层就 422，
# 不必等进到状态机才报错，也避免把内部状态词表暴露成可任意输入的字段。
LifecycleStateName = Literal[
    'candidate', 'active', 'reinforced', 'stale', 'conflicted',
    'deprecated', 'quarantined', 'rejected', 'forgotten', 'deleted',
]


class LifecycleTransitionIn(BaseModel):
    capsule_id: str = Field(min_length=1, max_length=64)
    to_state: LifecycleStateName
    reason: str = Field(default='manual', max_length=256)
    soul_id: str | None = Field(default=None, min_length=1, max_length=128)


class LifecycleConfirmIn(BaseModel):
    capsule_id: str = Field(min_length=1, max_length=64)
    reason: str = Field(default='human_confirmed', max_length=256)
    soul_id: str | None = Field(default=None, min_length=1, max_length=128)


class LifecycleResolveConflictIn(BaseModel):
    winner_capsule_id: str = Field(min_length=1, max_length=64)
    loser_capsule_id: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=256)
    # 默认归档败方而非删除：裁决失败的一方保留下来才有「当初为什么这么判」
    # 的现场证据（与 memoryos.lifecycle.resolve_conflict 的默认值一致）。
    loser_state: Literal['deprecated', 'forgotten'] = 'deprecated'
    soul_id: str | None = Field(default=None, min_length=1, max_length=128)


class LifecycleScanStaleIn(BaseModel):
    # idle_days 省略时用 WANWEI_LIFECYCLE_STALE_IDLE_DAYS（默认 0 = 只按
    # valid_until 判过期，不做闲置降权）。
    idle_days: float | None = Field(default=None, ge=0, le=3650)
    limit: int = Field(default=500, ge=1, le=5000)
    soul_id: str | None = Field(default=None, min_length=1, max_length=128)


class MemoryIncidentIn(BaseModel):
    mhg_level: int = Field(ge=1, le=5)
    incident_type: Literal[
        'leakage', 'poisoning', 'deletion_failure', 'conflict_escalation', 'other',
    ]
    description: str = Field(default='', max_length=2000)
    capsule_id: str | None = Field(default=None, min_length=1, max_length=64)
    detected_by: Literal['policy_gate', 'red_team', 'user_report', 'system'] = 'system'


class MemoryHealthSnapshotIn(BaseModel):
    # source 是自由文本标签（谁触发的这次采样），受控词表没有意义——
    # 未来的调用方会有 'cron:nightly'、'meb:full'、运维手动等各种来源。
    # 但仍然限长，避免把趋势表当日志用。
    source: str = Field(default='manual', min_length=1, max_length=64)
    soul_id: str | None = Field(default=None, min_length=1, max_length=128)
