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

"""万枢编程框架 —— 工具系统（能力注册表 + 内置工具 + 策略裁决）。

参照 deepseek-harness「一切皆能力」的思路，把编程框架的每一种动作
（读文件、改文件、跑命令、查 git……）统一建模为 ``ToolSpec``，由注册表
集中管理、统一裁决、统一记账。

调用链：``invoke()`` → 沙箱/策略裁决（``constants.decide_risk``）→
（allow）执行 / （ask）返回待审批 / （deny）拒绝。执行结果一律结构化，
写入会话事件流，供前端时间线与审计使用。

新增工具只需在本模块实现 handler 并 ``register()``，无需改动编排器——
这是"插件化"的最小落地形态。
"""
from __future__ import annotations

import fnmatch
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import constants
from .sandbox import (
    MAX_FILE_READ_BYTES,
    MAX_FILE_WRITE_BYTES,
    MAX_GREP_MATCHES,
    MAX_LIST_ENTRIES,
    SandboxViolation,
    Workspace,
    classify_command,
    run_command,
)


@dataclass(frozen=True)
class ToolSpec:
    """一个可被编排器调用的工具。"""

    id: str
    name_cn: str
    description: str
    risk: str                       # low / medium / high（静态风险；命令类工具动态裁决）
    parameters: dict[str, Any]      # 简化 JSON-Schema，供前端渲染参数表单
    handler: Callable[..., dict]
    category: str = 'file'
    dynamic_risk: bool = False      # True 表示风险由入参动态决定（如 run_shell）

    def public(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'name_cn': self.name_cn,
            'description': self.description,
            'risk': self.risk,
            'risk_label': constants.RISK_LEVEL_LABELS.get(self.risk, self.risk),
            'parameters': self.parameters,
            'category': self.category,
            'dynamic_risk': self.dynamic_risk,
        }


@dataclass
class ToolContext:
    """工具执行上下文。"""

    workspace: Workspace
    policy_mode: str = 'supervised'
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    """工具执行结果（结构化，恒可 JSON 序列化）。"""

    tool_id: str
    status: str                     # ok / error / denied / pending_approval / timeout
    risk: str
    decision: str                   # allow / ask / deny
    summary: str
    output: dict[str, Any] = field(default_factory=dict)
    error: str = ''

    def public(self) -> dict[str, Any]:
        return {
            'tool_id': self.tool_id,
            'status': self.status,
            'risk': self.risk,
            'risk_label': constants.RISK_LEVEL_LABELS.get(self.risk, self.risk),
            'decision': self.decision,
            'decision_label': constants.DECISION_LABELS.get(self.decision, self.decision),
            'summary': self.summary,
            'output': self.output,
            'error': self.error,
        }


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, ToolSpec] = {}


def register(spec: ToolSpec) -> ToolSpec:
    _REGISTRY[spec.id] = spec
    return spec


def get(tool_id: str) -> ToolSpec | None:
    return _REGISTRY.get(tool_id)


def catalog() -> list[dict[str, Any]]:
    """返回工具目录（稳定排序，供 API 与前端渲染）。"""
    return [spec.public() for spec in sorted(_REGISTRY.values(), key=lambda s: (s.category, s.id))]


# ---------------------------------------------------------------------------
# 内置工具实现
# ---------------------------------------------------------------------------


def _read_file(ctx: ToolContext, *, path: str, start_line: int = 1, max_lines: int = 2000) -> dict:
    target = ctx.workspace.resolve(path, must_exist=True)
    if target.is_dir():
        raise SandboxViolation(f'目标是目录而非文件：{path}')
    if target.stat().st_size > MAX_FILE_READ_BYTES:
        raise SandboxViolation(f'文件超过读取上限 {MAX_FILE_READ_BYTES} 字节：{path}')
    text = target.read_text(encoding='utf-8', errors='replace')
    lines = text.splitlines()
    begin = max(1, int(start_line))
    end = min(len(lines), begin - 1 + max(1, int(max_lines)))
    window = lines[begin - 1:end]
    numbered = '\n'.join(f'{begin + i:>5}  {line}' for i, line in enumerate(window))
    return {
        'path': ctx.workspace.relative(target),
        'total_lines': len(lines),
        'start_line': begin,
        'end_line': end,
        'content': numbered,
    }


def _write_file(ctx: ToolContext, *, path: str, content: str, create_dirs: bool = True) -> dict:
    name = Path(path).name
    if Workspace.is_secret_name(name):
        raise SandboxViolation(f'拒绝写入凭据类文件：{name}')
    raw = content.encode('utf-8')
    if len(raw) > MAX_FILE_WRITE_BYTES:
        raise SandboxViolation(f'内容超过写入上限 {MAX_FILE_WRITE_BYTES} 字节')
    target = ctx.workspace.resolve(path)
    existed = target.exists()
    if create_dirs:
        target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding='utf-8')
    return {
        'path': ctx.workspace.relative(target),
        'bytes': len(raw),
        'created': not existed,
        'lines': content.count('\n') + (0 if content.endswith('\n') or not content else 1),
    }


