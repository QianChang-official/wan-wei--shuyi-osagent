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

"""万枢编程框架 —— 沙箱策略层（工作区边界 + 命令策略）。

本模块是编程框架的**安全地基**：所有文件读写与命令执行都必须先经过
这里裁决。三条不可动摇的口径：

1. **工作区是硬边界**。任何工具路径先 ``realpath`` 规范化，再用
   ``commonpath`` 判定是否落在工作区根内；``..`` 逃逸、绝对路径越界、
   符号链接指向区外，一律拒绝（``SandboxViolation``）。
2. **系统敏感目录永不触碰**，即便被误配进白名单也拒绝（防呆）。
3. **命令不做 shell 解释**。命令以 ``shlex`` 切分为 argv 后直接
   ``subprocess`` 执行（``shell=False``），因此 ``;``/``|``/``&&``/重定向
   等 shell 元字符不构成注入面；再叠加"安全子命令白名单 + 危险模式黑名单"
   两层裁决。

与 ``platform_api.guards`` 的关系：那里面向"平台级 root_path 白名单"，
本模块面向"单次编码会话的工作区"。工作区根在创建时同样经
``validate_root_path`` 校验，复用同一套敏感目录清单，避免两处口径漂移。
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# 注意：``validate_root_path`` 必须在函数内惰性导入。``coding`` 与
# ``platform_api`` 存在「自动发现 → platform_api.coding → coding.api」
# 的互相引用，模块级导入会成环；惰性导入在首次调用时命中已初始化的缓存。
# 详见 ``platform_api/coding.py`` 的模块说明。

# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------


class SandboxViolation(ValueError):
    """工作区越界 / 命令被策略拒绝。调用方应映射为 403/422。"""


# ---------------------------------------------------------------------------
# 路径边界
# ---------------------------------------------------------------------------

# 与 platform_api.guards 对齐的系统敏感目录（防呆双保险）
_SENSITIVE_ROOTS: tuple[str, ...] = (
    '/etc', '/bin', '/sbin', '/usr', '/boot', '/lib', '/System', '/private',
    'C:\\Windows', 'C:\\Windows\\System32', 'C:\\Program Files',
    'C:\\Program Files (x86)', 'C:\\ProgramData',
)

# 默认拒绝写入的文件名/后缀（密钥、凭据、环境文件）
_SECRET_NAME_PATTERNS = (
    '.env', '.env.local', '.env.production', 'id_rsa', 'id_ed25519',
    '.npmrc', '.pypirc', '.netrc', 'credentials', 'secrets.json',
)
_SECRET_SUFFIXES = ('.pem', '.key', '.p12', '.pfx')

# 单文件读/写上限（字节）——防止把巨型文件灌进上下文或磁盘
MAX_FILE_READ_BYTES = 512 * 1024
MAX_FILE_WRITE_BYTES = 2 * 1024 * 1024
# 单次目录列举 / 检索返回条目上限
MAX_LIST_ENTRIES = 500
MAX_GREP_MATCHES = 200


def _norm(path: Path) -> str:
    """大小写不敏感平台（Windows）统一 normcase 后再比较。"""
    return os.path.normcase(str(path)) if os.name == 'nt' else str(path)


def _is_within(target: Path, root: Path) -> bool:
    norm_root = _norm(root)
    if _norm(target) == norm_root:
        return True
    return any(_norm(parent) == norm_root for parent in target.parents)


@dataclass(frozen=True)
class Workspace:
    """一个编码会话的工作区边界。"""

    root: Path

    @property
    def root_text(self) -> str:
        return os.fspath(self.root)

    def resolve(self, target: str | None, *, must_exist: bool = False) -> Path:
        """把（相对或绝对）路径解析到工作区内，越界即拒绝。

        - 空/缺省 → 工作区根；
        - 相对路径按工作区根拼接；
        - 结果 ``realpath`` 规范化后必须落在工作区根内；
        - ``must_exist=True`` 时要求路径存在（用于读取类工具）。
        """
        text = (target or '').strip()
        if '\x00' in text:
            raise SandboxViolation('路径含非法字符 (NUL)')
        candidate = Path(text)
        if text and (candidate.is_absolute() or (os.name == 'nt' and candidate.drive)):
            # 允许绝对路径，但必须在工作区内（下方统一校验）
            joined = text
        else:
            joined = os.path.join(self.root_text, text) if text else self.root_text

        real = Path(os.path.realpath(joined))
        if not _is_within(real, self.root):
            raise SandboxViolation(f'路径逃出工作区，已拒绝：{text or "."}')
        for sensitive in _SENSITIVE_ROOTS:
            s = Path(os.path.realpath(sensitive))
            if _is_within(real, s):
                raise SandboxViolation(f'路径触及系统敏感目录，已拒绝：{real}')
        if must_exist and not real.exists():
            raise SandboxViolation(f'路径不存在：{text or "."}')
        return real

    def relative(self, target: Path) -> str:
        """返回相对工作区根的 POSIX 风格路径（用于前端展示与稳定引用）。"""
        try:
            return target.relative_to(self.root).as_posix()
        except ValueError:
            return target.as_posix()

    @staticmethod
    def is_secret_name(name: str) -> bool:
        """判断文件名是否为敏感凭据类（写入时默认拒绝）。"""
        lowered = name.lower()
        if lowered in _SECRET_NAME_PATTERNS:
            return True
        return lowered.endswith(_SECRET_SUFFIXES)


def open_workspace(root_path: str) -> Workspace:
    """校验并打开一个工作区。root_path 越界/触及敏感目录时抛 ValueError。"""
    from ..platform_api.guards import validate_root_path  # 惰性导入，断开与 platform_api 的导入环

    root = validate_root_path(root_path)
    if not root.is_dir():
        raise SandboxViolation(f'工作区根不是目录：{root}')
    return Workspace(root=root)


# ---------------------------------------------------------------------------
# 命令策略
# ---------------------------------------------------------------------------

# 只读/安全子命令白名单（首 token 的 basename）。不在此列者需人工审批。
_SAFE_COMMANDS = frozenset({
    'ls', 'dir', 'pwd', 'cd', 'cat', 'head', 'tail', 'wc', 'stat', 'file',
    'find', 'grep', 'rg', 'sed', 'awk', 'sort', 'uniq', 'cut', 'tr', 'echo',
    'which', 'where', 'whoami', 'date', 'env', 'printenv', 'uname',
    'python', 'python3', 'pip', 'node', 'npm', 'pnpm', 'yarn', 'npx',
    'pytest', 'ruff', 'mypy', 'eslint', 'prettier', 'tsc', 'vite',
    'git', 'go', 'cargo', 'rustc', 'javac', 'java', 'mvn', 'gradle',
    'make', 'cmake', 'gcc', 'g++', 'clang', 'diff', 'jq', 'tree', 'du', 'df',
})

# 明确危险：任何情况下都拒绝（黑名单优先于白名单）
_DANGEROUS_COMMANDS = frozenset({
    'rm', 'rmdir', 'del', 'format', 'mkfs', 'dd', 'shutdown', 'reboot',
    'poweroff', 'halt', 'init', 'kill', 'killall', 'pkill', 'chmod', 'chown',
    'chgrp', 'sudo', 'su', 'passwd', 'useradd', 'userdel', 'groupadd',
    'mount', 'umount', 'iptables', 'ufw', 'firewall-cmd', 'systemctl',
    'service', 'crontab', 'at', 'nc', 'netcat', 'nmap', 'telnet',
    'curl', 'wget', 'scp', 'rsync', 'ssh', 'ftp', 'reg', 'regedit',
    'taskkill', 'net', 'netsh', 'bcdedit', 'diskpart',
})

# 危险参数模式（正则）：即便首命令在白名单，命中即拒绝
_DANGEROUS_ARG_PATTERNS = (
    re.compile(r'(^|/)\.\.(/|$)'),           # 路径逃逸
    re.compile(r'^-rf?$|^-fr$|^--recursive$'),  # 递归删除形态（配合 rm 已拦，双保险）
    re.compile(r'^/dev/(sd|hd|nvme|vd)', re.I),
    re.compile(r'^/etc/(passwd|shadow|sudoers)', re.I),
    re.compile(r'>\s*/dev/(sd|hd|nvme)', re.I),
)


@dataclass(frozen=True)
class CommandVerdict:
    """命令策略裁决结果。"""

    risk: str          # low / medium / high
    allowed: bool      # 是否属"直接可执行"（低风险白名单）
    reason: str
    argv: tuple[str, ...]


def _first_token(cmd: str) -> tuple[str, list[str]]:
    try:
        parts = shlex.split(cmd, posix=(os.name != 'nt'))
    except ValueError as exc:
        raise SandboxViolation(f'命令无法解析：{exc}') from exc
    if not parts:
        raise SandboxViolation('命令为空')
    return parts[0], parts[1:]


def classify_command(cmd: str) -> CommandVerdict:
    """把命令归入风险等级并给出是否可直接执行。

    - 黑名单首命令 / 危险参数 → ``high`` 且 ``allowed=False``（上层直接拒绝）；
    - 白名单首命令且无危险参数 → ``low`` 且 ``allowed=True``；
    - 其余 → ``medium`` 且 ``allowed=False``（需审批）。
    """
    text = (cmd or '').strip()
    if not text:
        raise SandboxViolation('命令为空')
    head, rest = _first_token(text)
    base = os.path.basename(head).lower()
    if base.endswith('.exe'):
        base = base[:-4]
    argv = (head, *rest)

    if base in _DANGEROUS_COMMANDS:
        return CommandVerdict('high', False, f'命令「{base}」在危险黑名单中', argv)

    for arg in rest:
        for pattern in _DANGEROUS_ARG_PATTERNS:
            if pattern.search(arg):
                return CommandVerdict('high', False, f'参数命中危险模式：{arg}', argv)

    if base in _SAFE_COMMANDS:
        # git 的写操作单独升风险：提交/推送/重置仍需人工把关
        if base == 'git' and rest and rest[0] in {'commit', 'push', 'reset', 'clean', 'checkout', 'rebase', 'merge'}:
            return CommandVerdict('medium', False, f'git {rest[0]} 属写操作，需审批', argv)
        return CommandVerdict('low', True, '安全白名单命令', argv)

    return CommandVerdict('medium', False, f'命令「{base}」不在安全白名单，需审批', argv)


def run_command(
    workspace: Workspace,
    cmd: str,
    *,
    timeout_s: int = 30,
    max_output_bytes: int = 64 * 1024,
) -> dict:
    """在工作区内执行命令，返回结构化结果。

    - ``shell=False``：不做 shell 解释，元字符无注入面；
    - ``cwd`` 固定为工作区根；
    - 输出按 ``max_output_bytes`` 截断，防止超大输出撑爆内存/上下文；
    - 超时抛 ``subprocess.TimeoutExpired`` 由上层转 ``timeout`` 状态。

    返回 ``{argv, cwd, exit_code, stdout, stderr, truncated}``。
    """
    verdict = classify_command(cmd)
    if not verdict.allowed:
        raise SandboxViolation(f'命令被策略拒绝：{verdict.reason}')

    argv = list(verdict.argv)
    try:
        proc = subprocess.run(  # noqa: S603 —— 已过策略白名单且 shell=False
            argv,
            cwd=workspace.root_text,
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
    except FileNotFoundError:
        return {
            'argv': argv, 'cwd': workspace.root_text, 'exit_code': 127,
            'stdout': '', 'stderr': f'命令不存在：{argv[0]}', 'truncated': False,
            '_missing': True,
        }
    except subprocess.TimeoutExpired:
        raise

    stdout = _decode(proc.stdout)
    stderr = _decode(proc.stderr)
    truncated = False
    if len(stdout) > max_output_bytes:
        stdout = stdout[:max_output_bytes] + f'\n…[输出截断，共 {len(proc.stdout)} 字节]'
        truncated = True
    if len(stderr) > max_output_bytes:
        stderr = stderr[:max_output_bytes] + f'\n…[错误输出截断，共 {len(proc.stderr)} 字节]'
        truncated = True
    return {
        'argv': argv,
        'cwd': workspace.root_text,
        'exit_code': proc.returncode,
        'stdout': stdout,
        'stderr': stderr,
        'truncated': truncated,
    }


def _decode(raw: bytes) -> str:
    """稳健解码子进程输出：优先 UTF-8，回退本地编码，再回退 replace。"""
    if not raw:
        return ''
    for encoding in ('utf-8', sys.getfilesystemencoding() or 'utf-8', 'gbk', 'latin-1'):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode('utf-8', errors='replace')
