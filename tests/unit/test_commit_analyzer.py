"""Unit tests for ingestion/commit_analyzer.py."""

from __future__ import annotations

import math
import time
from datetime import datetime, timedelta, timezone

import pytest

from ingestion.commit_analyzer import (
    CommitAnalysisResult,
    _BURST_THRESHOLD,
    _ENTROPY_HIGH_SUSPICION,
    _ENTROPY_LOW_SUSPICION,
    _detect_velocity_burst,
    _linear_map,
    _shannon_entropy,
    _weeks_between,
    analyze_commits,
)
from ingestion.github_crawler import CommitSummary


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _make_commits_uniform(count: int, message_length: int = 12) -> list[CommitSummary]:
    """All commits have the same message length — AI-like."""
    base_ts = datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp()
    return [
        CommitSummary(
            sha=f"sha{i}",
            committed_at=base_ts + i * 86400,  # one per day across many weeks
            message_length=message_length,
        )
        for i in range(count)
    ]


def _make_commits_varied(lengths: list[int]) -> list[CommitSummary]:
    """Commits with explicitly varied message lengths — human-like."""
    base_ts = datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp()
    return [
        CommitSummary(
            sha=f"sha{i}",
            committed_at=base_ts + i * 86400 * 7,  # one per week
            message_length=length,
        )
        for i, length in enumerate(lengths)
    ]


def _make_burst_commits(total: int, burst_fraction: float = 0.90) -> list[CommitSummary]:
    """Place burst_fraction of commits in a single week, the rest in other weeks."""
    burst_count = int(total * burst_fraction)
    rest_count = total - burst_count

    # Burst: all in the same ISO week
    burst_base = datetime(2025, 6, 2, tzinfo=timezone.utc).timestamp()  # Monday week 23
    burst = [
        CommitSummary(sha=f"b{i}", committed_at=burst_base + i * 3600, message_length=10)
        for i in range(burst_count)
    ]

    # Rest: spread across earlier weeks
    rest_base = datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp()
    rest = [
        CommitSummary(sha=f"r{i}", committed_at=rest_base + i * 7 * 86400, message_length=10)
        for i in range(rest_count)
    ]

    return burst + rest


# ── Regression: AI vs human suspicion bands ────────────────────────────────────

def test_uniform_commits_high_suspicion():
    """All-same message lengths → entropy ≈ 0 → high suspicion score."""
    commits = _make_commits_uniform(30, message_length=12)
    result = analyze_commits("uuid-ai-commits", commits)
    assert result.suspicion_score >= 0.60, (
        f"Expected ≥ 0.60 for uniform commits, got {result.suspicion_score}"
    )


def test_varied_commits_low_suspicion():
    """Naturally varied message lengths → high entropy → low suspicion score."""
    lengths = [5, 72, 18, 120, 33, 8, 55, 200, 15, 42, 90, 7, 65, 30, 110]
    commits = _make_commits_varied(lengths)
    result = analyze_commits("uuid-human-commits", commits)
    assert result.suspicion_score <= 0.50, (
        f"Expected ≤ 0.50 for varied commits, got {result.suspicion_score}"
    )


# ── Empty commit guard ─────────────────────────────────────────────────────────

def test_empty_commits_returns_zero_result():
    result = analyze_commits("uuid-empty", [])
    assert result.total_commits == 0
    assert result.suspicion_score == 0.0
    assert result.velocity_burst_detected is False
    assert result.message_length_entropy == 0.0


# ── Velocity burst detection ───────────────────────────────────────────────────

def test_velocity_burst_detected_when_above_threshold():
    """90 % of commits in one week → velocity_burst_detected = True."""
    commits = _make_burst_commits(20, burst_fraction=0.90)
    result = analyze_commits("uuid-burst", commits)
    assert result.velocity_burst_detected is True


def test_no_velocity_burst_when_spread():
    """Evenly spread commits (1 per week over many weeks) → no burst."""
    commits = _make_commits_uniform(20, message_length=10)
    result = analyze_commits("uuid-no-burst", commits)
    # Each commit is 1 day apart → 20 different weeks approximately
    assert result.velocity_burst_detected is False


def test_velocity_burst_raises_suspicion():
    """Velocity burst increases suspicion_score vs. same commits without burst."""
    no_burst = _make_commits_uniform(20, message_length=10)
    burst = _make_burst_commits(20, burst_fraction=0.90)

    r_no_burst = analyze_commits("uuid-noburst2", no_burst)
    r_burst = analyze_commits("uuid-burst2", burst)

    assert r_burst.suspicion_score >= r_no_burst.suspicion_score


# ── PII discipline ─────────────────────────────────────────────────────────────

def test_result_has_no_author_pii():
    """CommitAnalysisResult must not expose any author name or email fields."""
    commits = _make_commits_uniform(5)
    result = analyze_commits("uuid-pii", commits)
    assert not hasattr(result, "author_name")
    assert not hasattr(result, "author_email")
    assert not hasattr(result, "authors")


