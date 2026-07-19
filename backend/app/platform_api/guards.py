"""platform_api 共享：gear 档位门禁 + root_path 目录白名单 + 审计脱敏辅助。

第四批 P1 修复统一出口：
- ``require_gear``：device（整台设备）档默认禁用，仅当环境变量
  ``WANWEI_DEVICE_GEAR_ENABLED`` 为真值时放行；拒绝动作同步落审计
  （``gear_denied``），放行也落审计（``gear_device_allowed``），与文档
  「device 默认禁用、启用需显式授权并全程审计」的承诺对齐。
- ``validate_root_path`` / ``allowed_root_paths``：root_path 目录白名单，
  realpath 校验落点必须在允许根内，且系统敏感目录一律拒绝。
- ``audit_safe`` / ``audit_record``：platform_api 各端点统一接入
  ``app.audit.service.record``，落审计前先做长度截断，防止超大
  请求体撑爆 audit_logs 表。
- ``mask_secret_keys``：敏感键名打码，供需要保留键结构的场景
  （如 MCP env 键名回显）。

注：gear 档位仍为请求体自报的信任模型（本轮不重构），白名单与审计是
该模型下的纵深防御补强。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable

from app.audit.service import record as _audit_record
from app.security.redaction import redact_dict

# ---------------------------------------------------------------------------
# gear 门禁
# ---------------------------------------------------------------------------

_TRUE_VALUES = {'1', 'true', 'yes', 'on'}


def device_gear_enabled() -> bool:
    """整台设备档是否被显式授权（默认禁用）。"""
    return os.environ.get('WANWEI_DEVICE_GEAR_ENABLED', '').strip().lower() in _TRUE_VALUES


def require_gear(gear: str, *, action: str, context: dict[str, Any] | None = None) -> str | None:
    """校验档位是否允许执行动作。

    返回 None 表示放行；返回错误码字符串表示拒绝（调用方据此构造 403/
    错误响应）。拒绝与 device 档放行均落审计，审计失败不阻断主流程。
    """
    if gear != 'device':
        return None
    if device_gear_enabled():
        # device 档关键操作补审计标注：显式授权后的每次放行都可追溯
        try:
            _audit_record('gear_device_allowed', {
                'gear': gear,
                'action': action,
                'note': 'device 档已显式授权（WANWEI_DEVICE_GEAR_ENABLED），关键操作放行',
                **(context or {}),
            })
        except Exception:  # noqa: BLE001 —— 审计不可用不阻断业务
            pass
        return None
    try:
        _audit_record('gear_denied', {
            'gear': gear,
            'action': action,
            'reason': 'device_gear_disabled',
            'note': 'device 档默认禁用，设 WANWEI_DEVICE_GEAR_ENABLED=1 显式授权',
            **(context or {}),
        })
    except Exception:  # noqa: BLE001 —— 审计不可用时门禁照常生效
        pass
    return 'device_gear_disabled'


# ---------------------------------------------------------------------------
# root_path 目录白名单
# ---------------------------------------------------------------------------

_ROOT_WHITELIST_ENV = 'WANWEI_ROOT_PATH_WHITELIST'

# backend/app/platform_api/guards.py → 项目根
_PROJECT_ROOT = Path(__file__).resolve().parents[3]

# 系统敏感目录：即使被误配进白名单也一律拒绝（防呆，Windows 比较用 normcase）
_SENSITIVE_ROOTS: tuple[str, ...] = (
    '/',
    '/etc',
    '/bin',
    '/sbin',
    '/usr',
    '/boot',
    '/lib',
    '/System',
    '/private',
    'C:\\',
    'C:\\Windows',
    'C:\\Windows\\System32',
    'C:\\Program Files',
    'C:\\Program Files (x86)',
    'C:\\ProgramData',
)


def _norm(path: Path) -> str:
    """大小写不敏感平台（Windows）统一 normcase 后再比较。"""
    return os.path.normcase(str(path)) if os.name == 'nt' else str(path)


def _is_within(target: Path, root: Path) -> bool:
    norm_root = _norm(root)
    if _norm(target) == norm_root:
        return True
    return any(_norm(parent) == norm_root for parent in target.parents)


def allowed_root_paths(extra: Iterable[str | Path] | None = None) -> list[Path]:
    """解析允许的根目录白名单。

    优先级：显式参数 > 环境变量 ``WANWEI_ROOT_PATH_WHITELIST``
    （os.pathsep 分隔多个根）> 默认仅项目根（fail-closed）。
    """
    if extra is not None:
        raw = [str(item) for item in extra]
    else:
        env = os.environ.get(_ROOT_WHITELIST_ENV, '').strip()
        raw = env.split(os.pathsep) if env else []
    roots = [Path(item).expanduser().resolve() for item in raw if item.strip()]
    return roots or [_PROJECT_ROOT]


def validate_root_path(
    root_path: str | Path,
    *,
    allowed_roots: Iterable[str | Path] | None = None,
) -> Path:
    """校验 root_path 落在白名单根内且不触及系统敏感目录。

    返回 realpath 规范化后的绝对路径；拒绝时抛 ``ValueError``
    （调用方应映射为 403/422 响应）。
    """
    text = str(root_path or '').strip()
    if not text:
        raise ValueError('root_path 为空')
    target = Path(text).expanduser().resolve()
    for sensitive in _SENSITIVE_ROOTS:
        s = Path(sensitive).resolve()
        if s.parent == s:
            # 文件系统根（'/'、'C:\\'）：只拒根本身，不误伤整盘子路径
            if _norm(target) == _norm(s):
                raise ValueError(f'root_path 触及系统敏感目录，已拒绝：{target}')
        elif _is_within(target, s):
            raise ValueError(f'root_path 触及系统敏感目录，已拒绝：{target}')
    for root in allowed_root_paths(allowed_roots):
        if _is_within(target, root):
            return target
    raise ValueError(
        f'root_path 不在允许的根目录白名单内：{target}'
        f'（可用环境变量 {_ROOT_WHITELIST_ENV} 配置，os.pathsep 分隔多个根）'
    )


# ---------------------------------------------------------------------------
# 审计接入
# ---------------------------------------------------------------------------

_AUDIT_TEXT_LIMIT = 500


def _truncate(value: Any, limit: int = _AUDIT_TEXT_LIMIT) -> Any:
    """递归截断超长字符串，防止审计表膨胀。"""
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + f'…[+{len(value) - limit}字]'
    if isinstance(value, dict):
        return {key: _truncate(item, limit) for key, item in value.items()}
    if isinstance(value, list):
        return [_truncate(item, limit) for item in value[:50]]
    return value


def audit_safe(event_type: str, payload: dict[str, Any]) -> str | None:
    """platform_api 统一审计出口：截断 + 脱敏 + 落库，失败静默。"""
    try:
        return _audit_record(event_type, redact_dict(_truncate(payload)))
    except Exception:  # noqa: BLE001 —— 审计不可用不阻断业务
        return None


# ---------------------------------------------------------------------------
# 脱敏
# ---------------------------------------------------------------------------

_SENSITIVE_HINTS = ('key', 'token', 'secret', 'password', 'credential', 'passwd')


def is_sensitive_key(name: str) -> bool:
    lowered = name.lower()
    return any(hint in lowered for hint in _SENSITIVE_HINTS)


def mask_secret_keys(data: Any, *, placeholder: str = '******') -> Any:
    """递归把「键名含敏感词」的值替换为占位符，保留键结构。"""
    if isinstance(data, dict):
        return {
            key: placeholder if is_sensitive_key(key) else mask_secret_keys(value, placeholder=placeholder)
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [mask_secret_keys(item, placeholder=placeholder) for item in data]
    return data
