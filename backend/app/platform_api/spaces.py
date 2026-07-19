"""B3 空间舱：项目管理与空间语义 API。

- 项目 CRUD（项目空间 / 任务空间以 ``kind`` 区分，列表可按 kind 过滤）；
  任务空间可通过 ``parent_id`` 归属项目空间，删除父空间时级联删除后代空间
  （旧数据无 ``parent_id`` 视为根空间，行为不变）。
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

import logging
import os
import re
import shlex
import subprocess
import threading
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.platform_api.deps import WORK_GEARS
from app.platform_api.guards import audit_safe, require_gear, validate_root_path
from app.platform_api.store import JsonStore
from app.security import encryption
from app.utils.datetime_utils import utc_now_iso

router = APIRouter(tags=['spaces'])
logger = logging.getLogger(__name__)

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

# 真实提交互斥锁：同一进程内串行化 git 写操作，避免并发撞 index.lock
_commit_lock = threading.Lock()

# 提交模板支持的占位符
_TEMPLATE_PLACEHOLDERS = ('<type>', '<scope>', '<subject>')


# ---------------------------------------------------------------- 模型


class ProjectIn(BaseModel):
    name: str = Field(..., min_length=1)
    desc: str = ''
    root_path: str = ''
    kind: str = 'project_space'
    default_branch: str = 'main'
    parent_id: str | None = None


class ProjectUpdateIn(BaseModel):
    name: str | None = None
    desc: str | None = None
    root_path: str | None = None
    kind: str | None = None
    default_branch: str | None = None
    parent_id: str | None = None
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
        logger.warning(
            'Space tree git read failed: project_id=%s error_type=%s',
            project.get('id'),
            type(exc).__name__,
            exc_info=True,
        )
        return _simulated_tree(project, note='git 读取失败，已回退模拟')


def _compile_template_pattern(template_cfg: dict) -> re.Pattern:
    """把项目自定义模板编译为正则；非法模板抛 ValueError（调用方转 400）。

    占位符 <type>/<scope>/<subject> 由模板串决定位置与字面量；
    require_scope=False 时模板中的 ``(<scope>)`` 片段视为可选。
    同名占位符出现多次会产生重复命名分组，编译前先行拦截；
    ``re.S`` 让 <subject> 支持多行提交信息。
    """
    template = template_cfg['template']
    for placeholder in _TEMPLATE_PLACEHOLDERS:
        if template.count(placeholder) > 1:
            raise ValueError(
                f'模板中占位符 {placeholder} 出现多次，会产生重复正则命名分组，请只保留一处'
            )
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
    try:
        return re.compile(r'^\s*' + pattern + r'\s*$', flags=re.S)
    except re.error as exc:
        logger.warning(
            'Space commit template regex compilation failed: error_type=%s',
            type(exc).__name__,
            exc_info=True,
        )
        raise ValueError('提交模板无法编译为正则') from exc


def _validate_commit_message(message: str, template_cfg: dict, regex: re.Pattern) -> str | None:
    """按编译后的模板正则校验 message；返回 None 表示通过。"""
    template = template_cfg['template']
    match = regex.match(message.strip())
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


# git check-ref-format 规则子集：空格、控制字符与 ~^:?*[\ 一律非法
_BRANCH_FORBIDDEN_CHARS = re.compile(r'[\x00-\x1f\x7f ~^:?*\[\\]')


def _validate_branch_name(branch: str) -> str | None:
    """按 git check-ref-format 规则子集校验分支名；返回 None 表示合法。"""
    if not branch:
        return '分支名不能为空'
    if branch.startswith('-'):
        return f'分支名不能以 - 开头：{branch}'
    if _BRANCH_FORBIDDEN_CHARS.search(branch):
        return f'分支名含非法字符（空格/控制字符/~^:?*[\\）：{branch}'
    if '..' in branch or '@{' in branch:
        return f'分支名含非法序列（.. 或 @{{）：{branch}'
    if branch == '@':
        return '分支名不能为单独的 @'
    if branch.startswith('/') or branch.endswith('/') or '//' in branch:
        return f'分支名不能以 / 开头或结尾，也不能含 //：{branch}'
    if branch.endswith('.'):
        return f'分支名不能以 . 结尾：{branch}'
    if branch.endswith('.lock'):
        return f'分支名不能以 .lock 结尾：{branch}'
    if any(part.startswith('.') for part in branch.split('/')):
        return f'分支名路径段不能以 . 开头：{branch}'
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


def _check_root_path(root_path: str | None) -> None:
    """root_path 非空时，校验其落在白名单内且不触及敏感目录。"""
    text = (root_path or '').strip()
    if not text:
        return
    try:
        validate_root_path(text)
    except ValueError as exc:
        logger.warning(
            'Space root path rejected: error_type=%s',
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=422,
            detail='root_path 未通过允许目录白名单校验',
        ) from None


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
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail='name 不能为纯空白字符')
    parent_id = (body.parent_id or '').strip() or None
    if parent_id is not None and not isinstance(_projects.get(parent_id), dict):
        raise HTTPException(status_code=400, detail=f'父空间不存在：{parent_id}')
    _check_root_path(body.root_path)
    project = {
        'id': _new_project_id(),
        'name': name,
        'desc': body.desc,
        'root_path': body.root_path,
        'kind': body.kind,
        'kind_label': PROJECT_KIND_LABELS[body.kind],
        'default_branch': body.default_branch.strip() or 'main',
        'parent_id': parent_id,
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
        raise HTTPException(status_code=422, detail='name 不能为纯空白字符')
    if 'root_path' in changes:
        _check_root_path(changes['root_path'])
    if 'parent_id' in changes:
        parent_id = (changes['parent_id'] or '').strip() or None
        if parent_id is not None:
            if parent_id == pid:
                raise HTTPException(status_code=400, detail='父空间不能是自身')
            if not isinstance(_projects.get(parent_id), dict):
                raise HTTPException(status_code=400, detail=f'父空间不存在：{parent_id}')
        changes['parent_id'] = parent_id
    if 'default_branch' in changes:
        changes['default_branch'] = (changes['default_branch'] or '').strip() or 'main'
    project.update(changes)
    _projects.set(pid, project)
    return _public_project(project)


@router.delete('/spaces/projects/{pid}')
def delete_project(pid: str) -> dict:
    _get_project_or_404(pid)
    # 级联删除后代空间（旧数据无 parent_id 视为根空间，不受影响）
    descendants: list[str] = []
    frontier = [pid]
    all_projects = _projects.all()
    while frontier:
        current = frontier.pop()
        children = [
            key for key, value in all_projects.items()
            if isinstance(value, dict) and value.get('parent_id') == current
        ]
        descendants.extend(children)
        frontier.extend(children)
    for child_id in descendants:
        _store_delete(_projects, child_id)
    _store_delete(_projects, pid)
    return {'ok': True, 'id': pid, 'deleted_children': descendants}


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
    token = stored['token_encrypted']
    try:
        token = encryption.decrypt(token)
    except encryption.LegacyCiphertextError:
        # 02-#4：旧 base64 明文不再原样返回，视同解密失败走下方显式提示路径
        token = ''
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
            logger.warning(
                'GitHub integration probe failed: error_type=%s',
                type(exc).__name__,
                exc_info=True,
            )
            return {'ok': False, 'mode': 'live', 'note': 'GitHub 连通性测试失败，请稍后重试'}

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
    try:
        _compile_template_pattern(template_cfg)
    except ValueError as exc:
        logger.warning(
            'Space commit template rejected: project_id=%s error_type=%s',
            pid,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=400,
            detail='提交模板非法：同一占位符不能出现多次，且模板必须可编译',
        ) from None
    project['commit_template'] = template_cfg
    _projects.set(pid, project)
    if not any(ph in template_cfg['template'] for ph in _TEMPLATE_PLACEHOLDERS):
        return {
            **template_cfg,
            'warning': '模板不含任何占位符（<type>/<scope>/<subject>），校验将退化为字面量全串匹配',
        }
    return template_cfg


@router.post('/spaces/{pid}/commit')
def commit_in_space(pid: str, body: CommitIn) -> dict:
    project = _get_project_or_404(pid)
    root = (project.get('root_path') or '').strip()
    if root:
        try:
            validate_root_path(root)
        except ValueError as exc:
            logger.warning(
                'Space commit root path rejected: project_id=%s error_type=%s',
                pid,
                type(exc).__name__,
            )
            return {
                'ok': False,
                'dry_run': body.dry_run,
                'commands': [],
                'error': 'root_path_denied',
                'note': 'root_path 未通过允许目录白名单校验',
            }
    branch = (body.branch or '').strip() or project.get('default_branch') or 'main'
    branch_error = _validate_branch_name(branch)
    if branch_error:
        raise HTTPException(status_code=400, detail=branch_error)
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

    # device 档默认禁用：未显式授权时拒绝真实提交（dry_run 预览仍允许）
    if not body.dry_run and require_gear(
        body.gear, action='space_commit', context={'project_id': pid, 'branch': branch}
    ):
        return {
            'ok': False,
            'dry_run': body.dry_run,
            'commands': [],
            'gear': body.gear,
            'gear_label': gear_label,
            'error': 'device_gear_disabled',
            'note': '整台设备档默认禁用；请改用沙盒工作档提交，或设 WANWEI_DEVICE_GEAR_ENABLED=1 显式授权（全程审计）',
        }

    template_cfg = _commit_template_of(project)
    try:
        template_re = _compile_template_pattern(template_cfg)
    except ValueError as exc:
        # 历史脏数据（PUT 校验上线前存入的非法模板）：诚实 400 而非 500
        logger.warning(
            'Stored commit template is invalid: project_id=%s error_type=%s',
            pid,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=400,
            detail='项目提交模板非法，请重新保存提交模板',
        ) from None
    message_error = _validate_commit_message(message, template_cfg, template_re)
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

    # 组装命令（先切分支，再 add，再 commit）；回显用 shlex.quote 安全引用，
    # 保证用户复制到 POSIX shell 执行时语义一致
    display_root = root or '.'
    commands: list[str] = [f'git -C {shlex.quote(display_root)} switch {shlex.quote(branch)}']
    if body.files:
        commands.append(
            f'git -C {shlex.quote(display_root)} add -- ' + ' '.join(shlex.quote(f) for f in body.files)
        )
    else:
        commands.append(f'git -C {shlex.quote(display_root)} add -A')
    commands.append(f'git -C {shlex.quote(display_root)} commit -m {shlex.quote(message)}')

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
        audit_safe('gear_denied', {
            'gear': body.gear, 'action': 'space_commit', 'project_id': pid,
            'reason': 'human_review_requires_dry_run',
        })
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

    resp: dict = {}
    original_branch = ''
    switched = False
    # 真实提交全程互斥，避免并发写操作撞 index.lock
    with _commit_lock:
        try:
            # 1) 切分支（若已在目标分支则跳过，并同步修正回显命令）
            current_proc = _run_git(root, ['rev-parse', '--abbrev-ref', 'HEAD'])
            current = current_proc.stdout.strip() if current_proc.returncode == 0 else ''
            original_branch = current
            if current != branch:
                switch_proc = _run_git(root, ['switch', branch])
                if switch_proc.returncode != 0:
                    return {
                        'ok': False,
                        **base,
                        'error': 'git_switch_failed',
                        'note': f'git switch {branch} 失败：{switch_proc.stderr.strip()[:300]}',
                    }
                switched = True
            else:
                commands = commands[1:]
                base['commands'] = commands

            # 2) add
            add_args = ['add', '--', *body.files] if body.files else ['add', '-A']
            add_proc = _run_git(root, add_args, timeout=15)
            if add_proc.returncode != 0:
                resp = {
                    'ok': False,
                    **base,
                    'error': 'git_add_failed',
                    'note': f'git add 失败：{add_proc.stderr.strip()[:300]}',
                }
                return resp

            # 3) commit
            commit_proc = _run_git(root, ['commit', '-m', message], timeout=15)
            if commit_proc.returncode != 0:
                resp = {
                    'ok': False,
                    **base,
                    'error': 'git_commit_failed',
                    'note': f'git commit 失败：{commit_proc.stderr.strip()[:300] or commit_proc.stdout.strip()[:300]}',
                }
                return resp
            rev_proc = _run_git(root, ['rev-parse', 'HEAD'])
            commit_id = rev_proc.stdout.strip() if rev_proc.returncode == 0 else None
            audit_safe('space_commit', {
                'project_id': pid, 'branch': branch, 'gear': body.gear,
                'commit_id': commit_id, 'files': body.files or 'all',
            })
            resp = {
                'ok': True,
                **base,
                'commit_id': commit_id,
                'note': f'已在分支 {branch} 真实提交（档位：{gear_label}）',
            }
            return resp
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            logger.warning(
                'Space commit git execution failed: project_id=%s error_type=%s',
                pid,
                type(exc).__name__,
                exc_info=True,
            )
            resp = {
                'ok': False,
                **base,
                'error': 'git_exec_error',
                'note': 'git 执行失败，请检查仓库路径与 Git 配置',
            }
            return resp
        finally:
            # 无论成功失败，切回进入前的原分支，避免仓库停留在半切换状态。
            # 失败时重试 3 次，仍失败则在响应中给出明确的手工恢复命令。
            if switched and original_branch:
                restore_cmd = f'git -C {shlex.quote(display_root)} switch {shlex.quote(original_branch)}'
                restored = False
                last_err = ''
                for _attempt in range(3):
                    try:
                        back = _run_git(root, ['switch', original_branch], timeout=15)
                        if back.returncode == 0:
                            restored = True
                            break
                        last_err = f'git_exit_{back.returncode}'
                        logger.warning(
                            'Space commit branch restore failed: project_id=%s returncode=%s',
                            pid,
                            back.returncode,
                        )
                    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
                        last_err = type(exc).__name__
                        logger.warning(
                            'Space commit branch restore raised: project_id=%s error_type=%s',
                            pid,
                            type(exc).__name__,
                            exc_info=True,
                        )
                if restored:
                    if resp:
                        resp['commands'].append(restore_cmd)
                else:
                    manual = (
                        f'手工恢复：请在仓库目录执行「git switch {original_branch}」'
                        f'（当前停留在 {branch}）'
                    )
                    if resp:
                        resp['note'] += (
                            f'；警告：切回原分支 {original_branch} 失败（已重试 3 次），'
                            f'{manual}'
                        )
                        resp.setdefault('restore_failed', True)
                        resp.setdefault('restore_command', restore_cmd)
                    audit_safe('space_commit_restore_failed', {
                        'project_id': pid, 'branch': branch, 'original_branch': original_branch,
                        'error': last_err, 'retries': 3,
                    })
