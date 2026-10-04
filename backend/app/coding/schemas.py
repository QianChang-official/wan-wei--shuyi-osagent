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

"""万枢编程框架 —— API 请求/响应模型。

约定与 ``platform_api`` 其余舱位一致：请求体做严格校验（长度、取值域、
正则），响应体顶层平铺，便于前端直用。
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from . import constants


class SessionCreateIn(BaseModel):
    title: str = Field(default='', max_length=120)
    task: str = Field(min_length=1, max_length=4000)
    workspace: str = Field(min_length=1, max_length=1024)
    policy_mode: Literal['readonly', 'supervised', 'trusted'] = 'supervised'
    provider_pid: str = Field(default='', max_length=64)

    @field_validator('title', 'task', 'workspace', mode='before')
    @classmethod
    def _strip(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class PlanGenerateIn(BaseModel):
    use_llm: bool = False
    max_steps: int = Field(default=6, ge=1, le=12)


class PlanConfirmIn(BaseModel):
    approved: bool = True


class ToolInvokeIn(BaseModel):
    tool_id: str = Field(min_length=1, max_length=64)
    params: dict[str, Any] = Field(default_factory=dict)


class ApprovalResolveIn(BaseModel):
    approved: bool = True
    note: str = Field(default='', max_length=500)


class TodoAddIn(BaseModel):
    items: list[str] = Field(default_factory=list, max_length=50)


class TodoUpdateIn(BaseModel):
    state: Literal['pending', 'doing', 'done', 'blocked']
    note: str = Field(default='', max_length=500)


class SubagentRunIn(BaseModel):
    role: Literal['explorer', 'reviewer', 'tester', 'implementer']
    task: str = Field(min_length=1, max_length=2000)


class MemoryWriteIn(BaseModel):
    kind: Literal['decision', 'pitfall', 'convention', 'context'] = 'context'
    title: str = Field(default='', max_length=160)
    text: str = Field(min_length=1, max_length=4000)


class WorkflowNodeIn(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    title: str = Field(default='', max_length=160)
    kind: Literal['tool', 'subagent', 'noop'] = 'noop'
    payload: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)


class WorkflowRunIn(BaseModel):
    nodes: list[WorkflowNodeIn] = Field(default_factory=list)
    concurrency: int = Field(default=constants.DEFAULT_WORKFLOW_CONCURRENCY, ge=1,
                             le=constants.MAX_WORKFLOW_CONCURRENCY)
