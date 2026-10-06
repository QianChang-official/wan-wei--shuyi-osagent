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

"""万枢编程框架 —— 技能系统（File-as-Truth）。

借鉴 wenflow 的 Prompt 工程做法：**文件是唯一真源，数据库只是镜像**。
一个技能就是一个目录：

    <skills_root>/<skill-id>/SKILL.md

``SKILL.md`` 以极简 frontmatter 声明元信息，正文即提示词模板：

    ---
    name: 代码审查
    description: 对改动做审查，产出分级问题清单
    tools: read_file, grep, git_diff
    ---
    你是资深代码审查员……（正文，可用 {arg} 占位）

本模块只做两件事：**扫描加载** 与 **渲染**。加载失败（缺 frontmatter /
目录损坏）只跳过该技能并记录原因，不拖垮整体——与 ``platform_api``
"单个子模块失败不影响其余" 的容错口径一致。

除工作区技能外，框架内置一组随代码发布的技能作为兜底（``BUILTIN_SKILLS``），
工作区同名技能覆盖内置技能。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 工作区内技能目录（相对工作区根）
WORKSPACE_SKILLS_DIR = '.wanshu/skills'
# 技能文件扩展名
SKILL_FILENAME = 'SKILL.md'

_FRONTMATTER_RE = re.compile(r'^---\s*\n(.*?)\n---\s*\n?(.*)$', re.DOTALL)


@dataclass
class SkillSpec:
    id: str
    name: str
    description: str
    tools: list[str] = field(default_factory=list)
    body: str = ''
    source: str = 'builtin'          # builtin / workspace
    path: str = ''

    def public(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'tools': self.tools,
            'source': self.source,
            'path': self.path,
        }


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """解析极简 frontmatter（``key: value`` 逐行），不引入 YAML 依赖。"""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    head, body = match.group(1), match.group(2)
    meta: dict[str, str] = {}
    for line in head.splitlines():
        if ':' not in line:
            continue
        key, _, value = line.partition(':')
        meta[key.strip().lower()] = value.strip()
    return meta, body


def _load_skill_file(skill_id: str, path: Path, *, source: str) -> SkillSpec | None:
    try:
        raw = path.read_text(encoding='utf-8')
    except OSError as exc:
        logger.warning('[coding.skills] 读取失败 %s：%r', path, exc)
        return None
    meta, body = _parse_frontmatter(raw)
    if not meta and not body.strip():
        logger.warning('[coding.skills] 空技能，跳过：%s', path)
        return None
    tools = [t.strip() for t in meta.get('tools', '').replace('，', ',').split(',') if t.strip()]
    return SkillSpec(
        id=skill_id,
        name=meta.get('name', skill_id),
        description=meta.get('description', ''),
        tools=tools,
        body=body.strip(),
        source=source,
        path=str(path),
    )


def load_workspace_skills(workspace_root: Path) -> list[SkillSpec]:
    """扫描工作区 ``.wanshu/skills/*/SKILL.md``。"""
    base = workspace_root / WORKSPACE_SKILLS_DIR
    if not base.is_dir():
        return []
    skills: list[SkillSpec] = []
    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        skill_file = child / SKILL_FILENAME
        if not skill_file.is_file():
            continue
        spec = _load_skill_file(child.name, skill_file, source='workspace')
        if spec:
            skills.append(spec)
    return skills


def load_all(workspace_root: Path | None = None) -> list[SkillSpec]:
    """内置技能 + 工作区技能（工作区同名覆盖内置）。"""
    merged: dict[str, SkillSpec] = {s.id: s for s in BUILTIN_SKILLS}
    if workspace_root is not None:
        for spec in load_workspace_skills(workspace_root):
            merged[spec.id] = spec
    return sorted(merged.values(), key=lambda s: s.id)


def render(skill: SkillSpec, args: dict[str, Any] | None = None) -> str:
    """把技能正文渲染为提示词；``{key}`` 占位用 args 填充，未提供的原样保留。"""
    body = skill.body
    for key, value in (args or {}).items():
        body = body.replace('{' + key + '}', str(value))
    return body


# ---------------------------------------------------------------------------
# 内置技能（随代码发布，作为兜底）
# ---------------------------------------------------------------------------

def _builtin(skill_id: str, name: str, description: str, tools: list[str], body: str) -> SkillSpec:
    return SkillSpec(id=skill_id, name=name, description=description, tools=tools, body=body, source='builtin')


BUILTIN_SKILLS: list[SkillSpec] = [
    _builtin(
        'code-review', '代码审查', '对指定改动做分级审查，产出问题清单与修复建议',
        ['read_file', 'grep', 'git_diff', 'list_dir'],
        '你是资深代码审查员。请针对目标改动做审查，按 阻断/严重/建议 三级输出问题清单，'
        '每条给出：位置、问题、影响、修复建议。重点关注：正确性、边界条件、安全（注入/越权/'
        '密钥泄漏）、并发、可维护性。审查对象：{target}',
    ),
    _builtin(
        'bug-fix', '缺陷修复', '定位并最小化修复一个缺陷，附回归验证',
        ['read_file', 'grep', 'glob', 'edit_file', 'run_shell'],
        '你是调试专家。先复现与定位根因（不要只治症状），再给出最小改动修复，最后补一条能'
        '拦住该缺陷的回归测试。缺陷描述：{bug}。每一步说明你的推理依据。',
    ),
    _builtin(
        'refactor', '重构', '在不改变外部行为的前提下改善结构',
        ['read_file', 'grep', 'edit_file', 'run_shell'],
        '你是重构专家。约束：不改外部行为、不扩大改动面、每步可回滚。先列出坏味道，'
        '再按小步提交式推进，每步后用测试/类型检查验证。重构目标：{target}',
    ),
    _builtin(
        'test-writer', '测试编写', '为既有代码补测试，覆盖正常与边界路径',
        ['read_file', 'grep', 'write_file', 'run_shell'],
        '你是测试工程师。为 {target} 补充测试：覆盖正常路径、边界条件、异常路径，'
        '断言聚焦行为而非实现细节。遵循仓库既有测试风格与命名约定。',
    ),
    _builtin(
        'doc-writer', '文档撰写', '为模块/接口产出准确、可维护的文档',
        ['read_file', 'grep', 'write_file'],
        '你是技术写作者。为 {target} 撰写文档：先说明"它解决什么问题"，再给出用法示例与'
        '参数说明，最后标注已知限制。事实必须来自代码，不得臆测。',
    ),
]
