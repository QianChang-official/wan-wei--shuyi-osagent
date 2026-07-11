from pydantic import BaseModel, Field
from typing import Any, Literal

class MemoryEventIn(BaseModel):
    source_type: str
    scene: str='general'
    content: dict[str, Any]

class ForgetPreviewIn(BaseModel):
    instruction: str
    scope: Literal['current_user']='current_user'

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

class CommandLoopIn(BaseModel):
    goal: str
    scene: str = 'general'
    top_k: int = Field(default=5, ge=1, le=50)

class ReflectionIn(BaseModel):
    task_id: str
    goal_achieved: bool = True
    memory_used: list[str] = Field(default_factory=list)
    helpful_memories: list[str] = Field(default_factory=list)
    misleading_memories: list[str] = Field(default_factory=list)
    new_preferences: list[dict[str, Any]] = Field(default_factory=list)
    new_knowledge: list[dict[str, Any]] = Field(default_factory=list)
    new_risks: list[dict[str, Any]] = Field(default_factory=list)
