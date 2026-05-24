"""GitHub repository crawler for source code artifact ingestion — Sprint 16.

Crawls public repositories via the GitHub REST API and returns eligible
source files for AI-generation scoring. Files are extension-filtered and
size-limited. Rate limits are respected; 429/403 responses trigger
exponential back-off.

UUID strategy:
    repo_uuid = uuid5(NAMESPACE_URL, repo_url) — deterministic, no PII.
    The raw repo URL is never written to logs; only the UUID is logged.

CLAUDE.md constraints:
  - No PII in logs: repo owner / name appear only as repo_uuid in log output.
  - API token loaded from config (env var GITHUB_API_TOKEN); never hardcoded.
  - Source code content is staged to MinIO, never logged.
"""

from __future__ import annotations

import base64
import hashlib
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

import config

logger = structlog.get_logger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

_GITHUB_API_BASE = "https://api.github.com"

_GITHUB_URL_RE = re.compile(
    r"https://github\.com/([^/\s]+)/([^/\s?#]+?)(?:\.git)?/*$"
)

_SOURCE_EXTENSIONS: frozenset[str] = frozenset({
    ".py", ".js", ".ts", ".tsx", ".go", ".java", ".rb", ".rs", ".cpp", ".md",
})

_EXT_TO_LANGUAGE: dict[str, str] = {
    ".py":  "python",
    ".js":  "javascript",
    ".ts":  "typescript",
    ".tsx": "typescript",
    ".go":  "go",
    ".java": "java",
    ".rb":  "ruby",
    ".rs":  "rust",
    ".cpp": "cpp",
    ".md":  "markdown",
}

_MAX_FILES_PER_REPO       = 500
_MAX_FILE_BYTES           = 10 * 1024 * 1024   # 10 MB
_MAX_COMMITS_PER_REPO     = 500                # 5 pages × 100
_MAX_RETRIES              = 3
_BACKOFF_BASE_SECONDS     = 5
_RATE_LIMIT_SAFETY_BUFFER = 10   # sleep when fewer than this many requests remain


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class CrawledFile:
    """A single source file extracted from a GitHub repository.

    Attributes:
        repo_uuid: UUID of the parent repository (no PII).
        file_path: Relative path within the repository.
        language: Detected programming language from file extension.
        content: Decoded UTF-8 text of the file.
        content_hash: SHA-256 hex digest of the UTF-8 content.
        size_bytes: File size as reported by the Git tree API.
    """

    repo_uuid: str
    file_path: str
    language: str
    content: str
    content_hash: str
    size_bytes: int


@dataclass
class CommitSummary:
    """PII-free commit metadata extracted from a repository.

    Author names and email addresses are deliberately omitted
    (CLAUDE.md §8.6 — no PII in output).

    Attributes:
        sha: Full commit SHA.
        committed_at: Unix timestamp of the author date.
        message_length: Character count of the commit message.
    """

    sha: str
    committed_at: float
    message_length: int


@dataclass
class RepoCrawlResult:
    """Output of GitHubCrawler.crawl_repo() for a single repository.

    Attributes:
        repo_uuid: uuid5(NAMESPACE_URL, repo_url) — deterministic, no PII.
        repo_url: Original GitHub URL (used for re-crawl deduplication).
        default_branch: Default branch name (e.g. "main").
        crawled_at: Unix timestamp of when the crawl completed.
        files: Eligible source files fetched from the repository.
        commits: PII-free commit summaries from the past 12 months.
        commit_count: Total commits fetched (len(commits)).
    """

    repo_uuid: str
    repo_url: str
    default_branch: str
    crawled_at: float
    files: list[CrawledFile] = field(default_factory=list)
    commits: list[CommitSummary] = field(default_factory=list)
    commit_count: int = 0


# ── Pure helpers ───────────────────────────────────────────────────────────────

def _parse_owner_repo(repo_url: str) -> tuple[str, str]:
    """Extract (owner, repo) from a GitHub URL.

    Args:
        repo_url: GitHub repository URL.

    Returns:
        (owner, repo_name) tuple.

    Raises:
        ValueError: If the URL does not match https://github.com/{owner}/{repo}.
    """
    m = _GITHUB_URL_RE.match(repo_url.strip())
    if not m:
        raise ValueError(
            f"Invalid GitHub URL '{repo_url}'. "
            "Expected https://github.com/{{owner}}/{{repo}}"
        )
    return m.group(1), m.group(2)


