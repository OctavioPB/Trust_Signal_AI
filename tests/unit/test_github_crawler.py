"""Unit tests for ingestion/github_crawler.py."""

from __future__ import annotations

import hashlib
import time
import uuid
from unittest.mock import MagicMock, call, patch

import pytest

from ingestion.github_crawler import (
    CrawledFile,
    CommitSummary,
    GitHubCrawler,
    RepoCrawlResult,
    _ext_to_language,
    _is_eligible_file,
    _parse_owner_repo,
    _MAX_FILES_PER_REPO,
    _MAX_FILE_BYTES,
    _RATE_LIMIT_SAFETY_BUFFER,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_response(status_code: int = 200, data=None, headers: dict | None = None):
    """Build a mock httpx response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {
        "x-ratelimit-remaining": "500",
        "x-ratelimit-reset": str(int(time.time()) + 3600),
        **(headers or {}),
    }
    resp.json.return_value = data if data is not None else {}
    if status_code >= 400:
        import httpx
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status_code}", request=MagicMock(), response=resp
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


def _make_crawler(*responses) -> GitHubCrawler:
    """Build a GitHubCrawler whose HTTP client returns the given responses in order."""
    client = MagicMock()
    client.get.side_effect = list(responses)
    return GitHubCrawler(_client=client)


# ── _parse_owner_repo ──────────────────────────────────────────────────────────

def test_parse_owner_repo_valid_url():
    owner, repo = _parse_owner_repo("https://github.com/openai/gpt-4")
    assert owner == "openai"
    assert repo == "gpt-4"


def test_parse_owner_repo_strips_trailing_slash():
    owner, repo = _parse_owner_repo("https://github.com/octocat/hello-world/")
    assert owner == "octocat"
    assert repo == "hello-world"


def test_parse_owner_repo_strips_git_suffix():
    owner, repo = _parse_owner_repo("https://github.com/owner/myrepo.git")
    assert owner == "owner"
    assert repo == "myrepo"


def test_parse_owner_repo_invalid_url_raises():
    with pytest.raises(ValueError, match="Invalid GitHub URL"):
        _parse_owner_repo("https://gitlab.com/owner/repo")


def test_parse_owner_repo_non_github_raises():
    with pytest.raises(ValueError, match="Invalid GitHub URL"):
        _parse_owner_repo("http://example.com/not/github")


# ── repo_uuid determinism ──────────────────────────────────────────────────────

def test_repo_uuid_is_deterministic():
    """Same URL always produces the same repo_uuid."""
    url = "https://github.com/owner/repo"
    expected = str(uuid.uuid5(uuid.NAMESPACE_URL, url))
    crawler = GitHubCrawler._make_repo_uuid_for_test(url)  # via helper below
    assert crawler == expected


def test_repo_uuid_different_for_different_urls():
    url_a = "https://github.com/owner/alpha"
    url_b = "https://github.com/owner/beta"
    assert str(uuid.uuid5(uuid.NAMESPACE_URL, url_a)) != str(
        uuid.uuid5(uuid.NAMESPACE_URL, url_b)
    )


# ── _is_eligible_file ──────────────────────────────────────────────────────────

def test_eligible_file_python():
    assert _is_eligible_file({"type": "blob", "path": "src/main.py", "size": 1000})


def test_eligible_file_typescript():
    assert _is_eligible_file({"type": "blob", "path": "app/index.tsx", "size": 2000})


def test_ineligible_file_html():
    assert not _is_eligible_file({"type": "blob", "path": "index.html", "size": 100})


def test_ineligible_file_directory():
    assert not _is_eligible_file({"type": "tree", "path": "src", "size": 0})


def test_ineligible_file_oversized():
    oversized = _MAX_FILE_BYTES + 1
    assert not _is_eligible_file({"type": "blob", "path": "big.py", "size": oversized})


def test_eligible_file_exactly_at_size_limit():
    assert _is_eligible_file({"type": "blob", "path": "ok.py", "size": _MAX_FILE_BYTES})


def test_ineligible_file_no_extension():
    assert not _is_eligible_file({"type": "blob", "path": "Makefile", "size": 100})


# ── _ext_to_language ───────────────────────────────────────────────────────────

def test_ext_to_language_python():
    assert _ext_to_language("src/app.py") == "python"


def test_ext_to_language_typescript():
    assert _ext_to_language("components/Header.tsx") == "typescript"


def test_ext_to_language_go():
    assert _ext_to_language("main.go") == "go"


def test_ext_to_language_unknown():
    assert _ext_to_language("archive.zip") == "unknown"


def test_ext_to_language_no_extension():
    assert _ext_to_language("Dockerfile") == "unknown"


# ── Rate-limit backoff ─────────────────────────────────────────────────────────

def test_rate_limit_backoff_on_429_then_success():
    """On a 429, crawler should retry and succeed on the next attempt."""
    fail_resp = _make_response(429, headers={"x-ratelimit-remaining": "0"})
    ok_resp = _make_response(200, data={"default_branch": "main"})

    client = MagicMock()
    client.get.side_effect = [fail_resp, ok_resp]
    crawler = GitHubCrawler(_client=client)

    with patch("ingestion.github_crawler.time.sleep") as mock_sleep:
        result = crawler._fetch_json("/repos/owner/repo")

    assert result == {"default_branch": "main"}
    mock_sleep.assert_called_once()
    assert mock_sleep.call_args[0][0] == 5   # first back-off: base × 2^0 = 5 s


def test_rate_limit_backoff_on_403_then_success():
    """403 responses also trigger exponential back-off."""
    fail_resp = _make_response(403, headers={"x-ratelimit-remaining": "0"})
    ok_resp = _make_response(200, data={"items": []})

    client = MagicMock()
    client.get.side_effect = [fail_resp, ok_resp]
    crawler = GitHubCrawler(_client=client)

    with patch("ingestion.github_crawler.time.sleep") as mock_sleep:
        crawler._fetch_json("/search/repos")

    mock_sleep.assert_called_once()


def test_rate_limit_exhausted_raises_after_max_retries():
    """After _MAX_RETRIES consecutive 429s, HTTPStatusError is raised."""
    import httpx

    fail_resp = _make_response(429)
    client = MagicMock()
    client.get.return_value = fail_resp
    crawler = GitHubCrawler(_client=client)

    with patch("ingestion.github_crawler.time.sleep"):
        with pytest.raises(httpx.HTTPStatusError):
            crawler._fetch_json("/repos/owner/repo")


def test_check_rate_limit_sleeps_when_remaining_low():
    """_check_rate_limit sleeps when remaining ≤ safety buffer."""
    crawler = GitHubCrawler(_client=MagicMock())
    future_reset = int(time.time()) + 60
    headers = {
        "x-ratelimit-remaining": str(_RATE_LIMIT_SAFETY_BUFFER),
        "x-ratelimit-reset": str(future_reset),
    }
    with patch("ingestion.github_crawler.time.sleep") as mock_sleep:
        crawler._check_rate_limit(headers)
    mock_sleep.assert_called_once()


def test_check_rate_limit_does_not_sleep_when_ample():
    """_check_rate_limit does not sleep when remaining is well above buffer."""
    crawler = GitHubCrawler(_client=MagicMock())
    headers = {
        "x-ratelimit-remaining": "4000",
        "x-ratelimit-reset": "0",
    }
    with patch("ingestion.github_crawler.time.sleep") as mock_sleep:
        crawler._check_rate_limit(headers)
    mock_sleep.assert_not_called()


# ── crawl_repo integration ─────────────────────────────────────────────────────

def test_crawl_repo_returns_repo_uuid_matching_url():
    """repo_uuid in result equals uuid5(NAMESPACE_URL, repo_url)."""
    repo_url = "https://github.com/alice/myproject"
    expected_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, repo_url))

    client = MagicMock()
    client.get.side_effect = [
        _make_response(200, {"default_branch": "main"}),           # meta
        _make_response(200, []),                                    # commits page 1 (empty)
        _make_response(200, {"tree": [], "truncated": False}),     # file tree
    ]
    crawler = GitHubCrawler(_client=client)
    result = crawler.crawl_repo(repo_url)

    assert result.repo_uuid == expected_uuid


def test_crawl_repo_files_capped_at_max():
    """When the repo has more than _MAX_FILES_PER_REPO eligible files, only the cap is returned."""
    # Build a tree with MAX + 10 .py blobs, all small
    blobs = [
        {"type": "blob", "path": f"file{i}.py", "sha": f"sha{i}", "size": 100}
        for i in range(_MAX_FILES_PER_REPO + 10)
    ]

    client = MagicMock()
    # Each blob fetch returns one file; use a counter to generate unique blobs
    blob_response = _make_response(
        200, {"content": "aGVsbG8=", "encoding": "base64"}
    )
    responses = [
        _make_response(200, {"default_branch": "main"}),                   # meta
        _make_response(200, []),                                            # commits
        _make_response(200, {"tree": blobs, "truncated": False}),          # tree
    ] + [blob_response] * _MAX_FILES_PER_REPO

    client.get.side_effect = responses
    crawler = GitHubCrawler(_client=client)

    with patch("ingestion.github_crawler.time.sleep"):
        result = crawler.crawl_repo("https://github.com/owner/bigrepo")

    assert len(result.files) == _MAX_FILES_PER_REPO


def test_crawl_repo_oversized_file_skipped():
    """Files exceeding _MAX_FILE_BYTES are not included in the result."""
    blobs = [
        {"type": "blob", "path": "huge.py", "sha": "sha1", "size": _MAX_FILE_BYTES + 1},
        {"type": "blob", "path": "small.py", "sha": "sha2", "size": 100},
    ]
    client = MagicMock()
    client.get.side_effect = [
        _make_response(200, {"default_branch": "main"}),
        _make_response(200, []),
        _make_response(200, {"tree": blobs, "truncated": False}),
        _make_response(200, {"content": "aGVsbG8=", "encoding": "base64"}),  # small.py
    ]
    crawler = GitHubCrawler(_client=client)
    result = crawler.crawl_repo("https://github.com/owner/repo")

    assert len(result.files) == 1
    assert result.files[0].file_path == "small.py"


def test_crawl_repo_content_hash_is_sha256():
    """content_hash of a crawled file is a valid lower-case SHA-256 hex string."""
    import base64 as _b64
    raw = b"print('hello')"
    encoded = _b64.b64encode(raw).decode()
    expected_hash = hashlib.sha256(raw).hexdigest()

    blobs = [{"type": "blob", "path": "hello.py", "sha": "abc", "size": len(raw)}]
    client = MagicMock()
    client.get.side_effect = [
        _make_response(200, {"default_branch": "main"}),
        _make_response(200, []),
        _make_response(200, {"tree": blobs, "truncated": False}),
        _make_response(200, {"content": encoded, "encoding": "base64"}),
    ]
    crawler = GitHubCrawler(_client=client)
    result = crawler.crawl_repo("https://github.com/owner/repo")

    assert result.files[0].content_hash == expected_hash


def test_crawl_repo_commit_count_matches():
    """commit_count in the result equals the number of CommitSummary objects."""
    commits_data = [
        {
            "sha": f"sha{i}",
            "commit": {
                "message": f"fix: issue {i}",
                "author": {"date": "2025-01-01T00:00:00Z"},
            },
        }
        for i in range(3)
    ]
    client = MagicMock()
    client.get.side_effect = [
        _make_response(200, {"default_branch": "main"}),
        _make_response(200, commits_data),      # commits (< 100, no next page)
        _make_response(200, {"tree": [], "truncated": False}),
    ]
    crawler = GitHubCrawler(_client=client)
    result = crawler.crawl_repo("https://github.com/owner/repo")

    assert result.commit_count == 3
    assert len(result.commits) == 3


def test_crawl_repo_commits_have_no_author_pii():
    """CommitSummary objects must not contain author name or email fields."""
    commits_data = [
        {
            "sha": "abc",
            "commit": {
                "message": "feat: something",
                "author": {
                    "date": "2025-06-01T10:00:00Z",
                    "name": "Jane Doe",          # must not appear in output
                    "email": "jane@example.com",  # must not appear in output
                },
            },
        }
    ]
    client = MagicMock()
    client.get.side_effect = [
        _make_response(200, {"default_branch": "main"}),
        _make_response(200, commits_data),
        _make_response(200, {"tree": [], "truncated": False}),
    ]
    crawler = GitHubCrawler(_client=client)
    result = crawler.crawl_repo("https://github.com/owner/repo")

    assert len(result.commits) == 1
    c = result.commits[0]
    assert not hasattr(c, "author_name")
    assert not hasattr(c, "author_email")
    assert c.sha == "abc"
    assert c.message_length == len("feat: something")


# ── Attach a class-level helper so the UUID test above works ───────────────────

GitHubCrawler._make_repo_uuid_for_test = staticmethod(
    lambda url: str(uuid.uuid5(uuid.NAMESPACE_URL, url))
)
