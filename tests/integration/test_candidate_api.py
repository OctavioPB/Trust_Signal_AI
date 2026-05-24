"""Integration test: create candidate → upload resume → link repo → verify state.

Requires the full docker-compose stack (Kafka + MinIO) to be running:
    docker compose up -d broker minio kafka-setup minio-setup

Run with:
    pytest --run-integration -m integration tests/integration/test_candidate_api.py

Definition of Done (PLAN.md Sprint 14):
  - POST /candidates returns a UUID; no PII in the response body.
  - POST /candidates/{id}/resume uploads the file to MinIO resumes bucket.
  - POST /candidates/{id}/repos validates and stores a GitHub URL.
  - Kafka event is published to candidate-resume-stream on resume upload.
  - candidate_uuid in all logs is a UUID (no PII pattern).
"""

from __future__ import annotations

import io
import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from minio import Minio

import config
from api.candidates import _CANDIDATES
from api.main import app

# ── Constants ──────────────────────────────────────────────────────────────────

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_ALGORITHM = "HS256"
_MINIMAL_PDF = b"%PDF-1.4 1 0 obj<</Type /Catalog>> endobj"


def _make_token(recruiter_id: str = "integration-recruiter-uuid") -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=1)
    return jwt.encode(
        {"sub": recruiter_id, "exp": expire},
        config.FASTAPI_SECRET_KEY,
        algorithm=_ALGORITHM,
    )


def _minio_client() -> Minio:
    host = config.MINIO_ENDPOINT.replace("http://", "").replace("https://", "")
    return Minio(
        host,
        access_key=config.MINIO_ACCESS_KEY,
        secret_key=config.MINIO_SECRET_KEY,
        secure=False,
    )


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clear_candidates():
    _CANDIDATES.clear()
    yield
    _CANDIDATES.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_make_token()}"}


# ── Tests ──────────────────────────────────────────────────────────────────────

@pytest.mark.integration
def test_create_candidate_uuid_is_valid(
    client: TestClient, auth_headers: dict
) -> None:
    resp = client.post("/candidates", headers=auth_headers)
    assert resp.status_code == 201
    assert _UUID_RE.match(resp.json()["candidate_uuid"]), (
        "candidate_uuid must be a UUID — no PII should appear here"
    )


@pytest.mark.integration
def test_create_candidate_no_pii_in_response(
    client: TestClient, auth_headers: dict
) -> None:
    """Response body must not contain anything that looks like an email address."""
    resp = client.post("/candidates", headers=auth_headers)
    body_text = resp.text
    assert not re.search(r"[\w.+-]+@[\w-]+\.\w+", body_text), (
        "PII (email address) found in candidate create response"
    )


@pytest.mark.integration
def test_upload_resume_file_appears_in_minio(
    client: TestClient, auth_headers: dict
) -> None:
    """After upload, the resume must be retrievable from MinIO resumes bucket."""
    candidate_uuid = client.post("/candidates", headers=auth_headers).json()["candidate_uuid"]

    resp = client.post(
        f"/candidates/{candidate_uuid}/resume",
        headers=auth_headers,
        files={"file": ("cv.pdf", io.BytesIO(_MINIMAL_PDF), "application/pdf")},
    )
    assert resp.status_code == 202, resp.text

    minio_path = resp.json()["minio_path"]
    # minio_path = "resumes/{uuid}/{timestamp}.pdf"
    # Verify object exists in MinIO
    bucket, object_name = minio_path.split("/", 1)
    minio = _minio_client()
    obj = minio.stat_object(bucket, object_name)
    assert obj is not None, f"Object not found in MinIO: {minio_path}"


