"""Unit tests for POST /candidates endpoints.

All MinIO and Kafka I/O is mocked — no real broker or object store is needed.
JWT tokens are generated using the same secret and algorithm as the live service.
"""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

import config
from api.candidates import _CANDIDATES, router
from api.main import app

# ── Helpers ────────────────────────────────────────────────────────────────────

_ALGORITHM = "HS256"


def _make_token(recruiter_id: str = "recruiter-test-uuid") -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=1)
    return jwt.encode(
        {"sub": recruiter_id, "exp": expire},
        config.FASTAPI_SECRET_KEY,
        algorithm=_ALGORITHM,
    )


@pytest.fixture(autouse=True)
def clear_candidates():
    """Reset the in-memory store between tests."""
    _CANDIDATES.clear()
    yield
    _CANDIDATES.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_make_token()}"}


# ── POST /candidates ───────────────────────────────────────────────────────────

def test_create_candidate_returns_201(client: TestClient, auth_headers: dict) -> None:
    resp = client.post("/candidates", headers=auth_headers)
    assert resp.status_code == 201


def test_create_candidate_returns_uuid(client: TestClient, auth_headers: dict) -> None:
    import re
    resp = client.post("/candidates", headers=auth_headers)
    body = resp.json()
    uuid_re = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    assert uuid_re.match(body["candidate_uuid"]), "candidate_uuid must be a UUID"


def test_create_candidate_status_is_pending(client: TestClient, auth_headers: dict) -> None:
    resp = client.post("/candidates", headers=auth_headers)
    assert resp.json()["status"] == "pending"


def test_create_candidate_requires_auth(client: TestClient) -> None:
    resp = client.post("/candidates")
    assert resp.status_code == 403


def test_create_candidate_rejects_bad_token(client: TestClient) -> None:
    resp = client.post("/candidates", headers={"Authorization": "Bearer bad-token"})
    assert resp.status_code == 401


# ── POST /candidates/{id}/resume ───────────────────────────────────────────────

def _create_candidate(client: TestClient, auth_headers: dict) -> str:
    resp = client.post("/candidates", headers=auth_headers)
    return resp.json()["candidate_uuid"]


@patch("api.candidates._make_resume_producer")
@patch("api.candidates._make_object_store")
def test_upload_resume_happy_path_returns_202(
    mock_store_factory: MagicMock,
    mock_producer_factory: MagicMock,
    client: TestClient,
    auth_headers: dict,
) -> None:
    mock_store = MagicMock()
    mock_store.upload_resume.return_value = "resumes/uuid/20260523T100000Z.pdf"
    mock_store_factory.return_value = mock_store
    mock_producer_factory.return_value = MagicMock()

    candidate_uuid = _create_candidate(client, auth_headers)
    pdf_data = b"%PDF-1.4 fake pdf content"
    resp = client.post(
        f"/candidates/{candidate_uuid}/resume",
        headers=auth_headers,
        files={"file": ("cv.pdf", io.BytesIO(pdf_data), "application/pdf")},
    )
    assert resp.status_code == 202


@patch("api.candidates._make_resume_producer")
@patch("api.candidates._make_object_store")
def test_upload_resume_response_contains_minio_path(
    mock_store_factory: MagicMock,
    mock_producer_factory: MagicMock,
    client: TestClient,
    auth_headers: dict,
) -> None:
    expected_path = "resumes/uuid/20260523T100000Z.pdf"
    mock_store = MagicMock()
    mock_store.upload_resume.return_value = expected_path
    mock_store_factory.return_value = mock_store
    mock_producer_factory.return_value = MagicMock()

    candidate_uuid = _create_candidate(client, auth_headers)
    resp = client.post(
        f"/candidates/{candidate_uuid}/resume",
        headers=auth_headers,
        files={"file": ("cv.pdf", io.BytesIO(b"%PDF"), "application/pdf")},
    )
    assert resp.json()["minio_path"] == expected_path


@patch("api.candidates._make_resume_producer")
@patch("api.candidates._make_object_store")
def test_upload_resume_publishes_kafka_event(
    mock_store_factory: MagicMock,
    mock_producer_factory: MagicMock,
    client: TestClient,
    auth_headers: dict,
) -> None:
    mock_store = MagicMock()
    mock_store.upload_resume.return_value = "resumes/uuid/ts.pdf"
    mock_store_factory.return_value = mock_store
    mock_producer = MagicMock()
    mock_producer_factory.return_value = mock_producer

    candidate_uuid = _create_candidate(client, auth_headers)
    client.post(
        f"/candidates/{candidate_uuid}/resume",
        headers=auth_headers,
        files={"file": ("cv.pdf", io.BytesIO(b"%PDF"), "application/pdf")},
    )
    mock_producer.publish_uploaded.assert_called_once()


def test_upload_resume_unknown_candidate_returns_404(
    client: TestClient, auth_headers: dict
) -> None:
    resp = client.post(
        "/candidates/nonexistent-uuid/resume",
        headers=auth_headers,
        files={"file": ("cv.pdf", io.BytesIO(b"%PDF"), "application/pdf")},
    )
    assert resp.status_code == 404


