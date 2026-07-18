"""B7 系统服务：系统级能力聚合模块。

挂载于 ``/platform/system`` 前缀（由 platform_api 包自动发现）。

能力清单：
- 防睡眠状态源（桌面端经 IPC powerSaveBlocker 实际执行）
- 通用设置（主题/语言/背景/自启/花瓣，background_opacity 固定只读）
- 语音输入存档（转写为 stub，待配置语音识别 provider）
- 防追踪浏览器（拦截规则 + 启动计划，实际拉起由桌面端执行）
- 模拟器镜像下载（后台守护线程模拟推进，不真实拉取大文件）
- 局域网手机控制（token + 局域网 URL，监听切换由桌面端执行）
- 沙盒命令执行（白名单 + cwd 监禁 + 5s 超时 + 4KB 截断）
- wanwei CLI 使用指南（静态文档）

持久化：JsonStore('system') / JsonStore('emulator')。
真实外部副作用一律遵循「配置就绪才启用，否则明确标注 stub/simulated」。
"""
import base64
import binascii
import os
import re
import secrets
import shlex
import socket
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.platform_api.deps import WORK_GEARS
from app.platform_api.store import JsonStore
from app.utils.datetime_utils import utc_now_iso

router = APIRouter()

_sys_store = JsonStore('system')
_emu_store = JsonStore('emulator')

# 与 store.py 同层 → 项目根；数据目录与 JsonStore 保持一致（支持环境变量覆盖）
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_env_dir = os.environ.get('WANWEI_PLATFORM_DIR', '').strip()
_PLATFORM_DIR = Path(_env_dir) if _env_dir else _PROJECT_ROOT / 'data' / 'platform'
_VOICE_DIR = _PLATFORM_DIR / 'voice'
_SANDBOX_DIR = _PLATFORM_DIR / 'sandbox'

_VOICE_MAX_BYTES = 12 * 1024 * 1024  # 解码后音频上限 12MB
_VOICE_HISTORY_MAX = 200
_SANDBOX_TIMEOUT_S = 5
_SANDBOX_TRUNCATE = 4096
_LAN_DEFAULT_PORT = int(os.environ.get('WANWEI_PORT') or os.environ.get('PORT') or '8000')


