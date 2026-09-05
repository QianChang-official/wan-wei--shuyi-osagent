"""Regression tests for issue #88: structured context truncation in _chat_request_context.

验证:
- system 消息永远保留且不被截断
- 非 system 消息按消息边界从最早开始丢弃
- 角色标签格式 [{role}] {content} 被保留
- 总长度不超过 4000 字符
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.app.app_runtime import _chat_request_context


@pytest.fixture(autouse=True)
def configured_chat_gateway(monkeypatch):
    """Provide deterministic gateway prerequisites for context-only tests.

    ``_chat_request_context`` imports the service functions at call time, so
    patch the live module rather than names captured before another test
    reloads it.
    """
    from backend.app.model_gateway import service

    monkeypatch.setattr(service, "active_chat_provider", lambda owner_id=None: None)
    monkeypatch.setattr(
        service,
        "local_llama_settings",
        lambda: ("http://127.0.0.1:11434/v1", "test-model", True),
    )


def test_system_message_always_preserved():
    """system 消息不应被截断，即使它本身超过 4000 字符。"""
    long_system = "x" * 5000
    messages = [
        {"role": "system", "content": long_system},
        {"role": "user", "content": "hello"},
    ]
    result = _chat_request_context(messages, "default")
    assert result is not None
    _provider, _api_base, _api_key, _model, prompt = result
    assert "[system]" in prompt
    assert long_system in prompt


def test_non_system_truncated_from_oldest():
    """非 system 消息从最早的开始丢弃，保留最新消息。"""
    messages = [
        {"role": "user", "content": "A" * 2000},
        {"role": "assistant", "content": "B" * 2000},
        {"role": "user", "content": "C" * 2000},
    ]
    result = _chat_request_context(messages, "default")
    assert result is not None
    _provider, _api_base, _api_key, _model, prompt = result
    # 最早的 A 应该被丢弃
    assert "[user] A" not in prompt
    # 最新的 C 应该保留
    assert "[user] C" in prompt
    # B 可能保留也可能被丢弃，取决于长度
    assert len(prompt) <= 4000


def test_role_tag_preserved():
    """每个消息都应保留 [{role}] {content} 格式。"""
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    result = _chat_request_context(messages, "default")
    assert result is not None
    _provider, _api_base, _api_key, _model, prompt = result
    assert "[system] sys" in prompt
    assert "[user] hi" in prompt
    assert "[assistant] hello" in prompt


def test_total_length_capped():
    """prompt 总长度不应超过 4000 字符。"""
    messages = [
        {"role": "user", "content": "x" * 3000},
        {"role": "assistant", "content": "y" * 3000},
    ]
    result = _chat_request_context(messages, "default")
    assert result is not None
    _provider, _api_base, _api_key, _model, prompt = result
    assert len(prompt) <= 4000


def test_empty_messages():
    """空消息列表应生成空 prompt。"""
    result = _chat_request_context([], "default")
    assert result is not None
    _provider, _api_base, _api_key, _model, prompt = result
    assert prompt == ""


def test_only_system_messages():
    """只有 system 消息时，system 消息应完整保留。"""
    messages = [
        {"role": "system", "content": "instruction one"},
        {"role": "system", "content": "instruction two"},
    ]
    result = _chat_request_context(messages, "default")
    assert result is not None
    _provider, _api_base, _api_key, _model, prompt = result
    assert "[system] instruction one" in prompt
    assert "[system] instruction two" in prompt
