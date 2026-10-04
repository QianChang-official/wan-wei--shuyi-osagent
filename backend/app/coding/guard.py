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

"""万枢编程框架 —— 循环护栏（loop hygiene）。

参照 deepseek-harness 的 ``guard`` 包：智能体循环最大的工程风险不是"不
够聪明"，而是**失控**——无限循环、工具风暴、同一步骤反复重试同一调用。
本模块为单次 run 建立一份预算账本，越界即抛 ``GuardTripped``，由编排器
捕获、落 ``guard_tripped`` 事件并中止（而非静默卡死）。

四道闸：

1. **轮次预算**（``max_iterations``）：一次 run 的"思考-行动"轮数上限。
2. **工具调用预算**（``max_tool_calls``）：工具调用总数上限。
3. **重复调用熔断**（``duplicate_limit``）：同一工具 + 同一参数连续重复
   达阈值即熔断，专治"LLM 卡在同一个无效调用上"。
4. **工具超时**：单次工具调用的墙钟上限（由 ``sandbox.run_command`` 落实，
   编排器统一转 ``timeout`` 状态）。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from . import constants


class GuardTripped(RuntimeError):
    """护栏触发。``reason`` 为机器可读码，供事件流与前端展示。"""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
        self.message = message


def _fingerprint(tool_id: str, params: dict[str, Any]) -> str:
    try:
        payload = json.dumps(params, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        payload = repr(params)
    return f'{tool_id}:{hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]}'


@dataclass
class GuardState:
    """单次 run 的预算账本。"""

    max_iterations: int = constants.DEFAULT_MAX_ITERATIONS
    max_tool_calls: int = constants.DEFAULT_MAX_TOOL_CALLS
    duplicate_limit: int = constants.DEFAULT_DUPLICATE_LIMIT
    iterations: int = 0
    tool_calls: int = 0
    _repeat: dict[str, int] = field(default_factory=dict)

    # ---- 计数 ----------------------------------------------------------

    def begin_iteration(self) -> int:
        self.iterations += 1
        if self.iterations > self.max_iterations:
            raise GuardTripped(
                'iteration_budget',
                f'已达轮次上限 {self.max_iterations}，主动中止以防失控循环',
            )
        return self.iterations

    def begin_tool_call(self) -> int:
        self.tool_calls += 1
        if self.tool_calls > self.max_tool_calls:
            raise GuardTripped(
                'tool_budget',
                f'已达工具调用上限 {self.max_tool_calls}，主动中止',
            )
        return self.tool_calls

    def note_tool_call(self, tool_id: str, params: dict[str, Any]) -> None:
        """记录一次工具调用，命中重复阈值即熔断。"""
        key = _fingerprint(tool_id, params)
        self._repeat[key] = self._repeat.get(key, 0) + 1
        if self._repeat[key] >= self.duplicate_limit:
            raise GuardTripped(
                'duplicate_call',
                f'工具 {tool_id} 以相同参数重复调用 {self._repeat[key]} 次，判定为无效循环并熔断',
            )

    def note_progress(self) -> None:
        """任何"有实质进展"的动作调用它清空重复计数（例如步骤状态推进）。"""
        self._repeat.clear()

    def snapshot(self) -> dict[str, Any]:
        return {
            'iterations': self.iterations,
            'max_iterations': self.max_iterations,
            'tool_calls': self.tool_calls,
            'max_tool_calls': self.max_tool_calls,
            'duplicate_limit': self.duplicate_limit,
            'repeat_watch': len(self._repeat),
        }