# ── commit_count and commits_per_week ──────────────────────────────────────────

def test_total_commits_matches_input():
    commits = _make_commits_uniform(15)
    result = analyze_commits("uuid-count", commits)
    assert result.total_commits == 15


def test_commits_per_week_is_positive():
    commits = _make_commits_uniform(10)
    result = analyze_commits("uuid-cpw", commits)
    assert result.commits_per_week > 0.0


def test_score_in_unit_interval():
    """suspicion_score is always in [0, 1]."""
    for commits in [
        _make_commits_uniform(5),
        _make_commits_varied([10, 200, 5, 50, 100]),
        _make_burst_commits(10),
        [],
    ]:
        result = analyze_commits("uuid-range", commits)
        assert 0.0 <= result.suspicion_score <= 1.0


def test_candidate_uuid_preserved():
    commits = _make_commits_uniform(5)
    result = analyze_commits("uuid-preserve", commits)
    assert result.repo_uuid == "uuid-preserve"


# ── _shannon_entropy ───────────────────────────────────────────────────────────

def test_shannon_entropy_all_same_returns_zero():
    """All identical values → entropy 0.0."""
    assert _shannon_entropy([5, 5, 5, 5, 5]) == pytest.approx(0.0, abs=1e-9)


def test_shannon_entropy_two_equal_classes():
    """Two equally probable classes → entropy 1.0 bit."""
    assert _shannon_entropy([0, 1, 0, 1, 0, 1]) == pytest.approx(1.0, abs=1e-6)


def test_shannon_entropy_four_equal_classes():
    """Four equally probable classes → entropy 2.0 bits."""
    values = [0, 1, 2, 3] * 10
    assert _shannon_entropy(values) == pytest.approx(2.0, abs=1e-6)


def test_shannon_entropy_empty():
    assert _shannon_entropy([]) == 0.0


def test_shannon_entropy_single_value():
    assert _shannon_entropy([42]) == pytest.approx(0.0, abs=1e-9)


def test_shannon_entropy_increases_with_diversity():
    uniform = _shannon_entropy([5] * 20)
    two_class = _shannon_entropy([1, 2] * 10)
    five_class = _shannon_entropy([1, 2, 3, 4, 5] * 4)
    assert uniform < two_class < five_class


# ── _weeks_between ─────────────────────────────────────────────────────────────

def test_weeks_between_empty():
    assert _weeks_between([]) == pytest.approx(1.0)


def test_weeks_between_single():
    assert _weeks_between([time.time()]) == pytest.approx(1.0)


def test_weeks_between_seven_days():
    base = 1_700_000_000.0
    assert _weeks_between([base, base + 7 * 24 * 3600]) == pytest.approx(1.0, abs=1e-6)


def test_weeks_between_two_weeks():
    base = 1_700_000_000.0
    assert _weeks_between([base, base + 14 * 24 * 3600]) == pytest.approx(2.0, abs=1e-6)


# ── _detect_velocity_burst ────────────────────────────────────────────────────

def test_detect_burst_single_commit():
    """One commit → fraction 1.0 > threshold → burst True."""
    ts = datetime(2025, 6, 2, tzinfo=timezone.utc).timestamp()
    assert _detect_velocity_burst([ts], _BURST_THRESHOLD) is True


def test_detect_burst_below_threshold():
    """50 % in one week is below 80 % threshold → no burst."""
    week_a = datetime(2025, 6, 2, tzinfo=timezone.utc).timestamp()  # week 23
    week_b = datetime(2025, 6, 9, tzinfo=timezone.utc).timestamp()  # week 24
    timestamps = [week_a] * 5 + [week_b] * 5
    assert _detect_velocity_burst(timestamps, _BURST_THRESHOLD) is False


def test_detect_burst_empty():
    assert _detect_velocity_burst([], _BURST_THRESHOLD) is False


# ── _linear_map ────────────────────────────────────────────────────────────────

def test_linear_map_entropy_at_high_suspicion_bound():
    assert _linear_map(_ENTROPY_HIGH_SUSPICION, _ENTROPY_HIGH_SUSPICION, _ENTROPY_LOW_SUSPICION) == pytest.approx(1.0)


def test_linear_map_entropy_at_low_suspicion_bound():
    assert _linear_map(_ENTROPY_LOW_SUSPICION, _ENTROPY_HIGH_SUSPICION, _ENTROPY_LOW_SUSPICION) == pytest.approx(0.0)


def test_linear_map_clamped_above():
    assert _linear_map(0.0, _ENTROPY_HIGH_SUSPICION, _ENTROPY_LOW_SUSPICION) == pytest.approx(1.0)


def test_linear_map_clamped_below():
    assert _linear_map(10.0, _ENTROPY_HIGH_SUSPICION, _ENTROPY_LOW_SUSPICION) == pytest.approx(0.0)


def test_linear_map_degenerate_returns_zero():
    assert _linear_map(0.5, 0.5, 0.5) == pytest.approx(0.0)
