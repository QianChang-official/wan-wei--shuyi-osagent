"""B7 系统服务：系统级能力聚合模块。

挂载于 ``/platform/system`` 前缀（由 platform_api 包自动发现）。

能力清单：
- 防睡眠状态源（桌面端经 IPC powerSaveBlocker 实际执行）
- 通用设置（主题/语言/背景/自启/花瓣，background_opacity 固定只读）
- 语音输入存档（12MB 上限 + 魔数校验，saved_path 只回相对路径；转写默认
  stub 仅存档，配好 WANWEI_ASR_BASE_URL + WANWEI_ASR_API_KEY 后对已存档
  音频真实调用 OpenAI 兼容 /audio/transcriptions 回填转写文本）
- 防追踪浏览器（拦截规则 + 启动计划，实际拉起由桌面端执行）
- 模拟器镜像下载（未配置 WANWEI_EMULATOR_IMAGE_URL 时后台线程模拟推进
  2%/0.5s；配置后 httpx 流式真实下载到 data/platform/downloads/，可选
  SHA256 校验，.part 临时名完成后原子改名）
- 沙盒命令执行（白名单 + cwd 监禁 + 5s 超时 + 4KB 截断）
- wanwei CLI 使用指南（静态文档）

持久化：JsonStore('system') / JsonStore('emulator')。
真实外部副作用一律遵循「配置就绪才启用，否则明确标注 stub/simulated」。
"""
import base64
import binascii
import hashlib
import logging
import math
import os
import re
import shlex
import subprocess
import threading
import time
import uuid
from pathlib import Path, PureWindowsPath
from typing import Any, Literal
from urllib.parse import urlparse, urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .deps import WORK_GEARS
from .guards import audit_safe, require_gear
from .store import JsonStore
from ..security.ssrf import SSRFError, resolve_external_url
from ..soul.ownership import actor_id_for_request, configured_actor_id
from ..utils.datetime_utils import utc_now_iso


def _require_device_owner(request: Request) -> None:
    """Keep device-level state behind the configured local principal.

    The system service controls one physical desktop (voice history, browser
    rules, emulator jobs and LAN pairing), rather than a tenant-owned object.
    Until a separate device-admin role exists, alternate API principals must
    not be able to read or mutate that shared state.
    """
    owner_id = actor_id_for_request(request)
    if owner_id not in {'anonymous', configured_actor_id()}:
        raise HTTPException(status_code=404, detail={'error': 'not_found'})


router = APIRouter(dependencies=[Depends(_require_device_owner)])

_sys_store = JsonStore('system')
_emu_store = JsonStore('emulator')

# 与 store.py 同层 → 项目根；数据目录与 JsonStore 保持一致（支持环境变量覆盖）
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _platform_dir() -> Path:
    """惰性解析平台数据目录，与 JsonStore._path 保持同一套环境变量语义。

    测试与多环境切换下 WANWEI_PLATFORM_DIR 可能在模块 import 后才被替换，
    因此不再在 import 期固化目录，避免语音/沙盒文件写入已失效的旧目录。
    """
    env_dir = os.environ.get('WANWEI_PLATFORM_DIR', '').strip()
    return Path(env_dir) if env_dir else _PROJECT_ROOT / 'data' / 'platform'


def _voice_dir() -> Path:
    return _platform_dir() / 'voice'


def _sandbox_dir() -> Path:
    return _platform_dir() / 'sandbox'


_VOICE_MAX_BYTES = 12 * 1024 * 1024  # 解码后音频上限 12MB（正文口径见 security/input_limits.py）
_VOICE_HISTORY_MAX = 200
_BACKGROUND_IMAGE_MAX_CHARS = 2 * 1024 * 1024  # 背景图 data URL 上限 2MB，防超大 base64 撑爆设置存储
_BACKGROUND_DATA_MIMES = frozenset({'image/png', 'image/jpeg', 'image/webp', 'image/gif'})
_BACKGROUND_UNSAFE_CHARS = re.compile(r'["\'()\\<>\r\n]')
_SANDBOX_TIMEOUT_S = 5
_SANDBOX_TRUNCATE = 4096

# 沙盒执行环境：仅保留运行白名单内系统命令所必需的最小环境变量，
# 绝不继承任何 WANWEI_* 变量，避免通过 `env` 等命令泄露主 API Key。
_SANDBOX_ENV_KEYS = {'PATH', 'SYSTEMROOT', 'TEMP', 'TMP', 'HOME', 'USERPROFILE', 'LANG', 'LC_ALL'}
_SANDBOX_ENV: dict[str, str] = {
    k: v for k, v in os.environ.items()
    if k.upper() in _SANDBOX_ENV_KEYS and not k.upper().startswith('WANWEI_')
}


