"""Rate limiter tests (v0.9.6, T6).

Verifies the per-IP token-bucket limiter:
- burst up to capacity is allowed, the next request is rejected;
- tokens refill proportional to elapsed time (deterministic clock);
- distinct IPs and distinct endpoints have independent buckets;
- the LRU cap bounds memory;
- unlimited endpoints always pass;
- the middleware returns HTTP 429 on burst-over-limit end to end.
"""
from __future__ import annotations

import pytest

from backend.app.security.rate_limit import RateLimiter, build_default_rate_limiter


def test_burst_up_to_capacity_then_reject():
    rl = RateLimiter({"/x": 5})
    # Fixed clock so no refill happens between calls.
    # "1.1.1.1" is an intentional deterministic test IP (NOSONAR); it only keys
    # an in-memory bucket, no traffic is sent. Do not make it configurable.
    t = 1000.0
    allowed = [rl.allow("1.1.1.1", "/x", now=t) for _ in range(5)]
    assert all(allowed), "first C requests must be allowed"
    assert rl.allow("1.1.1.1", "/x", now=t) is False, "over-capacity request must be rejected"


def test_refill_after_time():
    rl = RateLimiter({"/x": 60})  # 60/min => 1 token/sec
    t = 1000.0
    # Drain the bucket.
    for _ in range(60):
        assert rl.allow("ip", "/x", now=t) is True
    assert rl.allow("ip", "/x", now=t) is False
    # After 1 simulated second, exactly ~1 token should be available.
    assert rl.allow("ip", "/x", now=t + 1.0) is True
    assert rl.allow("ip", "/x", now=t + 1.0) is False


def test_distinct_ips_independent():
    rl = RateLimiter({"/x": 2})
    t = 500.0
    assert rl.allow("a", "/x", now=t) is True
    assert rl.allow("a", "/x", now=t) is True
    assert rl.allow("a", "/x", now=t) is False
    # A different IP still has a full bucket.
    assert rl.allow("b", "/x", now=t) is True


def test_distinct_endpoints_independent():
    rl = RateLimiter({"/x": 1, "/y": 1})
    t = 500.0
    assert rl.allow("a", "/x", now=t) is True
    assert rl.allow("a", "/x", now=t) is False
    # Same IP on a different endpoint has its own bucket.
    assert rl.allow("a", "/y", now=t) is True


def test_unlimited_endpoint_always_allows():
    rl = RateLimiter({"/x": 1})
    t = 500.0
    for _ in range(100):
        assert rl.allow("a", "/not-limited", now=t) is True


def test_default_write_limit_covers_unlisted_mutating_paths():
    rl = RateLimiter({}, default_write_limit_per_min=2)
    t = 500.0

    assert rl.allow("a", "/new-heavy-action", method="POST", now=t) is True
    assert rl.allow("a", "/new-heavy-action", method="POST", now=t) is True
    assert rl.allow("a", "/new-heavy-action", method="POST", now=t) is False
    assert rl.allow("a", "/new-heavy-action", method="GET", now=t) is True


def test_default_write_limit_shares_bucket_across_unlisted_paths():
    rl = RateLimiter({}, default_write_limit_per_min=2)
    t = 500.0

    assert rl.allow("a", "/unlisted-one", method="POST", now=t) is True
    assert rl.allow("a", "/unlisted-two", method="POST", now=t) is True
    assert rl.allow("a", "/unlisted-three", method="POST", now=t) is False


def test_protected_get_limit_covers_sensitive_prefixes():
    rl = RateLimiter(
        {},
        protected_get_limit_per_min=1,
        protected_get_paths={"/audit/logs"},
        protected_get_prefixes=("/workflow/runs",),
    )
    t = 500.0

    assert rl.allow("a", "/audit/logs", method="GET", now=t) is True
    assert rl.allow("a", "/audit/logs", method="GET", now=t) is False
    assert rl.allow("a", "/workflow/runs/run-1/trace", method="GET", now=t) is True
    assert rl.allow("a", "/workflow/runs/run-2/artifacts", method="GET", now=t) is False
    assert rl.allow("a", "/health", method="GET", now=t) is True


def test_default_limiter_covers_capsule_detail_reads():
    limiter = build_default_rate_limiter()

    assert limiter.limit_for("/memory/v2/capsules/cap_private", method="GET") == 120


def test_default_limiter_tightly_limits_native_status_probe():
    limiter = build_default_rate_limiter()

    assert limiter.limit_for("/kylin/sdk/status", method="GET") == 10


def test_default_limiter_covers_workflow_statistics():
    limiter = build_default_rate_limiter()

    assert limiter.limit_for("/workflow/stats", method="GET") == 60


def test_lru_cap_bounds_memory():
    rl = RateLimiter({"/x": 1}, max_ips=10)
    t = 500.0
    for i in range(50):
        rl.allow(f"ip-{i}", "/x", now=t)
    assert len(rl._buckets) <= 10


def test_middleware_returns_429_on_burst():
    """End-to-end: a limited endpoint returns 429 once its bucket empties."""
    import os
    os.environ["WANWEI_MEMORY_DB"] = "/tmp/wanwei_ratelimit_test.db"

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.app.security.rate_limit import RateLimitMiddleware, RateLimiter

    app = FastAPI()
    limiter = RateLimiter({"/ping": 3})
    app.add_middleware(RateLimitMiddleware, limiter=limiter)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    client = TestClient(app)
    codes = [client.get("/ping").status_code for _ in range(4)]
    assert codes[:3] == [200, 200, 200], f"first 3 should pass, got {codes}"
    assert codes[3] == 429, f"4th should be rate-limited, got {codes}"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/memory/forget/preview"),
        ("post", "/memory/forget/confirm"),
        ("post", "/memory/v2/command"),
        ("post", "/memory/v2/reflection"),
        ("post", "/kylin/sdk/reindex"),
        ("post", "/workflow/cleanup"),
        ("put", "/unlisted/state-change"),
        ("patch", "/unlisted/state-change"),
        ("delete", "/unlisted/state-change"),
        ("get", "/workflow/runs/run-1/trace"),
    ],
)
def test_middleware_rate_limits_heavy_state_changing_and_protected_paths(method, path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.app.security.rate_limit import RateLimitMiddleware

    app = FastAPI()
    limiter = RateLimiter(
        {
            "/memory/forget/preview": 1,
            "/memory/forget/confirm": 1,
            "/memory/v2/command": 1,
            "/memory/v2/reflection": 1,
            "/kylin/sdk/reindex": 1,
            "/workflow/cleanup": 1,
        },
        default_write_limit_per_min=1,
        protected_get_limit_per_min=1,
        protected_get_prefixes=("/workflow/runs",),
    )
    app.add_middleware(RateLimitMiddleware, limiter=limiter)

    async def ok():
        return {"ok": True}

    app.add_api_route(path, ok, methods=[method.upper()])
    client = TestClient(app)

    request = getattr(client, method)
    assert request(path).status_code == 200
    response = request(path)
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "1"


def test_middleware_leaves_public_health_unlimited():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.app.security.rate_limit import RateLimitMiddleware

    app = FastAPI()
    limiter = RateLimiter(
        {},
        default_write_limit_per_min=1,
        protected_get_limit_per_min=1,
        protected_get_paths={"/metrics"},
    )
    app.add_middleware(RateLimitMiddleware, limiter=limiter)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    client = TestClient(app)
    codes = [client.get("/health").status_code for _ in range(5)]
    assert codes == [200, 200, 200, 200, 200]
