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

"""万枢编程框架 —— 编排器（编码智能体主循环）。

编排器把"计划 / 工具 / 子智能体 / 技能 / 记忆 / 护栏"缝合成一条可执行、
可观测、可中断的主循环：

    侦察 → 精读 → 方案 → 实施 → 验证 → 落账

每一步都是**真实动作**（调用真实工具、真实子智能体、真实记忆库），
并全程写入事件流，供前端时间线实时呈现。设计要点：

- **计划确认门**：未 ``confirm`` 的计划不允许进入执行（对齐 wenflow
  "路径须经用户显式确认后才启动"）。
- **护栏**：轮次/工具/重复/超时四道闸（``guard``），越界即中止并落事件。
- **人在环**：写/执行类动作在 ``supervised`` 档下转为审批请求，会话暂停，
  由人工放行后再续跑——不静默执行高风险动作。
- **离线优先**：网关不可用时用确定性启发式推进，流程照跑、结果照记，
  只是"方案"文本质量降级，绝不假装成功。
- **记忆落账**：收尾把决策与踩坑写入可审计账本（``memory_bridge``），
  这是本框架的差异化能力。

编排器是**同步**实现；API 层用 ``asyncio.to_thread`` 丢进线程池，避免阻塞
事件循环。所有状态变更经 ``store`` 原子落盘，进程重启后可从会话记录恢复。
"""
from __future__ import annotations

import logging
from typing import Any

from . import constants, guard, llm, memory_bridge, skills, store, subagent, tools
from .plan import Plan, PlanError, PlanStep, confirm_plan, generate_plan, set_step_state
from .sandbox import SandboxViolation, open_workspace
from .tools import ToolContext

logger = logging.getLogger(__name__)


class OrchestratorError(RuntimeError):
    """编排前置条件不满足（状态非法 / 计划未确认 / 工作区越界）。"""


# ---------------------------------------------------------------------------
# 会话状态机
# ---------------------------------------------------------------------------


def transition(session: dict[str, Any], new_state: str) -> None:
    """按受控转移表推进会话状态；非法转移抛 ``OrchestratorError``。"""
    current = session.get('state', 'drafting')
    if new_state == current:
        return
    allowed = constants.SESSION_TRANSITIONS.get(current, ())
    if new_state not in allowed:
        raise OrchestratorError(f'非法会话状态转移：{current} → {new_state}')
    session['state'] = new_state


# ---------------------------------------------------------------------------
# 编排器
# ---------------------------------------------------------------------------


