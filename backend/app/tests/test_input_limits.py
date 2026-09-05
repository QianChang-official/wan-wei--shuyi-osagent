"""Focused tests for request body size enforcement."""

from __future__ import annotations

import json

import anyio
import pytest
from fastapi import FastAPI
from starlette.responses import JSONResponse

from backend.app.security.input_limits import (
    BodySizeLimitMiddleware,
    MAX_BODY_BYTES,
    MOBILE_UPLOAD_MAX_BODY_BYTES,
    MOBILE_UPLOAD_MAX_FILE_BYTES,
    MOBILE_UPLOAD_PATH,
    VOICE_UPLOAD_MAX_BODY_BYTES,
    VOICE_UPLOAD_PATH,
)


async def _body_reader_app(scope, receive, send):
    body = b""
    while True:
        message = await receive()
        if message["type"] != "http.request":
            continue
        body += message.get("body", b"")
        if not message.get("more_body", False):
            break

    response = JSONResponse({"size": len(body)})
    await response(scope, receive, send)


async def _call_asgi_app(app, headers, chunks, path='/'):
    messages = [
        {
            "type": "http.request",
            "body": chunk,
            "more_body": index < len(chunks) - 1,
        }
        for index, chunk in enumerate(chunks)
    ]
    if not messages:
        messages.append({"type": "http.request", "body": b"", "more_body": False})

    async def receive():
        if messages:
            return messages.pop(0)
        return {"type": "http.request", "body": b"", "more_body": False}

    sent = []

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": headers,
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }

    await app(scope, receive, send)
    status = next(message["status"] for message in sent if message["type"] == "http.response.start")
    body = b"".join(message.get("body", b"") for message in sent if message["type"] == "http.response.body")
    return status, body


async def _call_limited_app(headers, chunks, max_body_bytes=10):
    app = BodySizeLimitMiddleware(_body_reader_app, max_body_bytes=max_body_bytes)
    return await _call_asgi_app(app, headers, chunks)


def test_chunked_body_without_content_length_is_rejected_when_too_large():
    status, body = anyio.run(
        _call_limited_app,
        [(b"transfer-encoding", b"chunked")],
        [b"12345", b"678901"],
    )

    assert status == 413
    assert b"Request body too large" in body


def test_chunked_body_keeps_413_when_fastapi_parses_the_body():
    async def call_app():
        app = FastAPI()
        app.add_middleware(BodySizeLimitMiddleware, max_body_bytes=10)

        @app.post("/")
        async def parse_body(payload: dict):
            return payload

        return await _call_asgi_app(
            app,
            [
                (b"content-type", b"application/json"),
                (b"transfer-encoding", b"chunked"),
            ],
            [b'{"x":', b'"123"}'],
        )

    status, body = anyio.run(call_app)

    assert status == 413
    assert b"Request body too large" in body


def test_large_content_length_is_rejected_before_reading_body():
    async def blocked_app(scope, receive, send):
        raise AssertionError("app should not be called after content-length rejection")

    async def call_app():
        app = BodySizeLimitMiddleware(blocked_app, max_body_bytes=10)
        sent = []

        async def receive():
            raise AssertionError("request body should not be read after content-length rejection")

        async def send(message):
            sent.append(message)

        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": [(b"content-length", b"11")],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }

        await app(scope, receive, send)
        status = next(message["status"] for message in sent if message["type"] == "http.response.start")
        body = b"".join(message.get("body", b"") for message in sent if message["type"] == "http.response.body")
        return status, body

    status, body = anyio.run(call_app)

    assert status == 413
    assert b"Request body too large" in body


def test_streaming_body_with_forged_small_content_length_is_rejected_when_too_large():
    status, body = anyio.run(
        _call_limited_app,
        [(b"content-length", b"5")],
        [b"12345", b"678901"],
    )

    assert status == 413
    assert b"Request body too large" in body


def test_small_streaming_body_without_content_length_is_allowed():
    status, body = anyio.run(
        _call_limited_app,
        [],
        [b"123", b"456"],
    )

    assert status == 200
    assert json.loads(body) == {"size": 6}


@pytest.mark.parametrize('headers', [[], [(b'content-length', b'1')]])
def test_mobile_upload_body_limit_counts_streamed_bytes(headers):
    async def drain(scope, receive, send):
        size = 0
        while True:
            message = await receive()
            size += len(message.get('body', b''))
            if not message.get('more_body'):
                break
        await JSONResponse({'size': size})(scope, receive, send)

    async def exercise():
        app = BodySizeLimitMiddleware(drain)
        chunks = [b'x' * (1024 * 1024)] * 51
        status, body = await _call_asgi_app(app, headers, chunks, MOBILE_UPLOAD_PATH)
        assert status == 200
        assert json.loads(body)['size'] == MOBILE_UPLOAD_MAX_BODY_BYTES
        status, _ = await _call_asgi_app(app, headers, chunks + [b'x'], MOBILE_UPLOAD_PATH)
        assert status == 413

    anyio.run(exercise)


def test_mobile_upload_limit_is_path_scoped():
    app = BodySizeLimitMiddleware(_body_reader_app)
    assert MOBILE_UPLOAD_MAX_FILE_BYTES == 50 * 1024 * 1024
    assert MOBILE_UPLOAD_MAX_BODY_BYTES > MOBILE_UPLOAD_MAX_FILE_BYTES
    assert app._limit_for({'path': MOBILE_UPLOAD_PATH}) == MOBILE_UPLOAD_MAX_BODY_BYTES
    assert app._limit_for({'path': VOICE_UPLOAD_PATH}) == VOICE_UPLOAD_MAX_BODY_BYTES
    for path in ('/platform/system/settings', '/platform/mobile/list', MOBILE_UPLOAD_PATH + '/extra'):
        assert app._limit_for({'path': path}) == MAX_BODY_BYTES


def test_mobile_upload_declared_oversize_is_rejected_before_handler():
    async def blocked(scope, receive, send):
        raise AssertionError('Oversize request reached handler')

    async def exercise():
        app = BodySizeLimitMiddleware(blocked)
        status, _ = await _call_asgi_app(
            app,
            [(b'content-length', str(MOBILE_UPLOAD_MAX_BODY_BYTES + 1).encode())],
            [], MOBILE_UPLOAD_PATH,
        )
        assert status == 413

    anyio.run(exercise)
