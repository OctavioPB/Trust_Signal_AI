"""Candidate pre-screening API endpoints.

Routes (prefix /candidates):
  POST /candidates                    — Create a new candidate profile
  POST /candidates/{id}/resume        — Upload a resume (PDF / DOCX / TXT)
  POST /candidates/{id}/repos         — Link a public GitHub repository URL

Authentication: HS256 JWT bearer token issued by POST /auth/token.

Storage strategy:
  - In-memory dict (_CANDIDATES) for low-latency hot reads — same pattern as
    the session API in api/main.py.
  - MinIO for file persistence (resumes bucket, 90-day lifecycle).
  - Kafka event published to candidate-resume-stream so the Sprint 15 consumer
    can trigger text extraction and scoring asynchronously.
  - CandidateStore (DeltaLake) is the durable batch-path store; Airflow DAGs
    read from Delta — not from this in-memory dict.

Note: _auth is duplicated here from api/main.py. It will be extracted to
api/auth.py in Sprint 20 to eliminate duplication.
"""

from __future__ import annotations

import re
import time
import uuid
from datetime import datetime, timezone
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel, Field

import config
from api.auth import _auth, _bearer
from api.rate_limiter import RATE_LIMIT, limiter

logger = structlog.get_logger(__name__)

# ── File validation ────────────────────────────────────────────────────────────

_ALLOWED_MIMES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
    }
)

_MIME_TO_EXT: dict[str, str] = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/plain": "txt",
}

_GITHUB_REPO_RE = re.compile(
    r"^https://github\.com/[\w.\-]+/[\w.\-]+(\.git)?/?$"
)

_RESUME_MAX_BYTES: int = config.RESUME_MAX_MB * 1024 * 1024


# ── In-memory candidate store ──────────────────────────────────────────────────

_CANDIDATES: dict[str, dict] = {}


def _get_candidate(candidate_id: str) -> dict:
    c = _CANDIDATES.get(candidate_id)
    if c is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Candidate '{candidate_id}' not found.",
        )
    return c


# ── Lazy service factories ─────────────────────────────────────────────────────

def _make_object_store():
    from storage.object_store import ObjectStore
    return ObjectStore(
        endpoint=config.MINIO_ENDPOINT,
        access_key=config.MINIO_ACCESS_KEY,
        secret_key=config.MINIO_SECRET_KEY,
    )


def _make_resume_producer():
    from ingestion.resume_producer import ResumeProducer
    return ResumeProducer(
        bootstrap_servers=config.KAFKA_BOOTSTRAP_SERVERS,
        topic=config.KAFKA_TOPIC_RESUME,
    )


# ── Pydantic schemas ───────────────────────────────────────────────────────────

class CandidateCreateResponse(BaseModel):
    candidate_uuid: str
    status: str
    created_at: float


class ResumeUploadResponse(BaseModel):
    candidate_uuid: str
    minio_path: str
    status: str


class RepoLinkRequest(BaseModel):
    repo_url: str = Field(..., description="Public GitHub repository URL.")


class RepoLinkResponse(BaseModel):
    candidate_uuid: str
    repo_urls: list[str]


# ── Sprint 20: read + trigger schemas ─────────────────────────────────────────

class CandidateListItem(BaseModel):
    """Lightweight summary for paginated list — UUID + scores only; no PII."""
    candidate_uuid: str
    status: str
    resume_ai_score: float | None
    repo_ai_score: float | None
    prescreening_score: float | None
    flagged: bool
    scored_at: float | None
    created_at: float


class CandidatesListResponse(BaseModel):
    candidates: list[CandidateListItem]
    total: int
    limit: int
    offset: int


class CandidateDetailResponse(BaseModel):
    """Full candidate detail including per-signal breakdown — UUID only; no PII."""
    candidate_uuid: str
    status: str
    resume_ai_score: float | None
    repo_ai_score: float | None
    prescreening_score: float | None
    interview_trust_score: float | None
    flagged: bool
    severity: str
    flag_reason: str
    signals: list[dict]
    repo_urls: list[str]
    scored_at: float | None
    created_at: float