def _ext_to_language(file_path: str) -> str:
    """Derive programming language label from a file path's extension.

    Args:
        file_path: Relative path within the repository.

    Returns:
        Language string, or "unknown" for unmapped extensions.
    """
    if "." not in file_path:
        return "unknown"
    suffix = "." + file_path.rsplit(".", 1)[-1].lower()
    return _EXT_TO_LANGUAGE.get(suffix, "unknown")


def _is_eligible_file(item: dict[str, Any]) -> bool:
    """Return True if a tree item should be fetched and scored.

    A file is eligible when:
      - type == "blob" (not a directory)
      - extension is in the source allowlist
      - size is within _MAX_FILE_BYTES

    Args:
        item: A single entry from the Git Trees API response.

    Returns:
        True when the file should be fetched.
    """
    if item.get("type") != "blob":
        return False
    path = item.get("path", "")
    size = item.get("size", 0)
    if "." not in path:
        return False
    suffix = "." + path.rsplit(".", 1)[-1].lower()
    return suffix in _SOURCE_EXTENSIONS and size <= _MAX_FILE_BYTES


# ── Crawler ────────────────────────────────────────────────────────────────────

class GitHubCrawler:
    """Crawls a public GitHub repository and returns source code artifacts.

    Rate limiting is handled automatically:
      - Proactive: sleeps when X-RateLimit-Remaining falls below
        ``_RATE_LIMIT_SAFETY_BUFFER``.
      - Reactive: exponential back-off (5 s, 10 s, 20 s) on 429 / 403.

    Args:
        api_token: GitHub Personal Access Token. Defaults to
            ``config.GITHUB_API_TOKEN``. Unauthenticated requests are
            limited to 60 req/hr; authenticated to 5 000 req/hr.
        _client: Optional httpx.Client for test injection (avoids real
            HTTP calls in unit tests).
    """

    def __init__(
        self,
        api_token: str | None = None,
        _client: Any = None,
    ) -> None:
        token = api_token or config.GITHUB_API_TOKEN or ""
        self._headers: dict[str, str] = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            self._headers["Authorization"] = f"Bearer {token}"

        if _client is not None:
            self._client = _client
        else:
            import httpx
            self._client = httpx.Client(timeout=30.0)

        self._log = logger.bind(component="GitHubCrawler")

    def crawl_repo(self, repo_url: str) -> RepoCrawlResult:
        """Crawl a public GitHub repository.

        Fetches repo metadata, commit history (last 12 months), file tree,
        and eligible source file contents.

        Args:
            repo_url: GitHub repository URL
                (``https://github.com/{owner}/{repo}``).

        Returns:
            RepoCrawlResult with files and commits populated.

        Raises:
            ValueError: For malformed GitHub URLs.
            httpx.HTTPStatusError: For unrecoverable API errors.
        """
        owner, repo_name = _parse_owner_repo(repo_url)
        repo_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, repo_url))

        meta = self._fetch_json(f"/repos/{owner}/{repo_name}")
        default_branch = meta.get("default_branch", "main")

        since = (
            datetime.now(tz=timezone.utc) - timedelta(days=365)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        commits = self._fetch_commits(owner, repo_name, since)

        tree_items = self._fetch_file_tree(owner, repo_name, default_branch)

        eligible = [item for item in tree_items if _is_eligible_file(item)]
        if len(eligible) > _MAX_FILES_PER_REPO:
            self._log.warning(
                "repo_file_limit_exceeded",
                repo_uuid=repo_uuid,          # UUID — no PII
                total=len(eligible),
                limit=_MAX_FILES_PER_REPO,
            )
            eligible = eligible[:_MAX_FILES_PER_REPO]

        files: list[CrawledFile] = []
        for item in eligible:
            content = self._fetch_file_content(
                owner, repo_name, item["sha"], item.get("size", 0)
            )
            if content is None:
                continue
            language = _ext_to_language(item["path"])
            content_hash = hashlib.sha256(
                content.encode("utf-8", errors="replace")
            ).hexdigest()
            files.append(
                CrawledFile(
                    repo_uuid=repo_uuid,
                    file_path=item["path"],
                    language=language,
                    content=content,
                    content_hash=content_hash,
                    size_bytes=item.get("size", 0),
                )
            )

        self._log.info(
            "repo_crawled",
            repo_uuid=repo_uuid,          # UUID — no PII; URL never logged
            files_crawled=len(files),
            commit_count=len(commits),
        )

        return RepoCrawlResult(
            repo_uuid=repo_uuid,
            repo_url=repo_url,
            default_branch=default_branch,
            crawled_at=time.time(),
            files=files,
            commits=commits,
            commit_count=len(commits),
        )

    # ── Private API helpers ────────────────────────────────────────────────────

    def _fetch_commits(
        self,
        owner: str,
        repo: str,
        since: str,
    ) -> list[CommitSummary]:
        """Fetch commit history (last 12 months), stripping all author PII."""
        summaries: list[CommitSummary] = []
        page = 1

        while len(summaries) < _MAX_COMMITS_PER_REPO:
            data = self._fetch_json(
                f"/repos/{owner}/{repo}/commits"
                f"?since={since}&per_page=100&page={page}"
            )
            if not isinstance(data, list) or not data:
                break
            for item in data:
                author_date = (
                    item.get("commit", {}).get("author", {}).get("date", "")
                )
                try:
                    dt = datetime.fromisoformat(
                        author_date.replace("Z", "+00:00")
                    )
                    ts = dt.timestamp()
                except (ValueError, AttributeError):
                    ts = 0.0
                message = item.get("commit", {}).get("message", "")
                summaries.append(
                    CommitSummary(
                        sha=item.get("sha", ""),
                        committed_at=ts,
                        message_length=len(message),
                    )
                )
            if len(data) < 100:
                break
            page += 1

        return summaries

    def _fetch_file_tree(
        self,
        owner: str,
        repo: str,
        branch: str,
    ) -> list[dict[str, Any]]:
        """Fetch the complete file tree for a branch (recursive)."""
        data = self._fetch_json(
            f"/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
        )
        if data.get("truncated"):
            self._log.warning(
                "repo_tree_truncated",
                repo_uuid=str(uuid.uuid5(uuid.NAMESPACE_URL, f"https://github.com/{owner}/{repo}")),
            )
        return data.get("tree", [])

    def _fetch_file_content(
        self,
        owner: str,
        repo: str,
        sha: str,
        size: int,
    ) -> str | None:
        """Fetch and decode blob content.

        Returns None and logs a warning for blobs that exceed _MAX_FILE_BYTES.
        """
        if size > _MAX_FILE_BYTES:
            self._log.warning(
                "repo_file_oversized_skipped",
                sha=sha,
                size_bytes=size,
                limit_bytes=_MAX_FILE_BYTES,
            )
            return None

        data = self._fetch_json(f"/repos/{owner}/{repo}/git/blobs/{sha}")
        encoding = data.get("encoding", "")
        content_raw = data.get("content", "")

        if encoding == "base64":
            raw_bytes = base64.b64decode(content_raw.replace("\n", ""))
            return raw_bytes.decode("utf-8", errors="replace")
        return str(content_raw)

    def _fetch_json(self, path: str) -> Any:
        """GET a GitHub API path and return parsed JSON.

        Retries on 429 / 403 with exponential back-off. Proactively sleeps
        when the rate-limit remaining count drops near zero.

        Args:
            path: API path starting with ``/``, e.g. ``/repos/owner/repo``.

        Returns:
            Parsed JSON response (dict or list).

        Raises:
            httpx.HTTPStatusError: After all retries are exhausted.
        """
        url = f"{_GITHUB_API_BASE}{path}"
        response = None

        for attempt in range(_MAX_RETRIES):
            response = self._client.get(url, headers=self._headers)
            if response.status_code in (429, 403):
                if attempt == _MAX_RETRIES - 1:
                    response.raise_for_status()
                wait = _BACKOFF_BASE_SECONDS * (2 ** attempt)
                self._log.warning(
                    "github_api_backoff",
                    status=response.status_code,
                    attempt=attempt,
                    wait_seconds=wait,
                )
                time.sleep(wait)
                continue

            self._check_rate_limit(response.headers)
            response.raise_for_status()
            return response.json()

        # Exhausted retries without a successful response
        if response is not None:
            response.raise_for_status()
        raise RuntimeError(f"GitHub API request failed after {_MAX_RETRIES} attempts: {path}")

    def _check_rate_limit(self, headers: Any) -> None:
        """Sleep until reset when fewer than _RATE_LIMIT_SAFETY_BUFFER requests remain.

        Args:
            headers: Response headers (dict-like with .get()).
        """
        try:
            remaining = int(headers.get("x-ratelimit-remaining", "60"))
        except (ValueError, TypeError):
            return

        if remaining <= _RATE_LIMIT_SAFETY_BUFFER:
            try:
                reset_ts = int(headers.get("x-ratelimit-reset", "0"))
            except (ValueError, TypeError):
                reset_ts = 0
            wait = max(1, reset_ts - int(time.time()) + 1)
            self._log.warning(
                "github_rate_limit_low",
                remaining=remaining,
                wait_seconds=wait,
            )
            time.sleep(wait)