def _rel_to_root(path: Path) -> str:
    """尽量给出相对项目根的 POSIX 路径；环境变量把数据目录挪走时退为绝对路径。"""
    try:
        return path.resolve().relative_to(_PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def _background_image_has_expected_magic(mime: str, raw: bytes) -> bool:
    if mime == 'image/png':
        return raw.startswith(b'\x89PNG\r\n\x1a\n')
    if mime == 'image/jpeg':
        return raw.startswith(b'\xff\xd8\xff')
    if mime == 'image/gif':
        return raw.startswith((b'GIF87a', b'GIF89a'))
    if mime == 'image/webp':
        return len(raw) >= 12 and raw.startswith(b'RIFF') and raw[8:12] == b'WEBP'
    return False


def _validate_background_image(value: str | None) -> str | None:
    """Allow only non-scriptable image data URLs or absolute HTTPS URLs."""
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return ''
    if _BACKGROUND_UNSAFE_CHARS.search(normalized):
        raise ValueError('background_image 包含不安全字符')
    if normalized.lower().startswith('data:'):
        header, separator, payload = normalized.partition(',')
        if not separator or not header.lower().endswith(';base64'):
            raise ValueError('background_image data URL 必须使用 base64 编码')
        mime = header[5:-7].lower()
        if mime not in _BACKGROUND_DATA_MIMES:
            raise ValueError('background_image 仅允许 PNG/JPEG/WEBP/GIF')
        try:
            raw = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError('background_image base64 数据无效') from None
        if not _background_image_has_expected_magic(mime, raw):
            raise ValueError('background_image 内容与声明的图片类型不一致')
        return normalized

    parsed = urlparse(normalized)
    if (
        parsed.scheme.lower() != 'https'
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError('background_image 仅允许 HTTPS 绝对 URL 或受限图片 data URL')
    return normalized


def _require_device_action(gear: str, *, action: str) -> None:
    denied = require_gear(gear, action=action, context={'surface': 'system'})
    if denied:
        raise HTTPException(
            status_code=403,
            detail='device 档默认禁用，设 WANWEI_DEVICE_GEAR_ENABLED=1 后才允许该系统操作',
        )


# ---------------------------------------------------------------------------
# 请求模型（全部禁止未知字段）
# ---------------------------------------------------------------------------

class PowerIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    gear: Literal['device']
    prevent_sleep: bool | None = None
    mode: Literal['display', 'system'] | None = None


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    gear: Literal['device']
    theme: Literal['day', 'night', 'auto'] | None = None
    language: Literal['zh-CN', 'en-US'] | None = None
    # data URL 上限 2MB：裸 str 无上限会把数 MB base64 落进 JsonStore 并每次 GET 全量返回
    background_image: str | None = Field(default=None, max_length=_BACKGROUND_IMAGE_MAX_CHARS)
    background_opacity: float | None = None  # 固定只读：提交即忽略
    autostart: bool | None = None
    petals: bool | None = None

    @field_validator('background_image')
    @classmethod
    def _check_background_image(cls, value: str | None) -> str | None:
        return _validate_background_image(value)


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
    gear: Literal['device']
    url: str | None = Field(default=None, max_length=2048)
    profile: Literal['clean'] = 'clean'

    @field_validator('url')
    @classmethod
    def _check_url_scheme(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return v
        parsed = urlparse(v.strip())
        if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
            raise ValueError('browser launch URL only allows http/https absolute URLs')
        return v.strip()


class SandboxExecIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    command: str = Field(min_length=1, max_length=500)
    gear: Literal['sandbox']


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


@router.get('/system/health')
def health_get() -> dict:
    return {'ok': True, 'status': 'ok', 'note': 'platform_api system service reachable'}


@router.get('/system/power')
def power_get() -> dict:
    return {**_power_state(), 'note': _POWER_NOTE}


@router.put('/system/power')
def power_put(req: PowerIn) -> dict:
    _require_device_action(req.gear, action='system_power_update')
    patch = req.model_dump(exclude_unset=True)
    patch.pop('gear', None)

    def _apply(data: dict) -> dict:
        stored = data.get('power')
        stored = stored if isinstance(stored, dict) else {}
        state = dict(_POWER_DEFAULTS)
        state.update({key: stored[key] for key in _POWER_DEFAULTS if key in stored})
        state.update(patch)
        data['power'] = state
        return state

    state = _sys_store.mutate(_apply)
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
    try:
        state['background_image'] = _validate_background_image(state.get('background_image'))
    except ValueError:
        # Legacy/corrupt values are never reflected back into a CSS URL sink.
        state['background_image'] = None
    state['background_opacity'] = _BACKGROUND_OPACITY_FIXED
    return state


@router.get('/system/settings')
def settings_get() -> dict:
    return _settings_state()


@router.put('/system/settings')
def settings_put(req: SettingsIn) -> dict:
    _require_device_action(req.gear, action='system_settings_update')
    payload = req.model_dump(exclude_unset=True)
    payload.pop('gear', None)
    payload.pop('background_opacity', None)  # 只读字段，PUT 一律忽略

    def _apply(data: dict) -> None:
        stored = data.get('settings')
        current = dict(stored) if isinstance(stored, dict) else {}
        current.update(payload)
        data['settings'] = current

    _sys_store.mutate(_apply)
    audit_safe('settings_updated', {'fields': sorted(payload.keys())})
    return _settings_state()


# ---------------------------------------------------------------------------
# 语音输入（存档 + 可选真实转写；未配置 ASR provider 时仅存档 stub）
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
_ASR_MODEL_DEFAULT = 'whisper-1'
# 转写超时上限：10s × 文件 MB（不足 1MB 按 1MB 计，下限 10s）
_ASR_TIMEOUT_S_PER_MB = 10.0
_VOICE_ID_RE = re.compile(r'^vo_[0-9a-f]{12}$')


class _AsrCallError(RuntimeError):
    """ASR 真实调用失败；public_note 为可安全返回给调用方的受控文案。

    通用异常的 str()（httpx 网络错误、SSRF 校验细节等）可能携带内网
    IP/主机等敏感细节，不得流入对外响应（CodeQL py/stack-trace-exposure）；
    _transcribe_audio 负责把一切失败收敛为本异常，消息由受控字面量与
    状态码/异常类名组装。
    """

    def __init__(self, public_note: str) -> None:
        super().__init__(public_note)
        self.public_note = public_note
# MP3 帧同步与 ADTS AAC 帧同步首字节形态相同（0xFF Ex），魔数层面不可可靠区分，按同一「帧音频族」放行
_FRAME_AUDIO_EXTS = {'.mp3', '.aac'}


def _asr_settings() -> dict[str, str] | None:
    """读取语音识别 provider 配置；base_url 与 api_key 任一缺失返回 None。

    配置就绪才启用（R-03）：未配置时转写保持 stub 仅存档，一字不改。
    api_key 只进请求头，绝不落盘、绝不回显、绝不进审计。
    """
    base_url = os.environ.get('WANWEI_ASR_BASE_URL', '').strip()
    api_key = os.environ.get('WANWEI_ASR_API_KEY', '').strip()
    if not base_url or not api_key:
        return None
    model = os.environ.get('WANWEI_ASR_MODEL', '').strip() or _ASR_MODEL_DEFAULT
    return {'base_url': base_url, 'api_key': api_key, 'model': model}


def _asr_timeout_seconds(n_bytes: int) -> float:
    """10s × 文件 MB 的超时上限：不足 1MB 按 1MB 计，下限 10s。"""
    megabytes = math.ceil(max(int(n_bytes), 1) / (1024 * 1024))
    return max(_ASR_TIMEOUT_S_PER_MB, megabytes * _ASR_TIMEOUT_S_PER_MB)


def _pinned_target(url: str, pinned_ip: str) -> tuple[str, str, dict | None]:
    """构造「连接到已校验 IP 但保留原 Host/SNI」的请求要素。

    与 providers._probe_pinned_url 同一 hardened 口径：URL 主机名只用于
    TLS SNI/Host 头与证书校验，TCP 连接固定打在 SSRF 校验过的解析 IP 上；
    trust_env=False 由调用方保证，防止代理替换已校验目标。
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
    sni_extensions = {'sni_hostname': hostname_ascii} if parsed.scheme == 'https' else None
    return pinned_url, original_host, sni_extensions


def _transcribe_audio(raw: bytes, filename: str, mime: str) -> str:
    """对已存档音频真实调用 OpenAI 兼容 /audio/transcriptions（multipart）。

    pinned-IP 解析走 resolve_external_url；超时上限为 10s × 文件 MB。
    返回转写文本；一切失败（含 SSRF 拦截与网络异常）都收敛为
    _AsrCallError（public_note 为可对外返回的受控文案），调用方如实降级为仅存档。
    """
    cfg = _asr_settings()
    assert cfg is not None  # 调用方已判空
    cfg = _asr_settings()
    assert cfg is not None  # 调用方已判空
    from ..security.ssrf import extra_allowed_hosts
    try:
        validated_base, pinned_ip = resolve_external_url(
            cfg['base_url'], allowlist=extra_allowed_hosts() or None,
        )
    except (ValueError, OSError, UnicodeError):
        # SSRFError 是 ValueError 子类；按 SSRF 拒绝处理，不向调用方回显校验细节
        raise _AsrCallError('语音识别目标地址未通过 SSRF 防护校验，已拒绝连接') from None
    url = validated_base.rstrip('/') + '/audio/transcriptions'
    pinned_url, host_header, sni_extensions = _pinned_target(url, pinned_ip)
    headers = {
        'Authorization': f"Bearer {cfg['api_key']}",
        'Host': host_header,
    }
    files = {'file': (filename, raw, mime or 'application/octet-stream')}
    data = {'model': cfg['model']}
    timeout_s = _asr_timeout_seconds(len(raw))
    # trust_env=False：代理不得替换已校验的 pinned 目标
    try:
        with httpx.Client(timeout=timeout_s, trust_env=False, follow_redirects=False) as client:
            resp = client.post(pinned_url, headers=headers, files=files, data=data, extensions=sni_extensions)
    except Exception as exc:  # noqa: BLE001 —— 网络层异常统一收敛为类名级受控文案
        raise _AsrCallError(f'语音识别接口网络调用失败（{type(exc).__name__}）') from exc
    if resp.status_code >= 400:
        raise _AsrCallError(f'语音识别接口返回 HTTP {resp.status_code}')
    try:
        payload = resp.json()
    except ValueError as exc:
        raise _AsrCallError('语音识别接口返回非 JSON 响应') from exc
    text = str((payload or {}).get('text') or '').strip()
    if not text:
        raise _AsrCallError('语音识别接口未返回转写文本')
    return text


def _sniff_audio_ext(raw: bytes) -> str | None:
    """按文件头魔数嗅探音频容器类型；无法识别返回 None。"""
    if raw[:4] == b'\x1aE\xdf\xa3':
        return '.webm'  # EBML（webm/mkv）
    if raw[:4] == b'OggS':
        return '.ogg'
    if raw[:4] == b'RIFF' and raw[8:12] == b'WAVE':
        return '.wav'
    if raw[:4] == b'fLaC':
        return '.flac'
    if raw[4:8] == b'ftyp':
        return '.m4a'  # ISO BMFF（m4a/mp4）
    if raw[:3] == b'ID3' or (len(raw) >= 2 and raw[0] == 0xFF and (raw[1] & 0xE0) == 0xE0):
        return '.mp3'  # ID3 标签或 MPEG/ADTS 帧同步
    return None


def _voice_history() -> list:
    history = _sys_store.get('voice_history')
    return history if isinstance(history, list) else []


def _normalize_voice_record(record: dict) -> dict:
    """读取兼容：旧记录的 saved_path 可能是绝对/项目相对路径，统一归一为
    ``voice/<文件名>`` 相对路径，绝不对外泄露宿主机绝对路径与存储布局。"""
    out = dict(record)
    # PureWindowsPath 在所有宿主系统上都识别 ``\`` 与 ``/``，可安全读取
    # 由旧 Windows 版本写入、后来迁移到 Linux 的绝对路径记录。
    name = PureWindowsPath(str(out.get('saved_path') or '')).name
    out['saved_path'] = f'voice/{name}' if name else None
    return out


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
    if ext != '.bin':
        # 魔数校验：声明的音频类型必须与文件头一致（未知 mime 落 .bin，无从校验，跳过）
        sniffed = _sniff_audio_ext(raw)
        matched = sniffed == ext or (sniffed in _FRAME_AUDIO_EXTS and ext in _FRAME_AUDIO_EXTS)
        if not matched:
            raise HTTPException(status_code=422, detail=f'音频文件头与声明的类型 {mime} 不符，已拒绝存档')

    filename = f'{voice_id}{ext}'
    voice_dir = _voice_dir()
    voice_dir.mkdir(parents=True, exist_ok=True)
    (voice_dir / filename).write_bytes(raw)

    saved_path = f'voice/{filename}'  # 对外只回相对路径，不回绝对路径
    record: dict[str, Any] = {
        'id': voice_id,
        'saved_path': saved_path,
        'mime': req.mime,
        'duration_ms': req.duration_ms,
        'size_bytes': len(raw),
        'created_at': utc_now_iso(),
    }

    # 转写：配置就绪才真实调用（OpenAI 兼容 multipart）；未配置/失败时保持
    # 「仅存档」stub 标注一字不改，绝不让转写失败影响存档本身。
    transcription_note = _VOICE_NOTE
    transcription: str | None = None
    stub = True
    asr = _asr_settings()
    if asr is not None:
        try:
            transcription = _transcribe_audio(raw, filename, mime)
            stub = False
            transcription_note = (
                f"已通过配置的语音识别 provider（model={asr['model']}，"
                'OpenAI 兼容 /audio/transcriptions）完成真实转写'
            )
            audit_safe('voice_transcribed', {
                'id': voice_id, 'model': asr['model'], 'size_bytes': len(raw),
            })
        except _AsrCallError as exc:
            # 受控文案（含 HTTP 状态码/异常类名）可对外返回；细节不外泄
            transcription_note = f'音频已存档；转写失败（{exc.public_note}），可检查 provider 配置后重试'
            audit_safe('voice_transcription_failed', {
                'id': voice_id, 'reason': exc.public_note[:200],
            })
        except Exception as exc:  # noqa: BLE001 —— 未预期异常：对外只回类名，细节仅进审计
            transcription_note = f'音频已存档；转写失败（{type(exc).__name__}），可检查 provider 配置后重试'
            audit_safe('voice_transcription_failed', {
                'id': voice_id, 'reason': f'{type(exc).__name__}: {str(exc)[:180]}',
            })
    record.update({
        'transcription': transcription,
        'note': transcription_note,
        'stub': stub,
    })

    history = [record, *_voice_history()][:_VOICE_HISTORY_MAX]
    _sys_store.set('voice_history', history)

    return {
        'id': voice_id,
        'saved_path': saved_path,
        'transcription': transcription,
        'note': transcription_note,
        'stub': stub,
    }


@router.get('/system/voice')
def voice_list() -> list:
    return [_normalize_voice_record(r) for r in _voice_history()]


@router.delete('/system/voice/{voice_id}')
def voice_delete(voice_id: str) -> dict:
    """删除录音记录并同步清理磁盘文件（DELETE 属写方法，由 API Key 中间件鉴权）。"""
    if not _VOICE_ID_RE.fullmatch(voice_id):
        raise HTTPException(status_code=404, detail=f'录音不存在：{voice_id}')
    history = _voice_history()
    record = next((r for r in history if r.get('id') == voice_id), None)
    if record is None:
        raise HTTPException(status_code=404, detail=f'录音不存在：{voice_id}')

    file_deleted = False
    name = PureWindowsPath(str(record.get('saved_path') or '')).name
    if name:
        voice_dir = _voice_dir().resolve()
        candidate = (voice_dir / name).resolve()
        try:
            candidate.relative_to(voice_dir)
        except ValueError:
            candidate = None  # 路径越出语音目录，拒绝删除
        if candidate is not None and candidate.is_file():
            candidate.unlink()
            file_deleted = True

    def _remove(data: dict) -> dict:
        data['voice_history'] = [r for r in (data.get('voice_history') or []) if r.get('id') != voice_id]
        return data
    _sys_store.mutate(_remove)
    audit_safe('voice_deleted', {'id': voice_id, 'file_deleted': file_deleted})
    return {'ok': True, 'id': voice_id, 'file_deleted': file_deleted}


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
_HOST_RULES_MAX = 32  # host-rules 规则数上限：命令行长度有限，超出截断并如实回报 applied_count


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
                new_domain = _normalize_domain(payload['domain'])
                # 与 create 对齐：update 改域名同样查重，避免经 update 制造重名规则
                if any(r.get('domain') == new_domain and r.get('id') != rid for r in rules):
                    raise HTTPException(status_code=409, detail=f'域名已存在拦截规则：{new_domain}')
                payload['domain'] = new_domain
            rule.update(payload)
            _sys_store.set('browser_rules', rules)
            return rule
    raise HTTPException(status_code=404, detail=f'规则不存在：{rid}')


@router.delete('/system/browser/rules/{rid}')
def browser_rules_delete(rid: str) -> dict:
    rules = _load_rules()
    remaining = [r for r in rules if r.get('id') != rid]
    if len(remaining) == len(rules):
        raise HTTPException(status_code=404, detail=f'规则不存在：{rid}')
    _sys_store.set('browser_rules', remaining)
    audit_safe('browser_rule_deleted', {'id': rid})
    return {'ok': True, 'id': rid, 'deleted': True}


@router.post('/system/browser/launch')
def browser_launch(req: BrowserLaunchIn) -> dict:
    _require_device_action(req.gear, action='browser_launch')
    rules = _load_rules()
    blocked_domains = sorted({r['domain'] for r in rules if r.get('enabled') and r.get('domain')})
    # host-rules 语法：逗号分隔的多条 MAP 规则（空格串联整规则非法）；
    # 命令行长度有限，超出 _HOST_RULES_MAX 截断并如实回报 applied_count。
    applied = blocked_domains[:_HOST_RULES_MAX]
    host_rules = ','.join(f'MAP {d} ~NOTFOUND' for d in applied)
    plan = [
        '--incognito',
        '--disable-third-party-cookies',
        '--disable-background-networking',
        '--disable-sync',
        '--disable-extensions',
        '--no-first-run',
        # 占位符约定：执行端（桌面 IPC）须把 {tmp_profile} 替换为真实临时干净配置目录
        '--user-data-dir={tmp_profile}',
    ]
    if host_rules:
        plan.append(f'--host-rules={host_rules}')
    return {
        'ok': True,
        'mode': 'plan',
        'plan': plan,
        'url': req.url,
        'profile': req.profile,
        'blocked_count': len(blocked_domains),
        'applied_count': len(applied),
        'note': '由桌面端按此计划拉起浏览器；{tmp_profile} 为占位符需执行端填充；'
                '--do-not-track 并非真实 Chrome 开关（DNT 已从 Chromium 移除），已剔除',
    }


# ---------------------------------------------------------------------------
# 模拟器镜像下载（双模式：未配置 env 时后台线程模拟推进 2%/0.5s；
# 配置 WANWEI_EMULATOR_IMAGE_URL 后 httpx 流式真实下载，可选 SHA256 校验）
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

# 真实下载（配置 WANWEI_EMULATOR_IMAGE_URL 才启用）：流式落盘
# data/platform/downloads/，进度按真实字节/Content-Length 推进，
# .part 临时名写完后原子改名；SHA256 可选校验。
_DOWNLOADS_SUBDIR = 'downloads'
_DOWNLOAD_CHUNK_BYTES = 256 * 1024
# 单文件硬上限（issue #131）：content-length 预检 + 流中累计双重判定；
# 默认 10 GiB，可用 WANWEI_EMULATOR_IMAGE_MAX_BYTES 调整（0/负数/非数字回退默认）。
_DOWNLOAD_MAX_BYTES_DEFAULT = 10 * 1024 ** 3
# 进度落盘节流（issue #131）：JsonStore 每次 set 是全文件读改写并抢跨模块共享锁，
# 逐 chunk（256KB）写一次会让大镜像下载期间整个平台舱写串行排队。改为按时间节流：
# 0.25s 既保证前端进度条可见性，也把 5GB 下载的落盘次数从 ~2 万次压到百次量级。
_PROGRESS_FLUSH_SECONDS = 0.25
_LOGGER = logging.getLogger(__name__)
_REAL_DOWNLOAD_RESET_KEYS = ('received_bytes', 'total_bytes', 'sha256_verified', 'saved_file')
_SAFE_FILENAME_RE = re.compile(r'[^A-Za-z0-9._-]+')


def _download_max_bytes() -> int:
    """单次下载的字节硬上限；环境变量非法或 ≤0 时回退默认值。"""
    raw = os.environ.get('WANWEI_EMULATOR_IMAGE_MAX_BYTES', '').strip()
    if raw.isdigit():
        value = int(raw)
        if value > 0:
            return value
    return _DOWNLOAD_MAX_BYTES_DEFAULT


class _DownloadCancelled(Exception):
    """真实下载被 cancel 中断的内部信号（区别于失败）。"""


def _emulator_image_config() -> dict[str, str] | None:
    """读取镜像下载配置；未设置 WANWEI_EMULATOR_IMAGE_URL 返回 None。

    返回 None 时完全保持既有模拟推进行为与 simulated:true 标注；
    配置后 start 走真实下载路径（R-03：外部调用显式环境变量开启）。
    """
    url = os.environ.get('WANWEI_EMULATOR_IMAGE_URL', '').strip()
    if not url:
        return None
    sha256 = os.environ.get('WANWEI_EMULATOR_IMAGE_SHA256', '').strip().lower()
    return {'url': url, 'sha256': sha256}


def _download_filename(did: str, url: str) -> str:
    """从 URL 路径派生安全文件名：白名单字符 + 长度上限，无可用段回退 did。"""
    raw_name = PureWindowsPath(urlsplit(url).path.replace('/', '\\')).name
    cleaned = _SAFE_FILENAME_RE.sub('_', raw_name).strip('._')[:80]
    return cleaned or f'{did}.bin'


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as fh:
        for block in iter(lambda: fh.read(_DOWNLOAD_CHUNK_BYTES), b''):
            digest.update(block)
    return digest.hexdigest()


def _update_downloading_record(did: str, **fields: Any) -> None:
    """锁内更新 downloading 记录字段；记录已非 downloading（被取消）时忽略。"""
    with _download_lock:
        data = _load_downloads()
        rec = data.get(did)
        if not rec or rec.get('status') != 'downloading':
            return
        rec.update(fields)
        data[did] = rec
        _emu_store.set('downloads', data)


def _mark_real_download_error(did: str, note: str, *, clear_saved_file: bool = False) -> None:
    """真实下载失败收尾：仅当仍处 downloading 时标 error（取消竞态下让位）。

    clear_saved_file：终态文件未产生时清掉 saved_file，避免记录指向不存在路径；
    .part 清理失败的残留路径改由 note 携带（可见性优先）。
    """
    with _download_lock:
        data = _load_downloads()
        rec = data.get(did)
        if rec and rec.get('status') == 'downloading':
            rec['status'] = 'error'
            rec['note'] = note
            rec['simulated'] = False
            if clear_saved_file:
                # 终态文件从未产生：清掉指向不存在路径的 saved_file；
                # received_bytes/total_bytes 如实保留——失败前的字节账目是真实信息
                rec.pop('saved_file', None)
            data[did] = rec
            _emu_store.set('downloads', data)


def _real_download_worker(did: str, url: str, sha_expected: str, stop: threading.Event) -> None:
    """真实下载线程体：pinned-IP 流式拉取 → .part → SHA256 校验 → 原子改名。"""
    def _discard_part(path: Path | None) -> bool:
        # 失败路径在写终态前先删 .part：保证「error 状态对外可见时必无残留」。
        # 清理失败不再静默（issue #131）：残留 GB 级孤儿文件必须可观测。
        if path is None:
            return True
        try:
            path.unlink(missing_ok=True)
            return True
        except OSError as exc:
            _LOGGER.warning('下载 .part 清理失败，残留文件占盘：%s (%s)', path, exc)
            return False

    part_path: Path | None = None
    try:
        from ..security.ssrf import extra_allowed_hosts
        validated_url, pinned_ip = resolve_external_url(
            url, allowlist=extra_allowed_hosts() or None,
        )
        filename = _download_filename(did, validated_url)
        dest_dir = _platform_dir() / _DOWNLOADS_SUBDIR
        dest_dir.mkdir(parents=True, exist_ok=True)
        part_path = dest_dir / f'{filename}.part'
        pinned_url, host_header, sni_extensions = _pinned_target(validated_url, pinned_ip)

        received = 0
        total: int | None = None
        timeout = httpx.Timeout(connect=15.0, read=60.0, write=60.0, pool=15.0)
        # trust_env=False：代理不得替换 SSRF 校验过的目标；重定向不跟随
        with httpx.Client(timeout=timeout, trust_env=False, follow_redirects=False) as client:
            with client.stream(
                'GET', pinned_url, headers={'Host': host_header}, extensions=sni_extensions,
            ) as resp:
                if 300 <= resp.status_code < 400:
                    raise RuntimeError(f'HTTP {resp.status_code}：重定向未跟随（SSRF 防护）')
                if resp.status_code >= 400:
                    raise RuntimeError(f'源站返回 HTTP {resp.status_code}')
                content_length = resp.headers.get('content-length')
                if content_length and content_length.strip().isdigit():
                    total = int(content_length)
                max_bytes = _download_max_bytes()
                if total is not None and total > max_bytes:
                    raise RuntimeError(
                        f'镜像声明体积 {total} 字节超过单文件上限 {max_bytes}'
                        f'（WANWEI_EMULATOR_IMAGE_MAX_BYTES），已拒绝下载'
                    )
                _update_downloading_record(
                    did,
                    received_bytes=0,
                    total_bytes=total,
                    saved_file=f'{_DOWNLOADS_SUBDIR}/{filename}',
                    sha256_verified=False,
                )
                with part_path.open('wb') as fh:
                    last_flush = time.monotonic()
                    for chunk in resp.iter_bytes(chunk_size=_DOWNLOAD_CHUNK_BYTES):
                        # cancel 真正中断：块间检查停止信号，残留 .part 在 finally 清理
                        if stop.is_set():
                            raise _DownloadCancelled()
                        if received + len(chunk) > max_bytes:
                            raise RuntimeError(
                                f'下载数据累计超过单文件上限 {max_bytes}'
                                f'（WANWEI_EMULATOR_IMAGE_MAX_BYTES），已中断并丢弃'
                            )
                        fh.write(chunk)
                        received += len(chunk)
                        # 进度落盘节流（issue #131）：按时间而非逐 chunk，避免
                        # 大文件下载期间高频全量重写 JsonStore 抢占跨模块共享锁；
                        # 终态（done/error）不受节流影响，字节账目在收尾时精确落盘。
                        if time.monotonic() - last_flush >= _PROGRESS_FLUSH_SECONDS:
                            fields: dict[str, Any] = {'received_bytes': received}
                            if total:
                                fields['progress'] = min(100, int(received * 100 / total))
                                fields['total_bytes'] = total
                            _update_downloading_record(did, **fields)
                            last_flush = time.monotonic()

        if sha_expected:
            actual_sha = _sha256_file(part_path)
            if actual_sha != sha_expected:
                raise RuntimeError(
                    f'SHA256 校验不匹配：期望 {sha_expected}，实际 {actual_sha}，已丢弃下载内容'
                )

        final_path = part_path.with_name(filename)
        os.replace(part_path, final_path)  # 原子改名：完整文件才出现在最终名下
        part_path = None
        _update_downloading_record(
            did,
            status='done',
            progress=100,
            received_bytes=received,
            total_bytes=total if total is not None else received,
            simulated=False,
            sha256_verified=bool(sha_expected),
            note='真实下载完成：来源 WANWEI_EMULATOR_IMAGE_URL'
                 + ('，SHA256 校验通过' if sha_expected else ''),
        )
        audit_safe('emulator_download_completed', {
            'id': did, 'bytes': received, 'sha256_verified': bool(sha_expected),
        })
    except _DownloadCancelled:
        # cancel 端点负责把状态置回 idle；这里只负责清理 .part 残留
        pass
    except SSRFError:
        _discard_part(part_path)
        part_path = None
        # 终态文件从未产生：saved_file 一并清掉，不再指向不存在的路径
        _mark_real_download_error(
            did, '真实下载失败：URL 未通过 SSRF 校验', clear_saved_file=True,
        )
        audit_safe('emulator_download_failed', {'id': did, 'reason': 'ssrf_blocked'})
    except Exception as exc:  # noqa: BLE001 —— 后台线程异常落盘标注，不抛出
        removed = _discard_part(part_path)
        orphan = part_path.name if (part_path is not None and not removed) else ''
        part_path = None
        # 受控 RuntimeError（体积上限 / SHA256 不匹配等自产异常）由本模块用
        # 固定模板拼出，不含任何网络/主机细节，可如实回显帮助用户理解失败
        # 原因；其余意外异常只回显异常类名（str() 可能带内网 URL 等细节）。
        if isinstance(exc, RuntimeError) and not isinstance(exc, _AsrCallError):
            note = f'真实下载失败：{exc}'
        else:
            note = f'真实下载失败：{type(exc).__name__}'
        if orphan:
            note += f'（警告：.part 清理失败，残留文件占盘：{orphan}）'
        _mark_real_download_error(did, note, clear_saved_file=True)
        audit_safe('emulator_download_failed', {'id': did, 'reason': str(exc)[:200]})
    finally:
        if part_path is not None:
            try:
                part_path.unlink(missing_ok=True)
            except OSError as exc:
                _LOGGER.warning('下载 .part 清理失败，残留文件占盘：%s (%s)', part_path, exc)
        with _download_lock:
            # 仅当注册表里仍是本线程时才清理（同 _progress_download 口径）：
            # start 重启同一下载项后，旧线程退出不得误删新线程注册项。
            if _download_threads.get(did) is threading.current_thread():
                _download_threads.pop(did, None)
                _download_stops.pop(did, None)
                # 注（issue #131 取消竞态）：终态翻转由各退出分支与 cancel 端点
                # （join 后置 idle）负责；线程被硬杀的场景由服务重启时
                # _downloads_list 的 downloading 孤儿扫描兕底，此处不越权代写，
                # 否则会在 cancel 的 join 窗口内抢标 error、覆盖端点的 idle 语义。


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
    # 服务重启后 downloading 状态失去后台线程，诚实标注为 error。
    # 线程注册表必须在锁内读取：start 的落库与注册已收进同一把锁，
    # 这里若不加锁，可能在 start 的窗口期误判「丢线程」把新下载打成 error。
    with _download_lock:
        live_threads = set(_download_threads)
    changed = False
    for did, rec in data.items():
        if rec.get('status') == 'downloading' and did not in live_threads:
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
            # 读-改-写与 cancel/start 共用同一把锁，避免旧快照覆盖取消状态。
            with _download_lock:
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
            # 仅当注册表里仍是本线程时才清理：start 重启同一下载项后，
            # 旧线程退出不得误删新线程的注册项与停止事件。
            if _download_threads.get(did) is threading.current_thread():
                _download_threads.pop(did, None)
                _download_stops.pop(did, None)


@router.get('/system/emulator/downloads')
def emulator_downloads_list() -> list:
    return _downloads_list()


@router.post('/system/emulator/downloads/{did}/start')
def emulator_download_start(did: str) -> dict:
    # 落库与线程注册收进同一把锁：消除「并发 GET 误判丢线程标 error」与
    # 「两并发 start 双双通过检查起双线程」两起竞态；重复 start 幂等返回现状。
    # 未配置 WANWEI_EMULATOR_IMAGE_URL 时完全保持既有模拟推进行为；
    # 配置后同一线程/锁模型走真实流式下载（simulated:false）。
    real_cfg = _emulator_image_config()
    with _download_lock:
        data = _load_downloads()
        rec = data.get(did)
        if not rec:
            raise HTTPException(status_code=404, detail=f'下载项不存在：{did}')
        if rec.get('status') == 'downloading' and did in _download_threads:
            if real_cfg is not None:
                return {**rec, 'ok': True, 'note': '已在真实下载中'}
            return {**rec, 'ok': True, 'note': '已在模拟下载中'}
        if rec.get('status') == 'done' and int(rec.get('progress', 0)) >= 100:
            if rec.get('simulated') is False:
                return {**rec, 'ok': True, 'note': '镜像文件已真实下载完成，无需重复开始'}
            return {**rec, 'ok': True, 'note': '已下载完成（模拟），无需重复开始'}

        rec['status'] = 'downloading'
        rec.pop('note', None)
        # 上一次真实下载的残留字段一律清零（真实/模拟模式可随 env 切换），
        # 并同步 simulated 标注与本次实际行为一致（诚实红线）。
        for key in _REAL_DOWNLOAD_RESET_KEYS:
            rec.pop(key, None)
        rec['simulated'] = real_cfg is None
        data[did] = rec
        _emu_store.set('downloads', data)

        stop = threading.Event()
        if real_cfg is not None:
            thread = threading.Thread(
                target=_real_download_worker,
                args=(did, real_cfg['url'], real_cfg['sha256'], stop),
                name=f'emulator-download-real-{did}',
                daemon=True,
            )
            note = (
                f"真实下载已启动：httpx 流式拉取落盘 {_DOWNLOADS_SUBDIR}/"
                + ('，含 SHA256 校验' if real_cfg['sha256'] else '')
            )
            simulated = False
        else:
            thread = threading.Thread(
                target=_progress_download,
                args=(did, stop),
                name=f'emulator-download-{did}',
                daemon=True,
            )
            note = '模拟下载已启动：每 0.5s 推进 2%，不真实拉取大文件'
            simulated = True
        _download_stops[did] = stop
        _download_threads[did] = thread
        thread.start()
    if real_cfg is not None:
        audit_safe('emulator_download_started_real', {'id': did})
    return {
        **rec,
        'ok': True,
        'simulated': simulated,
        'note': note,
    }


@router.post('/system/emulator/downloads/{did}/cancel')
def emulator_download_cancel(did: str) -> dict:
    with _download_lock:
        data = _load_downloads()
        rec = data.get(did)
        if not rec:
            raise HTTPException(status_code=404, detail=f'下载项不存在：{did}')
        stop = _download_stops.pop(did, None)
        thread = _download_threads.get(did)
    if stop:
        stop.set()
    if thread and thread.is_alive():
        thread.join(timeout=1.5)
    with _download_lock:
        data = _load_downloads()
        rec = data.get(did)
        if not rec:
            raise HTTPException(status_code=404, detail=f'下载项不存在：{did}')
        if rec.get('status') == 'downloading':
            rec['status'] = 'idle'
            if rec.get('simulated') is False:
                # 真实下载中断后 .part 已清理、不支持断点续传，如实说明
                rec['note'] = '已取消（真实下载已中断，重新开始将从头下载）'
            else:
                rec['note'] = '已取消（进度保留，可继续）'
            data[did] = rec
            _emu_store.set('downloads', data)
    return {**rec, 'ok': True}


# ---------------------------------------------------------------------------
# 沙盒执行（白名单 + cwd 监禁 data/platform/sandbox/ + 5s 超时 + 4KB 截断）
# ---------------------------------------------------------------------------

# 取值：'any' 任意参数（路径参数须落在监禁目录内）；'none' 不允许参数；list 精确匹配
# 安全说明：
# - `env` 已从白名单移除：即使不带参数，stdout 也会完整打印进程环境变量，
#   包括由桌面端注入的 WANWEI_API_KEY，导致主密钥泄露。
# - `whoami`/`hostname`/`id`/`uname`/`which`/`df` 已一并移除：主机身份
#   指纹、工具链路径、挂载布局经沙盒 stdout 外泄，属不必要的信息暴露面。
_SANDBOX_COMMANDS: dict[str, Any] = {
    'ls': 'any',
    'pwd': 'none',
    'cat': 'any',
    'echo': 'any',
    'head': 'any',
    'tail': 'any',
    'wc': 'any',
    'date': 'none',
    'python': ['--version'],
    'python3': ['--version'],
    'git': ['status'],
}
# 匹配真实换行/回车：旧写法 `\\n` 匹配的是字面两字符 `\n`，「换行拒绝」从未生效
_SHELL_META_RE = re.compile(r'[;&|<>`$\r\n]')
# 短选项束（如 -la、-n5）：仅字母数字，不内嵌路径/赋值
_SHORT_FLAGS_RE = re.compile(r'^-[A-Za-z0-9]+$')


def _within_sandbox(arg: str) -> bool:
    sandbox = _sandbox_dir()
    try:
        (sandbox / arg).resolve().relative_to(sandbox.resolve())
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
        'cwd': _rel_to_root(_sandbox_dir()),
        'timeout_s': _SANDBOX_TIMEOUT_S,
        'truncate_bytes': _SANDBOX_TRUNCATE,
    }


@router.post('/system/sandbox/exec')
def sandbox_exec(req: SandboxExecIn) -> dict:
    if req.gear != 'sandbox':
        audit_safe('gear_denied', {
            'gear': req.gear, 'action': 'sandbox_exec',
            'reason': 'sandbox_exec_requires_sandbox_gear',
        })
        raise HTTPException(
            status_code=403,
            detail=f'沙盒执行仅允许在「{WORK_GEARS["sandbox"]}」档位下进行，当前档位：{req.gear}',
        )
    command = req.command.strip()
    if _SHELL_META_RE.search(command):
        audit_safe('sandbox_denied', {'command': command, 'reason': 'shell_meta_chars'})
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
        audit_safe('sandbox_denied', {'command': name, 'reason': 'not_in_whitelist'})
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
                # 选项参数显式校验，不再盲目跳过：
                # - 长选项 --opt=value 的 value 可内嵌路径（如 wc --files0-from=FILE），
                #   必须同样落在监禁目录内；
                # - 短选项束仅允许字母数字（如 -la、-n5），内嵌路径/赋值一律拒绝。
                if arg.startswith('--'):
                    opt_value = arg.partition('=')[2] if '=' in arg else ''
                    if opt_value and not _within_sandbox(opt_value):
                        audit_safe('sandbox_denied', {'command': command, 'reason': 'path_escape', 'arg': arg})
                        raise HTTPException(status_code=403, detail=f'选项参数越出沙盒监禁目录：{arg}')
                elif not _SHORT_FLAGS_RE.fullmatch(arg):
                    audit_safe('sandbox_denied', {'command': command, 'reason': 'bad_option_arg', 'arg': arg})
                    raise HTTPException(status_code=403, detail=f'不允许的选项参数（疑似内嵌路径或赋值）：{arg}')
                continue
            if not _within_sandbox(arg):
                audit_safe('sandbox_denied', {'command': command, 'reason': 'path_escape', 'arg': arg})
                raise HTTPException(status_code=403, detail=f'路径越出沙盒监禁目录：{arg}')

    sandbox = _sandbox_dir()
    sandbox.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            argv,
            cwd=sandbox,
            capture_output=True,
            text=True,
            errors='replace',
            timeout=_SANDBOX_TIMEOUT_S,
            shell=False,
            env=_SANDBOX_ENV,
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
