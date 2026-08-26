"""B8 · MCP 协议枢纽。

职责：
- MCP 服务器注册 CRUD（持久化于 ``JsonStore('mcp_servers')``）；
- 工具发现：三种传输均以 JSON-RPC（``initialize`` → ``tools/list``）实时探测——
  stdio 走 subprocess 管道通信（需服务端 device 授权 + command 白名单）；
  sse / streamable_http 走 pinned-IP httpx 直连（见下「协议说明」）；
  initialize 握手独立 10 秒预算，``tools/list`` /
  ``tools/call`` 每次请求单独计时（默认 30 秒，可用服务器级
  ``timeout_seconds`` 覆盖，上限 300 秒）；
- 调用代理：真实连接可用（enabled + 各传输所需 command/url 就绪）时转发
  ``tools/call`` 返回 ``live``；连接失败/协议错误如实返回 ``error``（原因入日志，
  不外泄异常细节），超时返回 ``timeout``；``stub`` 仅保留给未来传输类型的
  兜底场景。调用记录写入前参数做敏感键打码与大小截断，同时落平台审计
  （``mcp_tool_call``）。
- 总览：服务器数 / 启用数 / 已发现工具数 / 最近 20 条调用记录。

存储约定（单文件 ``platform_mcp_servers.json``）：
- 服务器记录以其 ``id`` 为键；
- 保留键以下划线开头：``_recent_calls``（最近调用，最新在前，≤20 条）、
  ``_seeded_at``（预置示例写入标记，防止用户清空后重复播种）。
- env 值以 ``enc:v1:`` 前缀的 Fernet 密文落盘（复用 platform 统一密钥），
  响应侧仅回键名；存量明文 env 在首次读取时惰性加密回写。
- stdio 子进程使用最小环境，只叠加当前服务器记录配置的 env，不继承
  ``WANWEI_*`` 或父进程里的第三方凭据。

协议说明：
- 协议版本 2024-11-05，JSON-RPC id 在会话内单调递增；
- stdio：写帧采用平台契约要求的 LSP 风格 ``Content-Length`` 帧；读帧宽容：
  同时兼容 Content-Length 帧与 MCP 官方 stdio 的换行分隔 JSON（NDJSON），
  以提高对真实 MCP 服务器的命中率；
- streamable_http：向用户配置 url 直接 POST JSON-RPC，
  ``Accept: application/json, text/event-stream``；响应体兼容整段 JSON 与
  SSE ``data:`` 帧，遵循 ``Mcp-Session-Id`` 会话头；
- sse：先 GET 建立 ``text/event-stream`` 流读取 ``endpoint`` 事件拿到上报端点
 （相对地址按 SSE url 解析），再向该端点 POST JSON-RPC 并从流上等待匹配
  响应；宽容兼容直接在 POST 响应体返回结果的实现；
- 两种远程传输的每次真实连接都先经 ``resolve_external_url`` 做 pinned-IP
  复核（写入时已过 ``validate_external_url``；连接前复核防 DNS 重绑定），
  以 IP 直连 + 原 Host 头 + https SNI 保持的方式发请求，``trust_env=False``
  且禁跟随重定向；内网/回环目标须由部署者通过
  ``WANWEI_MCP_HTTP_HOST_ALLOWLIST`` 显式精确主机放行，默认全拒。

前端接线现状（诚实边界）：
- 当前模块仅为 API 面，前端 console 尚未接入 ``/platform/mcp/*``
  （全前端无消费者）；注册表 CRUD 与持久化链路仅经 API 级测试验证，
  未走 UI 路径。
"""
import asyncio
import json
import logging
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .guards import audit_safe, device_gear_enabled, mask_secret_keys
from .store import JsonStore
from ..security import encryption
from ..security.ssrf import resolve_external_url, validate_external_url

# Python ≤3.10：asyncio.TimeoutError 与内建 TimeoutError 是两个不同的类，
# 3.11 起才合而为一。asyncio.wait_for 超时抛前者，若只捕获内建类，3.10 上
# 超时会落进通用 Exception 分支被误分类为 error。所有超时捕获点统一用此元组。
_TIMEOUT_ERRORS: tuple[type[BaseException], ...] = tuple(dict.fromkeys((
    TimeoutError,
    getattr(asyncio, 'TimeoutError', TimeoutError),
)))

router = APIRouter(prefix='/mcp', tags=['mcp-hub'])
logger = logging.getLogger(__name__)

_store = JsonStore('mcp_servers')

Transport = Literal['stdio', 'sse', 'streamable_http']

# status 合法取值：unknown（初始/已重置）、connected（探测/调用成功）、
# error（最近一次失败）、timeout（最近一次超时）。连接态只能由服务端根据
# 真实探测/调用结果写入，客户端请求模型仅允许显式重置为 'unknown'
#（合法状态迁移集 {* → unknown}），杜绝直写 'connected' 伪造连接态。

_CALLS_KEY = '_recent_calls'
_SEED_KEY = '_seeded_at'
_COMMAND_CLEAR_KEY = '_preset_command_cleared_at'
_CONFIG_REVISION_KEY = '_config_revision'
_CALLS_CAP = 20
_HANDSHAKE_BUDGET = 10.0  # initialize 握手独立预算（秒），与业务请求计时分离
_DEFAULT_CALL_BUDGET = 30.0  # tools/list、tools/call 单次请求的保守默认预算（秒）
_MAX_CALL_BUDGET = 300.0  # 服务器级 timeout_seconds 上限（秒）
_MAX_CONTENT_LENGTH = 1 * 1024 * 1024  # stdio Content-Length 上限 1MB
_MCP_PROTOCOL_VERSION = '2024-11-05'

# 远程传输（sse / streamable_http）的显式精确主机白名单环境变量。SSRF denylist
# 默认拒绝回环/内网/保留地址；受控部署确需连接本机或内网 MCP 端点时，由部署者
# 以逗号分隔的精确主机名逐个放行（写入校验与真实连接前复核共用同一份白名单）。
_HTTP_ALLOWLIST_ENV = 'WANWEI_MCP_HTTP_HOST_ALLOWLIST'

# SSRF 拦截对调用方的固定公共文案。异常对象的 str() 不得流入对外响应
#（CodeQL py/stack-trace-exposure）；_McpSsrfBlocked 只以此常量构造，
# 捕获方也直接引用常量，不经过 str(exc)。
_SSRF_BLOCKED_NOTE = '目标地址未通过 SSRF 防护校验，已拒绝连接'

# 真实 stdio 会启动本机进程，必须同时满足服务端 device 授权和显式命令
# 白名单。既支持 PATH 中的可执行文件名，也支持受控绝对路径。把
# python/node/powershell 或 npx/uvx 等解释器、包启动器加入白名单，本质上
# 等同授予任意代码执行能力；生产部署应只允许受控的专用 MCP 包装器路径。
_DEFAULT_STDIO_COMMANDS: frozenset[str] = frozenset()
_STDIO_COMMANDS_ENV = 'WANWEI_MCP_STDIO_COMMANDS'

# 子进程只继承定位可执行文件和正常运行所需的非敏感系统变量；任何
# WANWEI_* 服务秘密及父进程中的第三方凭据都不会隐式下放。
_MINIMAL_ENV_KEYS = (
    'PATH', 'PATHEXT', 'COMSPEC', 'SystemRoot', 'WINDIR',
    'HOME', 'USERPROFILE', 'TMP', 'TEMP', 'LANG', 'LC_ALL',
)


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------

class ServerIn(BaseModel):
    """POST /mcp/servers 请求体。"""

    model_config = ConfigDict(extra='forbid')

    name: str = Field(min_length=1)
    transport: Transport
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = Field(default=None, max_length=2048)
    enabled: bool = True
    # 连接态为服务端内部状态，客户端仅可声明/重置为 unknown（缺省即 unknown）
    status: Literal['unknown'] = 'unknown'
    note: str | None = None
    # 服务器级单次请求预算（秒）；缺省用 _DEFAULT_CALL_BUDGET
    timeout_seconds: float | None = Field(default=None, gt=0, le=_MAX_CALL_BUDGET)


class ServerPatch(BaseModel):
    """PUT /mcp/servers/{sid} 请求体（部分更新，仅合并显式传入字段）。"""

    model_config = ConfigDict(extra='forbid')

    name: str | None = Field(default=None, min_length=1)
    transport: Transport | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    url: str | None = Field(default=None, max_length=2048)
    enabled: bool | None = None
    # 仅允许重置为 unknown；connected/error 由服务端探测/调用结果维护
    status: Literal['unknown'] | None = None
    note: str | None = None
    timeout_seconds: float | None = Field(default=None, gt=0, le=_MAX_CALL_BUDGET)


class CallIn(BaseModel):
    """POST /mcp/servers/{sid}/call 请求体。"""

    model_config = ConfigDict(extra='forbid')

    tool: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# 存储辅助
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec='seconds')


def _new_id() -> str:
    return f'srv_{uuid.uuid4().hex[:8]}'


