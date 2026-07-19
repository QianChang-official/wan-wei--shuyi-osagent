"""Input validation and size limits to prevent DoS attacks."""
from __future__ import annotations

import json
from fastapi import HTTPException, status
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Maximum request body size in bytes (5MB)
MAX_BODY_BYTES = 5 * 1024 * 1024

# 语音上传专用正文上限：POST /platform/system/voice 的 audio_b64 解码后上限
# 为 12MB（见 platform_api/system_svc.py 的 _VOICE_MAX_BYTES），base64 编码
# 膨胀 4/3 → 正文约 16MB，再加 JSON 包装开销放宽到 20MB。全局其余路由仍
# 受 5MB 限制——12MB 与 5MB 的口径在此统一为「语音专用 12MB，全局 5MB」。
VOICE_UPLOAD_PATH = "/platform/system/voice"
VOICE_UPLOAD_MAX_BODY_BYTES = 20 * 1024 * 1024
DEFAULT_PATH_BODY_LIMITS = {VOICE_UPLOAD_PATH: VOICE_UPLOAD_MAX_BODY_BYTES}

# Query parameter limits
MAX_QUERY_LENGTH = 512
MAX_TOP_K = 50
MAX_GOAL_LENGTH = 2000
MAX_PROMPT_LENGTH = 4000


class _BodyTooLarge(HTTPException):
    """Raised when a streamed request body exceeds the configured limit."""

    def __init__(self, max_body_bytes: int) -> None:
        super().__init__(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Request body too large. Maximum {max_body_bytes} bytes allowed.",
        )


class BodySizeLimitMiddleware:
    """Middleware to enforce maximum request body size.

    支持按路径放宽上限（``path_body_limits``）：默认仅放行语音上传路由
    （见 DEFAULT_PATH_BODY_LIMITS），其余路径一律沿用全局 5MB。
    """

    def __init__(
        self,
        app: ASGIApp,
        max_body_bytes: int = MAX_BODY_BYTES,
        path_body_limits: dict[str, int] | None = None,
    ) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.path_body_limits = dict(
            DEFAULT_PATH_BODY_LIMITS if path_body_limits is None else path_body_limits
        )

    def _limit_for(self, scope: Scope) -> int:
        return self.path_body_limits.get(scope.get("path", ""), self.max_body_bytes)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = self._limit_for(scope)
        content_length = Headers(scope=scope).get("content-length")
        if content_length:
            try:
                length = int(content_length)
                if length > limit:
                    await self._reject(scope, receive, send, limit)
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
                if received > limit:
                    raise _BodyTooLarge(limit)
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
            await self._reject(scope, receive, send, limit)

    async def _reject(self, scope: Scope, receive: Receive, send: Send, limit: int) -> None:
        response = JSONResponse(
            {"detail": f"Request body too large. Maximum {limit} bytes allowed."},
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
