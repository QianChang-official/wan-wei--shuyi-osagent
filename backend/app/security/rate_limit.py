"""Per-IP in-memory rate limiting (v0.9.6, T6).

Boundaries / honest scope:
- This is a SINGLE-PROCESS, in-memory token-bucket limiter. Each worker process
  keeps its own bucket table, so behind multiple workers/replicas the effective
  limit is (configured rate * worker count). Cross-process shared rate limiting
  (Redis/central store) is deliberately deferred to v1.0.
- The bucket table is bounded by an LRU cap so the limiter itself cannot become
  a memory-exhaustion (DoS) vector under a flood of distinct source IPs.
- Expensive/state-changing endpoints get explicit limits. Other mutating
  requests (POST/PUT/PATCH/DELETE) get a conservative default per-IP budget, and
  protected read paths get a separate default. Public health checks stay
  unlimited.
- The protected-read surface is SINGLE-SOURCED from security.auth: any GET
  that APIKeyMiddleware treats as non-public (i.e. requires an API key) also
  gets the default protected-read budget here. There is no second hand-kept
  list to drift out of sync.

Token bucket model:
- capacity C  -> maximum burst size
- refill rate r tokens/sec (r = limit_per_min / 60) -> maximum sustained rate
- a request costs 1 token; when the bucket is empty the request is rejected 429.
"""
from __future__ import annotations

import threading
import time
import ipaddress
import os
from collections import OrderedDict
from collections.abc import Callable, Collection

from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .auth import is_public_path

# Per-endpoint limits, requests per minute. Chosen by cost/risk:
# - model-gateway/test is external + expensive  -> tightest
# - reindex/cleanup/forget confirm mutate broad state -> tight
# - workflow/memory command paths create persistent state or run heavier loops
# - memory search/capsules are read/query paths -> looser
_LIMITS_PER_MIN: dict[str, int] = {
    "/model-gateway/test": 10,
    "/kylin/sdk/status": 10,
    "/kylin/sdk/reindex": 10,
    "/workflow/cleanup": 10,
    "/workflow/stats": 60,
    "/memory/forget/confirm": 20,
    "/memory/forget/preview": 30,
    "/workflow/runs": 30,
    "/workflow/run-dry-run": 30,
    "/memory/v2/command": 30,
    "/memory/v2/reflection": 30,
    "/memory/v2/search": 60,
    "/memory/v2/capsules": 60,
    "/memory/search": 60,
    "/platform/mcp/servers": 30,
    "/platform/mcp/overview": 30,
}

# Burst capacity per endpoint == its per-minute limit (allows a short burst up to
# the minute budget, then throttles to the sustained refill rate).
_DEFAULT_WRITE_LIMIT_PER_MIN = 120
_PROTECTED_READ_LIMIT_PER_MIN = 120
_MAX_TRACKED_IPS = 10_000  # LRU cap: bounds limiter memory footprint.
_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class _Bucket:
    __slots__ = ("tokens", "last")

    def __init__(self, capacity: float, now: float) -> None:
        self.tokens = capacity
        self.last = now