_PRESETS: list[dict[str, Any]] = [
    {
        'id': 'srv_filesystem',
        'name': 'filesystem',
        'transport': 'stdio',
        # 预置示例默认不启用、不配置 command，防止未授权调用触发真实进程拉起。
        # 用户启用前需自行填入可执行命令与允许访问的目录。
        'command': None,
        'args': [],
        'env': {},
        'url': None,
        'enabled': False,
        'status': 'unknown',
        'note': '示例：官方文件系统 MCP 服务器（需 Node.js；启用前请在 command 填入 npx 等启动命令，并确认允许访问的目录）',
    },
    {
        'id': 'srv_brave_search',
        'name': 'brave-search',
        'transport': 'stdio',
        'command': None,
        'args': [],
        'env': {'BRAVE_API_KEY': ''},
        'url': None,
        'enabled': False,
        'status': 'unknown',
        'note': '示例：Brave 搜索 MCP 服务器（需在 env 中填入 BRAVE_API_KEY，并在 command 填入 npx 启动命令后方可启用）',
    },
    {
        'id': 'srv_sqlite',
        'name': 'sqlite',
        'transport': 'stdio',
        'command': None,
        'args': [],
        'env': {},
        'url': None,
        'enabled': False,
        'status': 'unknown',
        'note': '示例：SQLite MCP 服务器（需 uv/uvx；启用前请在 command 填入启动命令，并确认库文件路径）',
    },
]


def _ensure_seeded() -> None:
    """首次访问时写入 3 个预置示例服务器（enabled:false），幂等。"""
    def _seed(data: dict) -> None:
        if data.get(_SEED_KEY):
            return
        now = _now()
        data[_SEED_KEY] = now
        for preset in _PRESETS:
            rec = dict(preset)
            rec['created_at'] = now
            rec['tools_cache'] = []
            rec['tools_count'] = 0
            rec[_CONFIG_REVISION_KEY] = 1
            data[rec['id']] = rec

    if not _store.get(_SEED_KEY):
        _store.mutate(_seed)
    _migrate_clear_preset_commands()


def _migrate_clear_preset_commands() -> None:
    """一次性迁移：修复前播种的预置示例仍带可执行 command，将其清空。"""
    preset_ids = {p['id'] for p in _PRESETS}

    def _migrate(data: dict) -> None:
        if data.get(_COMMAND_CLEAR_KEY):
            return
        for sid in preset_ids:
            stored = data.get(sid)
            if not isinstance(stored, dict):
                continue
            # Only clear untouched, disabled legacy presets; custom commands remain.
            if stored.get('command') not in {'npx', 'uvx'} or stored.get('enabled'):
                continue
            rec = dict(stored)
            rec['command'] = None
            rec['args'] = []
            rec[_CONFIG_REVISION_KEY] = _config_revision(rec) + 1
            rec['note'] = next(
                (p['note'] for p in _PRESETS if p['id'] == sid),
                rec.get('note', ''),
            )
            data[sid] = rec
        data[_COMMAND_CLEAR_KEY] = _now()

    if not _store.get(_COMMAND_CLEAR_KEY):
        _store.mutate(_migrate)


def _servers() -> dict[str, dict]:
    """全部服务器记录（过滤保留键与墓碑）。"""
    return {
        key: value
        for key, value in _store.all().items()
        if not key.startswith('_') and isinstance(value, dict)
    }


def _get_server_or_404(sid: str) -> dict:
    rec = _store.get(sid)
    if not isinstance(rec, dict):
        raise HTTPException(status_code=404, detail=f'MCP 服务器不存在：{sid}')
    return rec


def _config_revision(rec: dict) -> int:
    """Return the persisted configuration generation, tolerating legacy records."""
    value = rec.get(_CONFIG_REVISION_KEY)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _redact_env(rec: dict) -> dict:
    """返回服务器记录的脱敏副本：env 只保留键名，不暴露真实密钥值。"""
    redacted = dict(rec)
    redacted.pop(_CONFIG_REVISION_KEY, None)
    env = redacted.get('env')
    if isinstance(env, dict):
        redacted['env'] = {k: '' for k in env}
    return redacted


# ---------------------------------------------------------------------------
# env 落盘加密（第四批 P1：惰性迁移，读取时自动加密存量明文）
# ---------------------------------------------------------------------------

_ENC_PREFIX = 'enc:v1:'


def _encrypt_env(env: dict[str, str] | None) -> dict[str, str]:
    """落盘前加密 env 值；空值保持空串，不加密（无内容可泄）。"""
    secured: dict[str, str] = {}
    for key, value in (env or {}).items():
        if not isinstance(value, str) or not value:
            secured[key] = value if isinstance(value, str) else ''
        elif value.startswith(_ENC_PREFIX):
            secured[key] = value
        else:
            secured[key] = _ENC_PREFIX + encryption.encrypt(value)
    return secured


def _decrypt_env(rec: dict) -> dict[str, str]:
    """读取侧解密 env；遇到存量明文则惰性加密回写（一次性迁移）。"""
    env = rec.get('env')
    if not isinstance(env, dict):
        return {}
    plain: dict[str, str] = {}
    migrated = False
    for key, value in env.items():
        if not isinstance(value, str) or not value:
            plain[key] = value if isinstance(value, str) else ''
        elif value.startswith(_ENC_PREFIX):
            plain[key] = encryption.decrypt(value[len(_ENC_PREFIX):])
        else:
            # 存量明文：直接使用并回写密文，完成惰性迁移
            plain[key] = value
            migrated = True
    if migrated:
        sid = rec.get('id')
        if sid:
            def _migrate_current(data: dict) -> None:
                current = data.get(sid)
                if not isinstance(current, dict):
                    return
                current_env = current.get('env')
                if not isinstance(current_env, dict):
                    return
                secured_env = _encrypt_env(current_env)
                if secured_env == current_env:
                    return
                updated = dict(current)
                updated['env'] = secured_env
                data[sid] = updated

            # Only replace the current env field. Rewriting the stale record passed
            # here could roll back a concurrent configuration update.
            _store.mutate(_migrate_current)
    return plain


def _delete_key(key: str) -> None:
    """Delete one record through the store's atomic mutation boundary."""
    def _delete(data: dict) -> None:
        data.pop(key, None)

    _store.mutate(_delete)


_CALL_ARGS_LIMIT = 400


def _sanitize_call_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """调用参数入库前脱敏：敏感键打码 + 超长值截断（第四批 P1）。"""
    if not isinstance(arguments, dict):
        return {'_raw': '[非对象参数已省略]'}
    masked = mask_secret_keys(arguments)
    text = json.dumps(masked, ensure_ascii=False)
    if len(text) <= _CALL_ARGS_LIMIT:
        return masked
    return {
        '_truncated': True,
        '_preview': text[:_CALL_ARGS_LIMIT] + f'…[+{len(text) - _CALL_ARGS_LIMIT}字]',
    }


def _redact_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """响应侧调用计划同样脱敏（error/timeout/降级路径不回显敏感参数值）。"""
    safe = dict(plan)
    safe['arguments'] = _sanitize_call_arguments(plan.get('arguments'))
    return safe


def _record_call(rec: dict, payload: CallIn, *, ok: bool, mode: str, note: str) -> dict:
    """向 _recent_calls 追加一条调用记录（最新在前，封顶 20 条）。

    读-改-写收进模块级单锁，避免并发调用互相覆盖丢记录（_CALLS_KEY
    的唯一写方即本函数，模块级锁即可保证原子性）。
    """
    entry = {
        'id': f'call_{uuid.uuid4().hex[:8]}',
        'ts': _now(),
        'server_id': rec.get('id'),
        'server_name': rec.get('name'),
        'tool': payload.tool,
        'arguments': _sanitize_call_arguments(payload.arguments),
        'ok': ok,
        'mode': mode,
        'note': note,
    }
    def _prepend(data: dict) -> None:
        calls = data.get(_CALLS_KEY, [])
        if not isinstance(calls, list):
            calls = []
        calls.insert(0, entry)
        data[_CALLS_KEY] = calls[:_CALLS_CAP]

    _store.mutate(_prepend)
    audit_safe('mcp_tool_call', {
        'server_id': rec.get('id'),
        'tool': payload.tool,
        'arguments': _sanitize_call_arguments(payload.arguments),
        'ok': ok,
        'mode': mode,
    })
    return entry


# ---------------------------------------------------------------------------
# stdio JSON-RPC 客户端（Content-Length 帧写入，宽容读帧；握手与请求分离计时）
# ---------------------------------------------------------------------------

# cmd.exe 元字符：.cmd/.bat shim 经 cmd 解析时这些字符可逃逸引号上下文
# （含 %VAR% 展开与 " 切换引用状态），逐 token 拒绝以杜绝注入。
_CMD_METACHARS = frozenset('&|<>^%!\r\n"')