class Orchestrator:
    """单次 run 的编排上下文。"""

    def __init__(self, session: dict[str, Any], *, owner_id: str | None = None):
        self.session = session
        self.session_id = session['id']
        self.owner_id = owner_id
        self.guard = guard.GuardState()
        workspace_root = session.get('workspace', '')
        self.workspace = open_workspace(workspace_root)
        self.ctx = ToolContext(workspace=self.workspace, policy_mode=session.get('policy_mode', 'supervised'))
        self.plan = Plan.from_dict(session.get('plan') or {})
        self._candidates: list[str] = []

    # ---- 基础设施 ------------------------------------------------------

    def emit(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        store.append_event(self.session_id, event_type, payload or {})

    def persist(self) -> None:
        store.update_session(self.session_id, {
            'state': self.session['state'],
            'plan': self.plan.public(),
            'todos': self.session.get('todos', []),
            'subagents': self.session.get('subagents', []),
            'approvals': self.session.get('approvals', []),
            'guard': self.guard.snapshot(),
            'last_run': self.session.get('last_run'),
        })

    def _record_subagent(self, spec: subagent.SubagentSpec) -> None:
        self.emit('subagent_spawned', {'subagent': spec.public()})
        bucket = self.session.setdefault('subagents', [])
        bucket.append(spec.public())
        self.session['subagents'] = bucket[-20:]

    def _finish_subagent(self, spec: subagent.SubagentSpec) -> None:
        self.emit('subagent_finished', {'subagent': spec.public()})
        bucket = self.session.setdefault('subagents', [])
        for idx, item in enumerate(bucket):
            if item.get('id') == spec.id:
                bucket[idx] = spec.public()
                break

    # ---- 主循环 --------------------------------------------------------

    def run(self) -> dict[str, Any]:
        """推进整条主循环，返回本次 run 的结果摘要。"""
        if not self.plan.steps:
            raise OrchestratorError('会话尚无计划，无法执行')
        if not self.plan.confirmed:
            raise OrchestratorError('计划未经确认，拒绝执行（先 confirm 计划）')

        if self.session.get('state') in ('drafting', 'planning', 'awaiting'):
            transition(self.session, 'running')
        elif self.session.get('state') == 'paused':
            transition(self.session, 'running')
        elif self.session.get('state') != 'running':
            raise OrchestratorError(f'会话状态 {self.session.get("state")} 不允许执行')
        self.emit('session_state', {'state': 'running'})

        try:
            for step in self.plan.steps:
                if step.state == 'done':
                    continue
                self.guard.begin_iteration()
                self.guard.note_progress()
                set_step_state(self.plan, step.id, 'in_progress')
                self.emit('step_started', {'step': step.public()})

                outcome = self._execute_step(step)
                if outcome.get('needs_approval'):
                    # 高风险动作：记录审批请求并暂停会话，等待人工放行
                    approval = self._create_approval(outcome)
                    set_step_state(self.plan, step.id, 'pending')
                    transition(self.session, 'paused')
                    self.persist()
                    return {
                        'status': 'awaiting_approval',
                        'session_id': self.session_id,
                        'step': step.public(),
                        'approval': approval,
                        'guard': self.guard.snapshot(),
                    }
                final_state = 'done' if outcome.get('status') in ('ok', 'skipped') else 'failed'
                set_step_state(self.plan, step.id, final_state, result=outcome.get('summary', ''))
                self.emit('step_started', {'step': step.public(), 'finished': True})
                if final_state == 'failed':
                    transition(self.session, 'failed')
                    self.persist()
                    return {'status': 'failed', 'session_id': self.session_id,
                            'step': step.public(), 'reason': outcome.get('summary', '')}

            transition(self.session, 'done')
            self.session['last_run'] = {'status': 'done', 'steps': len(self.plan.steps),
                                        'guard': self.guard.snapshot()}
            self.persist()
            return {'status': 'done', 'session_id': self.session_id,
                    'plan': self.plan.public(), 'guard': self.guard.snapshot()}
        except guard.GuardTripped as tripped:
            self.emit('guard_tripped', {'reason': tripped.reason, 'message': tripped.message})
            transition(self.session, 'paused')
            self.session['last_run'] = {'status': 'guard_tripped', 'reason': tripped.reason,
                                        'guard': self.guard.snapshot()}
            self.persist()
            return {'status': 'guard_tripped', 'session_id': self.session_id,
                    'reason': tripped.reason, 'message': tripped.message}
        except (OrchestratorError, SandboxViolation, PlanError) as exc:
            self.emit('error', {'message': str(exc)})
            try:
                transition(self.session, 'failed')
            except OrchestratorError:
                pass
            self.persist()
            return {'status': 'failed', 'session_id': self.session_id, 'reason': str(exc)}

    # ---- 步骤分派 ------------------------------------------------------

    def _execute_step(self, step: PlanStep) -> dict[str, Any]:
        hint = step.tool_hint
        if 'memory' in hint:
            return self._do_memory(step)
        if 'run_shell' in hint:
            return self._do_verify(step)
        if 'edit_file' in hint or 'write_file' in hint:
            return self._do_implement(step)
        if hint == 'plan':
            return self._do_design(step)
        if 'read_file' in hint:
            return self._do_read(step)
        return self._do_recon(step)

    def _do_recon(self, step: PlanStep) -> dict[str, Any]:
        spec = subagent.spawn(role='explorer', task=self.session.get('task', ''), parent_depth=0)
        self._record_subagent(spec)
        subagent.run(spec, self.ctx)
        self._finish_subagent(spec)
        self._candidates = list(spec.findings.get('candidate_files') or [])
        return {'status': 'ok', 'summary': spec.findings.get('summary', '侦察完成'),
                'output': spec.findings}

    def _do_read(self, step: PlanStep) -> dict[str, Any]:
        files = self._candidates[:3] or []
        previews: list[dict[str, Any]] = []
        for rel in files:
            self.guard.begin_tool_call()
            self.guard.note_tool_call('read_file', {'path': rel})
            result = tools.invoke('read_file', {'path': rel, 'max_lines': 80}, self.ctx)
            self.emit('tool_called', {'tool_id': 'read_file', 'params': {'path': rel}})
            self.emit('tool_result', {'result': result.public()})
            previews.append({'path': rel, 'status': result.status,
                             'preview': (result.output.get('content') or '')[:1200]})
        summary = f'精读 {len(previews)} 个关键文件' if previews else '未命中候选文件，跳过精读'
        return {'status': 'ok', 'summary': summary, 'output': {'previews': previews}}

    def _do_design(self, step: PlanStep) -> dict[str, Any]:
        task = self.session.get('task', '')
        context = '\n'.join(f'- {p}' for p in self._candidates[:20]) or '（无候选文件）'
        proposal = ''
        source = 'heuristic'
        if llm.available(self.owner_id):
            prompt = (
                f'你是资深工程师。任务：{task}\n候选文件：\n{context}\n'
                '请给出具体、最小、可执行的改动清单（涉及文件 + 改动要点 + 风险），用简洁条目输出。'
            )
            res = llm.complete(prompt, owner_id=self.owner_id)
            if res.get('ok'):
                proposal = res['text']
                source = 'llm'
        if not proposal:
            proposal = (
                f'改动清单（启发式基线，任务：{task}）：\n'
                f'1. 围绕 {", ".join(self._candidates[:5]) or "目标文件"} 定位改动落点；\n'
                '2. 保持最小改动、可回滚，避免扩大影响面；\n'
                '3. 补充/更新对应测试，覆盖正常与边界路径；\n'
                '4. 运行 lint / 测试确认不破坏既有行为。'
            )
        return {'status': 'ok', 'summary': f'方案已生成（来源：{source}）',
                'output': {'proposal': proposal, 'source': source}}

    def _do_implement(self, step: PlanStep) -> dict[str, Any]:
        """实施步骤：产出改动提案；涉及写文件时进入审批门（不静默落盘）。"""
        design = next((s for s in self.plan.steps if s.tool_hint == 'plan'), None)
        proposal = (design.result if design else '') or '（无方案，按最小改动原则实施）'
        mode = self.session.get('policy_mode', 'supervised')
        if mode == 'readonly':
            return {'status': 'ok', 'summary': '只读档：仅产出改动提案，不写入文件',
                    'output': {'proposal': proposal, 'applied': False}}
        # 有具体文件落点时才发起写审批；否则仅登记提案
        target = self._candidates[0] if self._candidates else ''
        if not target:
            return {'status': 'ok', 'summary': '无明确落点，改动提案待人工实施',
                    'output': {'proposal': proposal, 'applied': False}}
        return {
            'needs_approval': True,
            'tool_id': 'write_file',
            'params': {'path': f'{target}.wanshu-proposal.md', 'content': proposal},
            'risk': 'medium',
            'summary': f'写入改动提案需审批：{target}.wanshu-proposal.md',
        }

    def _do_verify(self, step: PlanStep) -> dict[str, Any]:
        spec = subagent.spawn(role='tester', task=self.session.get('task', ''), parent_depth=0)
        self._record_subagent(spec)
        subagent.run(spec, self.ctx)
        self._finish_subagent(spec)
        passed = bool(spec.findings.get('passed'))
        return {'status': 'ok', 'summary': spec.findings.get('summary', '验证完成'),
                'output': {'passed': passed, 'attempts': spec.findings.get('attempts', [])}}

    def _do_memory(self, step: PlanStep) -> dict[str, Any]:
        design = next((s for s in self.plan.steps if s.tool_hint == 'plan'), None)
        decisions = (design.result if design else '') or '（无显式决策记录）'
        written: list[dict[str, Any]] = []
        entries = [
            ('decision', '改动决策', decisions[:1500]),
            ('context', '任务背景', self.session.get('task', '')[:800]),
        ]
        for kind, title, text in entries:
            if not text.strip():
                continue
            res = memory_bridge.remember(
                session_id=self.session_id,
                workspace=self.workspace.root_text,
                kind=kind, title=title, text=text, owner_id=self.owner_id,
            )
            if res.get('ok'):
                written.append({'capsule_id': res.get('capsule_id'), 'kind': kind, 'title': title})
                self.emit('memory_written', {'capsule_id': res.get('capsule_id'), 'kind': kind, 'title': title})
        ok = len(written) > 0
        summary = (f'已沉淀 {len(written)} 条可审计记忆' if ok
                   else '记忆库不可用或无可沉淀内容（未写入）')
        return {'status': 'ok' if ok else 'skipped', 'summary': summary,
                'output': {'written': written, 'memory_available': ok}}

    # ---- 审批 ----------------------------------------------------------

    def _create_approval(self, outcome: dict[str, Any]) -> dict[str, Any]:
        approval = {
            'id': store.new_id('apr'),
            'tool_id': outcome.get('tool_id', ''),
            'params': outcome.get('params', {}),
            'risk': outcome.get('risk', 'medium'),
            'summary': outcome.get('summary', ''),
            'status': 'pending',
            'created_at': store.now(),
            'resolved_at': None,
            'note': '',
        }
        bucket = self.session.setdefault('approvals', [])
        bucket.append(approval)
        self.session['approvals'] = bucket[-50:]
        self.emit('approval_requested', {'approval': approval})
        return approval


# ---------------------------------------------------------------------------
# 便捷入口（供 API 调用）
# ---------------------------------------------------------------------------


def build_plan_for(session: dict[str, Any]) -> Plan:
    """为会话生成启发式计划（可被 LLM 覆盖，见 API 层）。"""
    try:
        workspace = open_workspace(session.get('workspace', ''))
        listing = tools.invoke('list_dir', {'path': '.'}, ToolContext(workspace=workspace, policy_mode='readonly'))
        files = [e['path'] for e in (listing.output.get('entries') or [])]
        globbed = tools.invoke('glob', {'pattern': '**/*'}, ToolContext(workspace=workspace, policy_mode='readonly'))
        files += list(globbed.output.get('matches') or [])[:200]
    except (SandboxViolation, ValueError):
        files = []
    return generate_plan(session.get('task', ''), file_paths=files)


def run_session(session: dict[str, Any], *, owner_id: str | None = None) -> dict[str, Any]:
    return Orchestrator(session, owner_id=owner_id).run()


def resolve_approval(
    session: dict[str, Any], approval_id: str, *, approved: bool, note: str = '',
    owner_id: str | None = None,
) -> dict[str, Any]:
    """处理一条审批：放行则执行其工具调用，拒绝则记录并保持暂停。"""
    approvals = session.get('approvals') or []
    approval = next((a for a in approvals if a.get('id') == approval_id), None)
    if approval is None:
        raise OrchestratorError(f'审批不存在：{approval_id}')
    if approval.get('status') != 'pending':
        raise OrchestratorError(f'审批已处理：{approval_id}')

    approval['status'] = 'approved' if approved else 'rejected'
    approval['resolved_at'] = store.now()
    approval['note'] = note

    workspace = open_workspace(session.get('workspace', ''))
    ctx = ToolContext(workspace=workspace, policy_mode='trusted')  # 人工放行后按信任档执行
    result: dict[str, Any] | None = None
    if approved:
        result = tools.invoke(approval['tool_id'], approval.get('params') or {}, ctx).public()

    store.append_event(session['id'], 'approval_resolved',
                       {'approval': approval, 'result': result})
    store.update_session(session['id'], {'approvals': approvals})
    return {'approval': approval, 'result': result}


def run_tool_direct(
    session: dict[str, Any], tool_id: str, params: dict[str, Any], *, owner_id: str | None = None,
) -> dict[str, Any]:
    """直接调用一个工具（走策略裁决）。需审批时登记审批请求并返回。"""
    workspace = open_workspace(session.get('workspace', ''))
    ctx = ToolContext(workspace=workspace, policy_mode=session.get('policy_mode', 'supervised'))
    result = tools.invoke(tool_id, params, ctx)
    store.append_event(session['id'], 'tool_called', {'tool_id': tool_id, 'params': params})
    store.append_event(session['id'], 'tool_result', {'result': result.public()})
    payload: dict[str, Any] = {'result': result.public()}
    if result.status == 'pending_approval':
        approvals = session.setdefault('approvals', [])
        approval = {
            'id': store.new_id('apr'),
            'tool_id': tool_id,
            'params': params,
            'risk': result.risk,
            'summary': result.summary,
            'status': 'pending',
            'created_at': store.now(),
            'resolved_at': None,
            'note': '',
        }
        approvals.append(approval)
        store.update_session(session['id'], {'approvals': approvals[-50:]})
        store.append_event(session['id'], 'approval_requested', {'approval': approval})
        payload['approval'] = approval
    return payload


def list_skills(session: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    root = None
    if session and session.get('workspace'):
        try:
            root = open_workspace(session['workspace']).root
        except (SandboxViolation, ValueError):
            root = None
    return [s.public() for s in skills.load_all(root)]


def confirm(session: dict[str, Any], *, approved: bool) -> dict[str, Any]:
    """人工确认/否决计划。放行则 planning→awaiting→running；否决退回 planning。"""
    plan = Plan.from_dict(session.get('plan') or {})
    confirm_plan(plan, approved=approved)
    session['plan'] = plan.public()
    if approved:
        if session.get('state') in ('drafting', 'planning'):
            transition(session, 'awaiting')
        transition(session, 'running')
    elif session.get('state') in ('awaiting', 'drafting'):
        transition(session, 'planning')
    store.append_event(session['id'], 'plan_confirmed', {'approved': approved})
    store.update_session(session['id'], {'plan': plan.public(), 'state': session['state']})
    return {'plan': plan.public(), 'state': session['state']}
