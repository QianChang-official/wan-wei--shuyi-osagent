from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from collections import defaultdict

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_logger = logging.getLogger("uvicorn.error")


def request_id(value: str | None) -> str:
    if value and _REQUEST_ID_PATTERN.fullmatch(value):
        return value
    return "req_" + uuid.uuid4().hex


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started = time.monotonic()
        self._requests: dict[tuple[str, str, int], int] = defaultdict(int)
        self._duration: dict[tuple[str, str], float] = defaultdict(float)
        self._in_flight = 0

    def begin(self) -> None:
        with self._lock:
            self._in_flight += 1

    def finish(self, method: str, route: str, status_code: int, duration: float) -> None:
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)
            self._requests[(method, route, status_code)] += 1
            self._duration[(method, route)] += duration

    def render(self, version: str) -> str:
        with self._lock:
            requests = list(self._requests.items())
            durations = list(self._duration.items())
            in_flight = self._in_flight
            uptime = time.monotonic() - self._started

        lines = [
            "# HELP wanwei_build_info Build and version information.",
            "# TYPE wanwei_build_info gauge",
            f'wanwei_build_info{{version="{_escape_label(version)}"}} 1',
            "# HELP wanwei_uptime_seconds Process uptime in seconds.",
            "# TYPE wanwei_uptime_seconds gauge",
            f"wanwei_uptime_seconds {uptime:.6f}",
            "# HELP wanwei_http_requests_in_flight Current in-flight HTTP requests.",
            "# TYPE wanwei_http_requests_in_flight gauge",
            f"wanwei_http_requests_in_flight {in_flight}",
            "# HELP wanwei_http_requests_total HTTP requests by method, route, and status.",
            "# TYPE wanwei_http_requests_total counter",
        ]
        for (method, route, status_code), count in sorted(requests):
            labels = (
                f'method="{_escape_label(method)}",'
                f'route="{_escape_label(route)}",status="{status_code}"'
            )
            lines.append(f"wanwei_http_requests_total{{{labels}}} {count}")
        lines.extend([
            "# HELP wanwei_http_request_duration_seconds_total Cumulative request duration.",
            "# TYPE wanwei_http_request_duration_seconds_total counter",
        ])
        for (method, route), duration in sorted(durations):
            labels = f'method="{_escape_label(method)}",route="{_escape_label(route)}"'
            lines.append(f"wanwei_http_request_duration_seconds_total{{{labels}}} {duration:.6f}")
        return "\n".join(lines) + "\n"


metrics = MetricsRegistry()


class ObservabilityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, registry: MetricsRegistry | None = None) -> None:
        super().__init__(app)
        self._registry = registry or metrics

    async def dispatch(self, request: Request, call_next):
        correlation_id = request_id(request.headers.get("x-request-id"))
        request.state.request_id = correlation_id
        started = time.perf_counter()
        self._registry.begin()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = correlation_id
            duration = time.perf_counter() - started
            response.headers["Server-Timing"] = f"app;dur={duration * 1000:.2f}"
            return response
        finally:
            duration = time.perf_counter() - started
            route = request.scope.get("route")
            route_path = getattr(route, "path", "__unmatched__")
            self._registry.finish(request.method, route_path, status_code, duration)
            _logger.info(
                "request_complete method=%s route=%s status=%s duration_ms=%.2f request_id=%s",
                request.method,
                route_path,
                status_code,
                duration * 1000,
                correlation_id,
            )