def _edit_file(ctx: ToolContext, *, path: str, old_string: str, new_string: str, replace_all: bool = False) -> dict:
    target = ctx.workspace.resolve(path, must_exist=True)
    text = target.read_text(encoding='utf-8', errors='replace')
    occurrences = text.count(old_string)
    if occurrences == 0:
        raise SandboxViolation(f'未找到待替换文本（old_string 不存在）：{path}')
    if occurrences > 1 and not replace_all:
        raise SandboxViolation(f'old_string 出现 {occurrences} 次，请提供更长的唯一上下文或置 replace_all=true')
    updated = text.replace(old_string, new_string) if replace_all else text.replace(old_string, new_string, 1)
    target.write_text(updated, encoding='utf-8')
    return {
        'path': ctx.workspace.relative(target),
        'replaced': occurrences if replace_all else 1,
        'delta_lines': updated.count('\n') - text.count('\n'),
    }


def _list_dir(ctx: ToolContext, *, path: str = '.') -> dict:
    target = ctx.workspace.resolve(path or '.', must_exist=True)
    if not target.is_dir():
        raise SandboxViolation(f'目标不是目录：{path}')
    entries: list[dict[str, Any]] = []
    for child in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
        if len(entries) >= MAX_LIST_ENTRIES:
            break
        try:
            size = child.stat().st_size if child.is_file() else None
        except OSError:
            size = None
        entries.append({
            'name': child.name,
            'path': ctx.workspace.relative(child),
            'type': 'dir' if child.is_dir() else 'file',
            'size': size,
        })
    return {'path': ctx.workspace.relative(target), 'count': len(entries), 'entries': entries}


def _glob(ctx: ToolContext, *, pattern: str, path: str = '.') -> dict:
    base = ctx.workspace.resolve(path or '.', must_exist=True)
    matches: list[str] = []
    for candidate in sorted(base.glob(pattern)):
        if len(matches) >= MAX_LIST_ENTRIES:
            break
        try:
            resolved = Path(__import__('os').path.realpath(candidate))
        except OSError:
            continue
        if resolved.is_file():
            matches.append(ctx.workspace.relative(resolved))
    return {'pattern': pattern, 'count': len(matches), 'matches': matches}


def _grep(
    ctx: ToolContext,
    *,
    pattern: str,
    path: str = '.',
    file_glob: str = '*',
    max_matches: int = 100,
    ignore_case: bool = False,
) -> dict:
    base = ctx.workspace.resolve(path or '.', must_exist=True)
    flags = re.IGNORECASE if ignore_case else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error as exc:
        raise SandboxViolation(f'正则非法：{exc}') from exc
    limit = min(int(max_matches), MAX_GREP_MATCHES)
    hits: list[dict[str, Any]] = []
    scanned = 0
    candidates = [base] if base.is_file() else [p for p in base.rglob('*') if p.is_file()]
    for file in candidates:
        if not fnmatch.fnmatch(file.name, file_glob):
            continue
        try:
            if file.stat().st_size > MAX_FILE_READ_BYTES:
                continue
        except OSError:
            continue
        scanned += 1
        try:
            text = file.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                hits.append({
                    'path': ctx.workspace.relative(file),
                    'line': lineno,
                    'text': line.strip()[:300],
                })
                if len(hits) >= limit:
                    return {'pattern': pattern, 'scanned_files': scanned, 'count': len(hits), 'hits': hits, 'truncated': True}
    return {'pattern': pattern, 'scanned_files': scanned, 'count': len(hits), 'hits': hits, 'truncated': False}


def _run_shell(ctx: ToolContext, *, command: str, timeout_s: int = constants.DEFAULT_TOOL_TIMEOUT_S) -> dict:
    return run_command(ctx.workspace, command, timeout_s=int(timeout_s))


def _git_status(ctx: ToolContext) -> dict:
    return run_command(ctx.workspace, 'git status --short --branch', timeout_s=15)


def _git_diff(ctx: ToolContext, *, path: str = '', staged: bool = False) -> dict:
    cmd = 'git diff'
    if staged:
        cmd += ' --staged'
    if path:
        safe = ctx.workspace.resolve(path, must_exist=False)
        cmd += f' -- {ctx.workspace.relative(safe)}'
    return run_command(ctx.workspace, cmd, timeout_s=20)


# ---------------------------------------------------------------------------
# 内置工具注册
# ---------------------------------------------------------------------------