class RateLimiter:
    """Thread-safe per-(ip, endpoint) token-bucket store with an LRU cap."""

    def __init__(
        self,
        limits_per_min: dict[str, int],
        max_ips: int = _MAX_TRACKED_IPS,
        *,
        default_write_limit_per_min: int | None = None,
        protected_get_limit_per_min: int | None = None,
        protected_get_paths: Collection[str] | None = None,
        protected_get_prefixes: tuple[str, ...] = (),
        write_methods: Collection[str] = _WRITE_METHODS,
        public_path_checker: Callable[[str], bool] | None = None,
    ) -> None:
        self._limits = dict(limits_per_min)
        self._max_ips = max_ips
        self._default_write_limit_per_min = default_write_limit_per_min
        self._protected_get_limit_per_min = protected_get_limit_per_min
        self._protected_get_paths = frozenset(protected_get_paths or ())
        self._protected_get_prefixes = tuple(protected_get_prefixes)
        self._write_methods = frozenset(method.upper() for method in write_methods)
        # 判定「公开路径」的外部来源（默认接线到 security.auth.is_public_path），
        # 使保护性 GET 限流面与鉴权面同源，不再手工维护第二份清单。
        self._public_path_checker = public_path_checker
        self._lock = threading.Lock()
        # key: (ip, policy_key) -> _Bucket ; OrderedDict gives us cheap LRU eviction.
        self._buckets: "OrderedDict[tuple[str, str], _Bucket]" = OrderedDict()

    def _protected_prefix_for(self, path: str) -> str | None:
        for prefix in self._protected_get_prefixes:
            if path == prefix or path.startswith(f"{prefix}/"):
                return prefix
        return None

    def _policy_for(self, method: str, path: str) -> tuple[str, int] | None:
        if path in self._limits:
            return path, self._limits[path]

        normalized_method = method.upper()
        if normalized_method == "GET" and self._protected_get_limit_per_min is not None:
            if path in self._protected_get_paths:
                return path, self._protected_get_limit_per_min
            protected_prefix = self._protected_prefix_for(path)
            if protected_prefix is not None:
                return f"{protected_prefix}/*", self._protected_get_limit_per_min
            if self._public_path_checker is not None and not self._public_path_checker(path):
                # 与 APIKeyMiddleware 同源：所有需鉴权的 GET（含 /platform/* 等
                # 未单独列名的保护性读取）共享默认保护性读额度。
                return path, self._protected_get_limit_per_min

        if normalized_method in self._write_methods and self._default_write_limit_per_min is not None:
            return f"__write_default__:{normalized_method}:*", self._default_write_limit_per_min
        return None

    def limit_for(self, path: str, *, method: str = "GET") -> int | None:
        policy = self._policy_for(method, path)
        if policy is None:
            return None
        return policy[1]

    def allow(self, ip: str, path: str, *, method: str = "GET", now: float | None = None) -> bool:
        """Consume one token for (ip, path). Returns False if the bucket is empty."""
        policy = self._policy_for(method, path)
        if policy is None:
            return True  # endpoint not rate-limited
        policy_key, limit = policy
        capacity = float(limit)
        refill_per_sec = capacity / 60.0
        t = time.monotonic() if now is None else now
        key = (ip, policy_key)
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


def build_default_rate_limiter() -> RateLimiter:
    return RateLimiter(
        _LIMITS_PER_MIN,
        default_write_limit_per_min=_DEFAULT_WRITE_LIMIT_PER_MIN,
        protected_get_limit_per_min=_PROTECTED_READ_LIMIT_PER_MIN,
        public_path_checker=is_public_path,
    )


def resolve_client_ip(peer: str, forwarded_for: str | None, trusted_proxy_ips: str = "") -> str:
    if not forwarded_for or not trusted_proxy_ips:
        return peer
    try:
        peer_address = ipaddress.ip_address(peer)
        networks = tuple(
            ipaddress.ip_network(value.strip(), strict=False)
            for value in trusted_proxy_ips.split(",")
            if value.strip()
        )
        forwarded_chain = tuple(
            ipaddress.ip_address(value.strip())
            for value in forwarded_for.split(",")
            if value.strip()
        )
    except ValueError:
        return peer
    if not networks or not forwarded_chain or not any(peer_address in network for network in networks):
        return peer
    # Walk from the application outward. A trusted proxy that appends to an
    # untrusted incoming X-Forwarded-For chain cannot make its leftmost value
    # control the rate-limit bucket.
    for candidate in reversed(forwarded_chain):
        if not any(candidate in network for network in networks):
            return str(candidate)
    return peer


def _client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    return resolve_client_ip(
        peer,
        request.headers.get("x-forwarded-for"),
        os.getenv("WANWEI_TRUSTED_PROXY_IPS", ""),
    )


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests that exceed the per-IP token-bucket budget with HTTP 429."""

    def __init__(self, app, limiter: RateLimiter | None = None) -> None:
        super().__init__(app)
        self._limiter = limiter or build_default_rate_limiter()

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if self._limiter.limit_for(path, method=request.method) is not None:
            ip = _client_ip(request)
            if not self._limiter.allow(ip, path, method=request.method):
                return JSONResponse(
                    {"detail": "Rate limit exceeded. Retry later."},
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    headers={"Retry-After": "1"},
                )
        return await call_next(request)
