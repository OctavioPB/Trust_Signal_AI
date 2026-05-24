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
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel, Field

import config

logger = structlog.get_logger(__name__)

# ── Auth ───────────────────────────────────────────────────────────────────────
# Extracted to api/auth.py in Sprint 20.

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
        "candidate_uuid": candidate_uuid,
        "recruiter_id":   recruiter_id,
        "status":         "pending",
        "created_at":     created_at,
        "resume_path":    None,
        "repo_urls":      [],
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