register(ToolSpec(
    id='read_file', name_cn='读取文件', category='file', risk='low',
    description='读取工作区内文本文件，返回带行号的窗口内容。',
    parameters={'path': 'string', 'start_line': 'int?', 'max_lines': 'int?'},
    handler=_read_file,
))
register(ToolSpec(
    id='write_file', name_cn='写入文件', category='file', risk='medium',
    description='在工作区内创建或覆盖文件；拒绝凭据类文件名。',
    parameters={'path': 'string', 'content': 'string', 'create_dirs': 'bool?'},
    handler=_write_file,
))
register(ToolSpec(
    id='edit_file', name_cn='编辑文件', category='file', risk='medium',
    description='按精确字符串替换编辑文件；多处匹配须显式 replace_all。',
    parameters={'path': 'string', 'old_string': 'string', 'new_string': 'string', 'replace_all': 'bool?'},
    handler=_edit_file,
))
register(ToolSpec(
    id='list_dir', name_cn='列目录', category='file', risk='low',
    description='列出工作区内某个目录的条目。',
    parameters={'path': 'string?'},
    handler=_list_dir,
))
register(ToolSpec(
    id='glob', name_cn='模式匹配文件', category='search', risk='low',
    description='按 glob 模式在工作区内查找文件。',
    parameters={'pattern': 'string', 'path': 'string?'},
    handler=_glob,
))
register(ToolSpec(
    id='grep', name_cn='内容检索', category='search', risk='low',
    description='按正则在工作区内检索文件内容。',
    parameters={'pattern': 'string', 'path': 'string?', 'file_glob': 'string?', 'max_matches': 'int?', 'ignore_case': 'bool?'},
    handler=_grep,
))
register(ToolSpec(
    id='run_shell', name_cn='执行命令', category='exec', risk='medium', dynamic_risk=True,
    description='在工作区内执行命令（shell=False）。风险按命令动态裁决：安全白名单放行，写操作/未知命令需审批，危险命令拒绝。',
    parameters={'command': 'string', 'timeout_s': 'int?'},
    handler=_run_shell,
))
register(ToolSpec(
    id='git_status', name_cn='Git 状态', category='git', risk='low',
    description='查看工作区 git 状态。',
    parameters={},
    handler=_git_status,
))
register(ToolSpec(
    id='git_diff', name_cn='Git 差异', category='git', risk='low',
    description='查看工作区 git 差异（可指定路径或暂存区）。',
    parameters={'path': 'string?', 'staged': 'bool?'},
    handler=_git_diff,
))


# ---------------------------------------------------------------------------
# 统一调用入口
# ---------------------------------------------------------------------------


def effective_risk(spec: ToolSpec, params: dict[str, Any]) -> tuple[str, str]:
    """返回 (风险等级, 说明)。命令类工具按入参动态裁决。"""
    if spec.dynamic_risk and spec.id == 'run_shell':
        verdict = classify_command(str(params.get('command', '')))
        return verdict.risk, verdict.reason
    return spec.risk, ''


def invoke(tool_id: str, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """裁决并执行一次工具调用。不抛异常，一切以 ``ToolResult.status`` 表达。"""
    spec = _REGISTRY.get(tool_id)
    if spec is None:
        return ToolResult(tool_id, 'error', 'low', 'deny', f'未知工具：{tool_id}', error='unknown_tool')

    risk, reason = effective_risk(spec, params)
    decision = constants.decide_risk(ctx.policy_mode, risk)

    if decision == 'deny':
        detail = reason or f'{constants.RISK_LEVEL_LABELS.get(risk, risk)}风险工具在当前「{ctx.policy_mode}」档下被拒绝'
        return ToolResult(tool_id, 'denied', risk, 'deny', detail, error='policy_denied')

    if decision == 'ask':
        detail = reason or f'{constants.RISK_LEVEL_LABELS.get(risk, risk)}风险操作需人工审批'
        return ToolResult(tool_id, 'pending_approval', risk, 'ask', detail,
                          output={'params': params}, error='')

    try:
        output = spec.handler(ctx, **params)
    except SandboxViolation as exc:
        return ToolResult(tool_id, 'error', risk, 'allow', str(exc), error='sandbox_violation')
    except TypeError as exc:
        return ToolResult(tool_id, 'error', risk, 'allow', f'参数不合法：{exc}', error='bad_params')
    except Exception as exc:  # noqa: BLE001 —— 工具边界统一兜底，不外泄堆栈
        return ToolResult(tool_id, 'error', risk, 'allow', f'工具执行异常：{exc}', error='tool_error')

    return ToolResult(tool_id, 'ok', risk, 'allow', f'{spec.name_cn}完成', output=output)