class PreScreeningReport(BaseModel):
    """Structured pre-screening report with all flags and explanations."""
    candidate_uuid: str
    prescreening_score: float | None
    flagged: bool
    severity: str
    flag_reason: str
    flags: list[dict]   # [{signal, explanation, score}]
    generated_at: float


class TriggerResponse(BaseModel):
    candidate_uuid: str
    status: str                 # "queued" | "no_data"
    prescreening_score: float | None
    flagged: bool


# ── Router ─────────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/candidates", tags=["Candidates"])


@router.post(
    "",
    response_model=CandidateCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_candidate(
    recruiter_id: Annotated[str, Depends(_auth)],
) -> CandidateCreateResponse:
    """Create a new candidate profile.

    Returns a ``candidate_uuid`` (UUID only — no PII stored or returned).
    Pass this UUID to all subsequent pre-screening endpoints.
    """
    candidate_uuid = str(uuid.uuid4())
    created_at = time.time()

    _CANDIDATES[candidate_uuid] = {
        "candidate_uuid":       candidate_uuid,
        "recruiter_id":         recruiter_id,
        "status":               "pending",
        "created_at":           created_at,
        "resume_path":          None,
        "repo_urls":            [],
        # Scoring fields — populated by the Airflow DAG after scoring runs
        "resume_ai_score":      None,
        "repo_ai_score":        None,
        "prescreening_score":   None,
        "interview_trust_score": None,
        "flagged":              False,
        "severity":             "low",
        "flag_reason":          "",
        "signals":              [],
        "scored_at":            None,
    }

    logger.info(
        "candidate_created",
        candidate_uuid=candidate_uuid,  # UUID — no PII
        recruiter_id=recruiter_id,
    )
    return CandidateCreateResponse(
        candidate_uuid=candidate_uuid,
        status="pending",
        created_at=created_at,
    )


@router.post(
    "/{candidate_id}/resume",
    response_model=ResumeUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_resume(
    candidate_id: str,
    recruiter_id: Annotated[str, Depends(_auth)],
    file: UploadFile = File(...),
) -> ResumeUploadResponse:
    """Upload a candidate resume document (PDF, DOCX, or plain text).

    The file is stored in MinIO (resumes/{uuid}/{timestamp}.{ext}) and a
    resume-uploaded event is published to candidate-resume-stream. Text
    extraction and AI scoring run asynchronously in Sprint 15.

    Raises:
        404: Candidate not found.
        413: File exceeds RESUME_MAX_MB.
        415: Unsupported MIME type.
        502: MinIO storage temporarily unavailable.
    """
    _get_candidate(candidate_id)

    content_type = (file.content_type or "").split(";")[0].strip()
    if content_type not in _ALLOWED_MIMES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"Unsupported file type '{content_type}'. "
                "Accepted: application/pdf, "
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document, "
                "text/plain."
            ),
        )
    file_ext = _MIME_TO_EXT[content_type]

    data = await file.read()
    if len(data) > _RESUME_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"File size {len(data) / 1_048_576:.1f} MB exceeds the "
                f"{config.RESUME_MAX_MB} MB limit."
            ),
        )

    timestamp_iso = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    try:
        store = _make_object_store()
        minio_path = store.upload_resume(
            candidate_uuid=candidate_id,
            timestamp_iso=timestamp_iso,
            file_ext=file_ext,
            data=data,
        )
    except Exception as exc:
        logger.error(
            "resume_minio_upload_failed",
            candidate_uuid=candidate_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Resume storage temporarily unavailable.",
        )

    # Publish Kafka event — non-fatal; MinIO upload already succeeded.
    # Sprint 15 DAG can recover via MinIO scan if the event is lost.
    try:
        producer = _make_resume_producer()
        producer.publish_uploaded(
            candidate_uuid=candidate_id,
            minio_path=minio_path,
            file_ext=file_ext,
            uploaded_at=timestamp_iso,
        )
        producer.flush()
    except Exception as exc:
        logger.warning(
            "resume_kafka_event_failed",
            candidate_uuid=candidate_id,
            error=str(exc),
        )

    _CANDIDATES[candidate_id]["resume_path"] = minio_path

    logger.info(
        "resume_uploaded",
        candidate_uuid=candidate_id,  # UUID — no PII
        file_ext=file_ext,
        size_bytes=len(data),
    )
    return ResumeUploadResponse(
        candidate_uuid=candidate_id,
        minio_path=minio_path,
        status=_CANDIDATES[candidate_id]["status"],
    )


