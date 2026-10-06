# Copyright (c) 2026 QianChang-official
#
# 宛委·枢忆 is licensed under Mulan PSL v2.
# You can use this software according to the terms of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
# http://license.coscl.org.cn/MulanPSL2
#
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

from pydantic import BaseModel, ConfigDict, Field
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
    production_context: dict[str, Any] | None = None
    alignment_metadata: dict[str, Any] | None = None
    relation_edges: list[dict[str, Any]] | None = None
    soul_id: str | None = Field(default=None, min_length=1, max_length=128)

class CommandLoopIn(BaseModel):
    goal: str
    scene: str = 'general'
    top_k: int = Field(default=5, ge=1, le=50)
    soul_id: str | None = Field(default=None, min_length=1, max_length=128)

class ReflectionIn(BaseModel):
    # issue #117：列表长度与 ForgetConfirmIn 对齐（旧实现无 max_length，
    # 单个 POST 即可 deprecate 全库——比对破坏力更小的 forget 通路反而
    # 有 50 条上限）。存在性与召回凭证校验在端点层完成（memory_ledger
    # op_type=retrieve 是授权依据）。
    task_id: str = Field(min_length=1, max_length=128)
    goal_achieved: bool = True
    memory_used: list[str] = Field(default_factory=list, max_length=50)
    helpful_memories: list[str] = Field(default_factory=list, max_length=50)
    misleading_memories: list[str] = Field(default_factory=list, max_length=50)
    new_preferences: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    new_knowledge: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    new_risks: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    soul_id: str | None = Field(default=None, min_length=1, max_length=128)

# v0.11 Soul Awakening schemas
class SoulConnectIn(BaseModel):
    soul_id: str | None = None

class SoulChatIn(BaseModel):
    soul_id: str
    messages: list[dict[str, Any]]
    model: str = "default"

class SoulPersonaUpdateIn(BaseModel):
    name: str | None = None
    core_traits: list[str] | None = None
    voice: str | None = None
    soul_values: list[str] | None = None
    self_narrative: str | None = None

class SoulDreamIn(BaseModel):
    # issue #117：与 ReflectionIn 同口径（同一份自我申报面，dream 通路同样
    # 会把 helpful/misleading 交给 evolution 结算）。
    soul_id: str
    task_id: str = Field(min_length=1, max_length=128)
    goal_achieved: bool = True
    memory_used: list[str] = Field(default_factory=list, max_length=50)
    helpful_memories: list[str] = Field(default_factory=list, max_length=50)
    misleading_memories: list[str] = Field(default_factory=list, max_length=50)
    new_preferences: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    new_knowledge: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    new_risks: list[dict[str, Any]] = Field(default_factory=list, max_length=20)

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


# v0.14 视觉记忆 schemas（VISTA 启发的无损视觉记忆，见 memory_visual/）
#
# 图片字节走 base64 JSON 而不是 multipart：与既有端点保持同一种请求形态，
# 8MiB 字节上限在 store 层校验（base64 解码后计），这里的 12M 字符上限
# 只是传输层粗闸（base64 膨胀率 4/3）。


class VisualWriteIn(BaseModel):
    data_base64: str = Field(min_length=1, max_length=12 * 1024 * 1024)
    caption: str = Field(min_length=1, max_length=4096)
    # current=当前观察 / historical=历史归档 / derived=派生产物（必须署名来源）。
    kind: Literal['current', 'historical', 'derived'] = 'current'
    derived_from: list[str] = Field(default_factory=list, max_length=64)
    source_type: str = Field(default='user_input', max_length=64)
    scene: str = Field(default='general', max_length=64)
    task_type: str = Field(default='planning', max_length=64)
    risk_class: Literal['low', 'medium', 'high'] = 'low'
    soul_id: str | None = Field(default=None, min_length=1, max_length=128)


class VisualRegion(BaseModel):
    model_config = ConfigDict(extra='forbid')

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(ge=1)
    height: int = Field(ge=1)


class VisualInspectView(BaseModel):
    model_config = ConfigDict(extra='forbid')

    label: str = Field(min_length=1, max_length=128)
    asset_id: str = Field(min_length=1, max_length=64)
    region: VisualRegion | None = None


