"""Per-IP in-memory rate limiting (v0.9.6, T6).

Boundaries / honest scope:
- This is a SINGLE-PROCESS, in-memory token-bucket limiter. Each worker process
  keeps its own bucket table, so behind multiple workers/replicas the effective
  limit is (configured rate * worker count). Cross-process shared rate limiting
  (Redis/central store) is deliberately deferred to v1.0.
- The bucket table is bounded by an LRU cap so the limiter itself cannot become
  a memory-exhaustion (DoS) vector under a flood of distinct source IPs.
- Only a small set of expensive/state-changing endpoints are limited; everything
  else passes through untouched.

Token bucket model:
- capacity C  -> maximum burst size
- refill rate r tokens/sec (r = limit_per_min / 60) -> maximum sustained rate
- a request costs 1 token; when the bucket is empty the request is rejected 429.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict

from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# Per-endpoint limits, requests per minute. Chosen by cost/risk:
# - model-gateway/test is external + expensive  -> tightest
# - workflow/runs creates persistent state       -> moderate
# - memory search/capsules are read/query paths   -> looser
_LIMITS_PER_MIN: dict[str, int] = {
    "/model-gateway/test": 10,
    "/workflow/runs": 30,
    "/memory/v2/search": 60,
    "/memory/v2/capsules": 60,
}

# Burst capacity per endpoint == its per-minute limit (allows a short burst up to
# the minute budget, then throttles to the sustained refill rate).
_MAX_TRACKED_IPS = 10_000  # LRU cap: bounds limiter memory footprint.


class _Bucket:
    __slots__ = ("tokens", "last")

    def __init__(self, capacity: float, now: float) -> None:
        self.tokens = capacity
        self.last = now


class RateLimiter:
    """Thread-safe per-(ip, endpoint) token-bucket store with an LRU cap."""

    def __init__(self, limits_per_min: dict[str, int], max_ips: int = _MAX_TRACKED_IPS) -> None:
        self._limits = limits_per_min
        self._max_ips = max_ips
        self._lock = threading.Lock()
        # key: (ip, path) -> _Bucket ; OrderedDict gives us cheap LRU eviction.
        self._buckets: "OrderedDict[tuple[str, str], _Bucket]" = OrderedDict()

    def limit_for(self, path: str) -> int | None:
        return self._limits.get(path)

    def allow(self, ip: str, path: str, *, now: float | None = None) -> bool:
        """Consume one token for (ip, path). Returns False if the bucket is empty."""
        limit = self._limits.get(path)
        if limit is None:
            return True  # endpoint not rate-limited
        capacity = float(limit)
        refill_per_sec = capacity / 60.0
        t = time.monotonic() if now is None else now
        key = (ip, path)
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(capacity, t)
                self._buckets[key] = bucket
            else:
                # Refill proportional to elapsed time, capped at capacity.
                elapsed = t - bucket.last
                if elapsed > 0:
                    bucket.tokens = min(capacity, bucket.tokens + elapsed * refill_per_sec)
                    bucket.last = t
                self._buckets.move_to_end(key)  # mark as recently used

            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                allowed = True
            else:
                allowed = False

            # Enforce LRU cap so a flood of unique IPs cannot exhaust memory.
            while len(self._buckets) > self._max_ips:
                self._buckets.popitem(last=False)
            return allowed


_limiter = RateLimiter(_LIMITS_PER_MIN)


def _client_ip(request: Request) -> str:
    # Honour X-Forwarded-For first hop when present (reverse-proxy deployments),
    # otherwise fall back to the direct peer. Not used for auth — only bucketing.
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests that exceed the per-IP token-bucket budget with HTTP 429."""

    def __init__(self, app, limiter: RateLimiter | None = None) -> None:
        super().__init__(app)
        self._limiter = limiter or _limiter

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if self._limiter.limit_for(path) is not None:
            ip = _client_ip(request)
            if not self._limiter.allow(ip, path):
                return JSONResponse(
                    {"detail": "Rate limit exceeded. Retry later."},
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                )
        return await call_next(request)
