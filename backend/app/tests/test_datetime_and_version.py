"""
测试 v0.9.5 datetime utilities 和 version 模块

验证：
1. utc_now() 返回 timezone-aware datetime
2. 各种 ISO 格式输出正确
3. 版本号正确
"""

import pytest
from datetime import datetime, timezone


def test_utc_now_is_timezone_aware():
    """测试 utc_now() 返回带时区信息的 datetime"""
    from backend.app.utils.datetime_utils import utc_now

    now = utc_now()

    assert isinstance(now, datetime)
    assert now.tzinfo is not None
    assert now.tzinfo == timezone.utc


def test_utc_now_iso_format():
    """测试 ISO 格式输出"""
    from backend.app.utils.datetime_utils import utc_now_iso

    iso_str = utc_now_iso()

    # 应该包含时区信息
    assert '+00:00' in iso_str or 'Z' in iso_str
    # 应该可以解析回 datetime
    parsed = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
    assert parsed.tzinfo is not None


def test_utc_now_iso_compact():
    """测试紧凑 ISO 格式（无微秒，Z 结尾）"""
    from backend.app.utils.datetime_utils import utc_now_iso_compact

    compact_str = utc_now_iso_compact()

    # 应该以 Z 结尾
    assert compact_str.endswith('Z')
    # 不应该有微秒
    assert '.' not in compact_str
    # 格式应该是 YYYY-MM-DDTHH:MM:SSZ
    assert len(compact_str) == 20  # 固定长度


def test_utc_timestamp_legacy_compatibility():
    """测试向后兼容的时间戳格式"""
    from backend.app.utils.datetime_utils import utc_timestamp_legacy

    legacy_str = utc_timestamp_legacy()

    # 不应该包含时区信息（向后兼容）
    assert '+' not in legacy_str
    assert 'Z' not in legacy_str or legacy_str.endswith('Z') is False
    # 应该可以解析
    parsed = datetime.fromisoformat(legacy_str)
    # tzinfo 应该是 None（naive datetime）
    assert parsed.tzinfo is None


def test_version_constant():
    """测试版本常量"""
    from backend.app.version import VERSION, VERSION_HISTORY

    # 版本号应该是字符串
    assert isinstance(VERSION, str)
    assert VERSION == "v0.10.0-delivery-hardening"

    # 版本历史应该是列表
    assert isinstance(VERSION_HISTORY, list)
    assert len(VERSION_HISTORY) >= 3

    # 最新版本应该是当前交付硬化版本
    latest = VERSION_HISTORY[0]
    assert latest['version'] == "v0.10.0-delivery-hardening"
    assert latest['status'] == "in_progress"


def test_datetime_utils_no_deprecation_warning():
    """确保不使用已废弃的 datetime.utcnow()"""
    import warnings
    from backend.app.utils.datetime_utils import utc_now, utc_now_iso

    # 启用所有警告
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")

        # 调用我们的函数
        utc_now()
        utc_now_iso()

        # 不应该有 DeprecationWarning
        deprecation_warnings = [warning for warning in w if issubclass(warning.category, DeprecationWarning)]
        assert len(deprecation_warnings) == 0, f"Found deprecation warnings: {deprecation_warnings}"