@router.post(
    "/{candidate_id}/repos",
    response_model=RepoLinkResponse,
)
def link_repo(
    candidate_id: str,
    body: RepoLinkRequest,
    recruiter_id: Annotated[str, Depends(_auth)],
) -> RepoLinkResponse:
    """Link a public GitHub repository to a candidate profile.

    The URL is validated against the GitHub domain and stored for crawling by
    the Sprint 16 ingestion pipeline.

    Raises:
        404: Candidate not found.
        422: URL is not a valid GitHub repository URL.
    """
    _get_candidate(candidate_id)

    if not _GITHUB_REPO_RE.match(body.repo_url):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "repo_url must be a valid public GitHub repository URL: "
                "https://github.com/{owner}/{repo}"
            ),
        )

    candidate = _CANDIDATES[candidate_id]
    if body.repo_url not in candidate["repo_urls"]:
        candidate["repo_urls"].append(body.repo_url)

    logger.info(
        "repo_linked",
        candidate_uuid=candidate_id,  # UUID — no PII
        repo_count=len(candidate["repo_urls"]),
    )
    return RepoLinkResponse(
        candidate_uuid=candidate_id,
        repo_urls=candidate["repo_urls"],
    )


# ── Sprint 20: read + trigger endpoints ───────────────────────────────────────

@router.get(
    "",
    response_model=CandidatesListResponse,
)
@limiter.limit(RATE_LIMIT)
def list_candidates(
    request: Request,
    recruiter_id: Annotated[str, Depends(_auth)],
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> CandidatesListResponse:
    """Paginated list of candidates. Returns UUID + status + scores only; no PII.

    Args:
        limit:  Page size (1–200, default 50).
        offset: Zero-based page offset.
    """
    all_candidates = [
        c for c in _CANDIDATES.values()
        if c["recruiter_id"] == recruiter_id
    ]
    total   = len(all_candidates)
    page    = all_candidates[offset: offset + limit]

    items = [
        CandidateListItem(
            candidate_uuid=c["candidate_uuid"],
            status=c["status"],
            resume_ai_score=c["resume_ai_score"],
            repo_ai_score=c["repo_ai_score"],
            prescreening_score=c["prescreening_score"],
            flagged=c["flagged"],
            scored_at=c["scored_at"],
            created_at=c["created_at"],
        )
        for c in page
    ]
    return CandidatesListResponse(
        candidates=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{candidate_id}",
    response_model=CandidateDetailResponse,
)
@limiter.limit(RATE_LIMIT)
def get_candidate(
    candidate_id: str,
    request: Request,
    recruiter_id: Annotated[str, Depends(_auth)],
) -> CandidateDetailResponse:
    """Full candidate detail including signal breakdown. UUID only; no PII."""
    c = _get_candidate(candidate_id)
    return CandidateDetailResponse(
        candidate_uuid=c["candidate_uuid"],
        status=c["status"],
        resume_ai_score=c["resume_ai_score"],
        repo_ai_score=c["repo_ai_score"],
        prescreening_score=c["prescreening_score"],
        interview_trust_score=c["interview_trust_score"],
        flagged=c["flagged"],
        severity=c["severity"],
        flag_reason=c["flag_reason"],
        signals=c["signals"],
        repo_urls=c["repo_urls"],
        scored_at=c["scored_at"],
        created_at=c["created_at"],
    )


@router.get(
    "/{candidate_id}/report",
    response_model=PreScreeningReport,
)
@limiter.limit(RATE_LIMIT)
def get_prescreening_report(
    candidate_id: str,
    request: Request,
    recruiter_id: Annotated[str, Depends(_auth)],
) -> PreScreeningReport:
    """Pre-screening report with all flags and explanations.

    Raises:
        404: Candidate not found.
        422: Pre-screening has not been run yet (prescreening_score is None).
    """
    c = _get_candidate(candidate_id)

    if c["prescreening_score"] is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Pre-screening has not been run for this candidate yet.",
        )

    flags = [
        {
            "signal":      s.get("signal_name", ""),
            "explanation": s.get("explanation", ""),
            "score":       s.get("raw_suspicion", 0.0),
        }
        for s in c["signals"]
        if s.get("raw_suspicion", 0.0) >= 0.5
    ]

    return PreScreeningReport(
        candidate_uuid=c["candidate_uuid"],
        prescreening_score=c["prescreening_score"],
        flagged=c["flagged"],
        severity=c["severity"],
        flag_reason=c["flag_reason"],
        flags=flags,
        generated_at=time.time(),
    )


