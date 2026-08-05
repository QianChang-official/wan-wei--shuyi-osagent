"""
FIX-21（04-#07）：memory_center._normalize_session 的 int() 强转容错回归测试。

背景
----
原实现 `turns: int(raw.get('turns', 0) or 0)` 对脏数据（字符串 "abc"）直接
抛 ValueError，导致整个 `GET /memory/sessions` 端点 500。

修复：加 try/except，非法值默认 0，防止单条脏数据污染整个列表响应。
"""

import pytest


def _normalize(raw):
    """延迟导入：memory_center 依赖 app.platform_api 模块树。"""
    from backend.app.platform_api.memory_center import _normalize_session

    return _normalize_session(raw)


def test_normalize_session_valid_turns():
    """正常数值 turns 必须保持原样。"""
    assert _normalize({'id': 's1', 'turns': 42})['turns'] == 42


def test_normalize_session_string_number_turns():
    """字符串形式的数字（'123'）应被转换，这是合法的类型宽容。"""
    assert _normalize({'id': 's1', 'turns': '123'})['turns'] == 123


def test_normalize_session_invalid_turns_defaults_zero():
    """非法 turns（字符串 'abc'、None、对象等）默认 0，不抛异常。

    修复前：`int('abc')` → ValueError → 整个端点 500。
    修复后：捕获异常，turns 归零，列表其余条目正常返回。
    """
    assert _normalize({'id': 's1', 'turns': 'abc'})['turns'] == 0
    assert _normalize({'id': 's2', 'turns': None})['turns'] == 0
    assert _normalize({'id': 's3', 'turns': {'bad': 'object'}})['turns'] == 0
    assert _normalize({'id': 's4', 'turns': float('inf')})['turns'] == 0


def test_normalize_session_missing_turns_defaults_zero():
    """缺失 turns 字段默认 0（既有行为，必须保持）。"""
    assert _normalize({'id': 's1'})['turns'] == 0


def test_normalize_session_preserves_other_fields():
    """容错路径不得影响其他字段的正常规范化。"""
    result = _normalize({
        'id': 's1',
        'title': 'Test Session',
        'turns': 'invalid',
        'archived': True,
        'pinned': False,
        'updated_at': '2026-08-03T12:00:00Z',
    })
    assert result['id'] == 's1'
    assert result['title'] == 'Test Session'
    assert result['turns'] == 0  # 容错默认
    assert result['archived'] is True
    assert result['pinned'] is False
    assert result['updated_at'] == '2026-08-03T12:00:00Z'
