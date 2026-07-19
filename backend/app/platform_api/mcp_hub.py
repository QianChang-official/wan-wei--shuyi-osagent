"""B8 · MCP 协议枢纽。

职责：
- MCP 服务器注册 CRUD（持久化于 ``JsonStore('mcp_servers')``）；
- 工具发现：stdio 传输下以 JSON-RPC（``initialize`` → ``tools/list``）实时探测，
  subprocess 管道通信；initialize 握手独立 10 秒预算，``tools/list`` /
  ``tools/call`` 每次请求单独计时（默认 30 秒，可用服务器级
  ``timeout_seconds`` 覆盖，上限 300 秒）；
- 调用代理：真实连接可用（enabled + stdio + command）且服务端显式授权
  device 档、command 命中部署白名单时转发 ``tools/call``，
  否则诚实返回 ``stub`` 调用计划；调用记录写入前参数做敏感键打码与
  大小截断，同时落平台审计（``mcp_tool_call``）。
- 总览：服务器数 / 启用数 / 已发现工具数 / 最近 20 条调用记录。

存储约定（单文件 ``platform_mcp_servers.json``）：
- 服务器记录以其 ``id`` 为键；
- 保留键以下划线开头：``_recent_calls``（最近调用，最新在前，≤20 条）、
  ``_seeded_at``（预置示例写入标记，防止用户清空后重复播种）。
- env 值以 ``enc:v1:`` 前缀的 Fernet 密文落盘（复用 platform 统一密钥），
  响应侧仅回键名；存量明文 env 在首次读取时惰性加密回写。
- stdio 子进程使用最小环境，只叠加当前服务器记录配置的 env，不继承
  ``WANWEI_*`` 或父进程里的第三方凭据。

协议说明（诚实边界）：
- 写帧采用平台契约要求的 LSP 风格 ``Content-Length`` 帧；
- 读帧宽容：同时兼容 Content-Length 帧与 MCP 官方 stdio 的换行分隔 JSON
  （NDJSON），以提高对真实 MCP 服务器的命中率；
- sse / streamable_http 传输暂未接入真实连接，相关发现/调用一律返回
  ``stub`` 标识与说明，不伪装已连接。

前端接线现状（诚实边界）：
- 当前模块仅为 API 面，前端 console 尚未接入 ``/platform/mcp/*``
  （全前端无消费者）；注册表 CRUD 与持久化链路仅经 API 级测试验证，
  未走 UI 路径。
"""
import json
import os
import queue
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.platform_api.guards import audit_safe, device_gear_enabled, mask_secret_keys
from app.platform_api.store import JsonStore
from app.security import encryption

router = APIRouter(prefix='/mcp', tags=['mcp-hub'])

_store = JsonStore('mcp_servers')

Transport = Literal['stdio', 'sse', 'streamable_http']

# status 合法取值：unknown（初始/已重置）、connected（探测/调用成功）、
# error（最近一次失败）、timeout（最近一次超时）。连接态只能由服务端根据
# 真实探测/调用结果写入，客户端请求模型仅允许显式重置为 'unknown'
#（合法状态迁移集 {* → unknown}），杜绝直写 'connected' 伪造连接态。

_CALLS_KEY = '_recent_calls'
_SEED_KEY = '_seeded_at'
_COMMAND_CLEAR_KEY = '_preset_command_cleared_at'
_CALLS_CAP = 20
_HANDSHAKE_BUDGET = 10.0  # initialize 握手独立预算（秒），与业务请求计时分离
_DEFAULT_CALL_BUDGET = 30.0  # tools/list、tools/call 单次请求的保守默认预算（秒）
_MAX_CALL_BUDGET = 300.0  # 服务器级 timeout_seconds 上限（秒）

# 真实 stdio 会启动本机进程，必须同时满足服务端 device 授权和显式命令
# 白名单。既支持 PATH 中的可执行文件名，也支持受控绝对路径；不要允许
# python/powershell/cmd 这类通用解释器，以免退化为任意命令执行。
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
    url: str | None = None
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
    url: str | None = None
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
    if not _store.get(_SEED_KEY):
        now = _now()
        mapping: dict[str, Any] = {_SEED_KEY: now}
        for preset in _PRESETS:
            rec = dict(preset)
            rec['created_at'] = now
            rec['tools_cache'] = []
            rec['tools_count'] = 0
            mapping[rec['id']] = rec
        _store.update(mapping)
    _migrate_clear_preset_commands()


