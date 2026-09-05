import pytest

from backend.app.security.auth import (
    _api_key_hash,
    _verify_api_key,
    actor_id_from_api_key,
    rotate_api_key,
)


def test_rotate_round_trip_reactivates_original_key(isolated_db, monkeypatch):
    # issue #211 修复后,自动注册仅限配置的 owner key——轮换测试的起点
    # key 必须先作为 owner 配置,再走 rotate 显式注册新 key。
    monkeypatch.setenv("WANWEI_API_KEY", "key-a")
    identity = actor_id_from_api_key("key-a")
    assert rotate_api_key("key-a", "key-b") == identity
    assert not _verify_api_key("key-a")
    assert rotate_api_key("key-b", "key-a") == identity
    assert _verify_api_key("key-a")
    assert not _verify_api_key("key-b")


def test_rotate_multiple_round_trips_are_repeatable(isolated_db, monkeypatch):
    monkeypatch.setenv("WANWEI_API_KEY", "key-a")
    identity = actor_id_from_api_key("key-a")
    for old_key, new_key in (("key-a", "key-b"), ("key-b", "key-a"), ("key-a", "key-b"), ("key-b", "key-a")):
        assert rotate_api_key(old_key, new_key) == identity
    assert _verify_api_key("key-a")
    assert not _verify_api_key("key-b")


def test_rotate_old_key_is_immediately_rejected(isolated_db, monkeypatch):
    monkeypatch.setenv("WANWEI_API_KEY", "old-key")
    actor_id_from_api_key("old-key")
    rotate_api_key("old-key", "new-key")
    assert not _verify_api_key("old-key")
    assert _verify_api_key("new-key")


def test_rotate_failure_rolls_back_prior_update(isolated_db, monkeypatch):
    monkeypatch.setenv("WANWEI_API_KEY", "key-a")
    actor_id_from_api_key("key-a")
    with pytest.raises(Exception):
        rotate_api_key("key-a", "key-a")
    assert _verify_api_key("key-a")
    from backend.app.db import get_conn
    row = get_conn().execute(
        "SELECT is_active FROM identity WHERE api_key_hash=?", (_api_key_hash("key-a"),)
    ).fetchone()
    assert row["is_active"] == 1


def test_stranger_key_cannot_rotate_into_identity(isolated_db, monkeypatch):
    """issue #211 回归:陌生 key 不能借 rotate 洗白成注册凭据。"""
    monkeypatch.setenv("WANWEI_API_KEY", "owner-key-1234567890abcdef1234567890")
    actor_id_from_api_key("owner-key-1234567890abcdef1234567890")
    with pytest.raises(KeyError, match="old key not registered"):
        rotate_api_key("stranger-key-000000000000000000000000", "anything-key")
