"""Focused SSE lifecycle tests without HTTP servers or persistent stores."""
import asyncio
import json
from itertools import count
from types import SimpleNamespace

import pytest


@pytest.fixture
def stream_module(monkeypatch):
    from backend.app.platform_api import mobile_remote as mod

    monkeypatch.setattr(mod, '_EVENT_BUFFER', [])
    monkeypatch.setattr(mod, '_EVENT_SEQUENCE', count(1))
    monkeypatch.setattr(mod, '_SUBSCRIBERS', set())
    monkeypatch.setattr(mod, '_SUBSCRIBER_OWNERS', {})
    monkeypatch.setattr(mod, '_BUS_LOCK', asyncio.Lock())
    monkeypatch.setattr(mod, 'actor_id_for_request', lambda request: 'owner-a')
    monkeypatch.setattr(mod, 'configured_actor_id', lambda: 'owner-a')
    monkeypatch.setattr(mod, '_SESSION_CHECK_INTERVAL', 0.01)
    return mod


def _request(lan=False):
    return SimpleNamespace(
        headers={'x-api-key': 'lan_test'},
        state=SimpleNamespace(is_lan_session=lan),
    )


async def _open(mod, lan=False):
    response = await mod.realtime_events(request=_request(lan), since=0, max_idle=0)
    return response.body_iterator


async def _event(mod, name, owner='owner-a'):
    await mod._append_event({'ts': 1.0, 'event_type': name, 'owner_id': owner})


def _assert_clean(mod):
    assert not mod._SUBSCRIBERS
    assert not mod._SUBSCRIBER_OWNERS


def test_unstarted_stream_does_not_reserve_slot(stream_module):
    mod = stream_module

    async def exercise():
        stream = await _open(mod)
        _assert_clean(mod)
        await stream.aclose()
        _assert_clean(mod)

    asyncio.run(exercise())


def test_disconnect_during_backlog_releases_slot(stream_module):
    mod = stream_module

    async def exercise():
        await _event(mod, 'first')
        await _event(mod, 'second')
        stream = await _open(mod)
        assert 'first' in await anext(stream)
        assert len(mod._SUBSCRIBERS) == 1
        await stream.aclose()
        _assert_clean(mod)

    asyncio.run(exercise())


def test_events_during_yield_are_delivered_once_with_equal_timestamps(stream_module):
    mod = stream_module

    async def exercise():
        await _event(mod, 'first')
        stream = await _open(mod)
        assert 'first' in await anext(stream)
        for i in range(8):
            await _event(mod, f'new-{i}')
        await _event(mod, 'foreign', owner='owner-b')
        for i in range(8):
            frame = await asyncio.wait_for(anext(stream), timeout=1)
            payload = json.loads(frame.split('data: ', 1)[1])
            assert payload['event_type'] == f'new-{i}'
            assert 'owner_id' not in payload
            assert '_sequence' not in payload
        waiting = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        assert not waiting.done()
        await _event(mod, 'last')
        assert 'last' in await asyncio.wait_for(waiting, timeout=1)
        await stream.aclose()
        _assert_clean(mod)

    asyncio.run(exercise())


@pytest.mark.parametrize('failure', ['expired', 'revoked', 'database_error'])
def test_lan_stream_checks_session_while_idle(stream_module, monkeypatch, failure):
    mod = stream_module
    valid = True

    def identity(credential):
        assert credential == 'lan_test'
        if not valid and failure == 'database_error':
            raise mod.sqlite3.OperationalError('unavailable')
        return 'owner-a' if valid else None

    monkeypatch.setattr(mod, '_lan_session_identity', identity)

    async def exercise():
        nonlocal valid
        await _event(mod, 'first')
        stream = await _open(mod, lan=True)
        assert 'first' in await anext(stream)
        waiting = asyncio.create_task(anext(stream))
        await asyncio.sleep(0.03)
        assert not waiting.done()
        valid = False
        frame = await asyncio.wait_for(waiting, timeout=1)
        assert 'session_expired_or_revoked' in frame
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
        _assert_clean(mod)

    asyncio.run(exercise())


def test_lan_revocation_stops_remaining_backlog(stream_module, monkeypatch):
    mod = stream_module
    monkeypatch.setattr(mod, '_lan_session_identity', lambda credential: 'owner-a')

    async def exercise():
        await _event(mod, 'first')
        await _event(mod, 'private-second')
        stream = await _open(mod, lan=True)
        assert 'first' in await anext(stream)
        monkeypatch.setattr(mod, '_lan_session_identity', lambda credential: None)
        frame = await anext(stream)
        assert 'session_expired_or_revoked' in frame
        assert 'private-second' not in frame
        await stream.aclose()
        _assert_clean(mod)

    asyncio.run(exercise())


def test_cancel_idle_stream_releases_slot(stream_module):
    mod = stream_module

    async def exercise():
        stream = await _open(mod)
        waiting = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        assert len(mod._SUBSCRIBERS) == 1
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        _assert_clean(mod)

    asyncio.run(exercise())