def _migrate_clear_preset_commands() -> None:
    """一次性迁移：修复前播种的预置示例仍带可执行 command，将其清空。"""
    if _store.get(_COMMAND_CLEAR_KEY):
        return
    preset_ids = {p['id'] for p in _PRESETS}
    updated: dict[str, Any] = {_COMMAND_CLEAR_KEY: _now()}
    for sid in preset_ids:
        rec = _store.get(sid)
        if not isinstance(rec, dict):
            continue
        # 仅当记录仍携带旧版预置命令（npx/uvx）时才清空，避免误伤用户自定义配置
        old_commands = {'npx', 'uvx'}
        if rec.get('command') in old_commands and not rec.get('enabled'):
            rec['command'] = None
            rec['args'] = []
            rec['note'] = next(
                (p['note'] for p in _PRESETS if p['id'] == sid),
                rec.get('note', ''),
            )
            updated[sid] = rec
    _store.update(updated)


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


def _redact_env(rec: dict) -> dict:
    """返回服务器记录的脱敏副本：env 只保留键名，不暴露真实密钥值。"""
    redacted = dict(rec)
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
        rec = dict(rec)
        rec['env'] = _encrypt_env(env)
        sid = rec.get('id')
        if sid:
            _store.set(sid, rec)
    return plain


def _delete_key(key: str) -> None:
    """JsonStore 无公开 delete，整读重写移除指定键（带锁，失败退化为墓碑）。"""
    data = _store.all()
    if key not in data:
        return
    data.pop(key)
    write = getattr(_store, '_write', None)
    lock = getattr(_store, '_lock', None)
    if callable(write) and lock is not None:
        with lock:
            write(data)
    else:  # 私有结构变化时的兜底：墓碑（读路径已过滤非 dict 值）
        _store.set(key, None)


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
    """响应侧调用计划同样脱敏（stub/error 路径不回显敏感参数值）。"""
    safe = dict(plan)
    safe['arguments'] = _sanitize_call_arguments(plan.get('arguments'))
    return safe


