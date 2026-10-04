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

"""万枢编程框架 —— 计划模式与待办。

借鉴 wenflow「先澄清目标、路径须经用户显式确认后才启动」的做法，
本模块把「计划」建模为一等公民：

- ``Plan``：有序 ``PlanStep`` 序列 + 确认位。生成后处于 ``awaiting``，
  未经 ``confirm_plan`` 不允许进入执行（编排器强制）。
- ``Todo``：更细粒度的清单项，状态机 ``pending/doing/done/blocked``。
- 状态转移由本模块唯一裁决（``set_step_state`` / ``set_todo_state``），
  非法转移抛 ``PlanError``，与 ``memoryos.lifecycle`` 同源思想。

``generate_plan`` 提供**确定性**的启发式规划（离线可跑、测试可断言），
当模型网关可用时编排器可用 LLM 覆盖步骤标题——但"确认门"始终保留。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from . import constants


class PlanError(ValueError):
    """非法计划/待办状态转移。调用方映射为 422。"""


def _new_id(prefix: str) -> str:
    return f'{prefix}_{uuid.uuid4().hex[:10]}'


# ---------------------------------------------------------------------------
# 计划
# ---------------------------------------------------------------------------


@dataclass
class PlanStep:
    id: str
    title: str
    detail: str = ''
    tool_hint: str = ''
    state: str = 'pending'
    result: str = ''

    def public(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'title': self.title,
            'detail': self.detail,
            'tool_hint': self.tool_hint,
            'state': self.state,
            'state_label': constants.STEP_STATE_LABELS.get(self.state, self.state),
            'result': self.result,
        }


@dataclass
class Plan:
    steps: list[PlanStep] = field(default_factory=list)
    confirmed: bool = False
    source: str = 'heuristic'     # heuristic / llm / manual
    rationale: str = ''

    def public(self) -> dict[str, Any]:
        done = sum(1 for s in self.steps if s.state == 'done')
        return {
            'steps': [s.public() for s in self.steps],
            'confirmed': self.confirmed,
            'source': self.source,
            'rationale': self.rationale,
            'total': len(self.steps),
            'done': done,
            'progress': round(done / len(self.steps), 3) if self.steps else 0.0,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Plan:
        steps = [
            PlanStep(
                id=str(s.get('id') or _new_id('step')),
                title=str(s.get('title', '')),
                detail=str(s.get('detail', '')),
                tool_hint=str(s.get('tool_hint', '')),
                state=str(s.get('state', 'pending')),
                result=str(s.get('result', '')),
            )
            for s in (data.get('steps') or [])
        ]
        return cls(
            steps=steps,
            confirmed=bool(data.get('confirmed', False)),
            source=str(data.get('source', 'heuristic')),
            rationale=str(data.get('rationale', '')),
        )


def set_step_state(plan: Plan, step_id: str, state: str, *, result: str = '') -> PlanStep:
    """按状态机更新步骤状态；非法转移抛 ``PlanError``。"""
    step = next((s for s in plan.steps if s.id == step_id), None)
    if step is None:
        raise PlanError(f'步骤不存在：{step_id}')
    if state not in constants.STEP_STATES:
        raise PlanError(f'非法步骤状态：{state}')
    allowed = constants.STEP_TRANSITIONS.get(step.state, ())
    if state != step.state and state not in allowed:
        raise PlanError(f'非法转移：{step.state} → {state}')
    step.state = state
    if result:
        step.result = result
    return step


def confirm_plan(plan: Plan, *, approved: bool = True) -> Plan:
    """人工确认计划。拒绝则清空确认位，会话退回可重新规划。"""
    plan.confirmed = bool(approved)
    if not approved:
        for step in plan.steps:
            step.state = 'pending'
            step.result = ''
    return plan


# ---------------------------------------------------------------------------
# 待办
# ---------------------------------------------------------------------------


@dataclass
class Todo:
    id: str
    text: str
    state: str = 'pending'
    note: str = ''

    def public(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'text': self.text,
            'state': self.state,
            'state_label': constants.TODO_STATE_LABELS.get(self.state, self.state),
            'note': self.note,
        }


_TODO_TRANSITIONS: dict[str, tuple[str, ...]] = {
    'pending': ('doing', 'blocked', 'done'),
    'doing': ('done', 'blocked', 'pending'),
    'blocked': ('doing', 'pending'),
    'done': ('pending',),
}


def set_todo_state(todos: list[Todo], todo_id: str, state: str, *, note: str = '') -> Todo:
    todo = next((t for t in todos if t.id == todo_id), None)
    if todo is None:
        raise PlanError(f'待办不存在：{todo_id}')
    if state not in constants.TODO_STATES:
        raise PlanError(f'非法待办状态：{state}')
    allowed = _TODO_TRANSITIONS.get(todo.state, ())
    if state != todo.state and state not in allowed:
        raise PlanError(f'非法转移：{todo.state} → {state}')
    todo.state = state
    if note:
        todo.note = note
    return todo


def make_todos(items: list[str]) -> list[Todo]:
    return [Todo(id=_new_id('todo'), text=str(t).strip()) for t in items if str(t).strip()]


# ---------------------------------------------------------------------------
# 启发式规划器（确定性、离线可用）
# ---------------------------------------------------------------------------

_LANG_BY_SUFFIX = {
    '.py': 'Python', '.ts': 'TypeScript', '.tsx': 'TypeScript', '.js': 'JavaScript',
    '.vue': 'Vue', '.go': 'Go', '.rs': 'Rust', '.java': 'Java', '.c': 'C', '.cpp': 'C++',
    '.cs': 'C#', '.rb': 'Ruby', '.php': 'PHP', '.kt': 'Kotlin', '.swift': 'Swift',
    '.md': 'Markdown', '.json': 'JSON', '.yml': 'YAML', '.yaml': 'YAML',
}


def detect_stack(file_paths: list[str]) -> list[str]:
    """从文件路径后缀粗判技术栈，供规划器生成更贴切的步骤。"""
    counts: dict[str, int] = {}
    for path in file_paths:
        suffix = ''
        idx = path.rfind('.')
        if idx >= 0:
            suffix = path[idx:].lower()
        lang = _LANG_BY_SUFFIX.get(suffix)
        if lang:
            counts[lang] = counts.get(lang, 0) + 1
    return [lang for lang, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]]


def generate_plan(task: str, *, file_paths: list[str] | None = None, max_steps: int = 6) -> Plan:
    """基于任务描述 + 工作区文件概览生成有序计划。

    这是**离线可跑的基线规划器**：不依赖模型即可产出结构化、可执行、
    可断言的步骤序列。编排器在网关可用时可用 LLM 覆盖标题，但步骤骨架
    与"侦察→实施→验证→落账"的闭环保持不变。
    """
    task_text = (task or '').strip() or '（未提供任务描述）'
    files = list(file_paths or [])
    stack = detect_stack(files)
    stack_hint = '、'.join(stack) if stack else '未知'

    steps: list[PlanStep] = [
        PlanStep(
            id=_new_id('step'), title='侦察工作区', tool_hint='list_dir/glob/grep',
            detail=f'扫描工作区结构（{len(files)} 个文件，技术栈：{stack_hint}），定位与任务相关的文件与入口。',
        ),
        PlanStep(
            id=_new_id('step'), title='精读相关文件', tool_hint='read_file',
            detail='读取上一步命中的关键文件，确认现状与改动落点，记录约束与约定。',
        ),
        PlanStep(
            id=_new_id('step'), title='拟定改动方案', tool_hint='plan',
            detail=f'针对「{task_text}」给出具体改动清单：涉及文件、函数/组件、兼容性影响。',
        ),
        PlanStep(
            id=_new_id('step'), title='实施改动', tool_hint='edit_file/write_file',
            detail='按方案修改代码；每次改动保持最小、可回滚，并说明理由。',
        ),
        PlanStep(
            id=_new_id('step'), title='验证改动', tool_hint='run_shell',
            detail='运行相关测试 / lint / 构建命令，确认改动不破坏既有行为。',
        ),
        PlanStep(
            id=_new_id('step'), title='沉淀可审计记忆', tool_hint='memory',
            detail='把本次决策、踩坑与约定写入可证明删除的记忆账本，供后续会话与审计追溯。',
        ),
    ]
    plan = Plan(steps=steps[:max_steps], source='heuristic',
                rationale=f'围绕任务「{task_text}」的通用工程闭环：侦察 → 精读 → 方案 → 实施 → 验证 → 落账。')
    return plan
