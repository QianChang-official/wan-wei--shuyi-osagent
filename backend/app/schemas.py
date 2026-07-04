from pydantic import BaseModel
from typing import Any

class MemoryEventIn(BaseModel):
    source_type: str
    scene: str='general'
    content: dict[str, Any]

class ForgetPreviewIn(BaseModel):
    instruction: str
    scope: str='current_user'

class ForgetConfirmIn(BaseModel):
    forget_request_id: str
    confirm: bool=True
    mode: str='cascade'

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
    top_k: int = 5

class ReflectionIn(BaseModel):
    task_id: str
    goal_achieved: bool = True
    memory_used: list[str] = []
    helpful_memories: list[str] = []
    misleading_memories: list[str] = []
    new_preferences: list[dict[str, Any]] = []
    new_knowledge: list[dict[str, Any]] = []
    new_risks: list[dict[str, Any]] = []