_CALLS_LOCK = threading.Lock()


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
    with _CALLS_LOCK:
        calls = _store.get(_CALLS_KEY, [])
        if not isinstance(calls, list):
            calls = []
        calls.insert(0, entry)
        _store.set(_CALLS_KEY, calls[:_CALLS_CAP])
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
    allowed_names = {item.lower() for item in allowed if '/' not in item and '\\' not in item}
    if basename not in allowed_names:
        raise ValueError(
            f'MCP stdio command「{basename or value}」不在允许列表；'
            f'请通过 {_STDIO_COMMANDS_ENV} 显式配置受信任的 MCP 启动器'
        )
    return resolved


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
    except ValueError as exc:
        audit_safe('mcp_stdio_denied', {
            'server_id': rec.get('id'),
            'action': action,
            'reason': 'command_not_allowed',
        })
        raise HTTPException(status_code=403, detail=str(exc)) from exc
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
    try:
        subprocess.run(
            ['taskkill', '/PID', str(proc.pid), '/T', '/F'],
            capture_output=True,
            timeout=5,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
    except Exception:  # noqa: BLE001 —— taskkill 不可用等场景回退单进程终止
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001 —— 清理阶段不再抛错
            pass
    try:
        proc.wait(timeout=1.5)
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:  # noqa: BLE001 —— 清理阶段不再抛错
            pass


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
        return int(header_line.split(b':', 1)[1].strip())
    except (IndexError, ValueError):
        return None


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
    超时/进程退出/协议错误均抛异常，由调用方落为 error/stub 响应。
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
                    length = _parse_length(stripped)
                    # 吞掉其余头部，直到空行
                    while True:
                        header = stream.readline()
                        if not header or not header.strip():
                            break
                        if header.strip().lower().startswith(b'content-length:'):
                            length = _parse_length(header.strip())
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
        assert self._proc.stdin is not None
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


def _mark_error(sid: str, rec: dict, message: str) -> None:
    rec['status'] = 'error'
    rec['last_error'] = message
    _store.set(sid, rec)


def _mark_timeout(sid: str, rec: dict, message: str) -> None:
    rec['status'] = 'timeout'
    rec['last_error'] = message
    _store.set(sid, rec)


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
    data = payload.model_dump()
    data['env'] = _encrypt_env(data.get('env'))
    rec = {
        'id': sid,
        **data,
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
    rec = _get_server_or_404(sid)
    patch = payload.model_dump(exclude_unset=True)
    if 'env' in patch and patch['env'] is not None:
        patch['env'] = _encrypt_env(patch['env'])
    if {'command', 'args', 'transport'} & patch.keys():
        rec['status'] = 'unknown'
        rec['last_error'] = None
        rec['tools_cache'] = []
        rec['tools_count'] = 0
        rec.pop('last_discovery_at', None)
    rec.update(patch)
    _store.set(sid, rec)
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

    stdio + command 时发起真实 JSON-RPC 探测（握手 10 秒独立预算 +
    按服务器配置的单次请求预算）；其余情形返回 stub/error 标识与说明，
    绝不伪装已连接。
    """
    _ensure_seeded()
    rec = _get_server_or_404(sid)
    if not rec.get('enabled'):
        raise HTTPException(
            status_code=403,
            detail=f'MCP 服务器 {sid} 未启用，请先启用后再执行工具发现',
        )
    transport = rec.get('transport')

    if transport != 'stdio':
        cache = rec.get('tools_cache') or []
        return {
            'server': sid,
            'transport': transport,
            'tools': cache,
            'status': 'stub',
            'note': f'传输方式 {transport} 的真实发现暂未接入（当前仅支持 stdio），返回已缓存清单',
        }
    if not rec.get('command'):
        return {
            'server': sid,
            'transport': transport,
            'tools': [],
            'status': 'stub',
            'note': '未配置 command，无法发起 stdio 探测',
        }
    _require_stdio_execution(rec, action='tools_discovery')

    try:
        rpc = _open_session(rec)
        try:
            result = rpc.request('tools/list')
        finally:
            rpc.close()
    except TimeoutError as exc:
        note = f'工具发现超时：{exc}'
        _mark_timeout(sid, rec, note)
        return {'server': sid, 'transport': transport, 'tools': [], 'status': 'timeout', 'note': note}
    except Exception as exc:  # noqa: BLE001 —— 子进程/协议失败落为 error
        note = f'工具发现失败：{exc}'
        _mark_error(sid, rec, note)
        return {'server': sid, 'transport': transport, 'tools': [], 'status': 'error', 'note': note}

    tools = result.get('tools') if isinstance(result, dict) else None
    tools = tools if isinstance(tools, list) else []
    rec['status'] = 'connected'
    rec['last_error'] = None
    rec['tools_cache'] = tools
    rec['tools_count'] = len(tools)
    rec['last_discovery_at'] = _now()
    _store.set(sid, rec)
    return {
        'server': sid,
        'transport': transport,
        'tools': tools,
        'status': 'connected',
        'source': 'live',
        'note': f'实时探测成功，发现 {len(tools)} 个工具',
    }


# ---------------------------------------------------------------------------
# 调用代理
# ---------------------------------------------------------------------------

@router.post('/servers/{sid}/call')
def call_tool(sid: str, payload: CallIn) -> dict:
    """转发一次 tools/call。

    真实连接可用（enabled + stdio + command）时执行并返回 mode:'live'；
    连接不可用时返回 mode:'stub' 与调用计划；真实调用超时返回 mode:'timeout'；
    其它失败返回 mode:'error'。四种结局都会写入最近调用记录。
    """
    _ensure_seeded()
    rec = _get_server_or_404(sid)
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
    live_ready = rec.get('transport') == 'stdio' and bool(rec.get('command'))

    if not live_ready:
        note = 'MCP 服务器未连接，调用计划已记录'
        _record_call(rec, payload, ok=False, mode='stub', note=note)
        return {'ok': False, 'mode': 'stub', 'note': note, 'plan': _redact_plan(plan)}
    _require_stdio_execution(rec, action='tool_call')

    try:
        rpc = _open_session(rec)
        try:
            result = rpc.request('tools/call', {'name': payload.tool, 'arguments': payload.arguments})
        finally:
            rpc.close()
    except TimeoutError as exc:
        note = f'真实调用超时：{exc}'
        _mark_timeout(sid, rec, note)
        _record_call(rec, payload, ok=False, mode='timeout', note=note)
        return {'ok': False, 'mode': 'timeout', 'note': note, 'plan': _redact_plan(plan)}
    except Exception as exc:  # noqa: BLE001
        note = f'真实调用失败：{exc}'
        _mark_error(sid, rec, note)
        _record_call(rec, payload, ok=False, mode='error', note=note)
        return {'ok': False, 'mode': 'error', 'note': note, 'plan': _redact_plan(plan)}

    rec['status'] = 'connected'
    rec['last_error'] = None
    _store.set(sid, rec)
    note = '真实转发成功'
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
