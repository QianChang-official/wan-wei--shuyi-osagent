"""Input validation and size limits to prevent DoS attacks."""
from __future__ import annotations

import json
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# Maximum request body size in bytes (5MB)
MAX_BODY_BYTES = 5 * 1024 * 1024

# Query parameter limits
MAX_QUERY_LENGTH = 512
MAX_TOP_K = 50
MAX_GOAL_LENGTH = 2000
MAX_PROMPT_LENGTH = 4000


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Middleware to enforce maximum request body size."""

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                length = int(content_length)
                if length > MAX_BODY_BYTES:
                    return JSONResponse(
                        {"detail": f"Request body too large. Maximum {MAX_BODY_BYTES} bytes allowed."},
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
                    )
            except ValueError:
                pass
        return await call_next(request)


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
