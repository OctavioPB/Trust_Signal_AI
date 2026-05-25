"""Per-API-key rate limiter — Sprint 20.

Uses slowapi (a thin Starlette wrapper around the `limits` library) with the
default in-memory storage backend.

Limit: ``config.RATE_LIMIT_PER_MINUTE`` requests per minute per API key.
Key: first 20 characters of the JWT Bearer token; falls back to remote IP when
no token is present. Using a prefix (not the full token) avoids logging
sensitive material while still giving each credential its own bucket.

Wire-up (api/main.py):
    from api.rate_limiter import limiter, rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

Per-endpoint usage:
    from api.rate_limiter import limiter, RATE_LIMIT
    from fastapi import Request

    @router.get("/candidates")
    @limiter.limit(RATE_LIMIT)
    def list_candidates(request: Request, ...):
        ...
"""

from __future__ import annotations

from fastapi import Request
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

import config


def _get_api_key(request: Request) -> str:
    """Rate limit key: token prefix or remote IP."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ") and len(auth) > 27:
        return f"key:{auth[7:27]}"
    return get_remote_address(request)


limiter = Limiter(key_func=_get_api_key)
rate_limit_exceeded_handler = _rate_limit_exceeded_handler
RATE_LIMIT: str = f"{config.RATE_LIMIT_PER_MINUTE}/minute"