class VisualInspectIn(BaseModel):
    question: str = Field(min_length=1, max_length=1024)
    views: list[VisualInspectView] = Field(min_length=1, max_length=16)
    display_size: int = Field(default=1024, ge=1, le=4096)
    soul_id: str | None = Field(default=None, min_length=1, max_length=128)


class VisualPixelView(BaseModel):
    model_config = ConfigDict(extra='forbid')

    label: str = Field(min_length=1, max_length=128)
    asset_id: str = Field(min_length=1, max_length=64)
    region: VisualRegion | None = None
    rows: int = Field(ge=1, le=4096)
    columns: int = Field(ge=1, le=4096)


class VisualReadPixelsIn(BaseModel):
    question: str = Field(min_length=1, max_length=1024)
    views: list[VisualPixelView] = Field(min_length=1, max_length=64)
    soul_id: str | None = Field(default=None, min_length=1, max_length=128)


class VisualSearchIn(BaseModel):
    """以图搜图：查询图（base64）或库内资产二选一，都填以 query_asset_id 为准。"""

    model_config = ConfigDict(extra='forbid')

    data_base64: str | None = Field(default=None, min_length=1, max_length=12 * 1024 * 1024)
    query_asset_id: str | None = Field(default=None, min_length=1, max_length=64)
    top_k: int = Field(default=20, ge=1, le=100)
    min_score: float = Field(default=0.0, ge=-1.0, le=1.0)
    soul_id: str | None = Field(default=None, min_length=1, max_length=128)


# v0.15 多模态感知层 schemas（perception/adapters + pipeline）


class PerceptionBase(BaseModel):
    session_id: str | None = Field(default=None, min_length=1, max_length=64)
    soul_id: str | None = Field(default=None, min_length=1, max_length=128)


class PerceptionImageIn(PerceptionBase):
    data_base64: str = Field(min_length=1, max_length=12 * 1024 * 1024)
    caption: str = Field(min_length=1, max_length=4096)
    kind: Literal['current', 'historical', 'derived'] = 'current'
    derived_from: list[str] = Field(default_factory=list, max_length=64)


class PerceptionAudioIn(PerceptionBase):
    data_base64: str = Field(min_length=1, max_length=48 * 1024 * 1024)
    transcribe: bool = True


class PerceptionVideoIn(PerceptionBase):
    # 两路二选一：上游已解码的 PNG 帧序列，或视频文件字节（需 OpenCV）。
    frames_base64: list[str] | None = Field(default=None, max_length=10000)
    video_base64: str | None = Field(default=None, min_length=1, max_length=128 * 1024 * 1024)
    caption: str = Field(default='视频关键帧', min_length=1, max_length=1024)
    threshold: float = Field(default=0.18, ge=0.0, le=1.0)


class SensorAlarmRule(BaseModel):
    model_config = ConfigDict(extra='forbid')

    channel: int = Field(ge=0, le=255)
    high: float
    hysteresis: float = Field(default=1.0, ge=0.0)


class PerceptionSensorIn(PerceptionBase):
    stream_base64: str = Field(min_length=1, max_length=16 * 1024 * 1024)
    alarms: list[SensorAlarmRule] = Field(default_factory=list, max_length=64)



# v0.13.x Preference Graph schemas（issue #198：偏好记忆图与偏好演化机制）
#
# 边类型用 Literal 与 memory_runtime.preference_graph.EDGE_TYPES 对齐，
# 非法边名在 Pydantic 层就 422。

class PreferenceEvolutionIn(BaseModel):
    """记录一条偏好演化边（replaces 演化 / conflicts_with 冲突标记）。"""
    new_capsule_id: str = Field(min_length=1, max_length=64)
    old_capsule_id: str = Field(min_length=1, max_length=64)
    edge_type: Literal['replaces', 'conflicts_with'] = 'replaces'
    soul_id: str | None = Field(default=None, min_length=1, max_length=128)


