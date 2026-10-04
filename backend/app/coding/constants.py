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

"""万枢编程框架 —— 全局常量与受控枚举。

设计口径与仓库既有做法一致：所有跨模块共享的字面量集中在此定义，
避免多头定义漂移；枚举一律以元组给出合法取值，配套中文标签供前端直用。

本模块只放"契约"，不放逻辑——逻辑分别落在 ``sandbox``（策略）、
``tools``（能力）、``plan``（计划/待办）、``orchestrator``（编排）等处。
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# 权限模式（policy mode）——一次编码会话内允许工具触达的执行面
# ---------------------------------------------------------------------------

# readonly   只读：仅放行低风险工具（读文件/检索/git 查询），写入与执行一律拒绝
# supervised 监督：低风险直接放行，中/高风险进入人工审批（默认档）
# trusted    信任：低/中风险直接放行，仅高风险进入人工审批
POLICY_MODES = ('readonly', 'supervised', 'trusted')

POLICY_MODE_LABELS = {
    'readonly': '只读',
    'supervised': '监督',
    'trusted': '信任',
}

# ---------------------------------------------------------------------------
# 工具风险等级
# ---------------------------------------------------------------------------

RISK_LEVELS = ('low', 'medium', 'high')

RISK_LEVEL_LABELS = {
    'low': '低',
    'medium': '中',
    'high': '高',
}

# 各权限模式下，风险等级对应的裁决
# allow=直接放行  ask=进入审批  deny=拒绝
_POLICY_MATRIX: dict[str, dict[str, str]] = {
    'readonly': {'low': 'allow', 'medium': 'deny', 'high': 'deny'},
    'supervised': {'low': 'allow', 'medium': 'ask', 'high': 'ask'},
    'trusted': {'low': 'allow', 'medium': 'allow', 'high': 'ask'},
}

# 裁决取值
DECISIONS = ('allow', 'ask', 'deny')

DECISION_LABELS = {
    'allow': '放行',
    'ask': '待审',
    'deny': '拒绝',
}


def decide_risk(policy_mode: str, risk: str) -> str:
    """按权限模式 × 风险等级裁决工具调用。非法入参 fail-closed 归为 ``deny``。"""
    row = _POLICY_MATRIX.get(policy_mode)
    if not row:
        return 'deny'
    return row.get(risk, 'deny')


# ---------------------------------------------------------------------------
# 会话状态机
# ---------------------------------------------------------------------------

# drafting   草拟：会话已建，尚未生成计划
# planning   规划中：正在生成/修订计划
# awaiting   待确认：计划已生成，等待人确认（对齐"路径须显式确认后才启动"）
# running    执行中：编排器推进计划
# paused     暂停：等待人工审批或用户中止
# done       完成：全部步骤结束
# failed     失败：不可恢复错误
# cancelled  取消
SESSION_STATES = ('drafting', 'planning', 'awaiting', 'running', 'paused', 'done', 'failed', 'cancelled')

SESSION_STATE_LABELS = {
    'drafting': '草拟',
    'planning': '规划中',
    'awaiting': '待确认',
    'running': '执行中',
    'paused': '已暂停',
    'done': '已完成',
    'failed': '已失败',
    'cancelled': '已取消',
}

# 允许的状态转移（唯一裁决源）。未列出的转移一律 422。
SESSION_TRANSITIONS: dict[str, tuple[str, ...]] = {
    'drafting': ('planning', 'cancelled'),
    'planning': ('awaiting', 'failed', 'cancelled'),
    'awaiting': ('running', 'planning', 'cancelled'),
    'running': ('paused', 'done', 'failed', 'cancelled'),
    'paused': ('running', 'cancelled', 'failed'),
    'done': (),
    'failed': ('planning', 'cancelled'),
    'cancelled': (),
}

TERMINAL_SESSION_STATES = ('done', 'cancelled')


# ---------------------------------------------------------------------------
# 计划步骤状态
# ---------------------------------------------------------------------------

STEP_STATES = ('pending', 'in_progress', 'done', 'skipped', 'failed')

STEP_STATE_LABELS = {
    'pending': '待办',
    'in_progress': '进行中',
    'done': '已完成',
    'skipped': '已跳过',
    'failed': '已失败',
}

STEP_TRANSITIONS: dict[str, tuple[str, ...]] = {
    'pending': ('in_progress', 'skipped'),
    'in_progress': ('done', 'failed', 'skipped', 'pending'),
    'done': ('pending',),          # 允许回退重开（人工纠偏）
    'skipped': ('pending',),
    'failed': ('pending', 'in_progress'),
}

# ---------------------------------------------------------------------------
# 待办（todo）状态
# ---------------------------------------------------------------------------

TODO_STATES = ('pending', 'doing', 'done', 'blocked')

TODO_STATE_LABELS = {
    'pending': '未开始',
    'doing': '进行中',
    'done': '已完成',
    'blocked': '受阻',
}

# ---------------------------------------------------------------------------
# 工具调用结果状态
# ---------------------------------------------------------------------------

TOOL_STATES = ('ok', 'error', 'denied', 'pending_approval', 'timeout')

# ---------------------------------------------------------------------------
# 事件类型（会话事件流，供前端时间线渲染）
# ---------------------------------------------------------------------------

EVENT_TYPES = (
    'session_created',
    'plan_proposed',
    'plan_confirmed',
    'step_started',
    'tool_called',
    'tool_result',
    'approval_requested',
    'approval_resolved',
    'memory_written',
    'memory_forgotten',
    'subagent_spawned',
    'subagent_finished',
    'skill_loaded',
    'guard_tripped',
    'workflow_started',
    'workflow_finished',
    'assistant_message',
    'session_state',
    'error',
)

# ---------------------------------------------------------------------------
# 编排器循环护栏默认值
# ---------------------------------------------------------------------------

DEFAULT_MAX_ITERATIONS = 24          # 单次 run 的最大"思考-行动"轮数
DEFAULT_MAX_TOOL_CALLS = 60          # 单次 run 的工具调用总预算
DEFAULT_TOOL_TIMEOUT_S = 30          # 单个工具调用的墙钟超时（秒）
DEFAULT_DUPLICATE_LIMIT = 3          # 同一工具+同一参数的重复调用阈值

# 子智能体委派的最大嵌套深度（parent→child 到第 1 层为止，再深即拒绝）
SUBAGENT_MAX_DEPTH = 2

# 工作流默认并发上限
DEFAULT_WORKFLOW_CONCURRENCY = 4
MAX_WORKFLOW_CONCURRENCY = 16

# 会话事件流保留上限（单会话）
EVENT_RETENTION = 2000
# 会话列表保留上限（每 owner）
SESSION_RETENTION = 200
