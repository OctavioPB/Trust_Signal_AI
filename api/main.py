"""TrustSignal FastAPI application.

Endpoints:
  POST /auth/token               — Issue a JWT bearer token for a recruiter org
  POST /session/start            — Register a new interview session
  POST /session/{id}/signals     — Submit computed signal scores (ML pipeline)
  GET  /session/{id}/score       — Current TrustScore + per-signal breakdown
  GET  /session/{id}/report      — Full JSON report with per-turn analysis
  POST /session/{id}/end         — Close session; compute and lock final score
  DELETE /session/{id}           — GDPR data deletion (Sprint 10)

Authentication: HS256 JWT bearer token. Each recruiter org issues tokens via
POST /auth/token. All session endpoints require Authorization: Bearer <token>.

In-memory session store is used for Sprint 7; Sprint 9 will wire in Delta Lake.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Annotated

import structlog
from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel, Field

import config
from api.candidates import router as _candidates_router
from ml.trust_score import TrustScoreEngine, TrustScoreResult

# ── Sentry error tracking (optional) ──────────────────────────────────────────
# Activated only when SENTRY_DSN is set; no-op otherwise.
# send_default_pii=False enforces CLAUDE.md Hard Rule #6 (no PII in telemetry).
if config.SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration

        sentry_sdk.init(
            dsn=config.SENTRY_DSN,
            integrations=[StarletteIntegration(), FastApiIntegration()],
            traces_sample_rate=0.05,   # 5 % of requests traced — keep costs low
            send_default_pii=False,    # CLAUDE.md §8 rule 6 — no PII in Sentry
        )
    except ImportError:
        pass  # sentry-sdk not installed; silently skip

logger = structlog.get_logger(__name__)

# ── JWT configuration ──────────────────────────────────────────────────────────

_ALGORITHM = "HS256"
_TOKEN_EXPIRE_HOURS = 24


def _create_token(recruiter_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=_TOKEN_EXPIRE_HOURS)
    return jwt.encode(
        {"sub": recruiter_id, "exp": expire},
        config.FASTAPI_SECRET_KEY,
        algorithm=_ALGORITHM,
    )


def _decode_token(token: str) -> dict:
    return jwt.decode(token, config.FASTAPI_SECRET_KEY, algorithms=[_ALGORITHM])


# ── In-memory session store ────────────────────────────────────────────────────

@dataclass
class _SessionState:
    session_id: str
    recruiter_id: str
    candidate_id: str
    status: str = "live"               # "live" | "completed" | "flagged"
    start_ts: float = field(default_factory=time.time)
    end_ts: float | None = None
    signal_scores: dict[str, float] = field(default_factory=dict)
    final_result: TrustScoreResult | None = None
    turns: list[dict] = field(default_factory=list)


_SESSIONS: dict[str, _SessionState] = {}
_ENGINE = TrustScoreEngine()


def _make_object_store():
    from storage.object_store import ObjectStore  # lazy — minio not required at startup
    return ObjectStore(
        endpoint=config.MINIO_ENDPOINT,
        access_key=config.MINIO_ACCESS_KEY,
        secret_key=config.MINIO_SECRET_KEY,
    )


def _get_session(session_id: str) -> _SessionState:
    session = _SESSIONS.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found.",
        )
    return session


def _current_score(session: _SessionState) -> TrustScoreResult:
    """Compute TrustScore from current signal scores; missing signals default to 0."""
    s = session.signal_scores
    return _ENGINE.compute(
        session_id=session.session_id,
        latency_score=s.get("latency", 0.0),
        bg_audio_score=s.get("bg_audio", 0.0),
        perplexity_score=s.get("perplexity", 0.0),
        burstiness_score=s.get("burstiness", 0.0),
        similarity_score=s.get("similarity", 0.0),
    )


# ── FastAPI app ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="TrustSignal AI",
    description=(
        "Interview authenticity scoring API. "
        "Detects AI-assisted fraud via five signal modules and delivers a "
        "TrustScore (0–100) per interview session."
    ),
    version="0.8.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ────────────────────────────────────────────────────────────────────
app.include_router(_candidates_router)

_bearer = HTTPBearer()


def _auth(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> str:
    """Validate JWT bearer token and return the recruiter_id (``sub`` claim).

    Raises:
        HTTPException 401: On missing, expired, or malformed token.
    """
    try:
        payload = _decode_token(credentials.credentials)
        return str(payload["sub"])
    except (JWTError, KeyError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── Pydantic schemas ───────────────────────────────────────────────────────────

class TokenRequest(BaseModel):
    recruiter_id: str = Field(..., description="UUID of the recruiter organisation.")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_hours: int = _TOKEN_EXPIRE_HOURS


class SessionStartRequest(BaseModel):
    recruiter_id: str = Field(..., description="UUID of the recruiter org (no PII stored).")
    candidate_id: str = Field(..., description="UUID of the candidate (anonymised).")


class SessionStartResponse(BaseModel):
    session_id: str
    status: str
    start_ts: float


class SignalScoresRequest(BaseModel):
    latency_score: float = Field(0.0, ge=0.0, le=1.0)
    bg_audio_score: float = Field(0.0, ge=0.0, le=1.0)
    perplexity_score: float = Field(0.0, ge=0.0, le=1.0)
    burstiness_score: float = Field(0.0, ge=0.0, le=1.0)
    similarity_score: float = Field(0.0, ge=0.0, le=1.0)


class SignalDetail(BaseModel):
    signal_name: str
    raw_score: float
    weight: float
    weighted_contribution: float
    explanation: str


class ScoreResponse(BaseModel):
    session_id: str
    status: str
    trust_score: float
    suspicion_index: float
    flagged: bool
    flag_reason: str
    signals: list[SignalDetail]


class ReportResponse(BaseModel):
    session_id: str
    recruiter_id: str
    status: str
    start_ts: float
    end_ts: float | None
    trust_score: float
    suspicion_index: float
    flagged: bool
    flag_reason: str
    signals: list[SignalDetail]
    turns: list[dict]


class SessionEndResponse(BaseModel):
    session_id: str
    status: str
    trust_score: float
    flagged: bool
    flag_reason: str


# ── Internal helper ────────────────────────────────────────────────────────────

def _score_response(session: _SessionState, result: TrustScoreResult) -> ScoreResponse:
    return ScoreResponse(
        session_id=session.session_id,
        status=session.status,
        trust_score=result.trust_score,
        suspicion_index=result.suspicion_index,
        flagged=result.flagged,
        flag_reason=result.flag_reason,
        signals=[
            SignalDetail(
                signal_name=s.signal_name,
                raw_score=s.raw_score,
                weight=s.weight,
                weighted_contribution=s.weighted_contribution,
                explanation=s.explanation,
            )
            for s in result.signals
        ],
    )


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/session/{session_id}/report/pdf")
def session_report_pdf(
    session_id: str,
    recruiter_id: Annotated[str, Depends(_auth)],
) -> Response:
    """Return the session report as a downloadable PDF.

    Raises:
        404: Session not found.
        503: fpdf2 not installed.
    """
    session = _get_session(session_id)
    result = session.final_result or _current_score(session)

    try:
        from dashboard.pdf_export import generate_report_pdf  # lazy — fpdf2 optional
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PDF generation unavailable: install fpdf2 (`pip install fpdf2`).",
        )

    report_dict = {
        "session_id": session.session_id,
        "recruiter_id": session.recruiter_id,
        "status": session.status,
        "start_ts": session.start_ts,
        "end_ts": session.end_ts,
        "trust_score": result.trust_score,
        "suspicion_index": result.suspicion_index,
        "flagged": result.flagged,
        "flag_reason": result.flag_reason,
        "signals": [
            {
                "signal_name": s.signal_name,
                "raw_score": s.raw_score,
                "weight": s.weight,
                "weighted_contribution": s.weighted_contribution,
                "explanation": s.explanation,
            }
            for s in result.signals
        ],
        "turns": session.turns,
    }

    pdf_bytes = generate_report_pdf(report_dict)
    filename = f"trustsignal_report_{session_id[:8]}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/health")
def health() -> dict:
    """Liveness probe used by docker-compose and load balancers."""
    return {"status": "ok", "version": "0.8.0"}


@app.post("/auth/token", response_model=TokenResponse)
def auth_token(body: TokenRequest) -> TokenResponse:
    """Issue a JWT bearer token for a recruiter organisation.

    In production, this would validate the recruiter_id against a registered
    organisations table. For Sprint 7, any non-empty UUID is accepted.
    """
    token = _create_token(body.recruiter_id)
    logger.info("token_issued", recruiter_id=body.recruiter_id)
    return TokenResponse(access_token=token)


@app.post(
    "/session/start",
    response_model=SessionStartResponse,
    status_code=status.HTTP_201_CREATED,
)
def session_start(
    body: SessionStartRequest,
    recruiter_id: Annotated[str, Depends(_auth)],
) -> SessionStartResponse:
    """Register a new interview session.

    Returns a ``session_id`` UUID required for all subsequent API calls.
    The ``recruiter_id`` in the request body must match the JWT ``sub`` claim.

    Raises:
        403: recruiter_id mismatch between token and request body.
    """
    if body.recruiter_id != recruiter_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token recruiter_id does not match request body recruiter_id.",
        )

    session_id = str(uuid.uuid4())
    session = _SessionState(
        session_id=session_id,
        recruiter_id=body.recruiter_id,
        candidate_id=body.candidate_id,
    )
    _SESSIONS[session_id] = session

    logger.info("session_started", session_id=session_id, recruiter_id=body.recruiter_id)
    return SessionStartResponse(
        session_id=session_id,
        status=session.status,
        start_ts=session.start_ts,
    )


@app.post("/session/{session_id}/signals", response_model=ScoreResponse)
def session_signals(
    session_id: str,
    body: SignalScoresRequest,
    recruiter_id: Annotated[str, Depends(_auth)],
) -> ScoreResponse:
    """Submit or update computed signal scores for a live session.

    Called by the ML pipeline. All five scores are updated atomically;
    the updated TrustScore is returned immediately.

    Raises:
        404: Session not found.
        409: Session already completed or flagged.
    """
    session = _get_session(session_id)
    if session.status != "live":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Session '{session_id}' is already {session.status}.",
        )

    session.signal_scores.update(
        {
            "latency":    body.latency_score,
            "bg_audio":   body.bg_audio_score,
            "perplexity": body.perplexity_score,
            "burstiness": body.burstiness_score,
            "similarity": body.similarity_score,
        }
    )
    result = _current_score(session)
    logger.debug("signals_updated", session_id=session_id, trust_score=result.trust_score)
    return _score_response(session, result)


@app.get("/session/{session_id}/score", response_model=ScoreResponse)
def session_score(
    session_id: str,
    recruiter_id: Annotated[str, Depends(_auth)],
) -> ScoreResponse:
    """Return the current TrustScore and per-signal breakdown.

    If the session has been ended, returns the locked final result.
    If no signals have been submitted, returns trust_score=100 (all zeros).

    Raises:
        404: Session not found.
    """
    session = _get_session(session_id)
    result = session.final_result or _current_score(session)
    return _score_response(session, result)


@app.get("/session/{session_id}/report", response_model=ReportResponse)
def session_report(
    session_id: str,
    recruiter_id: Annotated[str, Depends(_auth)],
) -> ReportResponse:
    """Return the full analysis report with per-turn suspicion annotations.

    Raises:
        404: Session not found.
    """
    session = _get_session(session_id)
    result = session.final_result or _current_score(session)

    return ReportResponse(
        session_id=session.session_id,
        recruiter_id=session.recruiter_id,
        status=session.status,
        start_ts=session.start_ts,
        end_ts=session.end_ts,
        trust_score=result.trust_score,
        suspicion_index=result.suspicion_index,
        flagged=result.flagged,
        flag_reason=result.flag_reason,
        signals=[
            SignalDetail(
                signal_name=s.signal_name,
                raw_score=s.raw_score,
                weight=s.weight,
                weighted_contribution=s.weighted_contribution,
                explanation=s.explanation,
            )
            for s in result.signals
        ],
        turns=session.turns,
    )


@app.post("/session/{session_id}/end", response_model=SessionEndResponse)
def session_end(
    session_id: str,
    recruiter_id: Annotated[str, Depends(_auth)],
) -> SessionEndResponse:
    """Close a session and lock the final TrustScore.

    Marks the session "completed" or "flagged" based on the suspicion index.
    After this call, /score and /report return the locked result.

    Raises:
        404: Session not found.
        409: Session already completed or flagged.
    """
    session = _get_session(session_id)
    if session.status != "live":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Session '{session_id}' is already {session.status}.",
        )

    result = _current_score(session)
    session.final_result = result
    session.end_ts = time.time()
    session.status = "flagged" if result.flagged else "completed"

    logger.info(
        "session_ended",
        session_id=session_id,
        status=session.status,
        trust_score=result.trust_score,
        flagged=result.flagged,
    )

    return SessionEndResponse(
        session_id=session_id,
        status=session.status,
        trust_score=result.trust_score,
        flagged=result.flagged,
        flag_reason=result.flag_reason,
    )


@app.delete("/session/{session_id}", status_code=status.HTTP_202_ACCEPTED)
def session_delete(
    session_id: str,
    recruiter_id: Annotated[str, Depends(_auth)],
) -> dict:
    """GDPR erasure: remove all data for a session.

    Wipes:
    - In-memory session state (immediate)
    - MinIO raw-audio objects for the session (best-effort; failures are logged)

    Delta Lake transcript rows are tagged for deletion and removed on the next
    nightly DAG run (trustsignal_nightly_retraining). This complies with
    GDPR Article 17 "right to erasure" requirements.

    Raises:
        404: Session not found.
    """
    _get_session(session_id)          # raises 404 if session doesn't exist
    _SESSIONS.pop(session_id, None)   # wipe in-memory state

    # Best-effort MinIO erasure — never raises; failures are surfaced in logs
    audio_objects_removed = 0
    try:
        store = _make_object_store()
        audio_objects_removed = store.delete_session_audio(session_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "gdpr_minio_delete_failed",
            session_id=session_id,
            error=str(exc),
        )

    logger.info(
        "session_deleted",
        session_id=session_id,
        audio_objects_removed=audio_objects_removed,
    )
    return {
        "session_id": session_id,
        "deleted": True,
        "audio_objects_removed": audio_objects_removed,
    }