@pytest.mark.integration
def test_upload_resume_path_follows_naming_convention(
    client: TestClient, auth_headers: dict
) -> None:
    """Path must match resumes/{uuid}/{yyyymmddThhmmssZ}.pdf — no PII in path."""
    candidate_uuid = client.post("/candidates", headers=auth_headers).json()["candidate_uuid"]

    resp = client.post(
        f"/candidates/{candidate_uuid}/resume",
        headers=auth_headers,
        files={"file": ("cv.pdf", io.BytesIO(_MINIMAL_PDF), "application/pdf")},
    )
    minio_path: str = resp.json()["minio_path"]

    # resumes/{uuid}/{timestamp}.pdf
    parts = minio_path.split("/")
    assert parts[0] == "resumes"
    assert _UUID_RE.match(parts[1]), "Second segment must be a UUID (no PII)"
    assert parts[2].endswith(".pdf")

    timestamp_part = parts[2].replace(".pdf", "")
    # Compact ISO: YYYYMMDDTHHMMSSz — 16 chars
    assert re.match(r"^\d{8}T\d{6}Z$", timestamp_part), (
        f"Unexpected timestamp format in path: {timestamp_part}"
    )


@pytest.mark.integration
def test_upload_resume_kafka_event_published(
    client: TestClient, auth_headers: dict
) -> None:
    """A consume from candidate-resume-stream must yield one message per upload."""
    from confluent_kafka import Consumer, KafkaException

    candidate_uuid = client.post("/candidates", headers=auth_headers).json()["candidate_uuid"]

    client.post(
        f"/candidates/{candidate_uuid}/resume",
        headers=auth_headers,
        files={"file": ("cv.pdf", io.BytesIO(_MINIMAL_PDF), "application/pdf")},
    )

    consumer = Consumer(
        {
            "bootstrap.servers": config.KAFKA_BOOTSTRAP_SERVERS,
            "group.id": f"integration-test-resume-{candidate_uuid[:8]}",
            "auto.offset.reset": "earliest",
        }
    )
    consumer.subscribe([config.KAFKA_TOPIC_RESUME])

    import json
    import time

    received_uuid: str | None = None
    deadline = time.monotonic() + 15.0
    try:
        while time.monotonic() < deadline:
            msg = consumer.poll(1.0)
            if msg is None or msg.error():
                continue
            payload = json.loads(msg.value())
            if payload.get("candidate_uuid") == candidate_uuid:
                received_uuid = payload["candidate_uuid"]
                break
    finally:
        consumer.close()

    assert received_uuid is not None, (
        f"No Kafka event received for candidate {candidate_uuid} within 15 s"
    )
    assert _UUID_RE.match(received_uuid), "candidate_uuid in Kafka payload must be a UUID"


@pytest.mark.integration
def test_link_repo_stored_in_memory(
    client: TestClient, auth_headers: dict
) -> None:
    candidate_uuid = client.post("/candidates", headers=auth_headers).json()["candidate_uuid"]
    repo_url = "https://github.com/octocat/Hello-World"

    resp = client.post(
        f"/candidates/{candidate_uuid}/repos",
        headers=auth_headers,
        json={"repo_url": repo_url},
    )
    assert resp.status_code == 200
    assert repo_url in resp.json()["repo_urls"]
    assert repo_url in _CANDIDATES[candidate_uuid]["repo_urls"]


@pytest.mark.integration
def test_full_prescreening_intake_flow(
    client: TestClient, auth_headers: dict
) -> None:
    """End-to-end: create → upload resume → link two repos → verify state."""
    # Create
    candidate_uuid = client.post("/candidates", headers=auth_headers).json()["candidate_uuid"]
    assert _UUID_RE.match(candidate_uuid)

    # Upload resume
    resume_resp = client.post(
        f"/candidates/{candidate_uuid}/resume",
        headers=auth_headers,
        files={"file": ("portfolio.pdf", io.BytesIO(_MINIMAL_PDF), "application/pdf")},
    )
    assert resume_resp.status_code == 202
    minio_path = resume_resp.json()["minio_path"]
    assert candidate_uuid in minio_path

    # Link two repos
    for repo in [
        "https://github.com/octocat/Hello-World",
        "https://github.com/octocat/Spoon-Knife",
    ]:
        repo_resp = client.post(
            f"/candidates/{candidate_uuid}/repos",
            headers=auth_headers,
            json={"repo_url": repo},
        )
        assert repo_resp.status_code == 200

    # Verify in-memory state
    record = _CANDIDATES[candidate_uuid]
    assert record["resume_path"] == minio_path
    assert len(record["repo_urls"]) == 2
    assert record["status"] == "pending"