@router.post(
    "/{candidate_id}/trigger",
    response_model=TriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def trigger_prescreening(
    candidate_id: str,
    recruiter_id: Annotated[str, Depends(_auth)],
) -> TriggerResponse:
    """Trigger an on-demand pre-screening run.

    Guarded by ``ALLOW_ADHOC_TRIGGER`` — disabled in production per CLAUDE.md §8.5.
    Set ``ALLOW_ADHOC_TRIGGER=true`` in staging/QA environments only. ML model
    updates require a nightly Airflow DAG run; this endpoint queues an
    out-of-schedule scoring request, not a model retrain.

    Raises:
        403: Ad-hoc triggers are disabled (production default).
        404: Candidate not found.
        422: No resume has been uploaded yet — nothing to score.
    """
    if not config.ALLOW_ADHOC_TRIGGER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Ad-hoc pre-screening triggers are disabled. "
                "Set ALLOW_ADHOC_TRIGGER=true to enable "
                "(staging/QA only — CLAUDE.md §8.5)."
            ),
        )

    c = _get_candidate(candidate_id)

    if c["resume_path"] is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No resume uploaded. Upload a resume before triggering pre-screening.",
        )

    # Publish a trigger event to Kafka — the scoring DAG picks it up.
    # Non-fatal: if Kafka is unavailable the DAG will process the candidate
    # on its next nightly window via MinIO scan.
    try:
        from ingestion.profile_producer import ProfileProducer
        producer = ProfileProducer(
            bootstrap_servers=config.KAFKA_BOOTSTRAP_SERVERS,
            topic=config.KAFKA_TOPIC_PROFILE,
        )
        producer.publish_prescreening_result(
            candidate_uuid=candidate_id,
            prescreening_score=None,
            resume_ai_score=None,
            repo_ai_score=None,
            interview_trust_score=None,
            flagged=False,
            severity="low",
            flag_reason="",
            scored_at=time.time(),
        )
        producer.flush()
    except Exception as exc:
        logger.warning(
            "trigger_kafka_event_failed",
            candidate_uuid=candidate_id,
            error=str(exc),
        )

    logger.info(
        "prescreening_trigger_queued",
        candidate_uuid=candidate_id,  # UUID — no PII
        recruiter_id=recruiter_id,
    )
    return TriggerResponse(
        candidate_uuid=candidate_id,
        status="queued",
        prescreening_score=c["prescreening_score"],
        flagged=c["flagged"],
    )
