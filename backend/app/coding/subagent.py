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

"""万枢编程框架 —— 子智能体委派（subagent）。

参照 deepseek-harness 的 ``subagent`` 包：把一个大任务拆给受**最小权限**
约束的子智能体去侦察/审查/验证，主智能体只收结论，避免主上下文被
海量文件内容淹没。

关键约束（fail-closed）：

- **深度上限**：``depth`` 不得超过 ``SUBAGENT_MAX_DEPTH``，杜绝无限递归委派；
- **权限收窄**：子智能体默认只读（``explorer``/``reviewer``），工具集是
  父级工具集的子集，写操作角色（``implementer``）也仅授予中风险工具；
- **作用域隔离**：子智能体仍在同一工作区内，但仅能触达被显式授予的工具。

本模块提供角色化子智能体，且**离线可跑**：``explorer`` 会基于任务关键词
做真实的工作区侦察（glob + grep + 目录概览），产出可断言的结构化发现，
而非空壳占位。
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from . import constants
from .tools import ToolContext, invoke

# 角色 → (中文名, 默认工具集, 是否只读)
ROLES: dict[str, dict[str, Any]] = {
    'explorer': {
        'label': '侦察者',
        'tools': ['list_dir', 'glob', 'grep', 'read_file'],
        'readonly': True,
        'mission': '定位与任务相关的文件与入口，产出候选文件清单与结构概览。',
    },
    'reviewer': {
        'label': '审查者',
        'tools': ['read_file', 'grep', 'git_status', 'git_diff'],
        'readonly': True,
        'mission': '审查改动，按 阻断/严重/建议 分级列出问题。',
    },
    'tester': {
        'label': '验证者',
        'tools': ['read_file', 'glob', 'run_shell'],
        'readonly': False,
        'mission': '运行测试与检查命令，汇总通过/失败结果。',
    },
    'implementer': {
        'label': '实施者',
        'tools': ['read_file', 'grep', 'edit_file', 'write_file'],
        'readonly': False,
        'mission': '按方案实施最小改动。',
    },
}

# 关键词抽取用的停用词（中英混排任务的粗过滤）
_STOPWORDS = frozenset({
    'the', 'a', 'an', 'and', 'or', 'to', 'of', 'in', 'on', 'for', 'with', 'is', 'are',
    'be', 'it', 'this', 'that', 'as', 'at', 'by', 'from', 'into', '请', '把', '的', '了',
    '和', '与', '在', '对', '给', '为', '一个', '以及', '并且', '然后', '支持', '实现',
})


class SubagentError(ValueError):
    """委派被拒（深度超限 / 角色非法 / 工具越权）。"""


@dataclass
class SubagentSpec:
    id: str
    role: str
    task: str
    depth: int
    allowed_tools: list[str]
    status: str = 'created'          # created / running / done / failed
    findings: dict[str, Any] = field(default_factory=dict)
    error: str = ''

    def public(self) -> dict[str, Any]:
        meta = ROLES.get(self.role, {})
        return {
            'id': self.id,
            'role': self.role,
            'role_label': meta.get('label', self.role),
            'task': self.task,
            'depth': self.depth,
            'allowed_tools': self.allowed_tools,
            'readonly': bool(meta.get('readonly', True)),
            'status': self.status,
            'findings': self.findings,
            'error': self.error,
        }


def spawn(*, role: str, task: str, parent_depth: int = 0) -> SubagentSpec:
    """创建子智能体。深度超限或角色非法即拒绝。"""
    if role not in ROLES:
        raise SubagentError(f'未知子智能体角色：{role}（可选：{", ".join(ROLES)}）')
    depth = int(parent_depth) + 1
    if depth > constants.SUBAGENT_MAX_DEPTH:
        raise SubagentError(f'委派深度 {depth} 超过上限 {constants.SUBAGENT_MAX_DEPTH}，拒绝继续下钻')
    text = (task or '').strip()
    if not text:
        raise SubagentError('子智能体任务描述不能为空')
    return SubagentSpec(
        id=f'sub_{uuid.uuid4().hex[:10]}',
        role=role,
        task=text,
        depth=depth,
        allowed_tools=list(ROLES[role]['tools']),
    )


def _keywords(task: str, limit: int = 6) -> list[str]:
    tokens = re.findall(r'[A-Za-z_][A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,}', task or '')
    seen: list[str] = []
    for token in tokens:
        low = token.lower()
        if low in _STOPWORDS or token in seen:
            continue
        seen.append(token)
        if len(seen) >= limit:
            break
    return seen


def _run_explorer(ctx: ToolContext, spec: SubagentSpec) -> dict[str, Any]:
    """侦察者：目录概览 + 关键词 glob + 关键词 grep，全部走真实工具。"""
    listing = invoke('list_dir', {'path': '.'}, ctx)
    keywords = _keywords(spec.task)
    candidates: list[str] = []
    hits: list[dict[str, Any]] = []
    for kw in keywords:
        glob_res = invoke('glob', {'pattern': f'**/*{kw}*'}, ctx)
        for match in (glob_res.output.get('matches') or [])[:20]:
            if match not in candidates:
                candidates.append(match)
        grep_res = invoke('grep', {'pattern': re.escape(kw), 'max_matches': 20}, ctx)
        for hit in (grep_res.output.get('hits') or [])[:10]:
            if hit not in hits:
                hits.append(hit)
    return {
        'top_level': [e['name'] for e in (listing.output.get('entries') or [])][:40],
        'keywords': keywords,
        'candidate_files': candidates[:40],
        'content_hits': hits[:40],
        'summary': f'侦察完成：命中 {len(candidates)} 个候选文件、{len(hits)} 处内容线索。',
    }


def _run_reviewer(ctx: ToolContext, spec: SubagentSpec) -> dict[str, Any]:
    """审查者：取 git 差异并做启发式风险扫描（敏感信息 / 调试残留 / TODO）。"""
    diff = invoke('git_diff', {}, ctx)
    text = (diff.output.get('stdout') or '')
    risks: list[dict[str, str]] = []
    patterns = {
        'debug_residue': r'^\+.*\b(print\(|console\.log|debugger|pdb\.set_trace|breakpoint\()',
        'secret_leak': r'^\+.*(api[_-]?key|password|secret|token)\s*[:=]\s*[\'"][^\'"]{6,}',
        'todo_left': r'^\+.*\b(TODO|FIXME|XXX)\b',
        'broad_except': r'^\+.*except\s*:\s*$',
    }
    for name, pattern in patterns.items():
        regex = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
        for match in regex.finditer(text):
            line = match.group(0).strip()[:200]
            risks.append({'kind': name, 'line': line})
            if len(risks) >= 40:
                break
    return {
        'changed_files': sorted({ln[3:] for ln in text.splitlines() if ln.startswith('+++ b/')}),
        'diff_bytes': len(text),
        'risks': risks,
        'summary': f'审查完成：{len(risks)} 处启发式风险点，{len(text)} 字节差异。',
    }


def _run_tester(ctx: ToolContext, spec: SubagentSpec) -> dict[str, Any]:
    """验证者：尝试常见测试命令，返回首个可执行者的结果。"""
    attempts: list[dict[str, Any]] = []
    for cmd in ('python -m pytest -q', 'npm test --silent', 'go test ./...'):
        result = invoke('run_shell', {'command': cmd, 'timeout_s': 120}, ctx)
        attempts.append({
            'command': cmd,
            'status': result.status,
            'summary': result.summary,
            'exit_code': (result.output or {}).get('exit_code'),
            'missing': bool((result.output or {}).get('_missing')),
        })
        if result.status == 'ok' and (result.output or {}).get('exit_code') == 0:
            return {'attempts': attempts, 'passed': True,
                    'summary': f'验证通过：{cmd} 退出码 0。'}
    return {'attempts': attempts, 'passed': False,
            'summary': '验证未通过：未找到可成功执行的测试命令。'}


_RUNNERS = {
    'explorer': _run_explorer,
    'reviewer': _run_reviewer,
    'tester': _run_tester,
}


def run(spec: SubagentSpec, ctx: ToolContext) -> SubagentSpec:
    """执行子智能体。只读角色不会产生写操作（工具集本身不含写工具）。"""
    runner = _RUNNERS.get(spec.role)
    if runner is None:
        # implementer 由编排器在受限策略下推进，这里不自动执行
        spec.status = 'done'
        spec.findings = {'summary': '实施者角色由编排器在受限策略下推进。'}
        return spec
    spec.status = 'running'
    try:
        # 子智能体一律在 readonly 档下运行，写工具即便被授予也会被策略拒绝
        sub_ctx = ToolContext(workspace=ctx.workspace, policy_mode='readonly')
        spec.findings = runner(sub_ctx, spec)
        spec.status = 'done'
    except Exception as exc:  # noqa: BLE001 —— 子智能体失败不拖垮父级
        spec.status = 'failed'
        spec.error = str(exc)
    return spec


def catalog() -> list[dict[str, Any]]:
    return [
        {
            'role': role,
            'label': meta['label'],
            'readonly': meta['readonly'],
            'tools': meta['tools'],
            'mission': meta['mission'],
        }
        for role, meta in ROLES.items()
    ]