def _allowed_stdio_commands() -> set[str]:
    """返回允许启动的 MCP stdio 命令（文件名或受控绝对路径）。"""
    configured = os.environ.get(_STDIO_COMMANDS_ENV, '').strip()
    raw = configured.split(',') if configured else _DEFAULT_STDIO_COMMANDS
    return {item.strip() for item in raw if item.strip()}


def _validate_stdio_command(command: str) -> str:
    """解析并校验 stdio command；拒绝通用解释器和未显式允许的命令。"""
    value = (command or '').strip()
    if not value:
        raise ValueError('MCP stdio command 不能为空')
    allowed = _allowed_stdio_commands()
    has_path = '/' in value or '\\' in value
    if has_path:
        candidate = os.path.normcase(os.path.abspath(value))
        allowed_paths = {
            os.path.normcase(os.path.abspath(item))
            for item in allowed
            if '/' in item or '\\' in item
        }
        if candidate not in allowed_paths:
            raise ValueError(
                'MCP stdio command 路径不在允许列表；'
                f'请通过 {_STDIO_COMMANDS_ENV} 配置该受信任绝对路径'
            )
        return candidate
    resolved = shutil.which(value) or value
    basename = os.path.basename(resolved).lower()
    requested_name = os.path.basename(value).lower()
    allowed_names = {item.lower() for item in allowed if '/' not in item and '\\' not in item}
    if requested_name not in allowed_names and basename not in allowed_names:
        raise ValueError(
            f'MCP stdio command「{basename or value}」不在允许列表；'
            f'请通过 {_STDIO_COMMANDS_ENV} 显式配置受信任的 MCP 启动器'
        )
    return resolved


_INTERPRETER_LAUNCHER_RE = re.compile(
    r'^(?:python(?:\d+(?:\.\d+)*)?|py|node|npx|uv|uvx|bun|deno|ruby|perl|php|'
    r'sh|bash|zsh|fish|pwsh|powershell|cmd)$',
)
_INLINE_EXEC_FLAGS = frozenset({
    '-c', '/c', '/k', '--command', '-command', '-e', '--eval', '-p', '--print',
    '--call', '-encodedcommand', '-encodedarguments', '-enc', '-ec',
})
_CASE_INSENSITIVE_LAUNCHERS = frozenset({'pwsh', 'powershell', 'cmd'})
_COMBINABLE_INLINE_FLAGS: dict[str, frozenset[str]] = {
    'sh': frozenset({'c'}),
    'bash': frozenset({'c'}),
    'zsh': frozenset({'c'}),
    'fish': frozenset({'c'}),
    'node': frozenset({'e', 'p'}),
    'ruby': frozenset({'e'}),
    'perl': frozenset({'e'}),
}
_PYTHON_COMBINABLE_SHORT_OPTIONS = frozenset('bBdEiIOPqRrsStTuvUx3')


def _launcher_name(command: str) -> str:
    name = os.path.basename((command or '').strip()).lower()
    for suffix in ('.exe', '.cmd', '.bat', '.com'):
        if name.endswith(suffix):
            return name[:-len(suffix)]
    return name


def _python_short_options_execute_inline(token: str) -> bool:
    """Return whether a Python short-option token contains ``-c``.

    CPython combines known no-value switches (for example ``-I`` and ``-B``).
    Every other switch consumes the remainder, terminates parsing, or is invalid,
    so a later ``c`` in that token cannot act as another short option.
    """
    if not token.startswith('-') or token.startswith('--'):
        return False
    for option in token[1:]:
        if option == 'c':
            return True
        if option not in _PYTHON_COMBINABLE_SHORT_OPTIONS:
            return False
    return False


def _cmd_token_executes_command(token: str) -> bool:
    """Return whether one CMD option token contains a ``/c`` or ``/k`` switch."""
    if not token.startswith('/'):
        return False
    # CMD accepts multiple slash-delimited switches in one argv token, so each
    # segment must be inspected instead of comparing only the complete token.
    return any(
        segment.startswith(('c', 'k'))
        for segment in token.lower().split('/')[1:]
        if segment
    )


def _validate_stdio_args(command: str, args: list[str] | None) -> None:
    """Reject direct inline-code switches for allowlisted interpreter launchers.

    An administrator can still deliberately allow an interpreter/package launcher,
    so the deployment allowlist remains a high-trust RCE boundary. The entire
    option vector is inspected until an explicit ``--`` boundary because checking
    only argv[0] is bypassable with harmless-looking leading options.
    """
    values = list(args or [])
    if values and not (command or '').strip():
        raise ValueError('MCP stdio args 不能在 command 为空时单独配置')
    if not values or not _INTERPRETER_LAUNCHER_RE.fullmatch(_launcher_name(command)):
        return
    launcher = _launcher_name(command)
    for raw_value in values:
        token = str(raw_value).strip()
        if token == '--' and launcher not in _CASE_INSENSITIVE_LAUNCHERS:
            break
        if not token:
            continue

        lowered = token.lower()
        option = lowered.split('=', 1)[0]
        case_insensitive = launcher in _CASE_INSENSITIVE_LAUNCHERS
        option_for_match = option if case_insensitive else token.split('=', 1)[0]
        inspected_token = lowered if case_insensitive else token
        has_attached_short_code = any(
            inspected_token.startswith(prefix) and len(token) > len(prefix)
            for prefix in ('-c', '/c', '/k', '-e', '-p')
        )
        is_python_launcher = launcher == 'py' or launcher.startswith('python')
        if is_python_launcher:
            has_combined_inline_flag = _python_short_options_execute_inline(token)
        else:
            combined_flags = _COMBINABLE_INLINE_FLAGS.get(launcher, frozenset())
            short_cluster = token[1:] if re.fullmatch(r'-[A-Za-z]+', token) else ''
            has_combined_inline_flag = bool(combined_flags.intersection(short_cluster))
        has_chained_cmd_execution = launcher == 'cmd' and _cmd_token_executes_command(token)
        if (
            option_for_match in _INLINE_EXEC_FLAGS
            or has_attached_short_code
            or has_combined_inline_flag
            or has_chained_cmd_execution
        ):
            raise ValueError('解释器类 MCP 启动器禁止使用内联代码执行参数')


def _normalize_server_config(record: dict[str, Any]) -> dict[str, Any]:
    """Validate persisted transport fields and return a normalized copy."""
    normalized = dict(record)
    raw_url = normalized.get('url')
    if isinstance(raw_url, str) and raw_url.strip():
        try:
            # 写入即拒：与真实连接前复核共用同一份显式精确主机白名单，
            # 保证「能配置的」与「能连的」不脱节。
            normalized['url'] = validate_external_url(
                raw_url.strip(), allowlist=_http_host_allowlist(),
            )
        except (ValueError, OSError, UnicodeError) as exc:
            logger.warning(
                'MCP transport URL rejected by SSRF policy: error_type=%s',
                type(exc).__name__,
            )
            raise HTTPException(
                status_code=422,
                detail='MCP transport URL 未通过 SSRF 防护校验',
            ) from None
    elif raw_url is not None:
        normalized['url'] = None

    try:
        _validate_stdio_args(
            str(normalized.get('command') or ''),
            normalized.get('args') or [],
        )
    except ValueError as exc:
        logger.warning(
            'MCP stdio arguments rejected: error_type=%s',
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=422,
            detail='MCP stdio 启动参数未通过安全校验',
        ) from None
    return normalized


def _minimal_subprocess_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """构造最小子进程环境，并只叠加当前 MCP 记录显式配置的 env。"""
    child = {
        key: value
        for key in _MINIMAL_ENV_KEYS
        if isinstance((value := os.environ.get(key)), str) and value
    }
    child.update({
        key: value
        for key, value in (extra or {}).items()
        if isinstance(key, str) and isinstance(value, str) and value
    })
    return child


def _require_stdio_execution(rec: dict, *, action: str) -> None:
    """真实 MCP 进程执行的服务端门禁：device 授权 + command 白名单。"""
    if not device_gear_enabled():
        audit_safe('mcp_stdio_denied', {
            'server_id': rec.get('id'),
            'action': action,
            'reason': 'device_gear_disabled',
        })
        raise HTTPException(
            status_code=403,
            detail='真实 MCP stdio 执行默认禁用；需设置 WANWEI_DEVICE_GEAR_ENABLED=1 显式授权',
        )
    try:
        _validate_stdio_command(str(rec.get('command') or ''))
        _validate_stdio_args(
            str(rec.get('command') or ''),
            rec.get('args') or [],
        )
    except ValueError as exc:
        audit_safe('mcp_stdio_denied', {
            'server_id': rec.get('id'),
            'action': action,
            'reason': 'command_or_args_not_allowed',
        })
        logger.warning(
            'MCP stdio command 校验失败：server_id=%s action=%s error_type=%s',
            rec.get('id'), action, type(exc).__name__,
        )
        raise HTTPException(
            status_code=403,
            detail='MCP stdio command 不在服务器允许列表，已拒绝执行',
        ) from None
    audit_safe('mcp_stdio_allowed', {'server_id': rec.get('id'), 'action': action})


