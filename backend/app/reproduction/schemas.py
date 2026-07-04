from pydantic import BaseModel
from typing import Any


class HippoRecallIn(BaseModel):
    query: str
    top_k: int = 5
    hops: int = 2


class RetentionSimulateIn(BaseModel):
    capsule_id: str | None = None
    action: str = "recall"
    days: int = 7
    importance: float = 0.7
    memory_strength: float = 0.8
    recall_count: int = 0


class ReflexionEvaluateIn(BaseModel):
    task_id: str
    goal_achieved: bool = True
    used_memories: list[str] = []
    evidence_cards: list[dict[str, Any]] = []
    notes: str = ""


class MemoryToolDryRunIn(BaseModel):
    tool_name: str
    payload: dict[str, Any] = {}
