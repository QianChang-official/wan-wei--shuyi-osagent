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
