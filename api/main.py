"""TrustSignal FastAPI application.

Endpoints:
  POST /auth/token               — Issue a JWT bearer token for a recruiter org
  POST /session/start            — Register a new interview session
  POST /session/{id}/signals     — Submit computed signal scores (ML pipeline)
  GET  /session/{id}/score       — Current TrustScore + per-signal breakdown
  GET  /session/{id}/report      — Full JSON report with per-turn analysis
  POST /session/{id}/end         — Close session; compute and lock final score
  DELETE /session/{id}           — GDPR data deletion (Sprint 10)
  POST /session/{id}/review      — Human verdict on a scored session (training label)
  GET  /reviews/pending          — Caller's flagged sessions still awaiting review
  POST /session/{id}/turn        — Per-turn text score → anytime-valid early flag

Authentication: HS256 JWT bearer token. Each recruiter org issues tokens via
POST /auth/token. All session endpoints require Authorization: Bearer <token>.

In-memory session store is used for Sprint 7; Sprint 9 will wire in Delta Lake.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

import structlog
from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from jose import jwt
from pydantic import BaseModel, Field
from slowapi.errors import RateLimitExceeded

import config
from api.auth import _ALGORITHM, _auth
from api.candidates import router as _candidates_router
from api.rate_limiter import limiter, rate_limit_exceeded_handler
from ml.sequential import SequentialMonitor, SequentialState
from ml.trust_score import TrustScoreResult, load_engine_from_config

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

_TOKEN_EXPIRE_HOURS = 24


def _create_token(recruiter_id: str) -> str:
    expire = datetime.now(UTC) + timedelta(hours=_TOKEN_EXPIRE_HOURS)
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
    review_verdict: str | None = None  # "confirmed" | "cleared" once a human reviews it
    sequential: SequentialState = field(default_factory=SequentialState)


_SESSIONS: dict[str, _SessionState] = {}
_ENGINE = load_engine_from_config()


def _load_sequential_monitor() -> SequentialMonitor | None:
    from pathlib import Path

    path = getattr(config, "SEQUENTIAL_MODEL_PATH", "") or ""
    return SequentialMonitor.load(Path(path)) if path else None


_MONITOR: SequentialMonitor | None = _load_sequential_monitor()


def _make_object_store():
    from storage.object_store import ObjectStore  # lazy — minio not required at startup
    return ObjectStore(
        endpoint=config.MINIO_ENDPOINT,
        access_key=config.MINIO_ACCESS_KEY,
        secret_key=config.MINIO_SECRET_KEY,
    )


def _make_review_store():
    from storage.review_store import ReviewStore  # lazy — duckdb only needed on review
    return ReviewStore(config.DELTA_LAKE_PATH)


def _get_session(session_id: str) -> _SessionState:
    session = _SESSIONS.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found.",
        )
    return session


def _current_score(session: _SessionState) -> TrustScoreResult:
    """Compute TrustScore from the signal scores received so far."""
    s = session.signal_scores
    return _ENGINE.compute(
        session_id=session.session_id,
        # Absent signals are passed as None: the legacy engine counts them as 0,
        # the calibrated engine models them as missing.
        latency_score=s.get("latency"),
        bg_audio_score=s.get("bg_audio"),
        perplexity_score=s.get("perplexity"),
        burstiness_score=s.get("burstiness"),
        similarity_score=s.get("similarity"),
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

# ── Rate limiter ───────────────────────────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)  # type: ignore[arg-type]

# ── Prometheus metrics ─────────────────────────────────────────────────────────
from api.metrics import instrument_app  # noqa: E402

instrument_app(app)

# ── Routers ────────────────────────────────────────────────────────────────────
app.include_router(_candidates_router)

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
    """Omit (or send null for) a signal that could not be computed: it is then
    missing, not 0. The legacy engine still counts missing as 0; the calibrated
    engine models it explicitly."""

    latency_score: float | None = Field(None, ge=0.0, le=1.0)
    bg_audio_score: float | None = Field(None, ge=0.0, le=1.0)
    perplexity_score: float | None = Field(None, ge=0.0, le=1.0)
    burstiness_score: float | None = Field(None, ge=0.0, le=1.0)
    similarity_score: float | None = Field(None, ge=0.0, le=1.0)


class TurnScoreRequest(BaseModel):
    text_score: float = Field(
        ..., ge=0.0, le=1.0,
        description="Text-detector suspicion for one candidate turn (TEXT_DETECTOR).",
    )


class SequentialSummary(BaseModel):
    turns: int
    evidence: float
    threshold: float | None
    early_flag: bool
    flagged_at_turn: int | None
    alpha: float


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
    sequential: SequentialSummary | None = None


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
    review_verdict: str | None = None


class ReviewRequest(BaseModel):
    verdict: Literal["confirmed", "cleared"] = Field(
        ...,
        description=(
            "'confirmed' = a human confirmed AI assistance; "
            "'cleared' = the flag was a false positive."
        ),
    )


class ReviewResponse(BaseModel):
    session_id: str
    verdict: str
    reviewed_at: float


class PendingReview(BaseModel):
    session_id: str
    trust_score: float
    flag_reason: str
    end_ts: float | None


class SessionEndResponse(BaseModel):
    session_id: str
    status: str
    trust_score: float
    flagged: bool
    flag_reason: str


# ── Internal helper ────────────────────────────────────────────────────────────

def _sequential_summary(session: _SessionState) -> SequentialSummary | None:
    if _MONITOR is None:
        return None
    st = session.sequential
    return SequentialSummary(
        turns=st.turns,
        evidence=round(st.evidence, 4),
        threshold=None if _MONITOR.threshold == float("inf") else round(_MONITOR.threshold, 4),
        early_flag=st.flagged,
        flagged_at_turn=st.flagged_at_turn,
        alpha=_MONITOR.alpha,
    )


def _with_sequential(session: _SessionState, result: TrustScoreResult) -> TrustScoreResult:
    """Merge an early sequential flag into a score result (a flag is never dropped)."""
    if _MONITOR is None or not session.sequential.flagged:
        return result
    reason = _MONITOR.flag_reason(session.sequential)
    if result.flagged:
        return replace(result, flag_reason=f"{result.flag_reason}\n{reason}")
    return replace(result, flagged=True, flag_reason=reason)


def _score_response(session: _SessionState, result: TrustScoreResult) -> ScoreResponse:
    result = _with_sequential(session, result)
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
        sequential=_sequential_summary(session),
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
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PDF generation unavailable: install fpdf2 (`pip install fpdf2`).",
        ) from exc

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

    # Only fields the caller sent are updated; an explicit null marks a signal missing.
    sent = body.model_dump(exclude_unset=True)
    session.signal_scores.update(
        {key.removesuffix("_score"): value for key, value in sent.items()}
    )
    result = _current_score(session)
    logger.debug("signals_updated", session_id=session_id, trust_score=result.trust_score)
    return _score_response(session, result)


@app.post("/session/{session_id}/turn", response_model=SequentialSummary)
def session_turn(
    session_id: str,
    body: TurnScoreRequest,
    recruiter_id: Annotated[str, Depends(_auth)],
) -> SequentialSummary:
    """Add one candidate turn's text score to the session's running evidence.

    The early flag uses an anytime-valid rule (ml/sequential.py): however many
    turns are submitted and however often the score is polled, a human session
    is flagged with probability at most alpha.

    Raises:
        404: Session not found.
        409: Session is not live.
        503: Sequential monitoring is not configured (SEQUENTIAL_MODEL_PATH).
    """
    session = _get_session(session_id)
    if session.status != "live":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Session '{session_id}' is already {session.status}.",
        )
    if _MONITOR is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sequential monitoring is not configured (set SEQUENTIAL_MODEL_PATH).",
        )
    was_flagged = session.sequential.flagged
    _MONITOR.update(session.sequential, body.text_score)
    if session.sequential.flagged and not was_flagged:
        logger.info(
            "sequential_early_flag",
            session_id=session_id,
            turn=session.sequential.flagged_at_turn,
        )
    summary = _sequential_summary(session)
    assert summary is not None
    return summary


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
        review_verdict=session.review_verdict,
    )


@app.post("/session/{session_id}/review", response_model=ReviewResponse)
def session_review(
    session_id: str,
    body: ReviewRequest,
    recruiter_id: Annotated[str, Depends(_auth)],
) -> ReviewResponse:
    """Record a human verdict on an ended session.

    Reviews are the ONLY training labels the nightly DAG uses: the system never
    learns from its own flags. A later review supersedes an earlier one; both are
    kept in the append-only review log for audit.

    Raises:
        404: Session not found.
        409: Session is still live (there is no final score to review yet).
        503: The review could not be persisted.
    """
    session = _get_session(session_id)
    if session.status == "live":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="End the session before reviewing it.",
        )

    try:
        record = _make_review_store().append(session_id, body.verdict, recruiter_id)
    except Exception as exc:
        logger.error("session_review_failed", session_id=session_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Review storage temporarily unavailable; the verdict was not saved.",
        ) from exc

    session.review_verdict = record.verdict
    return ReviewResponse(
        session_id=session_id,
        verdict=record.verdict,
        reviewed_at=record.reviewed_at,
    )


@app.get("/reviews/pending", response_model=list[PendingReview])
def reviews_pending(
    recruiter_id: Annotated[str, Depends(_auth)],
) -> list[PendingReview]:
    """The caller's flagged sessions that no human has reviewed yet, oldest first."""
    pending = [
        s for s in _SESSIONS.values()
        if s.recruiter_id == recruiter_id
        and s.status == "flagged"
        and s.review_verdict is None
        and s.final_result is not None
    ]
    pending.sort(key=lambda s: s.end_ts or 0.0)
    return [
        PendingReview(
            session_id=s.session_id,
            trust_score=s.final_result.trust_score,  # type: ignore[union-attr]
            flag_reason=s.final_result.flag_reason,  # type: ignore[union-attr]
            end_ts=s.end_ts,
        )
        for s in pending
    ]


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

    result = _with_sequential(session, _current_score(session))
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