class PreferenceActiveSuggestIn(BaseModel):
    """对一组冲突偏好给出「当前应信谁」的建议（只建议，不执行）。"""
    capsule_ids: list[str] = Field(min_length=1, max_length=50)
    soul_id: str | None = Field(default=None, min_length=1, max_length=128)


class PreferenceCascadeForgetIn(BaseModel):
    """级联遗忘一条偏好（含 replaces 链回溯与证据边摘除）。"""
    capsule_id: str = Field(min_length=1, max_length=64)
    mode: Literal['soft_delete', 'hard_delete'] = 'soft_delete'
    soul_id: str | None = Field(default=None, min_length=1, max_length=128)


class PreferenceRerankIn(BaseModel):
    """对一批候选胶囊做 preference-aware 重排（只读，不改库）。"""
    capsule_ids: list[str] = Field(min_length=1, max_length=200)
    weight: float = Field(default=0.30, ge=0.0, le=1.0)
    top_k: int | None = Field(default=None, ge=1, le=200)
    soul_id: str | None = Field(default=None, min_length=1, max_length=128)


# v0.13.x Knowledge Evolution schemas（issue #202：知识冲突消解与知识演化）
#
# 边类型 Literal 与 memory_runtime.knowledge_evolution.KNOWLEDGE_EDGE_TYPES 对齐。

class KnowledgeConflictDetectIn(BaseModel):
    """对一条 knowledge 胶囊做四类冲突检测（只产信号，不动生命周期）。"""
    capsule_id: str = Field(min_length=1, max_length=64)
    soul_id: str | None = Field(default=None, min_length=1, max_length=128)


class KnowledgeEvolutionIn(BaseModel):
    """记录知识演化边（supersedes/invalidates 转移旧知识，derived_from/
    conflicts_with 只写边）。"""
    new_capsule_id: str = Field(min_length=1, max_length=64)
    old_capsule_id: str = Field(min_length=1, max_length=64)
    edge_type: Literal[
        'supersedes', 'conflicts_with', 'derived_from', 'invalidates',
    ] = 'supersedes'
    conflict_type: Literal['fact', 'status', 'config', 'temporal'] | None = None
    soul_id: str | None = Field(default=None, min_length=1, max_length=128)


class KnowledgeActiveSuggestIn(BaseModel):
    """对一组冲突知识建议 active knowledge（只建议，不执行）。"""
    capsule_ids: list[str] = Field(min_length=1, max_length=50)
    soul_id: str | None = Field(default=None, min_length=1, max_length=128)


class KnowledgeRerankIn(BaseModel):
    """对候选胶囊按知识版本状态加权重排（只读）。"""
    capsule_ids: list[str] = Field(min_length=1, max_length=200)
    top_k: int | None = Field(default=None, ge=1, le=200)
    soul_id: str | None = Field(default=None, min_length=1, max_length=128)


# TKE（Temporal Knowledge Evolution）schemas（issue #204：知识双时态与演化时间轴）

class KnowledgeValidTimeIn(BaseModel):
    """写入知识的 valid_time 区间（双时态的真值时间轴；None=不改该端点）。"""
    capsule_id: str = Field(min_length=1, max_length=64)
    valid_from: str | None = Field(default=None, max_length=40)
    valid_until: str | None = Field(default=None, max_length=40)
    soul_id: str | None = Field(default=None, min_length=1, max_length=128)


class KnowledgeAsOfIn(BaseModel):
    """as-of 历史回放：时刻 T 的 active knowledge。

    mode: truth=世界真值（valid_time 判定，延迟导入场景）；belief=系统
    当时认知（valid_time+transaction_time 双过滤，严格双时态）。
    """
    capsule_ids: list[str] = Field(min_length=1, max_length=200)
    at: str = Field(min_length=10, max_length=40)
    mode: Literal['truth', 'belief'] = 'truth'
    soul_id: str | None = Field(default=None, min_length=1, max_length=128)


class KnowledgeVerifyIn(BaseModel):
    """记录知识的最近验证时间（freshness 输入；缺省取当前时间）。"""
    capsule_id: str = Field(min_length=1, max_length=64)
    verified_at: str | None = Field(default=None, max_length=40)
    soul_id: str | None = Field(default=None, min_length=1, max_length=128)
