"""HTTP client for the TrustSignal FastAPI backend.

All network calls are synchronous (Streamlit runs in a single thread).
Raises APIError on any non-2xx response so callers can display the detail
message directly in the dashboard.
"""

from __future__ import annotations

from typing import Any

import requests

DEFAULT_BASE_URL = "http://localhost:8000"


class APIError(Exception):
    """Raised when the TrustSignal API returns a non-2xx status."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code}: {detail}")


def _raise_for_status(resp: requests.Response) -> None:
    if not resp.ok:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        raise APIError(resp.status_code, str(detail))


def health_check(base_url: str) -> bool:
    """Return True if the API /health endpoint is reachable and returns ok."""
    try:
        resp = requests.get(f"{base_url}/health", timeout=5)
        return resp.ok
    except Exception:
        return False


def get_token(base_url: str, recruiter_id: str) -> str:
    """Issue a JWT bearer token for the given recruiter_id.

    Args:
        base_url: API root URL (e.g. "http://localhost:8000").
        recruiter_id: UUID of the recruiter organisation.

    Returns:
        JWT access token string.

    Raises:
        APIError: On non-2xx response.
    """
    resp = requests.post(
        f"{base_url}/auth/token",
        json={"recruiter_id": recruiter_id},
        timeout=10,
    )
    _raise_for_status(resp)
    return str(resp.json()["access_token"])


def get_score(base_url: str, token: str, session_id: str) -> dict[str, Any]:
    """Fetch the current TrustScore and per-signal breakdown for a session.

    Args:
        base_url: API root URL.
        token: JWT bearer token.
        session_id: UUID of the interview session.

    Returns:
        Parsed JSON dict matching the ScoreResponse schema.

    Raises:
        APIError: On non-2xx response (including 404 if session missing).
    """
    resp = requests.get(
        f"{base_url}/session/{session_id}/score",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    _raise_for_status(resp)
    return resp.json()  # type: ignore[return-value]


def get_report(base_url: str, token: str, session_id: str) -> dict[str, Any]:
    """Fetch the full analysis report including per-turn data.

    Args:
        base_url: API root URL.
        token: JWT bearer token.
        session_id: UUID of the interview session.

    Returns:
        Parsed JSON dict matching the ReportResponse schema.

    Raises:
        APIError: On non-2xx response.
    """
    resp = requests.get(
        f"{base_url}/session/{session_id}/report",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    _raise_for_status(resp)
    return resp.json()  # type: ignore[return-value]


def end_session(base_url: str, token: str, session_id: str) -> dict[str, Any]:
    """Close a session and lock the final TrustScore.

    Args:
        base_url: API root URL.
        token: JWT bearer token.
        session_id: UUID of the interview session.

    Returns:
        Parsed JSON dict matching the SessionEndResponse schema.

    Raises:
        APIError: On non-2xx response (including 409 if already ended).
    """
    resp = requests.post(
        f"{base_url}/session/{session_id}/end",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    _raise_for_status(resp)
    return resp.json()  # type: ignore[return-value]
