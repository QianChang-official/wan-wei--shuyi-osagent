from pydantic import BaseModel, Field
from typing import Any


class ReasoningDepthSimulateIn(BaseModel):
    mode: str = "normal"
    task_type: str = "architecture_review"
    task_risk: str = "medium"


class RedQueenEvaluateIn(BaseModel):
    agent_output: str = ""
    utility_epoch: str = "epoch_v091"
    adversarial_objective: str = "find weak assumptions"
    metrics: dict[str, Any] = Field(default_factory=dict)


class InterrogationAnswerIn(BaseModel):
    question_id: str
    detail_level: str = "deep"
    context: str = ""


class VisualChecklistIn(BaseModel):
    route: str = "/console/#/deepening"
    page_name: str = "DeepeningView"
    api_paths: list[str] = Field(default_factory=list)
    fallback_mode: bool = True