def _check_cmd_shim_argv(argv: list[str]) -> None:
    """Windows .cmd/.bat shim 路径逐 token 校验，含 cmd 元字符即拒绝执行。"""
    for token in argv:
        bad = sorted(set(token) & _CMD_METACHARS)
        if bad:
            raise ValueError(
                f'Windows .cmd/.bat shim 的 command/args 含 cmd 元字符 {bad}，已拒绝执行'
            )


def _kill_process_tree(proc: subprocess.Popen) -> None:
    """Windows 进程树回收：taskkill /T 覆盖孙进程、/F 强制；失败回退 terminate。"""
    taskkill_succeeded = False
    try:
        result = subprocess.run(
            ['taskkill', '/PID', str(proc.pid), '/T', '/F'],
            capture_output=True,
            timeout=5,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        taskkill_succeeded = result.returncode == 0
        if not taskkill_succeeded:
            logger.warning(
                'taskkill 回收 MCP 进程树失败：pid=%s returncode=%s',
                proc.pid, result.returncode,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning(
            'taskkill 回收 MCP 进程树失败：pid=%s error_type=%s',
            proc.pid, type(exc).__name__,
        )

    if not taskkill_succeeded:
        try:
            proc.terminate()
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning(
                'terminate 回收 MCP 进程失败：pid=%s error_type=%s',
                proc.pid, type(exc).__name__,
            )
    try:
        proc.wait(timeout=1.5)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning(
            '等待 MCP 进程退出失败：pid=%s error_type=%s',
            proc.pid, type(exc).__name__,
        )
        try:
            proc.kill()
        except (OSError, subprocess.SubprocessError) as kill_exc:
            logger.warning(
                'kill 回收 MCP 进程失败：pid=%s error_type=%s',
                proc.pid, type(kill_exc).__name__,
            )


def _request_budget(rec: dict) -> float:
    """服务器级单次请求预算：优先记录里的 timeout_seconds，缺省保守默认。"""
    try:
        value = float(rec.get('timeout_seconds') or 0)
    except (TypeError, ValueError):
        value = 0.0
    if value <= 0:
        return _DEFAULT_CALL_BUDGET
    return min(value, _MAX_CALL_BUDGET)


def _parse_length(header_line: bytes) -> int | None:
    try:
        length = int(header_line.split(b':', 1)[1].strip())
    except (IndexError, ValueError):
        return None
    if length < 1 or length > _MAX_CONTENT_LENGTH:
        raise ValueError(f'Content-Length {length} out of bounds [1, {_MAX_CONTENT_LENGTH}]')
    return length


def _read_exact(stream: Any, size: int) -> bytes | None:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b''.join(chunks)


class _StdioRpc:
    """一次性 stdio JSON-RPC 会话：启动子进程 → initialize → 一次请求 → 关闭。

    initialize 握手与后续业务请求分别计时（每次 ``request`` 自带 deadline），
    超时/进程退出/协议错误均抛异常，由调用方落为 error 响应。
    """

    def __init__(self, command: str, args: list[str], env: dict[str, str], request_timeout: float):
        self._request_timeout = request_timeout
        self._id = 0
        self._rx: queue.Queue = queue.Queue()

        # 路由在进入真实执行前已调用 _require_stdio_execution 完成服务端授权
        # 与白名单校验；这里仅解析 PATH，便于协议客户端保持可单元测试。
        resolved = shutil.which(command) or command
        argv = [resolved, *(args or [])]
        child_env = _minimal_subprocess_env(env)

        popen_kwargs: dict[str, Any] = {
            'stdin': subprocess.PIPE,
            'stdout': subprocess.PIPE,
            'stderr': subprocess.DEVNULL,
            'env': child_env,
        }
        if os.name == 'nt':
            # 桌面端后台进程不弹控制台窗口；独立进程组，便于整树回收
            popen_kwargs['creationflags'] = (
                getattr(subprocess, 'CREATE_NO_WINDOW', 0)
                | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
            )
        if os.name == 'nt' and resolved.lower().endswith(('.cmd', '.bat')):
            # Windows 的 npx/uvx 是 .cmd shim，CreateProcess 无法直接执行。
            # 不走 shell=True：逐 token 拒绝 cmd 元字符后，构造一次成型的
            # ``cmd.exe /d /s /c "<命令行>"``，shell=False 参数化拉起。
            _check_cmd_shim_argv(argv)
            # CreateProcess 不会对裸文件名做 PATH 搜索，cmd.exe 须解析为全路径
            comspec = (
                os.environ.get('COMSPEC')
                or shutil.which('cmd.exe')
                or os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'cmd.exe')
            )
            inner = subprocess.list2cmdline(argv)
            self._proc = subprocess.Popen(
                f'cmd.exe /d /s /c "{inner}"',
                executable=comspec,
                shell=False,
                **popen_kwargs,
            )
        else:
            self._proc = subprocess.Popen(argv, shell=False, **popen_kwargs)

        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()

    # -- 底层帧 -------------------------------------------------------------

    def _pump(self) -> None:
        """读帧线程：Content-Length 帧或 NDJSON 行，解析后放入队列；EOF 放哨兵。"""
        stream = self._proc.stdout
        try:
            while True:
                line = stream.readline()
                if not line:
                    break
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.lower().startswith(b'content-length:'):
                    try:
                        length = _parse_length(stripped)
                    except ValueError:
                        break
                    # 吞掉其余头部，直到空行
                    while True:
                        header = stream.readline()
                        if not header or not header.strip():
                            break
                        if header.strip().lower().startswith(b'content-length:'):
                            try:
                                length = _parse_length(header.strip())
                            except ValueError:
                                break
                    if not length:
                        continue
                    body = _read_exact(stream, length)
                    if body is None:
                        break
                    self._offer(body)
                elif stripped.startswith(b'{'):
                    self._offer(stripped)
                # 其余行视为服务器日志输出，忽略
        except Exception:  # noqa: BLE001 —— 读帧线程静默收口，由队列哨兵通知主线程
            pass
        finally:
            self._rx.put(None)

    def _offer(self, body: bytes) -> None:
        try:
            msg = json.loads(body.decode('utf-8', errors='replace'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if isinstance(msg, dict):
            self._rx.put(msg)

    def _send(self, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        frame = f'Content-Length: {len(body)}\r\n\r\n'.encode('ascii') + body
        if self._proc.stdin is None:
            raise RuntimeError('MCP stdio 进程 stdin 不可用（内部错误）')
        self._proc.stdin.write(frame)
        self._proc.stdin.flush()

    @staticmethod
    def _remaining(deadline: float, budget: float) -> float:
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError(f'MCP stdio 请求超过 {budget:.0f} 秒预算')
        return left

    # -- 会话动作 -----------------------------------------------------------

    def request(self, method: str, params: dict | None = None, *, timeout: float | None = None) -> Any:
        """发起一次请求并等待匹配响应；每次请求独立计时（默认用会话预算）。"""
        budget = timeout if timeout is not None else self._request_timeout
        deadline = time.monotonic() + budget
        self._id += 1
        rid = self._id
        self._send({'jsonrpc': '2.0', 'id': rid, 'method': method, 'params': params or {}})
        while True:
            try:
                msg = self._rx.get(timeout=self._remaining(deadline, budget))
            except queue.Empty as exc:
                raise TimeoutError(f'{method} 等待响应超时（{budget:.0f}s 预算内）') from exc
            if msg is None:
                raise ConnectionError('MCP 服务器进程已退出或标准输出关闭')
            if msg.get('id') != rid:  # 跳过通知与无关响应
                continue
            if 'error' in msg:
                raise RuntimeError(f'{method} 被服务器拒绝：{msg["error"]}')
            return msg.get('result', {})

    def notify(self, method: str, params: dict | None = None) -> None:
        self._send({'jsonrpc': '2.0', 'method': method, 'params': params or {}})

    def close(self) -> None:
        """关闭会话并回收子进程。

        Windows 下用 taskkill 整树回收：.cmd shim 场景直接 terminate 只杀
        cmd.exe 壳，真实服务器孙进程会变孤儿泄漏。
        """
        try:
            if self._proc.poll() is None:
                if os.name == 'nt':
                    _kill_process_tree(self._proc)
                    return
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=1.5)
                except Exception:  # noqa: BLE001
                    self._proc.kill()
        except Exception:  # noqa: BLE001 —— 清理阶段不再抛错
            pass


def _open_session(rec: dict) -> _StdioRpc:
    """启动子进程并完成 initialize 握手；任何失败抛异常。

    握手用独立预算 ``_HANDSHAKE_BUDGET``，不占用后续 tools/list、
    tools/call 的请求预算（按服务器级 ``timeout_seconds`` 或默认值）。
    """
    rpc = _StdioRpc(rec['command'], rec.get('args') or [], _decrypt_env(rec), _request_budget(rec))
    try:
        rpc.request('initialize', {
            'protocolVersion': '2024-11-05',
            'capabilities': {},
            'clientInfo': {'name': 'wanwei-mcp-hub', 'version': '0.1.0'},
        }, timeout=_HANDSHAKE_BUDGET)
        rpc.notify('notifications/initialized')
    except Exception:
        rpc.close()
        raise
    return rpc


def _update_runtime_state(
    sid: str,
    expected_revision: int,
    *,
    status: str,
    last_error: str | None,
    tools: list | None = None,
) -> bool:
    """CAS runtime results so slow operations cannot overwrite newer config.

    Runtime fields are merged into the current record only when its configuration
    generation still matches the snapshot used to launch the subprocess. A late
    discovery/call result is otherwise discarded, preserving concurrent updates.
    """
    def _apply(data: dict) -> bool:
        current = data.get(sid)
        if not isinstance(current, dict) or _config_revision(current) != expected_revision:
            return False
        updated = dict(current)
        updated['status'] = status
        updated['last_error'] = last_error
        if tools is not None:
            updated['tools_cache'] = tools
            updated['tools_count'] = len(tools)
            updated['last_discovery_at'] = _now()
        data[sid] = updated
        return True

    return bool(_store.mutate(_apply))


def _mark_error(sid: str, expected_revision: int, message: str) -> bool:
    return _update_runtime_state(
        sid,
        expected_revision,
        status='error',
        last_error=message,
    )


def _mark_timeout(sid: str, expected_revision: int, message: str) -> bool:
    return _update_runtime_state(
        sid,
        expected_revision,
        status='timeout',
        last_error=message,
    )


def _finish_discovery(sid: str, transport: Any, expected_revision: int, result: dict) -> dict:
    """三种传输共用的探测成功收尾：提取 tools + CAS 写回连接态与缓存。"""
    tools = result.get('tools') if isinstance(result, dict) else None
    tools = tools if isinstance(tools, list) else []
    state_applied = _update_runtime_state(
        sid,
        expected_revision,
        status='connected',
        last_error=None,
        tools=tools,
    )
    if not state_applied:
        return {
            'server': sid,
            'transport': transport,
            'tools': tools,
            'status': 'stale',
            'source': 'live',
            'note': '实时探测已完成，但配置在执行期间发生变化，结果未写入缓存',
        }
    return {
        'server': sid,
        'transport': transport,
        'tools': tools,
        'status': 'connected',
        'source': 'live',
        'note': f'实时探测成功，发现 {len(tools)} 个工具',
    }


# ---------------------------------------------------------------------------
# sse / streamable_http JSON-RPC 客户端（pinned-IP 直连 + 预算计时）
# ---------------------------------------------------------------------------


class _McpSsrfBlocked(RuntimeError):
    """真实连接前 SSRF 复核未通过；消息固定为 _SSRF_BLOCKED_NOTE，可安全返回给调用方。"""


def _http_host_allowlist() -> list[str]:
    """远程传输的显式精确主机白名单：MCP 专用 env + 全局白名单合并。

    ``WANWEI_MCP_HTTP_HOST_ALLOWLIST`` 为 MCP 专属高信任边界（默认空 = 全拒）；
    全局 ``WANWEI_SSRF_EXTRA_ALLOWED_HOSTS``（security.ssrf 单源）合并在内，
    与其它外呼路径同口径：fake-ip 代理下显式信任的主机才连得出去。
    """
    from ..security.ssrf import extra_allowed_hosts

    raw = os.environ.get(_HTTP_ALLOWLIST_ENV, '')
    merged = [item.strip().lower() for item in raw.split(',') if item.strip()]
    merged.extend(h.lower() for h in extra_allowed_hosts())
    return list(dict.fromkeys(merged))


def _pinned_http_target(url: str, pinned_ip: str) -> tuple[str, dict[str, str], dict[str, str] | None]:
    """把已校验 URL 重写为 pinned IP 直连目标，保留原 Host 头与 https SNI。

    与 ``providers._probe_pinned_url`` 同款模式：TCP 连接钉在解析后的 IP 上，
    httpcore 用 ``sni_hostname`` 扩展对原主机名做证书校验，防止 DNS 重绑定
    在「校验」与「连接」之间替换目标。
    """
    parsed = urlsplit(url)
    hostname = parsed.hostname or ''
    hostname_ascii = hostname.encode('idna').decode('ascii')
    pinned_host = f'[{pinned_ip}]' if ':' in pinned_ip else pinned_ip
    original_host = f'[{hostname_ascii}]' if ':' in hostname_ascii else hostname_ascii
    if parsed.port is not None:
        pinned_host = f'{pinned_host}:{parsed.port}'
        original_host = f'{original_host}:{parsed.port}'
    pinned_url = urlunsplit((parsed.scheme, pinned_host, parsed.path, parsed.query, ''))
    headers = {'Host': original_host}
    extensions = {'sni_hostname': hostname_ascii} if parsed.scheme == 'https' else None
    return pinned_url, headers, extensions


def _prepare_pinned_transport(rec: dict) -> tuple[str, str, dict[str, str], dict[str, str] | None]:
    """远程传输真实连接前的 SSRF 复核：返回 (transport, pinned url, Host 头, 扩展)。

    写入时已经过 ``validate_external_url`` 拒内网/保留地址；这里每次连接前再走
    ``resolve_external_url``，把主机名重新解析并钉住，防 TOCTOU/DNS 重绑定。
    """
    transport = str(rec.get('transport') or '')
    raw_url = str(rec.get('url') or '').strip()
    if not raw_url:
        raise RuntimeError('未配置 url，无法发起远程 MCP 连接')
    try:
        validated_url, pinned_ip = resolve_external_url(
            raw_url, allowlist=_http_host_allowlist(),
        )
        pinned_url, host_headers, extensions = _pinned_http_target(validated_url, pinned_ip)
    except (ValueError, OSError, UnicodeError) as exc:
        # SSRFError 是 ValueError 子类；统一按 SSRF 拒绝处理，不区分细节防泄露。
        logger.warning(
            'MCP remote connect rejected by SSRF policy: server_id=%s error_type=%s',
            rec.get('id'), type(exc).__name__,
        )
        raise _McpSsrfBlocked(_SSRF_BLOCKED_NOTE) from None
    return transport, pinned_url, host_headers, extensions


class _SseFrameParser:
    """增量 SSE 帧解析：逐行 feed，事件以空行结束，完成时返回 (event, data)。"""

    def __init__(self) -> None:
        self._event = 'message'
        self._data_lines: list[str] = []

    def feed(self, line: str) -> tuple[str, str] | None:
        stripped = line.rstrip('\r\n')
        if not stripped:
            if self._data_lines:
                completed = (self._event, '\n'.join(self._data_lines))
                self._event = 'message'
                self._data_lines = []
                return completed
            return None
        if stripped.startswith(':'):  # 注释 / keep-alive
            return None
        lowered = stripped.lower()
        if lowered.startswith('event:'):
            self._event = stripped.split(':', 1)[1].strip() or 'message'
        elif lowered.startswith('data:'):
            self._data_lines.append(stripped.split(':', 1)[1].strip())
        # 其余字段（id:/retry:）与本协议无关，忽略
        return None


def _parse_sse_text(text: str) -> list[tuple[str, str]]:
    """把一段完整 SSE 文本解析成 (event, data) 序列。"""
    parser = _SseFrameParser()
    events: list[tuple[str, str]] = []
    for line in text.splitlines():
        event = parser.feed(line)
        if event:
            events.append(event)
    trailing = parser.feed('')  # 宽容：末尾缺空行也收帧
    if trailing:
        events.append(trailing)
    return events


def _candidate_messages(body: bytes) -> list[Any]:
    """从响应体提取候选 JSON-RPC 消息：优先整段 JSON，兼容 SSE ``data:`` 帧。"""
    if not body:
        return []
    text = body.decode('utf-8', errors='replace')
    stripped = text.lstrip()
    if stripped.startswith('{') or stripped.startswith('['):
        try:
            data = json.loads(stripped)
            return data if isinstance(data, list) else [data]
        except json.JSONDecodeError:
            pass  # 声明 JSON 却不是合法 JSON → 落到 SSE 宽容解析
    messages: list[Any] = []
    for _, data in _parse_sse_text(text):
        if not data:
            continue
        try:
            messages.append(json.loads(data))
        except json.JSONDecodeError:
            continue
    return messages


class _HttpJsonRpc:
    """sse / streamable_http 共用的 JSON-RPC 会话基类（协议版本 2024-11-05）。

    id 单调递增；initialize 握手独立预算，后续请求各自计时。超时抛
    ``TimeoutError``、连接失败抛 ``ConnectionError``、协议/服务端拒绝抛
    ``RuntimeError``，与 stdio 客户端一致，由路由统一落 timeout/error。
    """

    def __init__(self, request_timeout: float):
        self._request_timeout = request_timeout
        self._id = 0

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    @staticmethod
    def _remaining(deadline: float, budget: float) -> float:
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError(f'MCP HTTP 请求超过 {budget:.0f} 秒预算')
        return left

    @staticmethod
    def _validate_response(method: str, message: Any, rid: int) -> dict:
        if (
            not isinstance(message, dict)
            or ('result' not in message and 'error' not in message)
        ):
            raise RuntimeError(f'{method} 收到的不是有效 JSON-RPC 响应')
        if message.get('id') != rid:
            raise RuntimeError(f'{method} 响应 id 不匹配（期待 {rid}）')
        if 'error' in message:
            raise RuntimeError(f'{method} 被服务器拒绝：{message["error"]}')
        result = message.get('result')
        return result if isinstance(result, dict) else {}

    async def initialize(self) -> dict:
        """握手 + initialized 通知；握手独立预算，不占业务请求预算。"""
        result = await self.request(
            'initialize',
            {
                'protocolVersion': _MCP_PROTOCOL_VERSION,
                'capabilities': {},
                'clientInfo': {'name': 'wanwei-mcp-hub', 'version': '0.1.0'},
            },
            timeout=_HANDSHAKE_BUDGET,
        )
        await self.notify('notifications/initialized')
        return result

    async def request(self, method: str, params: dict | None = None, *, timeout: float | None = None) -> dict:
        raise NotImplementedError

    async def notify(self, method: str, params: dict | None = None) -> None:
        raise NotImplementedError

    async def aclose(self) -> None:
        raise NotImplementedError


class _StreamableHttpRpc(_HttpJsonRpc):
    """streamable_http 传输：POST JSON-RPC 到用户配置 url，同步等待响应。

    响应体兼容整段 JSON 与 SSE 帧（Accept 协商 application/json,
    text/event-stream）；遵循服务器下发的 ``Mcp-Session-Id``。
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        pinned_url: str,
        host_headers: dict[str, str],
        extensions: dict[str, str] | None,
        request_timeout: float,
    ):
        super().__init__(request_timeout)
        self._client = client
        self._pinned_url = pinned_url
        self._base_headers = {
            **host_headers,
            'Accept': 'application/json, text/event-stream',
        }
        self._extensions = extensions or {}
        self.session_id: str | None = None

    def _headers(self) -> dict[str, str]:
        headers = dict(self._base_headers)
        if self.session_id:
            headers['Mcp-Session-Id'] = self.session_id
        return headers

    async def _post(self, payload: dict, deadline: float, budget: float) -> httpx.Response:
        method_name = str(payload.get('method'))
        remaining = self._remaining(deadline, budget)
        try:
            response = await asyncio.wait_for(
                self._client.post(
                    self._pinned_url,
                    json=payload,
                    headers=self._headers(),
                    extensions=self._extensions,
                ),
                remaining,
            )
        except _TIMEOUT_ERRORS as exc:
            raise TimeoutError(f'{method_name} 请求超时（{budget:.0f}s 预算内）') from exc
        except httpx.TimeoutException as exc:
            raise TimeoutError(f'{method_name} 请求超时（{budget:.0f}s 预算内）') from exc
        except httpx.HTTPError as exc:
            raise ConnectionError(f'{method_name} 无法连接 MCP 服务器') from exc
        if response.status_code >= 400:
            raise RuntimeError(f'{method_name} 被服务器拒绝：HTTP {response.status_code}')
        session_id = response.headers.get('mcp-session-id')
        if session_id:
            self.session_id = session_id
        return response

    async def request(self, method: str, params: dict | None = None, *, timeout: float | None = None) -> dict:
        budget = timeout if timeout is not None else self._request_timeout
        deadline = time.monotonic() + budget
        rid = self._next_id()
        payload = {'jsonrpc': '2.0', 'id': rid, 'method': method, 'params': params or {}}
        response = await self._post(payload, deadline, budget)
        if response.status_code == 202 or not response.content:
            # 202 只该出现在无 id 的通知上；带 id 的请求收到 202 属协议错误。
            raise RuntimeError(f'{method} 收到无响应体的应答（HTTP {response.status_code}）')
        candidates = _candidate_messages(response.content)
        for message in candidates:
            if isinstance(message, dict) and message.get('id') == rid:
                return self._validate_response(method, message, rid)
        raise RuntimeError(f'{method} 响应中没有匹配 id 的结果')

    async def notify(self, method: str, params: dict | None = None) -> None:
        budget = self._request_timeout
        deadline = time.monotonic() + budget
        payload = {'jsonrpc': '2.0', 'method': method, 'params': params or {}}
        response = await self._post(payload, deadline, budget)
        if response.status_code >= 300:
            logger.warning(
                'MCP streamable_http 通知被拒绝：%s HTTP %s', method, response.status_code,
            )

    async def aclose(self) -> None:
        return None  # 无持久流；连接池随 AsyncClient 关闭回收


class _SseRpc(_HttpJsonRpc):
    """sse 传输：GET 建立 text/event-stream 流拿 endpoint 事件，再 POST JSON-RPC。

    响应在流上异步送达（宽容兼容直接在 POST 响应体返回结果的实现）。POST 与
    SSE 读流共用同一 pinned AsyncClient，endpoint 相对地址按 pinned SSE url
    解析，保证上报目标同样钉在已校验 IP 上。
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        pinned_sse_url: str,
        host_headers: dict[str, str],
        extensions: dict[str, str] | None,
        request_timeout: float,
    ):
        super().__init__(request_timeout)
        self._client = client
        self._sse_url = pinned_sse_url
        self._host_headers = host_headers
        self._extensions = extensions or {}
        self.endpoint_url: str | None = None
        self._parser = _SseFrameParser()
        self._stream_cm: httpx.AsyncResponse | None = None
        self._response: httpx.Response | None = None
        self._line_iterator: Any | None = None  # 跨读持久迭代器，避免丢缓冲半行

    async def connect(self) -> None:
        """建立 SSE 流并等待 endpoint 事件；属连接建立阶段，用握手预算。"""
        deadline = time.monotonic() + _HANDSHAKE_BUDGET
        self._stream_cm = self._client.stream(
            'GET',
            self._sse_url,
            headers={**self._host_headers, 'Accept': 'text/event-stream'},
            extensions=self._extensions,
        )
        try:
            self._response = await asyncio.wait_for(
                self._stream_cm.__aenter__(), self._remaining(deadline, _HANDSHAKE_BUDGET),
            )
        except _TIMEOUT_ERRORS as exc:
            await self.aclose()
            raise TimeoutError(f'MCP SSE 连接超时（{_HANDSHAKE_BUDGET:.0f}s 握手预算内）') from exc
        except httpx.TimeoutException as exc:
            await self.aclose()
            raise TimeoutError(f'MCP SSE 连接超时（{_HANDSHAKE_BUDGET:.0f}s 握手预算内）') from exc
        except httpx.HTTPError as exc:
            await self.aclose()
            raise ConnectionError('MCP SSE 连接失败') from exc
        if self._response.status_code >= 400:
            status = self._response.status_code
            await self.aclose()
            raise RuntimeError(f'MCP SSE 连接被拒绝：HTTP {status}')
        content_type = self._response.headers.get('content-type', '')
        if 'text/event-stream' not in content_type:
            await self.aclose()
            raise RuntimeError(f'MCP SSE 端点返回非事件流响应：{content_type or "未知类型"}')
        self._line_iterator = self._response.aiter_lines()
        while True:
            event = await self._read_event(deadline, _HANDSHAKE_BUDGET)
            if event is None:
                await self.aclose()
                raise ConnectionError('MCP SSE 连接在收到 endpoint 事件前断开')
            name, data = event
            if name != 'endpoint':
                continue  # 其它先导事件忽略
            resolved = urljoin(self._sse_url, data.strip())
            if not data.strip():
                await self.aclose()
                raise RuntimeError('MCP endpoint 事件缺少地址')
            self.endpoint_url = resolved
            return

    async def _read_event(self, deadline: float, budget: float) -> tuple[str, str] | None:
        """从流上读下一个完整事件；EOF 返回 None，超预算抛 TimeoutError。"""
        assert self._line_iterator is not None
        while True:
            remaining = self._remaining(deadline, budget)
            try:
                line = await asyncio.wait_for(self._line_iterator.__anext__(), remaining)
            except StopAsyncIteration:
                return None
            except _TIMEOUT_ERRORS as exc:
                raise TimeoutError(f'MCP SSE 等待事件超过 {budget:.0f}s 预算') from exc
            except httpx.TimeoutException as exc:
                raise TimeoutError(f'MCP SSE 等待事件超过 {budget:.0f}s 预算') from exc
            except httpx.HTTPError as exc:
                raise ConnectionError('MCP SSE 读流失败') from exc
            event = self._parser.feed(line)
            if event:
                return event

    async def request(self, method: str, params: dict | None = None, *, timeout: float | None = None) -> dict:
        if self._response is None or not self.endpoint_url:
            raise RuntimeError('MCP SSE 会话尚未建立（内部错误）')
        budget = timeout if timeout is not None else self._request_timeout
        deadline = time.monotonic() + budget
        rid = self._next_id()
        payload = {'jsonrpc': '2.0', 'id': rid, 'method': method, 'params': params or {}}
        remaining = self._remaining(deadline, budget)
        try:
            post_response = await asyncio.wait_for(
                self._client.post(
                    self.endpoint_url,
                    json=payload,
                    headers={**self._host_headers, 'Accept': 'application/json'},
                ),
                remaining,
            )
        except _TIMEOUT_ERRORS as exc:
            raise TimeoutError(f'{method} 上报超时（{budget:.0f}s 预算内）') from exc
        except httpx.TimeoutException as exc:
            raise TimeoutError(f'{method} 上报超时（{budget:.0f}s 预算内）') from exc
        except httpx.HTTPError as exc:
            raise ConnectionError(f'{method} 无法连接 MCP 上报端点') from exc
        if post_response.status_code >= 400:
            raise RuntimeError(f'{method} 被服务器拒绝：HTTP {post_response.status_code}')
        # 宽容快路径：部分实现直接在 POST 响应体里回结果
        for message in _candidate_messages(post_response.content):
            if isinstance(message, dict) and message.get('id') == rid:
                return self._validate_response(method, message, rid)
        # 标准路径：响应经 SSE 流异步送达
        while True:
            event = await self._read_event(deadline, budget)
            if event is None:
                raise ConnectionError('MCP SSE 连接在收到响应前断开')
            _, data = event
            if not data:
                continue
            try:
                message = json.loads(data)
            except json.JSONDecodeError:
                continue  # 非JSON帧忽略
            if isinstance(message, dict) and message.get('id') == rid:
                return self._validate_response(method, message, rid)
            # 其它 id 的响应/通知跳过

    async def notify(self, method: str, params: dict | None = None) -> None:
        if not self.endpoint_url:
            raise RuntimeError('MCP SSE 会话尚未建立（内部错误）')
        budget = self._request_timeout
        deadline = time.monotonic() + budget
        payload = {'jsonrpc': '2.0', 'method': method, 'params': params or {}}
        remaining = self._remaining(deadline, budget)
        try:
            response = await asyncio.wait_for(
                self._client.post(self.endpoint_url, json=payload, headers=self._host_headers),
                remaining,
            )
        except _TIMEOUT_ERRORS as exc:
            raise TimeoutError(f'{method} 上报超时（{budget:.0f}s 预算内）') from exc
        except httpx.TimeoutException as exc:
            raise TimeoutError(f'{method} 上报超时（{budget:.0f}s 预算内）') from exc
        except httpx.HTTPError as exc:
            raise ConnectionError(f'{method} 无法连接 MCP 上报端点') from exc
        if response.status_code >= 400:
            logger.warning('MCP sse 通知被拒绝：%s HTTP %s', method, response.status_code)

    async def aclose(self) -> None:
        cm = self._stream_cm
        self._stream_cm = None
        self._response = None
        self._line_iterator = None
        if cm is None:
            return
        try:
            await cm.__aexit__(None, None, None)
        except Exception:  # noqa: BLE001 —— 清理阶段不再抛错
            pass


def _open_remote_rpc(
    prepared: tuple[str, str, dict[str, str], dict[str, str] | None],
    client: httpx.AsyncClient,
    budget: float,
) -> _HttpJsonRpc:
    transport, pinned_url, host_headers, extensions = prepared
    if transport == 'sse':
        rpc: _HttpJsonRpc = _SseRpc(client, pinned_url, host_headers, extensions, budget)
    else:
        rpc = _StreamableHttpRpc(client, pinned_url, host_headers, extensions, budget)
    return rpc


async def _remote_discover(rec: dict) -> dict:
    """sse / streamable_http 真实工具发现：SSRF 复核 → initialize → tools/list。"""
    prepared = _prepare_pinned_transport(rec)
    budget = _request_budget(rec)
    # read/write 不设硬超时：流式等待的截止时间由各请求的 wait_for(deadline)
    # 统一裁决，避免 httpx 层先到期的读超时被误分类成连接错误。
    timeout_cfg = httpx.Timeout(
        budget,
        connect=min(budget, _HANDSHAKE_BUDGET),
        read=None,
        pool=min(budget, _HANDSHAKE_BUDGET),
    )
    async with httpx.AsyncClient(timeout=timeout_cfg, follow_redirects=False, trust_env=False) as client:
        rpc = _open_remote_rpc(prepared, client, budget)
        if isinstance(rpc, _SseRpc):
            await rpc.connect()
        try:
            await rpc.initialize()
            return await rpc.request('tools/list')
        finally:
            await rpc.aclose()


async def _remote_call(rec: dict, payload: CallIn) -> dict:
    """sse / streamable_http 真实调用：SSRF 复核 → initialize → tools/call。"""
    prepared = _prepare_pinned_transport(rec)
    budget = _request_budget(rec)
    # 同 _remote_discover：截止时间统一由请求级 wait_for 裁决。
    timeout_cfg = httpx.Timeout(
        budget,
        connect=min(budget, _HANDSHAKE_BUDGET),
        read=None,
        pool=min(budget, _HANDSHAKE_BUDGET),
    )
    async with httpx.AsyncClient(timeout=timeout_cfg, follow_redirects=False, trust_env=False) as client:
        rpc = _open_remote_rpc(prepared, client, budget)
        if isinstance(rpc, _SseRpc):
            await rpc.connect()
        try:
            await rpc.initialize()
            return await rpc.request(
                'tools/call', {'name': payload.tool, 'arguments': payload.arguments},
            )
        finally:
            await rpc.aclose()


# ---------------------------------------------------------------------------
# 服务器注册 CRUD
# ---------------------------------------------------------------------------

@router.get('/servers')
def list_servers() -> dict:
    """服务器列表（含预置示例）；响应中 env 值脱敏。"""
    _ensure_seeded()
    servers = sorted(
        (_redact_env(s) for s in _servers().values()),
        key=lambda s: (s.get('created_at') or '', s.get('id') or ''),
    )
    return {'servers': servers, 'total': len(servers)}


@router.post('/servers', status_code=201)
def create_server(payload: ServerIn) -> dict:
    """注册新 MCP 服务器；env 值加密落盘，响应中脱敏。"""
    _ensure_seeded()
    sid = _new_id()
    data = _normalize_server_config(payload.model_dump())
    data['env'] = _encrypt_env(data.get('env'))
    rec = {
        'id': sid,
        **data,
        _CONFIG_REVISION_KEY: 1,
        'created_at': _now(),
        'tools_cache': [],
        'tools_count': 0,
    }
    _store.set(sid, rec)
    audit_safe('mcp_server_created', {'server_id': sid, 'name': rec.get('name'), 'transport': rec.get('transport')})
    return _redact_env(rec)


@router.get('/servers/{sid}')
def get_server(sid: str) -> dict:
    """单个服务器详情；响应中 env 值脱敏。"""
    _ensure_seeded()
    return _redact_env(_get_server_or_404(sid))


@router.put('/servers/{sid}')
def update_server(sid: str, payload: ServerPatch) -> dict:
    """部分更新服务器配置（仅合并显式传入字段）；env 更新加密落盘，响应脱敏。

    ``command``/``args``/``transport`` 变更时，旧的连接状态与工具缓存随之
    失效：重置 ``status:'unknown'`` 并清空 ``tools_cache``/``tools_count``，
    避免展示与真实配置脱节的陈旧缓存。``status`` 仅允许客户端重置为
    ``'unknown'``，``connected``/``error`` 由服务端探测/调用结果写入。
    """
    _ensure_seeded()
    patch = payload.model_dump(exclude_unset=True)
    if 'env' in patch and patch['env'] is not None:
        patch['env'] = _encrypt_env(patch['env'])

    def _apply(data: dict) -> dict:
        stored = data.get(sid)
        if not isinstance(stored, dict):
            raise HTTPException(status_code=404, detail=f'MCP 服务器不存在：{sid}')
        rec = dict(stored)
        rec.update(patch)
        rec = _normalize_server_config(rec)
        rec[_CONFIG_REVISION_KEY] = _config_revision(stored) + 1
        if {'command', 'args', 'transport', 'url'} & patch.keys():
            rec['status'] = 'unknown'
            rec['last_error'] = None
            rec['tools_cache'] = []
            rec['tools_count'] = 0
            rec.pop('last_discovery_at', None)
        data[sid] = rec
        return rec

    rec = _store.mutate(_apply)
    audit_safe('mcp_server_updated', {'server_id': sid, 'fields': sorted(patch.keys())})
    return _redact_env(rec)


@router.delete('/servers/{sid}')
def delete_server(sid: str) -> dict:
    """注销服务器（历史调用记录保留在总览中）。"""
    _ensure_seeded()
    rec = _get_server_or_404(sid)
    _delete_key(sid)
    audit_safe('mcp_server_deleted', {'server_id': sid, 'name': rec.get('name')})
    return {'ok': True, 'id': sid}


# ---------------------------------------------------------------------------
# 工具发现
# ---------------------------------------------------------------------------

@router.get('/servers/{sid}/tools')
def discover_tools(sid: str) -> dict:
    """实时探测服务器工具清单。

    三种传输均发起真实 JSON-RPC 探测（握手 10 秒独立预算 + 按服务器配置的
    单次请求预算）：stdio 走子进程管道（服务端 device 授权 + command 白名单），
    sse / streamable_http 走 pinned-IP HTTP 客户端；连接失败/协议错误如实
    返回 error（原因入日志，不外泄异常细节），超时返回 timeout，绝不伪装
    已连接。``stub`` 仅保留给未来传输类型的兑底。
    """
    _ensure_seeded()
    rec = _get_server_or_404(sid)
    expected_revision = _config_revision(rec)
    if not rec.get('enabled'):
        raise HTTPException(
            status_code=403,
            detail=f'MCP 服务器 {sid} 未启用，请先启用后再执行工具发现',
        )
    transport = rec.get('transport')

    if transport == 'stdio':
        if not rec.get('command'):
            note = '未配置 command，无法发起 stdio 探测'
            _mark_error(sid, expected_revision, note)
            return {
                'server': sid,
                'transport': transport,
                'tools': [],
                'status': 'error',
                'note': note,
            }
        _require_stdio_execution(rec, action='tools_discovery')

        def _probe() -> dict:
            rpc = _open_session(rec)
            try:
                return rpc.request('tools/list')
            finally:
                rpc.close()
    elif transport in ('sse', 'streamable_http'):
        if not str(rec.get('url') or '').strip():
            note = f'未配置 url，无法发起 {transport} 探测'
            _mark_error(sid, expected_revision, note)
            return {
                'server': sid,
                'transport': transport,
                'tools': [],
                'status': 'error',
                'note': note,
            }

        def _probe() -> dict:
            return asyncio.run(_remote_discover(rec))
    else:
        # 未来传输类型兑底：诚实返回未接入标识与已缓存清单，不伪装已连接。
        cache = rec.get('tools_cache') or []
        return {
            'server': sid,
            'transport': transport,
            'tools': cache,
            'status': 'stub',
            'note': f'传输方式 {transport} 的真实发现暂未接入，返回已缓存清单',
        }

    try:
        result = _probe()
    except _McpSsrfBlocked:
        logger.warning('MCP 工具发现被 SSRF 防护拦截：server_id=%s', sid)
        note = _SSRF_BLOCKED_NOTE
        _mark_error(sid, expected_revision, note)
        return {'server': sid, 'transport': transport, 'tools': [], 'status': 'error', 'note': note}
    except _TIMEOUT_ERRORS:
        # Python ≤3.10 中 asyncio.TimeoutError 与 builtins.TimeoutError 是
        # 两个独立类（3.11+ 起为别名）；wait_for 超时抛的是 asyncio 版本，
        # 统一元组捕获才能让超时如实落为 timeout 而非 error。
        logger.warning('MCP 工具发现超时：server_id=%s', sid, exc_info=True)
        note = '工具发现超时，请稍后重试'
        _mark_timeout(sid, expected_revision, note)
        return {'server': sid, 'transport': transport, 'tools': [], 'status': 'timeout', 'note': note}
    except Exception:  # noqa: BLE001 —— 子进程/协议/网络失败落为 error
        logger.exception('MCP 工具发现失败：server_id=%s', sid)
        note = '工具发现失败，请检查服务器配置或运行状态'
        _mark_error(sid, expected_revision, note)
        return {'server': sid, 'transport': transport, 'tools': [], 'status': 'error', 'note': note}
    return _finish_discovery(sid, transport, expected_revision, result)


# ---------------------------------------------------------------------------
# 调用代理
# ---------------------------------------------------------------------------

@router.post('/servers/{sid}/call')
def call_tool(sid: str, payload: CallIn) -> dict:
    """转发一次 tools/call。

    三种传输的真实连接可用时执行并返回 mode:'live'；真实调用超时返回
    mode:'timeout'；连接失败/协议错误/配置缺失如实返回 mode:'error'
   （原因入日志）；``stub`` 仅保留给未来传输类型兑底。各种结局都会写入
    最近调用记录。
    """
    _ensure_seeded()
    rec = _get_server_or_404(sid)
    expected_revision = _config_revision(rec)
    if not rec.get('enabled'):
        raise HTTPException(
            status_code=403,
            detail=f'MCP 服务器 {sid} 未启用，请先启用后再调用工具',
        )
    plan = {
        'server': sid,
        'server_name': rec.get('name'),
        'tool': payload.tool,
        'arguments': payload.arguments,
    }
    transport = rec.get('transport')
    known_transport = transport in ('stdio', 'sse', 'streamable_http')
    if known_transport and transport == 'stdio':
        live_ready = bool(rec.get('command'))
    elif known_transport:
        live_ready = bool(str(rec.get('url') or '').strip())
    else:
        live_ready = False

    if not live_ready:
        # issue #45 (4.2)：不伪装已连接，HTTP 状态必须是 503 —— 返回 200 会让
        # 前端把未连接渲染成灰色成功。响应体只保留 plan 与机器可读 reason。
        # mode 语义：已知传输但配置缺失 → 'error'；未知传输类型 → 'stub' 兑底。
        record_mode = 'error' if known_transport else 'stub'
        missing_field = 'command' if transport == 'stdio' else 'url'
        note = (
            f'MCP 服务器未配置 {missing_field}，调用计划已记录'
            if known_transport
            else 'MCP 服务器未连接，调用计划已记录'
        )
        _record_call(rec, payload, ok=False, mode=record_mode, note=note)
        raise HTTPException(
            status_code=503,
            detail={
                'ok': False,
                'reason': 'server_not_connected',
                'note': note,
                'plan': _redact_plan(plan),
            },
        )
    if transport == 'stdio':
        _require_stdio_execution(rec, action='tool_call')

        def _forward() -> dict:
            rpc = _open_session(rec)
            try:
                return rpc.request(
                    'tools/call', {'name': payload.tool, 'arguments': payload.arguments},
                )
            finally:
                rpc.close()
    else:

        def _forward() -> dict:
            return asyncio.run(_remote_call(rec, payload))

    try:
        result = _forward()
    except _McpSsrfBlocked:
        logger.warning('MCP 工具调用被 SSRF 防护拦截：server_id=%s tool=%s', sid, payload.tool)
        note = _SSRF_BLOCKED_NOTE
        _mark_error(sid, expected_revision, note)
        _record_call(rec, payload, ok=False, mode='error', note=note)
        return {'ok': False, 'mode': 'error', 'note': note, 'plan': _redact_plan(plan)}
    except _TIMEOUT_ERRORS:
        # Python ≤3.10 中 asyncio.TimeoutError 与 builtins.TimeoutError 是
        # 两个独立类（3.11+ 起为别名）；wait_for 超时抛的是 asyncio 版本，
        # 统一元组捕获才能让超时如实落为 timeout 而非 error。
        logger.warning('MCP 工具调用超时：server_id=%s tool=%s', sid, payload.tool, exc_info=True)
        note = '真实调用超时，请稍后重试'
        _mark_timeout(sid, expected_revision, note)
        _record_call(rec, payload, ok=False, mode='timeout', note=note)
        return {'ok': False, 'mode': 'timeout', 'note': note, 'plan': _redact_plan(plan)}
    except Exception:  # noqa: BLE001
        logger.exception('MCP 工具调用失败：server_id=%s tool=%s', sid, payload.tool)
        note = '真实调用失败，请检查服务器配置或运行状态'
        _mark_error(sid, expected_revision, note)
        _record_call(rec, payload, ok=False, mode='error', note=note)
        return {'ok': False, 'mode': 'error', 'note': note, 'plan': _redact_plan(plan)}

    state_applied = _update_runtime_state(
        sid,
        expected_revision,
        status='connected',
        last_error=None,
    )
    note = (
        '真实转发成功'
        if state_applied
        else '真实转发成功；配置在执行期间发生变化，连接状态未写回'
    )
    _record_call(rec, payload, ok=True, mode='live', note=note)
    return {'ok': True, 'mode': 'live', 'server': sid, 'tool': payload.tool, 'result': result, 'note': note}


# ---------------------------------------------------------------------------
# 总览
# ---------------------------------------------------------------------------

@router.get('/overview')
def overview() -> dict:
    """MCP 枢纽总览：规模统计 + 最近 20 条调用记录。"""
    _ensure_seeded()
    servers = _servers()
    calls = _store.get(_CALLS_KEY, [])
    if not isinstance(calls, list):
        calls = []
    return {
        'servers': len(servers),
        'enabled': sum(1 for s in servers.values() if s.get('enabled')),
        # 只统计实时探测成功（connected）的缓存，失败/陈旧缓存不计入
        'tools_discovered': sum(
            int(s.get('tools_count') or 0)
            for s in servers.values()
            if s.get('status') == 'connected'
        ),
        'recent_calls': calls[:_CALLS_CAP],
    }