def test_upload_resume_unsupported_mime_returns_415(
    client: TestClient, auth_headers: dict
) -> None:
    candidate_uuid = _create_candidate(client, auth_headers)
    resp = client.post(
        f"/candidates/{candidate_uuid}/resume",
        headers=auth_headers,
        files={"file": ("resume.xlsx", io.BytesIO(b"data"), "application/vnd.ms-excel")},
    )
    assert resp.status_code == 415


@patch("api.candidates._make_resume_producer")
@patch("api.candidates._make_object_store")
def test_upload_resume_oversized_file_returns_413(
    mock_store_factory: MagicMock,
    mock_producer_factory: MagicMock,
    client: TestClient,
    auth_headers: dict,
) -> None:
    mock_store_factory.return_value = MagicMock()
    mock_producer_factory.return_value = MagicMock()

    candidate_uuid = _create_candidate(client, auth_headers)
    oversized = b"A" * (config.RESUME_MAX_MB * 1024 * 1024 + 1)
    resp = client.post(
        f"/candidates/{candidate_uuid}/resume",
        headers=auth_headers,
        files={"file": ("big.pdf", io.BytesIO(oversized), "application/pdf")},
    )
    assert resp.status_code == 413


@patch("api.candidates._make_resume_producer")
@patch("api.candidates._make_object_store")
def test_upload_resume_minio_failure_returns_502(
    mock_store_factory: MagicMock,
    mock_producer_factory: MagicMock,
    client: TestClient,
    auth_headers: dict,
) -> None:
    from minio.error import S3Error

    mock_store = MagicMock()
    mock_store.upload_resume.side_effect = S3Error(
        "NoSuchBucket", "Bucket not found", "", "", "", ""
    )
    mock_store_factory.return_value = mock_store
    mock_producer_factory.return_value = MagicMock()

    candidate_uuid = _create_candidate(client, auth_headers)
    resp = client.post(
        f"/candidates/{candidate_uuid}/resume",
        headers=auth_headers,
        files={"file": ("cv.pdf", io.BytesIO(b"%PDF"), "application/pdf")},
    )
    assert resp.status_code == 502


# ── POST /candidates/{id}/repos ────────────────────────────────────────────────

def test_link_repo_valid_url_returns_200(
    client: TestClient, auth_headers: dict
) -> None:
    candidate_uuid = _create_candidate(client, auth_headers)
    resp = client.post(
        f"/candidates/{candidate_uuid}/repos",
        headers=auth_headers,
        json={"repo_url": "https://github.com/octocat/Hello-World"},
    )
    assert resp.status_code == 200


def test_link_repo_returns_url_in_list(
    client: TestClient, auth_headers: dict
) -> None:
    candidate_uuid = _create_candidate(client, auth_headers)
    url = "https://github.com/octocat/Hello-World"
    resp = client.post(
        f"/candidates/{candidate_uuid}/repos",
        headers=auth_headers,
        json={"repo_url": url},
    )
    assert url in resp.json()["repo_urls"]


def test_link_repo_deduplicates(client: TestClient, auth_headers: dict) -> None:
    candidate_uuid = _create_candidate(client, auth_headers)
    url = "https://github.com/octocat/Hello-World"
    client.post(f"/candidates/{candidate_uuid}/repos", headers=auth_headers, json={"repo_url": url})
    client.post(f"/candidates/{candidate_uuid}/repos", headers=auth_headers, json={"repo_url": url})
    resp = client.post(
        f"/candidates/{candidate_uuid}/repos", headers=auth_headers, json={"repo_url": url}
    )
    assert resp.json()["repo_urls"].count(url) == 1


def test_link_repo_invalid_url_returns_422(
    client: TestClient, auth_headers: dict
) -> None:
    candidate_uuid = _create_candidate(client, auth_headers)
    resp = client.post(
        f"/candidates/{candidate_uuid}/repos",
        headers=auth_headers,
        json={"repo_url": "https://gitlab.com/user/repo"},
    )
    assert resp.status_code == 422


def test_link_repo_non_github_http_returns_422(
    client: TestClient, auth_headers: dict
) -> None:
    candidate_uuid = _create_candidate(client, auth_headers)
    resp = client.post(
        f"/candidates/{candidate_uuid}/repos",
        headers=auth_headers,
        json={"repo_url": "http://github.com/user/repo"},  # http, not https
    )
    assert resp.status_code == 422


def test_link_repo_unknown_candidate_returns_404(
    client: TestClient, auth_headers: dict
) -> None:
    resp = client.post(
        "/candidates/ghost-uuid/repos",
        headers=auth_headers,
        json={"repo_url": "https://github.com/octocat/Hello-World"},
    )
    assert resp.status_code == 404


def test_link_repo_no_pii_in_response(client: TestClient, auth_headers: dict) -> None:
    """Response body must not contain anything that looks like a name or email."""
    import re

    candidate_uuid = _create_candidate(client, auth_headers)
    resp = client.post(
        f"/candidates/{candidate_uuid}/repos",
        headers=auth_headers,
        json={"repo_url": "https://github.com/octocat/Hello-World"},
    )
    body_str = resp.text
    # No email-like pattern
    assert not re.search(r"[\w.+-]+@[\w-]+\.\w+", body_str)
