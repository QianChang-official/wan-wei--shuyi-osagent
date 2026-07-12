"""Focused tests for request body size enforcement."""

from __future__ import annotations

import json

import anyio
from starlette.responses import JSONResponse

from backend.app.security.input_limits import BodySizeLimitMiddleware


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


async def _call_limited_app(headers, chunks, max_body_bytes=10):
    app = BodySizeLimitMiddleware(_body_reader_app, max_body_bytes=max_body_bytes)
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
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": headers,
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }

    await app(scope, receive, send)
    status = next(message["status"] for message in sent if message["type"] == "http.response.start")
    body = b"".join(message.get("body", b"") for message in sent if message["type"] == "http.response.body")
    return status, body


def test_chunked_body_without_content_length_is_rejected_when_too_large():
    status, body = anyio.run(
        _call_limited_app,
        [(b"transfer-encoding", b"chunked")],
        [b"12345", b"678901"],
    )

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
