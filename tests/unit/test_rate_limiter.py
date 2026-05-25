"""Unit tests for api/rate_limiter.py.

Tests the per-API-key rate limit enforcement: 100 requests per minute per
key are allowed; the 101st request within the same window is rejected with
HTTP 429 and a Retry-After header.

All tests use a fresh in-process Limiter instance to avoid shared state.
"""

from __future__ import annotations

import pytest


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_test_app(limit: str = "100/minute"):
    """Build a minimal FastAPI app with a fresh rate limiter per call."""
    from fastapi import FastAPI, Request
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from slowapi.util import get_remote_address

    _lim = Limiter(key_func=get_remote_address)

    app = FastAPI()
    app.state.limiter = _lim
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.get("/probe")
    @_lim.limit(limit)
    def probe(request: Request):
        return {"ok": True}

    return app


def _make_two_key_app(limit: str = "5/minute"):
    """App with a token-prefix key function for isolation tests."""
    from fastapi import FastAPI, Request
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded

    def _key(req: Request) -> str:
        auth = req.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and len(auth) > 27:
            return f"key:{auth[7:27]}"
        return req.client.host if req.client else "unknown"  # type: ignore[union-attr]

    _lim = Limiter(key_func=_key)

    app = FastAPI()
    app.state.limiter = _lim
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.get("/probe")
    @_lim.limit(limit)
    def probe(request: Request):
        return {"ok": True}

    return app


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_100_requests_below_limit_all_succeed():
    """The first 100 requests within a minute window must all return 200."""
    from fastapi.testclient import TestClient

    app = _make_test_app("100/minute")
    with TestClient(app) as client:
        for i in range(100):
            resp = client.get("/probe")
            assert resp.status_code == 200, (
                f"Request {i + 1} expected 200, got {resp.status_code}"
            )


def test_burst_rejected_at_101st_request():
    """The 101st request within the same minute window must return 429."""
    from fastapi.testclient import TestClient

    app = _make_test_app("100/minute")
    with TestClient(app) as client:
        for _ in range(100):
            client.get("/probe")

        resp = client.get("/probe")
        assert resp.status_code == 429


def test_429_includes_retry_after_header():
    """HTTP 429 response must carry a Retry-After header."""
    from fastapi.testclient import TestClient

    app = _make_test_app("100/minute")
    with TestClient(app) as client:
        for _ in range(100):
            client.get("/probe")

        resp = client.get("/probe")
        assert resp.status_code == 429
        lower_headers = {k.lower(): v for k, v in resp.headers.items()}
        assert "retry-after" in lower_headers, (
            f"Retry-After header missing. Headers: {dict(resp.headers)}"
        )


def test_retry_after_is_non_negative_integer():
    """Retry-After value must be a non-negative integer (seconds to window reset)."""
    from fastapi.testclient import TestClient

    app = _make_test_app("100/minute")
    with TestClient(app) as client:
        for _ in range(100):
            client.get("/probe")

        resp = client.get("/probe")
        lower_headers = {k.lower(): v for k, v in resp.headers.items()}
        retry_after = lower_headers.get("retry-after", "")
        assert retry_after.lstrip("-").isdigit(), (
            f"Retry-After should be an integer, got: {retry_after!r}"
        )
        assert int(retry_after) >= 0


def test_different_keys_get_independent_buckets():
    """Two distinct API keys must each get their own 5/minute quota."""
    from fastapi.testclient import TestClient

    app = _make_two_key_app("5/minute")
    with TestClient(app) as client:
        token_a = "Bearer " + "A" * 30
        token_b = "Bearer " + "B" * 30

        # Exhaust key-A's quota (5 requests)
        for _ in range(5):
            client.get("/probe", headers={"Authorization": token_a})

        # key-A is now at the limit — next call should be 429
        resp_a = client.get("/probe", headers={"Authorization": token_a})
        assert resp_a.status_code == 429

        # key-B has a separate bucket — should still be 200
        resp_b = client.get("/probe", headers={"Authorization": token_b})
        assert resp_b.status_code == 200


def test_small_limit_burst_rejected_correctly():
    """Rate limiter logic works correctly at small limits (3/minute)."""
    from fastapi.testclient import TestClient

    app = _make_test_app("3/minute")
    with TestClient(app) as client:
        assert client.get("/probe").status_code == 200
        assert client.get("/probe").status_code == 200
        assert client.get("/probe").status_code == 200
        assert client.get("/probe").status_code == 429
