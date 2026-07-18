"""B3 空间舱：项目管理与空间语义 API。

- 项目 CRUD（项目空间 / 任务空间以 ``kind`` 区分，列表可按 kind 过滤）
- 主干（main）/ 集成树（tree）/ 栖枝（perch）三态视图：root_path 指向真实
  git 仓库时用 subprocess 读取真实分支（5 秒超时），否则返回语义化模拟数据
  并标注 ``source: 'simulated'``。
- 自定义 git 提交模板与提交执行：默认 ``dry_run=True`` 只回显将执行的命令；
  真实提交要求工作档位为 ``sandbox`` / ``device``（人工审查档位只预览）。
- 账号绑定（github / linear）：token 用 Fernet 加密后落盘（复用
  model_gateway 的 ``app.security.encryption`` 密钥模式）；github 绑定后可
  真实调用 ``api.github.com/user`` 做连通性测试（5 秒超时），linear 为 stub。

持久化：JsonStore('spaces') 存项目（含提交模板），JsonStore('integrations')
存账号绑定（密文 token，任何接口均不回显明文）。
"""
from __future__ import annotations

import os
import re
import subprocess
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.platform_api.deps import WORK_GEARS
from app.platform_api.store import JsonStore
from app.security import encryption
from app.utils.datetime_utils import utc_now_iso

router = APIRouter(tags=['spaces'])

_projects = JsonStore('spaces')
_integrations = JsonStore('integrations')

PROJECT_KINDS = ('project_space', 'task_space')
PROJECT_KIND_LABELS = {
    'project_space': '项目空间',
    'task_space': '任务空间',
}
INTEGRATION_KINDS = ('github', 'linear')

# 主干 / 集成树 / 栖枝 三态角色文案（契约固定）
ROLE_TRUNK = '主干 受保护'
ROLE_TREE = '集成树 AI合并暂存'
ROLE_PERCH = '栖枝 实验/草稿'
ROLE_WORK = '工作分支'

DEFAULT_COMMIT_TEMPLATE: dict[str, Any] = {
    'template': '<type>(<scope>): <subject>',
    'types': ['feat', 'fix', 'docs', 'style', 'refactor', 'test', 'chore'],
    'require_scope': True,
}

_GIT_TIMEOUT = 5


# ---------------------------------------------------------------- 模型


class ProjectIn(BaseModel):
    name: str = Field(..., min_length=1)
    desc: str = ''
    root_path: str = ''
    kind: str = 'project_space'
    default_branch: str = 'main'


class ProjectUpdateIn(BaseModel):
    name: str | None = None
    desc: str | None = None
    root_path: str | None = None
    kind: str | None = None
    default_branch: str | None = None
    archived: bool | None = None


class CommitTemplateIn(BaseModel):
    template: str = Field(..., min_length=1)
    types: list[str] = Field(default_factory=lambda: list(DEFAULT_COMMIT_TEMPLATE['types']))
    require_scope: bool = True


class CommitIn(BaseModel):
    branch: str | None = None
    message: str = Field(..., min_length=1)
    files: list[str] | None = None
    dry_run: bool = True
    gear: str = 'human_review'


class BindIn(BaseModel):
    token: str = Field(..., min_length=1)
    account: str | None = None
    scopes: list[str] | None = None


# ---------------------------------------------------------------- 工具


def _new_project_id() -> str:
    return 'sp_' + uuid.uuid4().hex[:12]


def _get_project_or_404(pid: str) -> dict:
    project = _projects.get(pid)
    if not isinstance(project, dict):
        raise HTTPException(status_code=404, detail=f'项目不存在：{pid}')
    return project


def _public_project(project: dict) -> dict:
    """对外项目视图：剥离内部字段（commit_template 走专属接口）。"""
    return {key: value for key, value in project.items() if key != 'commit_template'}


def _commit_template_of(project: dict) -> dict:
    stored = project.get('commit_template')
    if isinstance(stored, dict) and stored.get('template'):
        return {
            'template': stored['template'],
            'types': list(stored.get('types') or DEFAULT_COMMIT_TEMPLATE['types']),
            'require_scope': bool(stored.get('require_scope', True)),
        }
    return dict(DEFAULT_COMMIT_TEMPLATE)


