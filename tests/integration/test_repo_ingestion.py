"""Integration tests: GitHub crawl → Kafka → DeltaLake round-trip.

All external services (GitHub API, Kafka, MinIO, Spark) are mocked.
Tests verify the end-to-end data flow and PII discipline without
requiring live infrastructure.

Run the full suite with:
    pytest tests/integration/test_repo_ingestion.py -m integration -v
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest

from ingestion.commit_analyzer import analyze_commits
from ingestion.github_crawler import (
    CommitSummary,
    GitHubCrawler,
    RepoCrawlResult,
)

pytestmark = pytest.mark.integration


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_http_response(status_code: int = 200, data=None, headers: dict | None = None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {
        "x-ratelimit-remaining": "4000",
        "x-ratelimit-reset": str(int(time.time()) + 3600),
        **(headers or {}),
    }
    resp.json.return_value = data if data is not None else {}
    resp.raise_for_status.return_value = None
    return resp


_REPO_URL = "https://github.com/acme/cool-project"
_CANDIDATE_UUID = "cand-uuid-1234"
_EXPECTED_REPO_UUID = str(uuid.uuid5(uuid.NAMESPACE_URL, _REPO_URL))

_PY_CONTENT = b"def main():\n    print('hello')\n"
_PY_CONTENT_HASH = hashlib.sha256(_PY_CONTENT).hexdigest()
_PY_CONTENT_B64 = base64.b64encode(_PY_CONTENT).decode()


def _build_mock_github_client():
    """Return an httpx.Client mock that simulates a minimal repo crawl."""
    commits_data = [
        {
            "sha": "abc123",
            "commit": {
                "message": "Initial commit",
                "author": {"date": "2025-01-15T10:00:00Z"},
            },
        },
        {
            "sha": "def456",
            "commit": {
                "message": "Add feature",
                "author": {"date": "2025-02-01T12:00:00Z"},
            },
        },
    ]

    blobs = [
        {"type": "blob", "path": "main.py", "sha": "blob1", "size": len(_PY_CONTENT)},
    ]

    client = MagicMock()
    client.get.side_effect = [
        _make_http_response(200, {"default_branch": "main"}),               # meta
        _make_http_response(200, commits_data),                             # commits p1
        _make_http_response(200, {"tree": blobs, "truncated": False}),     # tree
        _make_http_response(200, {"content": _PY_CONTENT_B64, "encoding": "base64"}),  # blob
    ]
    return client


# ── Test 1: full crawl produces correct RepoCrawlResult ───────────────────────

def test_crawl_returns_correct_repo_uuid():
    client = _build_mock_github_client()
    crawler = GitHubCrawler(_client=client)
    result = crawler.crawl_repo(_REPO_URL)

    assert result.repo_uuid == _EXPECTED_REPO_UUID


def test_crawl_returns_files_with_correct_hash():
    client = _build_mock_github_client()
    crawler = GitHubCrawler(_client=client)
    result = crawler.crawl_repo(_REPO_URL)

    assert len(result.files) == 1
    assert result.files[0].file_path == "main.py"
    assert result.files[0].content_hash == _PY_CONTENT_HASH
    assert result.files[0].language == "python"


def test_crawl_commit_summaries_have_no_pii():
    """CommitSummary objects must not expose author names or emails."""
    client = _build_mock_github_client()
    crawler = GitHubCrawler(_client=client)
    result = crawler.crawl_repo(_REPO_URL)

    for commit in result.commits:
        assert not hasattr(commit, "author_name")
        assert not hasattr(commit, "author_email")
        assert isinstance(commit.sha, str)
        assert isinstance(commit.committed_at, float)
        assert isinstance(commit.message_length, int)


# ── Test 2: Kafka round-trip ──────────────────────────────────────────────────

def test_kafka_payload_published_per_file():
    """RepoProducer.publish_file is called once per crawled file."""
    from ingestion.repo_producer import RepoProducer

    mock_producer_instance = MagicMock()
    with patch("ingestion.repo_producer.Producer", return_value=mock_producer_instance):
        producer = RepoProducer("localhost:9092", "candidate-repo-stream")

        client = _build_mock_github_client()
        crawler = GitHubCrawler(_client=client)
        result = crawler.crawl_repo(_REPO_URL)

        crawled_at = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        for f in result.files:
            producer.publish_file(
                repo_uuid=result.repo_uuid,
                candidate_uuid=_CANDIDATE_UUID,
                file_path=f.file_path,
                language=f.language,
                content_hash=f.content_hash,
                crawled_at=crawled_at,
            )

    assert mock_producer_instance.produce.call_count == len(result.files)


def test_kafka_payload_no_pii():
    """The Kafka payload must not contain repo owner, file content, or author PII."""
    from ingestion.repo_producer import RepoProducer

    captured_payloads: list[dict] = []

    def capture_produce(**kwargs):
        value = kwargs.get("value", b"")
        captured_payloads.append(json.loads(value.decode()))

    mock_producer_instance = MagicMock()
    mock_producer_instance.produce.side_effect = lambda *a, **kw: capture_produce(**kw)

    with patch("ingestion.repo_producer.Producer", return_value=mock_producer_instance):
        producer = RepoProducer("localhost:9092", "candidate-repo-stream")

        client = _build_mock_github_client()
        crawler = GitHubCrawler(_client=client)
        result = crawler.crawl_repo(_REPO_URL)

        crawled_at = "20250601T120000Z"
        for f in result.files:
            producer.publish_file(
                repo_uuid=result.repo_uuid,
                candidate_uuid=_CANDIDATE_UUID,
                file_path=f.file_path,
                language=f.language,
                content_hash=f.content_hash,
                crawled_at=crawled_at,
            )

    assert captured_payloads, "No Kafka events were published"
    for payload in captured_payloads:
        # Must not contain raw source code
        assert "content" not in payload
        assert "def main" not in str(payload)
        # Must contain UUID-only identifiers
        assert "repo_uuid" in payload
        assert "candidate_uuid" in payload
        # repo_uuid must be a valid UUID5, not a human-readable repo name
        parsed = uuid.UUID(payload["repo_uuid"])
        assert parsed.version == 5


# ── Test 3: commit analysis round-trip ───────────────────────────────────────

def test_commit_analysis_from_crawl_result():
    """analyze_commits produces a valid result from crawled commits."""
    client = _build_mock_github_client()
    crawler = GitHubCrawler(_client=client)
    result = crawler.crawl_repo(_REPO_URL)

    analysis = analyze_commits(result.repo_uuid, result.commits)

    assert analysis.repo_uuid == result.repo_uuid
    assert analysis.total_commits == result.commit_count
    assert 0.0 <= analysis.suspicion_score <= 1.0


def test_commit_analysis_no_pii_in_result():
    """CommitAnalysisResult must not expose any author PII."""
    client = _build_mock_github_client()
    crawler = GitHubCrawler(_client=client)
    result = crawler.crawl_repo(_REPO_URL)

    analysis = analyze_commits(result.repo_uuid, result.commits)

    assert not hasattr(analysis, "author_name")
    assert not hasattr(analysis, "author_email")
    assert not hasattr(analysis, "authors")


# ── Test 4: MinIO storage round-trip ─────────────────────────────────────────

def test_minio_upload_called_per_file():
    """upload_repo_file is called once per crawled file."""
    from storage.object_store import ObjectStore

    mock_minio = MagicMock()

    with patch("storage.object_store.Minio", return_value=mock_minio):
        store = ObjectStore("http://localhost:9000", "admin", "password")

        client = _build_mock_github_client()
        crawler = GitHubCrawler(_client=client)
        result = crawler.crawl_repo(_REPO_URL)

        for f in result.files:
            store.upload_repo_file(
                repo_uuid=result.repo_uuid,
                file_path=f.file_path,
                content=f.content.encode("utf-8", errors="replace"),
            )

    assert mock_minio.put_object.call_count == len(result.files)


def test_minio_path_includes_repo_uuid_not_owner():
    """MinIO object path uses repo_uuid, not the human-readable owner/name."""
    from storage.object_store import ObjectStore

    captured_paths: list[str] = []

    mock_minio = MagicMock()
    mock_minio.put_object.side_effect = lambda **kwargs: captured_paths.append(
        kwargs.get("object_name", "")
    )

    with patch("storage.object_store.Minio", return_value=mock_minio):
        store = ObjectStore("http://localhost:9000", "admin", "password")

        client = _build_mock_github_client()
        crawler = GitHubCrawler(_client=client)
        result = crawler.crawl_repo(_REPO_URL)

        for f in result.files:
            store.upload_repo_file(
                repo_uuid=result.repo_uuid,
                file_path=f.file_path,
                content=f.content.encode("utf-8"),
            )

    assert captured_paths, "No MinIO puts were made"
    for path in captured_paths:
        assert result.repo_uuid in path
        assert "acme" not in path        # no repo owner in path
        assert "cool-project" not in path  # no repo name in path
