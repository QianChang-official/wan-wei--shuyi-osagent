"""Security headers middleware for HTTP responses."""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all HTTP responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "SAMEORIGIN"

        # Control referrer information
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Content Security Policy for the Vue SPA. Inline styles are still used
        # by component rendering, but scripts must come from same-origin assets.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self' data:; "
            "connect-src 'self';"
        )

        # Prevent caching of sensitive API responses
        if request.url.path.startswith(("/memory/", "/audit/", "/workflow/")):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"

        # HSTS: instruct browsers to use HTTPS for 1 year (only meaningful behind TLS)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        return response
