"""Shared JWT bearer-token authentication for all FastAPI routers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

import config

_ALGORITHM = "HS256"
_bearer = HTTPBearer()


def _auth(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> str:
    """Validate JWT bearer token; return recruiter_id (``sub`` claim)."""
    try:
        payload = jwt.decode(
            credentials.credentials,
            config.FASTAPI_SECRET_KEY,
            algorithms=[_ALGORITHM],
        )
        return str(payload["sub"])
    except (JWTError, KeyError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
