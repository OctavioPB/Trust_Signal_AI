"""Commit history pattern analyzer for AI-generation detection — Sprint 16.

Computes three metrics from a repository's commit history that correlate
with AI-generated or copy-pasted code:

1. **Message length entropy** (Shannon bits):
   AI-assisted commits tend to have uniform message lengths (e.g. all
   "Update README" or all following a fixed template). Low entropy → high
   suspicion.

2. **Velocity burst**:
   Repositories created by dumping AI-generated code in a single session
   often have >80 % of commits concentrated in one calendar week.
   Velocity burst flag → raised suspicion.

3. **Commits per week**:
   Contextual metric; used for framing, not directly in the suspicion score.

PII discipline (CLAUDE.md §8.6):
   CommitSummary objects from GitHubCrawler contain no author names or email
   addresses — they carry only sha, committed_at (timestamp), and
   message_length. CommitAnalysisResult likewise exposes no author PII.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone

import structlog

logger = structlog.get_logger(__name__)

# ── Normalisation bounds ───────────────────────────────────────────────────────

_ENTROPY_HIGH_SUSPICION = 0.5   # ≤ 0.5 bits → entropy_suspicion 1.0 (very uniform)
_ENTROPY_LOW_SUSPICION  = 3.0   # ≥ 3.0 bits → entropy_suspicion 0.0 (naturally varied)
_BURST_THRESHOLD        = 0.80  # fraction of commits in one calendar week → burst

# Combined score weights
_W_ENTROPY = 0.70
_W_BURST   = 0.30


# ── Data class ─────────────────────────────────────────────────────────────────

@dataclass
class CommitAnalysisResult:
    """Commit-pattern metrics for a crawled repository.

    Attributes:
        repo_uuid: UUID of the repository (no PII).
        total_commits: Number of CommitSummary objects analysed.
        commits_per_week: Mean commits per calendar week over the observed span.
        message_length_entropy: Shannon entropy (bits) of commit message lengths.
            Low entropy → uniform message lengths → AI-like.
        avg_message_length: Mean commit message character count.
        velocity_burst_detected: True when > 80 % of commits fall in one
            calendar week (copy-paste / AI-dump signal).
        suspicion_score: Aggregate score in [0, 1]; higher → more AI-like.
    """

    repo_uuid: str
    total_commits: int
    commits_per_week: float
    message_length_entropy: float
    avg_message_length: float
    velocity_burst_detected: bool
    suspicion_score: float


# ── Public API ─────────────────────────────────────────────────────────────────

def analyze_commits(
    repo_uuid: str,
    commits: list,   # list[CommitSummary] — avoids circular import at type level
) -> CommitAnalysisResult:
    """Compute commit-pattern suspicion metrics for a repository.

    Args:
        repo_uuid: UUID of the repository (used in logs — no PII).
        commits: List of CommitSummary objects from GitHubCrawler.crawl_repo().
            CommitSummary must have: sha (str), committed_at (float), message_length (int).

    Returns:
        CommitAnalysisResult with suspicion_score in [0, 1].
        Returns all-zero result for an empty commit list (graceful fallback).
    """
    if not commits:
        logger.debug(
            "commit_analysis_skipped",
            repo_uuid=repo_uuid,   # UUID — no PII
            reason="empty_commits",
        )
        return CommitAnalysisResult(
            repo_uuid=repo_uuid,
            total_commits=0,
            commits_per_week=0.0,
            message_length_entropy=0.0,
            avg_message_length=0.0,
            velocity_burst_detected=False,
            suspicion_score=0.0,
        )

    lengths = [c.message_length for c in commits]
    entropy = _shannon_entropy(lengths)
    avg_length = sum(lengths) / len(lengths)

    timestamps = sorted(c.committed_at for c in commits if c.committed_at > 0)
    weeks_span = _weeks_between(timestamps)
    commits_per_week = len(timestamps) / weeks_span

    burst = _detect_velocity_burst(timestamps, _BURST_THRESHOLD)

    # Entropy suspicion: low entropy (uniform messages) → high suspicion
    entropy_susp = _linear_map(entropy, _ENTROPY_HIGH_SUSPICION, _ENTROPY_LOW_SUSPICION)
    burst_contrib = 1.0 if burst else 0.0
    suspicion = float(min(1.0, _W_ENTROPY * entropy_susp + _W_BURST * burst_contrib))

    logger.debug(
        "commit_analysis_scored",
        repo_uuid=repo_uuid,           # UUID — no PII
        total_commits=len(commits),
        message_length_entropy=round(entropy, 4),
        velocity_burst=burst,
        suspicion_score=round(suspicion, 4),
    )

    return CommitAnalysisResult(
        repo_uuid=repo_uuid,
        total_commits=len(commits),
        commits_per_week=round(commits_per_week, 4),
        message_length_entropy=round(entropy, 6),
        avg_message_length=round(avg_length, 2),
        velocity_burst_detected=burst,
        suspicion_score=round(suspicion, 4),
    )


# ── Pure helpers ───────────────────────────────────────────────────────────────

def _shannon_entropy(values: list[int]) -> float:
    """Compute Shannon entropy (bits) of a list of integer values.

    Args:
        values: List of integers (e.g. commit message lengths).

    Returns:
        Entropy in bits. 0.0 for empty list or all-same values.
    """
    if not values:
        return 0.0
    counter = Counter(values)
    total = len(values)
    return float(
        -sum((c / total) * math.log2(c / total) for c in counter.values())
    )


def _weeks_between(timestamps: list[float]) -> float:
    """Return fractional weeks between the first and last timestamp.

    Args:
        timestamps: Sorted Unix timestamps (may be empty).

    Returns:
        Weeks elapsed; minimum 1.0 to avoid division by zero.
    """
    if len(timestamps) < 2:
        return 1.0
    diff_seconds = timestamps[-1] - timestamps[0]
    return max(1.0, diff_seconds / (7 * 24 * 3600))


def _detect_velocity_burst(
    timestamps: list[float],
    threshold: float,
) -> bool:
    """Return True when > ``threshold`` fraction of commits fall in one ISO week.

    Args:
        timestamps: Sorted Unix timestamps.
        threshold: Fraction (0–1) that triggers a burst flag.

    Returns:
        True if any single calendar week contains more than threshold × total
        commits.
    """
    if not timestamps:
        return False
    total = len(timestamps)
    week_counts: Counter[str] = Counter()
    for ts in timestamps:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        year, week, _ = dt.isocalendar()
        week_counts[f"{year}-W{week:02d}"] += 1
    max_in_week = max(week_counts.values())
    return (max_in_week / total) > threshold


def _linear_map(value: float, max_susp: float, min_susp: float) -> float:
    """Map a metric value to a suspicion score in [0, 1] (clamped).

    value ≤ max_susp → 1.0; value ≥ min_susp → 0.0; linear in between.

    Args:
        value: The metric to map.
        max_susp: Metric threshold for maximum suspicion (score 1.0).
        min_susp: Metric threshold for zero suspicion (score 0.0).

    Returns:
        Suspicion score in [0, 1].
    """
    if max_susp == min_susp:
        return 0.0
    raw = (min_susp - value) / (min_susp - max_susp)
    return float(max(0.0, min(1.0, raw)))