def _run_git(root: str, args: list[str], timeout: int = _GIT_TIMEOUT) -> subprocess.CompletedProcess:
    return subprocess.run(
        ['git', '-C', root, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _is_git_repo(root: str) -> bool:
    if not root or not os.path.isdir(root):
        return False
    try:
        result = _run_git(root, ['rev-parse', '--is-inside-work-tree'])
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
    return result.returncode == 0 and result.stdout.strip() == 'true'


def _simulated_tree(project: dict, note: str = '') -> dict:
    trunk = project.get('default_branch') or 'main'
    payload = {
        'project_id': project['id'],
        'branches': [
            {'name': trunk, 'role': ROLE_TRUNK},
            {'name': 'tree', 'role': ROLE_TREE},
            {'name': 'perch', 'role': ROLE_PERCH},
        ],
        'active': trunk,
        'dirty': 3,
        'ahead_behind': {
            'tree': {'ahead': 2, 'behind': 0},
            'perch': {'ahead': 5, 'behind': 1},
        },
        'source': 'simulated',
    }
    if note:
        payload['note'] = note
    return payload


def _real_tree(project: dict) -> dict:
    """读取真实 git 仓库分支；任何失败回退模拟并注明原因。"""
    root = (project.get('root_path') or '').strip()
    trunk = project.get('default_branch') or 'main'
    if not _is_git_repo(root):
        return _simulated_tree(project, note='root_path 不是可用的 git 仓库，返回模拟三态')
    try:
        branch_proc = _run_git(root, ['branch', '--format=%(refname:short)'])
        if branch_proc.returncode != 0:
            return _simulated_tree(project, note=f'git branch 读取失败：{branch_proc.stderr.strip()[:200]}')
        real_names = [line.strip() for line in branch_proc.stdout.splitlines() if line.strip()]

        active_proc = _run_git(root, ['rev-parse', '--abbrev-ref', 'HEAD'])
        active = active_proc.stdout.strip() if active_proc.returncode == 0 else trunk

        status_proc = _run_git(root, ['status', '--porcelain'])
        dirty = len([line for line in status_proc.stdout.splitlines() if line.strip()]) if status_proc.returncode == 0 else 0

        def _ahead_behind(branch: str) -> dict:
            if branch not in real_names or trunk not in real_names or branch == trunk:
                return {'ahead': 0, 'behind': 0}
            proc = _run_git(root, ['rev-list', '--left-right', '--count', f'{trunk}...{branch}'])
            if proc.returncode != 0:
                return {'ahead': 0, 'behind': 0}
            parts = proc.stdout.split()
            if len(parts) != 2:
                return {'ahead': 0, 'behind': 0}
            behind, ahead = int(parts[0]), int(parts[1])
            return {'ahead': ahead, 'behind': behind}

        semantic = [
            (trunk, ROLE_TRUNK),
            ('tree', ROLE_TREE),
            ('perch', ROLE_PERCH),
        ]
        branches = [
            {
                'name': name,
                'role': role,
                'exists': name in real_names,
                'active': name == active,
            }
            for name, role in semantic
        ]
        semantic_names = {name for name, _ in semantic}
        for name in real_names:
            if name not in semantic_names:
                branches.append({'name': name, 'role': ROLE_WORK, 'exists': True, 'active': name == active})

        return {
            'project_id': project['id'],
            'branches': branches,
            'active': active or trunk,
            'dirty': dirty,
            'ahead_behind': {
                'tree': _ahead_behind('tree'),
                'perch': _ahead_behind('perch'),
            },
            'source': 'git',
        }
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError, ValueError) as exc:
        return _simulated_tree(project, note=f'git 读取异常，已回退模拟：{exc!r}')


def _validate_commit_message(message: str, template_cfg: dict) -> str | None:
    """按项目自定义模板动态生成正则校验 message；返回 None 表示通过。

    占位符 <type>/<scope>/<subject> 由模板串决定位置与字面量；
    require_scope=False 时模板中的 ``(<scope>)`` 片段视为可选。
    """
    template = template_cfg['template']
    pattern = re.escape(template)
    scope_seg = r'\((?P<scope>[^)]*)\)'
    if not template_cfg.get('require_scope'):
        scope_seg = r'(?:' + scope_seg + r')?'
    # 先用哨兵占位带括号的 scope 片段，避免替换结果里的 <scope> 文本被二次替换
    pattern = pattern.replace(r'\(<scope>\)', '\x00SCOPE\x00')
    pattern = pattern.replace('<type>', r'(?P<type>[A-Za-z]+)')
    pattern = pattern.replace('<subject>', r'(?P<subject>.+)')
    pattern = pattern.replace('<scope>', r'(?P<scope>[^)]*)')
    pattern = pattern.replace('\x00SCOPE\x00', scope_seg)
    match = re.match(r'^\s*' + pattern + r'\s*$', message.strip())
    if not match:
        return f'提交信息不符合模板 {template}'
    if '<type>' in template:
        commit_type = match.groupdict().get('type')
        if commit_type and commit_type not in template_cfg['types']:
            return f'type「{commit_type}」不在允许列表：{template_cfg["types"]}'
    if template_cfg.get('require_scope') and '<scope>' in template:
        if not (match.groupdict().get('scope') or '').strip():
            return '该模板要求填写 scope，例如 feat(spaces): ……'
    return None


def _integration_view(kind: str) -> dict:
    stored = _integrations.get(kind)
    if not isinstance(stored, dict) or not stored.get('token_encrypted'):
        return {'kind': kind, 'bound': False}
    view: dict[str, Any] = {'kind': kind, 'bound': True}
    if stored.get('account'):
        view['account'] = stored['account']
    if stored.get('scopes'):
        view['scopes'] = stored['scopes']
    if stored.get('bound_at'):
        view['bound_at'] = stored['bound_at']
    return view


def _check_integration_kind(kind: str) -> None:
    if kind not in INTEGRATION_KINDS:
        raise HTTPException(status_code=404, detail=f'未知集成类型：{kind}（支持 {list(INTEGRATION_KINDS)}）')


def _store_delete(store: JsonStore, key: str) -> None:
    """JsonStore 无公开 delete，锁内读-改-写实现按键删除。"""
    with store._lock:  # noqa: SLF001 —— 与 store 内部方法同一锁
        data = store._read()  # noqa: SLF001
        data.pop(key, None)
        store._write(data)  # noqa: SLF001


# ---------------------------------------------------------------- 项目 CRUD
# 注意路由顺序：固定段路由（projects/integrations）必须先于 /spaces/{pid}/… 注册。


@router.get('/spaces/projects')
def list_projects(kind: str | None = Query(default=None)) -> list[dict]:
    if kind is not None and kind not in PROJECT_KINDS:
        raise HTTPException(status_code=400, detail=f'kind 仅支持 {list(PROJECT_KINDS)}')
    items = [_public_project(p) for p in _projects.all().values() if isinstance(p, dict)]
    if kind is not None:
        items = [p for p in items if p.get('kind') == kind]
    items.sort(key=lambda p: p.get('created_at', ''), reverse=True)
    return items


@router.post('/spaces/projects', status_code=201)
def create_project(body: ProjectIn) -> dict:
    if body.kind not in PROJECT_KINDS:
        raise HTTPException(status_code=400, detail=f'kind 仅支持 {list(PROJECT_KINDS)}')
    project = {
        'id': _new_project_id(),
        'name': body.name.strip(),
        'desc': body.desc,
        'root_path': body.root_path,
        'kind': body.kind,
        'kind_label': PROJECT_KIND_LABELS[body.kind],
        'default_branch': body.default_branch.strip() or 'main',
        'created_at': utc_now_iso(),
        'archived': False,
    }
    _projects.set(project['id'], project)
    return _public_project(project)


@router.get('/spaces/projects/{pid}')
def get_project(pid: str) -> dict:
    return _public_project(_get_project_or_404(pid))


@router.put('/spaces/projects/{pid}')
def update_project(pid: str, body: ProjectUpdateIn) -> dict:
    project = _get_project_or_404(pid)
    changes = body.model_dump(exclude_unset=True)
    if 'kind' in changes:
        if changes['kind'] not in PROJECT_KINDS:
            raise HTTPException(status_code=400, detail=f'kind 仅支持 {list(PROJECT_KINDS)}')
        changes['kind_label'] = PROJECT_KIND_LABELS[changes['kind']]
    if 'name' in changes and not (changes['name'] or '').strip():
        raise HTTPException(status_code=400, detail='name 不能为空')
    if 'default_branch' in changes:
        changes['default_branch'] = (changes['default_branch'] or '').strip() or 'main'
    project.update(changes)
    _projects.set(pid, project)
    return _public_project(project)


@router.delete('/spaces/projects/{pid}')
def delete_project(pid: str) -> dict:
    _get_project_or_404(pid)
    _store_delete(_projects, pid)
    return {'ok': True, 'id': pid}


# ---------------------------------------------------------------- 账号绑定


@router.get('/spaces/integrations')
def list_integrations() -> list[dict]:
    return [_integration_view(kind) for kind in INTEGRATION_KINDS]


@router.post('/spaces/integrations/{kind}/bind')
def bind_integration(kind: str, body: BindIn) -> dict:
    _check_integration_kind(kind)
    token = body.token.strip()
    if not token:
        raise HTTPException(status_code=400, detail='token 不能为空')
    record = {
        'token_encrypted': encryption.encrypt(token),
        'account': (body.account or '').strip() or None,
        'scopes': body.scopes or [],
        'bound_at': utc_now_iso(),
    }
    _integrations.set(kind, record)
    return _integration_view(kind)


@router.post('/spaces/integrations/{kind}/unbind')
def unbind_integration(kind: str) -> dict:
    _check_integration_kind(kind)
    _store_delete(_integrations, kind)
    return {'kind': kind, 'bound': False}


@router.post('/spaces/integrations/{kind}/test')
def test_integration(kind: str) -> dict:
    _check_integration_kind(kind)
    stored = _integrations.get(kind)
    if not isinstance(stored, dict) or not stored.get('token_encrypted'):
        return {'ok': False, 'mode': 'stub', 'note': f'尚未绑定 {kind} 账号，无法测试'}
    token = encryption.decrypt(stored['token_encrypted'])
    if not token:
        return {'ok': False, 'mode': 'stub', 'note': 'token 解密失败（加密密钥可能已变更），请重新绑定'}

    if kind == 'github':
        try:
            with httpx.Client(timeout=5) as client:
                resp = client.get(
                    'https://api.github.com/user',
                    headers={
                        'Authorization': f'Bearer {token}',
                        'Accept': 'application/vnd.github+json',
                        'User-Agent': 'wanwei-shuyi-osagent',
                    },
                )
            if resp.status_code == 200:
                login = resp.json().get('login', 'unknown')
                return {'ok': True, 'mode': 'live', 'note': f'GitHub 连通正常，账号：{login}'}
            return {'ok': False, 'mode': 'live', 'note': f'GitHub 返回 HTTP {resp.status_code}，请检查 token 权限'}
        except (httpx.RequestError, httpx.TimeoutException, ValueError) as exc:
            return {'ok': False, 'mode': 'live', 'note': f'GitHub 连通性测试失败：{exc}'}

    # linear：真实 API 尚未接入，诚实标注 stub
    return {'ok': True, 'mode': 'stub', 'note': 'linear 连通性测试暂未接入真实 API，当前为模拟通过'}


# ---------------------------------------------------------------- 三态视图


@router.get('/spaces/{pid}/tree')
def space_tree(pid: str) -> dict:
    project = _get_project_or_404(pid)
    return _real_tree(project)


# ---------------------------------------------------------------- 提交模板与提交


@router.get('/spaces/{pid}/commit-template')
def get_commit_template(pid: str) -> dict:
    project = _get_project_or_404(pid)
    return _commit_template_of(project)


@router.put('/spaces/{pid}/commit-template')
def put_commit_template(pid: str, body: CommitTemplateIn) -> dict:
    project = _get_project_or_404(pid)
    types = [t.strip() for t in body.types if t and t.strip()]
    if not types:
        raise HTTPException(status_code=400, detail='types 不能为空')
    template_cfg = {
        'template': body.template.strip(),
        'types': types,
        'require_scope': bool(body.require_scope),
    }
    project['commit_template'] = template_cfg
    _projects.set(pid, project)
    return template_cfg


@router.post('/spaces/{pid}/commit')
def commit_in_space(pid: str, body: CommitIn) -> dict:
    project = _get_project_or_404(pid)
    root = (project.get('root_path') or '').strip()
    branch = (body.branch or '').strip() or project.get('default_branch') or 'main'
    if branch.startswith('-') or '..' in branch:
        raise HTTPException(status_code=400, detail=f'非法分支名：{branch}')
    message = body.message.strip()

    if body.gear not in WORK_GEARS:
        return {
            'ok': False,
            'dry_run': body.dry_run,
            'commands': [],
            'error': 'unknown_gear',
            'note': f'未知工作档位：{body.gear}（支持 {list(WORK_GEARS)}）',
        }
    gear_label = WORK_GEARS[body.gear]

    template_cfg = _commit_template_of(project)
    message_error = _validate_commit_message(message, template_cfg)
    if message_error:
        return {
            'ok': False,
            'dry_run': body.dry_run,
            'commands': [],
            'gear': body.gear,
            'gear_label': gear_label,
            'error': 'template_mismatch',
            'note': message_error,
        }

    is_repo = _is_git_repo(root)

    # 组装命令（先切分支，再 add，再 commit）
    commands: list[str] = [f'git -C {root or "."} switch {branch}']
    if body.files:
        commands.append(f'git -C {root or "."} add -- ' + ' '.join(body.files))
    else:
        commands.append(f'git -C {root or "."} add -A')
    commands.append(f'git -C {root or "."} commit -m {message!r}')

    base = {
        'dry_run': body.dry_run,
        'commands': commands,
        'gear': body.gear,
        'gear_label': gear_label,
        'source': 'git' if is_repo else 'simulated',
    }

    if body.dry_run:
        note = '预演模式：仅返回将执行的命令，未改动仓库'
        if not is_repo:
            note += '；root_path 不是真实 git 仓库，真实执行将失败'
        return {'ok': True, **base, 'note': note}

    # 真实提交：人工审查档位不允许直接落盘
    if body.gear == 'human_review':
        return {
            'ok': False,
            **base,
            'error': 'gear_denied',
            'note': '当前为人工审查档位，只允许 dry_run 预览；请切换到沙盒工作或整台设备档位后再真实提交',
        }
    if not is_repo:
        return {
            'ok': False,
            **base,
            'error': 'not_a_git_repo',
            'note': f'root_path（{root or "未配置"}）不是真实 git 仓库，无法真实提交',
        }

    try:
        # 1) 切分支（若已在目标分支则跳过，并同步修正回显命令）
        current_proc = _run_git(root, ['rev-parse', '--abbrev-ref', 'HEAD'])
        current = current_proc.stdout.strip() if current_proc.returncode == 0 else ''
        if current != branch:
            switch_proc = _run_git(root, ['switch', branch])
            if switch_proc.returncode != 0:
                return {
                    'ok': False,
                    **base,
                    'error': 'git_switch_failed',
                    'note': f'git switch {branch} 失败：{switch_proc.stderr.strip()[:300]}',
                }
        else:
            commands = commands[1:]
            base['commands'] = commands

        # 2) add
        add_args = ['add', '--', *body.files] if body.files else ['add', '-A']
        add_proc = _run_git(root, add_args, timeout=15)
        if add_proc.returncode != 0:
            return {
                'ok': False,
                **base,
                'error': 'git_add_failed',
                'note': f'git add 失败：{add_proc.stderr.strip()[:300]}',
            }

        # 3) commit
        commit_proc = _run_git(root, ['commit', '-m', message], timeout=15)
        if commit_proc.returncode != 0:
            return {
                'ok': False,
                **base,
                'error': 'git_commit_failed',
                'note': f'git commit 失败：{commit_proc.stderr.strip()[:300] or commit_proc.stdout.strip()[:300]}',
            }
        rev_proc = _run_git(root, ['rev-parse', 'HEAD'])
        commit_id = rev_proc.stdout.strip() if rev_proc.returncode == 0 else None
        return {
            'ok': True,
            **base,
            'commit_id': commit_id,
            'note': f'已在分支 {branch} 真实提交（档位：{gear_label}）',
        }
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return {
            'ok': False,
            **base,
            'error': 'git_exec_error',
            'note': f'git 执行异常：{exc!r}',
        }
