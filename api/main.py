"""TrustSignal FastAPI application.

Endpoints:
  POST /session/start            — Register a new interview session
  GET  /session/{id}/score       — Current TrustScore + breakdown
  GET  /session/{id}/report      — Full JSON report with per-turn analysis
  POST /session/{id}/end         — Close session; trigger final score
  DELETE /session/{id}           — GDPR data deletion (Sprint 10)

Authentication: JWT (HS256) per recruiter organisation. Implemented in Sprint 7.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(
    title="TrustSignal AI",
    description="Interview authenticity scoring API",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict:
    """Liveness probe used by docker-compose and load balancers."""
    return {"status": "ok", "version": "0.1.0"}


# ── Session endpoints — implemented in Sprint 7 ─────────────────────────────

@app.post("/session/start")
def session_start():  # type: ignore[return]
    """Register a new interview session and return a session_id UUID."""
    raise NotImplementedError  # Sprint 7


@app.get("/session/{session_id}/score")
def session_score(session_id: str):  # type: ignore[return]
    """Return the current TrustScore and per-signal breakdown for a live session."""
    raise NotImplementedError  # Sprint 7


@app.get("/session/{session_id}/report")
def session_report(session_id: str):  # type: ignore[return]
    """Return the full analysis report with per-turn suspicion annotations."""
    raise NotImplementedError  # Sprint 7


@app.post("/session/{session_id}/end")
def session_end(session_id: str):  # type: ignore[return]
    """Close the session and trigger final TrustScore computation."""
    raise NotImplementedError  # Sprint 7


@app.delete("/session/{session_id}")
def session_delete(session_id: str):  # type: ignore[return]
    """GDPR deletion: wipe all Delta rows and MinIO objects for this session."""
    raise NotImplementedError  # Sprint 10
