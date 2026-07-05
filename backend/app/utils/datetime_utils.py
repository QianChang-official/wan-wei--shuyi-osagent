"""
Timezone-aware datetime utilities

替代已废弃的 datetime.utcnow()，提供 timezone-aware UTC 时间戳。
确保向后兼容现有的 ISO 8601 格式。
"""

from datetime import datetime, timezone


def utc_now() -> datetime:
    """
    返回 timezone-aware 的当前 UTC 时间。

    替代: datetime.utcnow() (已废弃)
    返回: datetime with tzinfo=timezone.utc
    """
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    """
    返回 ISO 8601 格式的 UTC 时间字符串。

    格式: "2026-07-05T12:34:56.789123+00:00"
    兼容: 现有数据库中的 datetime.utcnow().isoformat() 格式
    """
    return utc_now().isoformat()


def utc_now_iso_compact() -> str:
    """
    返回紧凑的 ISO 8601 格式（无微秒）。

    格式: "2026-07-05T12:34:56Z"
    用于: 日志文件名、简化的时间戳
    """
    return utc_now().replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def utc_timestamp_legacy() -> str:
    """
    返回与 datetime.utcnow().isoformat() 格式兼容的时间戳。

    格式: "2026-07-05T12:34:56.789123" (无时区后缀)

    注意: 仅用于与现有数据库记录保持格式兼容。
    新代码应使用 utc_now_iso() 获取带时区信息的完整格式。
    """
    return utc_now().replace(tzinfo=None).isoformat()