def _rel_to_root(path: Path) -> str:
    """尽量给出相对项目根的 POSIX 路径；环境变量把数据目录挪走时退为绝对路径。"""
    try:
        return path.resolve().relative_to(_PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


# ---------------------------------------------------------------------------
# 请求模型（全部禁止未知字段）
# ---------------------------------------------------------------------------

class PowerIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    prevent_sleep: bool | None = None
    mode: Literal['display', 'system'] | None = None


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    theme: Literal['day', 'night', 'auto'] | None = None
    language: Literal['zh-CN', 'en-US'] | None = None
    background_image: str | None = None
    background_opacity: float | None = None  # 固定只读：提交即忽略
    autostart: bool | None = None
    petals: bool | None = None


class VoiceIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    audio_b64: str = Field(min_length=1, max_length=_VOICE_MAX_BYTES * 2)
    mime: str = Field(default='audio/webm', max_length=100)
    duration_ms: int = Field(default=0, ge=0, le=3_600_000)


class BrowserRuleIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    domain: str = Field(min_length=4, max_length=253)
    category: Literal['tracker', 'ad', 'fingerprint']
    enabled: bool = True


class BrowserRuleUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    domain: str | None = Field(default=None, min_length=4, max_length=253)
    category: Literal['tracker', 'ad', 'fingerprint'] | None = None
    enabled: bool | None = None


class BrowserLaunchIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    url: str | None = Field(default=None, max_length=2048)
    profile: Literal['clean'] = 'clean'


class LanVerifyIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    token: str = Field(min_length=1, max_length=128)


class SandboxExecIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    command: str = Field(min_length=1, max_length=500)
    gear: str = Field(min_length=1, max_length=32)


# ---------------------------------------------------------------------------
# 防睡眠
# ---------------------------------------------------------------------------

_POWER_DEFAULTS = {'prevent_sleep': False, 'mode': 'display'}
_POWER_NOTE = '桌面端经 IPC powerSaveBlocker 执行，此处为状态源'


def _power_state() -> dict:
    stored = _sys_store.get('power') or {}
    state = dict(_POWER_DEFAULTS)
    if isinstance(stored.get('prevent_sleep'), bool):
        state['prevent_sleep'] = stored['prevent_sleep']
    if stored.get('mode') in ('display', 'system'):
        state['mode'] = stored['mode']
    return state


@router.get('/system/power')
def power_get() -> dict:
    return {**_power_state(), 'note': _POWER_NOTE}


@router.put('/system/power')
def power_put(req: PowerIn) -> dict:
    state = _power_state()
    for key, value in req.model_dump(exclude_unset=True).items():
        state[key] = value
    _sys_store.set('power', state)
    return {**state, 'note': _POWER_NOTE}


# ---------------------------------------------------------------------------
# 通用设置（background_opacity 固定 0.8 只读；未知字段由 pydantic 拒绝 422）
# ---------------------------------------------------------------------------

_SETTINGS_DEFAULTS: dict[str, Any] = {
    'theme': 'auto',
    'language': 'zh-CN',
    'background_image': None,
    'autostart': False,
    'petals': True,
}
_BACKGROUND_OPACITY_FIXED = 0.8


def _settings_state() -> dict:
    stored = _sys_store.get('settings') or {}
    state = dict(_SETTINGS_DEFAULTS)
    for key in _SETTINGS_DEFAULTS:
        if key in stored:
            state[key] = stored[key]
    state['background_opacity'] = _BACKGROUND_OPACITY_FIXED
    return state


@router.get('/system/settings')
def settings_get() -> dict:
    return _settings_state()


@router.put('/system/settings')
def settings_put(req: SettingsIn) -> dict:
    payload = req.model_dump(exclude_unset=True)
    payload.pop('background_opacity', None)  # 只读字段，PUT 一律忽略
    stored = _sys_store.get('settings') or {}
    stored.update(payload)
    _sys_store.set('settings', stored)
    return _settings_state()


# ---------------------------------------------------------------------------
# 语音输入（仅存档；转写 stub，待配置语音识别 provider）
# ---------------------------------------------------------------------------

_MIME_EXT = {
    'audio/webm': '.webm',
    'audio/wav': '.wav',
    'audio/x-wav': '.wav',
    'audio/mpeg': '.mp3',
    'audio/mp3': '.mp3',
    'audio/ogg': '.ogg',
    'audio/m4a': '.m4a',
    'audio/mp4': '.m4a',
    'audio/aac': '.aac',
    'audio/flac': '.flac',
}
_VOICE_NOTE = '转写待配置语音识别 provider，当前仅存档'


def _voice_history() -> list:
    history = _sys_store.get('voice_history')
    return history if isinstance(history, list) else []


@router.post('/system/voice')
def voice_save(req: VoiceIn) -> dict:
    try:
        raw = base64.b64decode(req.audio_b64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=422, detail='audio_b64 不是合法的 base64 编码')
    if not raw:
        raise HTTPException(status_code=422, detail='音频内容为空')
    if len(raw) > _VOICE_MAX_BYTES:
        raise HTTPException(status_code=413, detail='音频超过 12MB 存档上限')

    voice_id = 'vo_' + uuid.uuid4().hex[:12]
    mime = req.mime.split(';')[0].strip().lower() or 'audio/webm'
    ext = _MIME_EXT.get(mime, '.bin')
    _VOICE_DIR.mkdir(parents=True, exist_ok=True)
    path = _VOICE_DIR / f'{voice_id}{ext}'
    path.write_bytes(raw)

    saved_path = _rel_to_root(path)
    record = {
        'id': voice_id,
        'saved_path': saved_path,
        'mime': req.mime,
        'duration_ms': req.duration_ms,
        'size_bytes': len(raw),
        'created_at': utc_now_iso(),
    }
    history = [record, *_voice_history()][:_VOICE_HISTORY_MAX]
    _sys_store.set('voice_history', history)

    return {
        'id': voice_id,
        'saved_path': saved_path,
        'transcription': None,
        'note': _VOICE_NOTE,
        'stub': True,
    }


@router.get('/system/voice')
def voice_list() -> list:
    return _voice_history()


# ---------------------------------------------------------------------------
# 防追踪浏览器（规则拦截 + 启动计划；实际拉起由桌面端执行）
# ---------------------------------------------------------------------------

_BROWSER_RULE_PRESETS: list[dict] = [
    {'id': 'preset-01', 'domain': 'google-analytics.com', 'category': 'tracker', 'enabled': True},
    {'id': 'preset-02', 'domain': 'googletagmanager.com', 'category': 'tracker', 'enabled': True},
    {'id': 'preset-03', 'domain': 'facebook.net', 'category': 'tracker', 'enabled': True},
    {'id': 'preset-04', 'domain': 'connect.facebook.net', 'category': 'tracker', 'enabled': True},
    {'id': 'preset-05', 'domain': 'analytics.twitter.com', 'category': 'tracker', 'enabled': True},
    {'id': 'preset-06', 'domain': 'scorecardresearch.com', 'category': 'tracker', 'enabled': True},
    {'id': 'preset-07', 'domain': 'quantserve.com', 'category': 'tracker', 'enabled': True},
    {'id': 'preset-08', 'domain': 'hotjar.com', 'category': 'tracker', 'enabled': True},
    {'id': 'preset-09', 'domain': 'mixpanel.com', 'category': 'tracker', 'enabled': True},
    {'id': 'preset-10', 'domain': 'cdn.segment.com', 'category': 'tracker', 'enabled': True},
    {'id': 'preset-11', 'domain': 'amplitude.com', 'category': 'tracker', 'enabled': True},
    {'id': 'preset-12', 'domain': 'umeng.com', 'category': 'tracker', 'enabled': True},
    {'id': 'preset-13', 'domain': 'cnzz.com', 'category': 'tracker', 'enabled': True},
    {'id': 'preset-14', 'domain': 'doubleclick.net', 'category': 'ad', 'enabled': True},
    {'id': 'preset-15', 'domain': 'googlesyndication.com', 'category': 'ad', 'enabled': True},
    {'id': 'preset-16', 'domain': 'googleadservices.com', 'category': 'ad', 'enabled': True},
    {'id': 'preset-17', 'domain': 'criteo.com', 'category': 'ad', 'enabled': True},
    {'id': 'preset-18', 'domain': 'adnxs.com', 'category': 'ad', 'enabled': True},
    {'id': 'preset-19', 'domain': 'ads.yahoo.com', 'category': 'ad', 'enabled': True},
    {'id': 'preset-20', 'domain': 'fpjs.io', 'category': 'fingerprint', 'enabled': True},
]
_DOMAIN_RE = re.compile(r'^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$')


def _normalize_domain(domain: str) -> str:
    d = domain.strip().lower().lstrip('*.')
    if not _DOMAIN_RE.match(d) or '..' in d:
        raise HTTPException(status_code=422, detail=f'域名格式不合法：{domain}')
    return d


def _load_rules() -> list:
    rules = _sys_store.get('browser_rules')
    if not isinstance(rules, list) or not rules:
        rules = [dict(r) for r in _BROWSER_RULE_PRESETS]
        _sys_store.set('browser_rules', rules)
    return rules


@router.get('/system/browser/rules')
def browser_rules_list() -> list:
    return _load_rules()


@router.post('/system/browser/rules')
def browser_rules_create(req: BrowserRuleIn) -> dict:
    rules = _load_rules()
    domain = _normalize_domain(req.domain)
    if any(r.get('domain') == domain for r in rules):
        raise HTTPException(status_code=409, detail=f'域名已存在拦截规则：{domain}')
    rule = {
        'id': 'rule_' + uuid.uuid4().hex[:8],
        'domain': domain,
        'category': req.category,
        'enabled': req.enabled,
    }
    rules.append(rule)
    _sys_store.set('browser_rules', rules)
    return rule


@router.put('/system/browser/rules/{rid}')
def browser_rules_update(rid: str, req: BrowserRuleUpdate) -> dict:
    rules = _load_rules()
    for rule in rules:
        if rule.get('id') == rid:
            payload = req.model_dump(exclude_unset=True)
            if 'domain' in payload:
                payload['domain'] = _normalize_domain(payload['domain'])
            rule.update(payload)
            _sys_store.set('browser_rules', rules)
            return rule
    raise HTTPException(status_code=404, detail=f'规则不存在：{rid}')


@router.post('/system/browser/launch')
def browser_launch(req: BrowserLaunchIn) -> dict:
    rules = _load_rules()
    blocked = [r for r in rules if r.get('enabled')]
    plan = [
        '--incognito',
        '--disable-third-party-cookies',
        '--do-not-track',
        '--disable-background-networking',
        '--disable-sync',
        '--disable-extensions',
        '--no-first-run',
        '--user-data-dir=<临时干净配置目录>',
        f'--host-rules=MAP {" ".join(sorted(r["domain"] for r in blocked[:8]))} ~NOTFOUND',
    ]
    return {
        'ok': True,
        'mode': 'plan',
        'plan': plan,
        'url': req.url,
        'profile': req.profile,
        'blocked_count': len(blocked),
        'note': '由桌面端按此计划拉起浏览器',
    }


# ---------------------------------------------------------------------------
# 模拟器镜像下载（后台守护线程模拟推进：每 0.5s +2%，不真实拉取大文件）
# ---------------------------------------------------------------------------

_EMULATOR_PRESETS: list[dict] = [
    {
        'id': 'kylin-v11-x86_64-qemu',
        'name': 'Kylin V11 x86_64 QEMU',
        'url': 'https://www.kylinos.cn/support/trial/download/kylin-v11-x86_64.qcow2',
        'size_mb': 4352,
    },
    {
        'id': 'kylin-v10-sp3-arm64-qemu',
        'name': 'Kylin V10 SP3 ARM64 QEMU',
        'url': 'https://www.kylinos.cn/support/trial/download/kylin-v10-sp3-arm64.qcow2',
        'size_mb': 3840,
    },
    {
        'id': 'ubuntukylin-2404-amd64-vm',
        'name': 'Ubuntu Kylin 24.04 amd64 VM',
        'url': 'https://www.ubuntukylin.com/downloads/ubuntukylin-24.04-amd64.ova',
        'size_mb': 5120,
    },
]

# 注：任务书原文为「asyncio 后台模拟推进」。实测 starlette TestClient 在请求结束后
# 回收事件循环，asyncio 任务随请求销毁、对外表现与 uvicorn 运行时不一致；为保障
# 「每 0.5s +2%」的可观测行为在任意 ASGI 运行时/测试端下一致，改用守护线程驱动，
# 对外契约（status/progress/simulated 字段与 start/cancel 语义）完全不变。
_download_threads: dict[str, threading.Thread] = {}
_download_stops: dict[str, threading.Event] = {}
_download_lock = threading.Lock()


def _load_downloads() -> dict:
    data = _emu_store.get('downloads')
    if not isinstance(data, dict):
        data = {}
    changed = False
    for preset in _EMULATOR_PRESETS:
        if preset['id'] not in data:
            data[preset['id']] = {
                **preset,
                'status': 'idle',
                'progress': 0,
                'simulated': True,
            }
            changed = True
    if changed or not _emu_store.get('downloads'):
        _emu_store.set('downloads', data)
    return data


def _downloads_list() -> list:
    data = _load_downloads()
    # 服务重启后 downloading 状态失去后台线程，诚实标注为 error
    changed = False
    for did, rec in data.items():
        if rec.get('status') == 'downloading' and did not in _download_threads:
            rec['status'] = 'error'
            rec['note'] = '后台任务中断（服务可能已重启），可重新开始'
            changed = True
    if changed:
        _emu_store.set('downloads', data)
    ordered = [data[p['id']] for p in _EMULATOR_PRESETS if p['id'] in data]
    ordered.extend(rec for did, rec in data.items() if did not in {p['id'] for p in _EMULATOR_PRESETS})
    return ordered


def _progress_download(did: str, stop: threading.Event) -> None:
    try:
        while not stop.wait(0.5):
            data = _load_downloads()
            rec = data.get(did)
            if not rec or rec.get('status') != 'downloading':
                return
            rec['progress'] = min(100, int(rec.get('progress', 0)) + 2)
            if rec['progress'] >= 100:
                rec['status'] = 'done'
                rec['note'] = '模拟下载完成（未真实拉取文件）'
            data[did] = rec
            _emu_store.set('downloads', data)
    except Exception:  # noqa: BLE001 —— 后台线程异常落盘标注，不抛出
        try:
            data = _load_downloads()
            if did in data:
                data[did]['status'] = 'error'
                data[did]['note'] = '模拟推进异常中断'
                _emu_store.set('downloads', data)
        except Exception:  # noqa: BLE001
            pass
    finally:
        with _download_lock:
            _download_threads.pop(did, None)
            _download_stops.pop(did, None)


@router.get('/system/emulator/downloads')
def emulator_downloads_list() -> list:
    return _downloads_list()


@router.post('/system/emulator/downloads/{did}/start')
def emulator_download_start(did: str) -> dict:
    data = _load_downloads()
    rec = data.get(did)
    if not rec:
        raise HTTPException(status_code=404, detail=f'下载项不存在：{did}')
    if rec.get('status') == 'downloading' and did in _download_threads:
        return {**rec, 'ok': True, 'note': '已在模拟下载中'}
    if rec.get('status') == 'done' and int(rec.get('progress', 0)) >= 100:
        return {**rec, 'ok': True, 'note': '已下载完成（模拟），无需重复开始'}

    rec['status'] = 'downloading'
    rec.pop('note', None)
    data[did] = rec
    _emu_store.set('downloads', data)

    stop = threading.Event()
    thread = threading.Thread(
        target=_progress_download,
        args=(did, stop),
        name=f'emulator-download-{did}',
        daemon=True,
    )
    with _download_lock:
        _download_stops[did] = stop
        _download_threads[did] = thread
    thread.start()
    return {
        **rec,
        'ok': True,
        'simulated': True,
        'note': '模拟下载已启动：每 0.5s 推进 2%，不真实拉取大文件',
    }


@router.post('/system/emulator/downloads/{did}/cancel')
def emulator_download_cancel(did: str) -> dict:
    data = _load_downloads()
    rec = data.get(did)
    if not rec:
        raise HTTPException(status_code=404, detail=f'下载项不存在：{did}')
    with _download_lock:
        stop = _download_stops.pop(did, None)
        thread = _download_threads.get(did)
    if stop:
        stop.set()
    if thread and thread.is_alive():
        thread.join(timeout=1.5)
    if rec.get('status') == 'downloading':
        rec['status'] = 'idle'
        rec['note'] = '已取消（进度保留，可继续）'
        data[did] = rec
        _emu_store.set('downloads', data)
    return {**rec, 'ok': True}


# ---------------------------------------------------------------------------
# 局域网手机控制（token + 局域网 URL；监听 0.0.0.0 切换由桌面端执行）
# ---------------------------------------------------------------------------

_LAN_NOTE = '需桌面端切换监听 0.0.0.0 后生效'


def _lan_state() -> dict:
    lan = _sys_store.get('lan')
    return lan if isinstance(lan, dict) else {}


def _detect_lan_ip() -> str | None:
    """UDP 伪连接探测本机出口 IP；失败返回 None。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(('8.8.8.8', 80))
        ip = sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()
    if not ip or ip.startswith('127.'):
        return None
    return ip


@router.get('/system/lan/status')
def lan_status() -> dict:
    lan = _lan_state()
    enabled = bool(lan.get('enabled'))
    return {
        'enabled': enabled,
        'bind': '127.0.0.1',
        'lan_url': lan.get('lan_url') if enabled else None,
        'token_set': bool(lan.get('token')),
    }


@router.post('/system/lan/enable')
def lan_enable() -> dict:
    token = secrets.token_hex(6)  # 12 位十六进制
    ip = _detect_lan_ip()
    ip_placeholder = ip is None
    if ip_placeholder:
        ip = '192.168.1.100'
    lan_url = f'http://{ip}:{_LAN_DEFAULT_PORT}/mobile?token={token}'
    _sys_store.set('lan', {
        'enabled': True,
        'token': token,
        'lan_url': lan_url,
        'port': _LAN_DEFAULT_PORT,
        'ip': ip,
        'ip_placeholder': ip_placeholder,
        'enabled_at': utc_now_iso(),
    })
    result = {
        'enabled': True,
        'lan_url': lan_url,
        'qr_payload': lan_url,
        'token': token,
        'note': _LAN_NOTE,
    }
    if ip_placeholder:
        result['ip_placeholder'] = True
        result['note'] = _LAN_NOTE + '；本机局域网 IP 探测失败，已使用 192.168.x.x 占位，请以实际网卡地址为准'
    return result


@router.post('/system/lan/disable')
def lan_disable() -> dict:
    lan = _lan_state()
    lan['enabled'] = False
    lan['lan_url'] = None
    lan['token'] = None  # 关闭即作废，旧 token 立即失效
    _sys_store.set('lan', lan)
    return lan_status()


@router.post('/system/lan/verify')
def lan_verify(req: LanVerifyIn) -> dict:
    lan = _lan_state()
    stored = lan.get('token') or ''
    ok = bool(lan.get('enabled')) and bool(stored) and secrets.compare_digest(stored, req.token)
    result = {'ok': ok}
    if not ok:
        result['reason'] = '未启用' if not lan.get('enabled') else 'token 不匹配'
    return result


# ---------------------------------------------------------------------------
# 沙盒执行（白名单 + cwd 监禁 data/platform/sandbox/ + 5s 超时 + 4KB 截断）
# ---------------------------------------------------------------------------

# 取值：'any' 任意参数（路径参数须落在监禁目录内）；'none' 不允许参数；list 精确匹配
_SANDBOX_COMMANDS: dict[str, Any] = {
    'ls': 'any',
    'pwd': 'none',
    'cat': 'any',
    'echo': 'any',
    'head': 'any',
    'tail': 'any',
    'wc': 'any',
    'date': 'none',
    'whoami': 'none',
    'hostname': 'none',
    'uname': 'any',
    'id': 'none',
    'which': 'any',
    'df': 'any',
    'env': 'none',
    'python': ['--version'],
    'python3': ['--version'],
    'git': ['status'],
}
_SHELL_META_RE = re.compile(r'[;&|<>`$]|\\n')


def _within_sandbox(arg: str) -> bool:
    try:
        (_SANDBOX_DIR / arg).resolve().relative_to(_SANDBOX_DIR.resolve())
        return True
    except (ValueError, OSError):
        return False


def _truncate(text: str) -> tuple[str, bool]:
    if len(text) > _SANDBOX_TRUNCATE:
        return text[:_SANDBOX_TRUNCATE], True
    return text, False


@router.get('/system/sandbox/whitelist')
def sandbox_whitelist() -> dict:
    return {
        'commands': sorted(_SANDBOX_COMMANDS),
        'cwd': _rel_to_root(_SANDBOX_DIR),
        'timeout_s': _SANDBOX_TIMEOUT_S,
        'truncate_bytes': _SANDBOX_TRUNCATE,
    }


@router.post('/system/sandbox/exec')
def sandbox_exec(req: SandboxExecIn) -> dict:
    if req.gear != 'sandbox':
        raise HTTPException(
            status_code=403,
            detail=f'沙盒执行仅允许在「{WORK_GEARS["sandbox"]}」档位下进行，当前档位：{req.gear}',
        )
    command = req.command.strip()
    if _SHELL_META_RE.search(command):
        raise HTTPException(status_code=403, detail='命令包含 shell 元字符（;&|<>`$ 或换行），已拒绝')
    try:
        argv = shlex.split(command)
    except ValueError:
        raise HTTPException(status_code=422, detail='命令解析失败：引号未闭合')
    if not argv:
        raise HTTPException(status_code=422, detail='命令为空')

    name = argv[0]
    args = argv[1:]
    spec = _SANDBOX_COMMANDS.get(name)
    if spec is None:
        raise HTTPException(
            status_code=403,
            detail=f'命令不在沙盒白名单内：{name}（白名单：{"、".join(sorted(_SANDBOX_COMMANDS))}）',
        )
    if spec == 'none' and args:
        raise HTTPException(status_code=403, detail=f'沙盒内 {name} 不允许携带参数')
    if isinstance(spec, list) and args != spec:
        raise HTTPException(status_code=403, detail=f'沙盒内 {name} 仅允许参数：{" ".join(spec)}')
    if spec == 'any':
        for arg in args:
            if arg.startswith('-'):
                continue
            if not _within_sandbox(arg):
                raise HTTPException(status_code=403, detail=f'路径越出沙盒监禁目录：{arg}')

    _SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            argv,
            cwd=_SANDBOX_DIR,
            capture_output=True,
            text=True,
            errors='replace',
            timeout=_SANDBOX_TIMEOUT_S,
            shell=False,
        )
        stdout, out_trunc = _truncate(proc.stdout or '')
        stderr, err_trunc = _truncate(proc.stderr or '')
        return {
            'ok': proc.returncode == 0,
            'stdout': stdout,
            'stderr': stderr,
            'code': proc.returncode,
            'truncated': out_trunc or err_trunc,
        }
    except FileNotFoundError:
        return {
            'ok': False,
            'stdout': '',
            'stderr': f'命令在当前平台不可执行（未找到可执行文件）：{name}',
            'code': None,
            'truncated': False,
        }
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b'').decode('utf-8', 'replace')
        err = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b'').decode('utf-8', 'replace')
        stdout, out_trunc = _truncate(out)
        stderr, err_trunc = _truncate(err)
        return {
            'ok': False,
            'stdout': stdout,
            'stderr': (stderr + f'\n执行超时（>{_SANDBOX_TIMEOUT_S}s），已终止').strip(),
            'code': None,
            'truncated': out_trunc or err_trunc,
        }


# ---------------------------------------------------------------------------
# wanwei CLI 指南（静态文档）
# ---------------------------------------------------------------------------

_CLI_COMMANDS: list[dict] = [
    {
        'name': 'worktree create',
        'usage': 'wanwei worktree create <任务名> [--base <分支>]',
        'summary': '为智能体任务创建隔离的 git worktree，避免污染主工作区',
        'example': 'wanwei worktree create feat-login --base main',
    },
    {
        'name': 'worktree list',
        'usage': 'wanwei worktree list',
        'summary': '列出当前所有任务 worktree 及其状态',
        'example': 'wanwei worktree list',
    },
    {
        'name': 'worktree remove',
        'usage': 'wanwei worktree remove <任务名> [--force]',
        'summary': '清理任务 worktree；--force 丢弃未提交改动',
        'example': 'wanwei worktree remove feat-login',
    },
    {
        'name': 'snapshot',
        'usage': 'wanwei snapshot [说明]',
        'summary': '对当前工作区打快照，出错可一键回滚',
        'example': 'wanwei snapshot "重构前的基线"',
    },
    {
        'name': 'run',
        'usage': 'wanwei run --gear <档位> "<任务描述>"',
        'summary': '在指定工作档位（human_review/sandbox/device）下运行智能体任务',
        'example': 'wanwei run --gear sandbox "整理下载目录里的安装包"',
    },
    {
        'name': 'approve',
        'usage': 'wanwei approve <动作ID> [--reject]',
        'summary': '人工审查档位下审批/驳回待确认动作',
        'example': 'wanwei approve act_3f9c21 --reject',
    },
    {
        'name': 'config',
        'usage': 'wanwei config get <键> | wanwei config set <键> <值>',
        'summary': '查看或修改 CLI 配置（主题、默认档位、模型路由等）',
        'example': 'wanwei config set gear.default sandbox',
    },
    {
        'name': 'status',
        'usage': 'wanwei status',
        'summary': '查看后端连接、当前档位与进行中的任务',
        'example': 'wanwei status',
    },
    {
        'name': 'logs',
        'usage': 'wanwei logs [--task <任务名>] [-f]',
        'summary': '查看任务执行日志，-f 持续跟随',
        'example': 'wanwei logs --task feat-login -f',
    },
    {
        'name': 'doctor',
        'usage': 'wanwei doctor',
        'summary': '环境自检：后端连通性、凭证、沙盒目录与依赖完整性',
        'example': 'wanwei doctor',
    },
]


@router.get('/system/cli/guide')
def cli_guide() -> dict:
    return {
        'delivery': 'docs',
        'name': 'wanwei CLI',
        'description': '宛委·万枢命令行工具：worktree 隔离、快照回滚、分档执行与人工审批',
        'commands': _CLI_COMMANDS,
    }
