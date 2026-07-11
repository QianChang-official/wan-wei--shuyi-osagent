"""Input validation and size limits to prevent DoS attacks."""
from __future__ import annotations

import json
from fastapi import HTTPException, status
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Maximum request body size in bytes (5MB)
MAX_BODY_BYTES = 5 * 1024 * 1024

# Query parameter limits
MAX_QUERY_LENGTH = 512
MAX_TOP_K = 50
MAX_GOAL_LENGTH = 2000
MAX_PROMPT_LENGTH = 4000


class _BodyTooLarge(Exception):
    """Raised when a streamed request body exceeds the configured limit."""


class BodySizeLimitMiddleware:
    """Middleware to enforce maximum request body size."""

    def __init__(self, app: ASGIApp, max_body_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_length = Headers(scope=scope).get("content-length")
        if content_length:
            try:
                length = int(content_length)
                if length > self.max_body_bytes:
                    await self._reject(scope, receive, send)
                    return
            except ValueError:
                pass

        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    raise _BodyTooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            if response_started:
                raise
            await self._reject(scope, receive, send)

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            {"detail": f"Request body too large. Maximum {self.max_body_bytes} bytes allowed."},
            status_code=status.HTTP_413_CONTENT_TOO_LARGE
        )
        await response(scope, receive, send)


def validate_search_params(q: str | None, top_k: int = 10) -> tuple[str, int]:
    """Validate and sanitize search parameters."""
    if q and len(q) > MAX_QUERY_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Query too long. Maximum {MAX_QUERY_LENGTH} characters allowed."
        )

    # Clamp top_k to valid range
    if top_k < 1:
        top_k = 1
    elif top_k > MAX_TOP_K:
        top_k = MAX_TOP_K

    return q or "", top_k


def validate_goal_length(goal: str) -> str:
    """Validate goal/user_goal length."""
    if len(goal) > MAX_GOAL_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Goal too long. Maximum {MAX_GOAL_LENGTH} characters allowed."
        )
    return goal


def validate_prompt_length(prompt: str) -> str:
    """Validate prompt preview length."""
    if len(prompt) > MAX_PROMPT_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Prompt too long. Maximum {MAX_PROMPT_LENGTH} characters allowed."
        )
    return prompt
