"""Unit tests for ml/features/commit_pattern.py."""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest

from ingestion.github_crawler import CommitSummary
from ml.features.commit_pattern import (
    CommitPatternFeatures,
    CommitPatternScorer,
    _LINE_ENTROPY_HIGH_SUSPICION,
    _LINE_ENTROPY_LOW_SUSPICION,
    _W_COMMIT,
    _W_LINE,
    _line_length_entropy,
    _normalise_line_entropy,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _make_commits(count: int, msg_len: int = 12) -> list[CommitSummary]:
    base = datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp()
    return [
        CommitSummary(sha=f"s{i}", committed_at=base + i * 86400, message_length=msg_len)
        for i in range(count)
    ]


def _make_burst_commits(total: int, burst_frac: float = 0.90) -> list[CommitSummary]:
    burst_n = int(total * burst_frac)
    rest_n  = total - burst_n
    burst_base = datetime(2025, 6, 2, tzinfo=timezone.utc).timestamp()
    rest_base  = datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp()
    burst = [
        CommitSummary(sha=f"b{i}", committed_at=burst_base + i * 3600, message_length=10)
        for i in range(burst_n)
    ]
    rest = [
        CommitSummary(sha=f"r{i}", committed_at=rest_base + i * 7 * 86400, message_length=10)
        for i in range(rest_n)
    ]
    return burst + rest


def _uniform_lines_content(n: int = 20, line_len: int = 30) -> str:
    """All lines same length → low entropy → high suspicion."""
    return "\n".join(["x" * line_len] * n)


def _varied_lines_content() -> str:
    """Lines with very different lengths → high entropy → low suspicion."""
    lines = [
        "x",
        "x" * 5,
        "x" * 15,
        "x" * 40,
        "x" * 80,
        "x" * 120,
        "x" * 3,
        "x" * 25,
        "x" * 60,
        "x" * 10,
    ]
    return "\n".join(lines * 5)   # 50 lines, very varied


# ── _line_length_entropy ───────────────────────────────────────────────────────

def test_line_entropy_uniform_lines_is_zero():
    content = _uniform_lines_content(20, 30)
    ent = _line_length_entropy(content)
    assert ent is not None
    assert ent == pytest.approx(0.0, abs=1e-9)


def test_line_entropy_two_equal_classes():
    content = "\n".join(["ab"] * 10 + ["abcde"] * 10)
    ent = _line_length_entropy(content)
    assert ent is not None
    assert ent == pytest.approx(1.0, abs=1e-6)


def test_line_entropy_returns_none_for_short_file():
    """Fewer than 5 non-empty lines → None (unreliable)."""
    assert _line_length_entropy("a\nb\nc") is None


def test_line_entropy_skips_blank_lines():
    content = "\n".join(["abc"] * 10 + [""] * 5)   # 5 blank lines
    ent = _line_length_entropy(content)
    assert ent == pytest.approx(0.0, abs=1e-9)


def test_line_entropy_increases_with_diversity():
    uniform = _line_length_entropy(_uniform_lines_content(20, 20))
    varied  = _line_length_entropy(_varied_lines_content())
    assert uniform is not None and varied is not None
    assert uniform < varied


# ── _normalise_line_entropy ────────────────────────────────────────────────────

def test_normalise_at_high_suspicion_bound():
    assert _normalise_line_entropy(_LINE_ENTROPY_HIGH_SUSPICION) == pytest.approx(1.0)


def test_normalise_at_low_suspicion_bound():
    assert _normalise_line_entropy(_LINE_ENTROPY_LOW_SUSPICION) == pytest.approx(0.0)


def test_normalise_below_high_bound_clamped():
    assert _normalise_line_entropy(0.0) == pytest.approx(1.0)


def test_normalise_above_low_bound_clamped():
    assert _normalise_line_entropy(10.0) == pytest.approx(0.0)


def test_normalise_midpoint_between_bounds():
    mid = (_LINE_ENTROPY_HIGH_SUSPICION + _LINE_ENTROPY_LOW_SUSPICION) / 2.0
    result = _normalise_line_entropy(mid)
    assert 0.0 < result < 1.0


# ── CommitPatternScorer.score_repo ─────────────────────────────────────────────

def test_score_repo_result_is_dataclass():
    scorer = CommitPatternScorer()
    commits = _make_commits(5)
    files   = [("f.py", _varied_lines_content())]
    result  = scorer.score_repo("uuid-1", commits, files)

    assert isinstance(result, CommitPatternFeatures)


def test_score_repo_preserves_repo_uuid():
    scorer = CommitPatternScorer()
    result = scorer.score_repo("my-uuid", _make_commits(5), [])

    assert result.repo_uuid == "my-uuid"


def test_score_repo_empty_commits_uses_neutral_score():
    """No commits → commit signal defaults to 0.5; files still scored."""
    scorer = CommitPatternScorer()
    files  = [("f.py", _uniform_lines_content())]
    result = scorer.score_repo("uuid-no-commits", commits=[], files=files)

    assert 0.0 <= result.suspicion_score <= 1.0
    assert result.velocity_burst_detected is False
    assert result.message_length_entropy == pytest.approx(0.0)


def test_score_repo_empty_commits_and_files_returns_weighted_neutral():
    """No commits, no files → commit 0.5, line 0.0 → score = _W_COMMIT * 0.5."""
    scorer = CommitPatternScorer()
    result = scorer.score_repo("uuid-empty-all", commits=[], files=[])

    expected = _W_COMMIT * 0.5 + _W_LINE * 0.0
    assert result.suspicion_score == pytest.approx(expected, abs=1e-4)


def test_score_repo_uniform_lines_raises_suspicion():
    """All same-length lines → high line entropy suspicion."""
    scorer  = CommitPatternScorer()
    commits = _make_commits(10, msg_len=10)
    files   = [("a.py", _uniform_lines_content(30, 40))]
    result  = scorer.score_repo("uuid-uniform", commits, files)

    assert result.avg_line_length_entropy == pytest.approx(0.0, abs=1e-6)
    assert result.suspicion_score > 0.4


def test_score_repo_varied_lines_lower_suspicion():
    """Varied line lengths → lower line suspicion contribution."""
    scorer  = CommitPatternScorer()
    commits = _make_commits(10, msg_len=10)
    uniform_result = scorer.score_repo("uuid-u", commits, [("a.py", _uniform_lines_content())])
    varied_result  = scorer.score_repo("uuid-v", commits, [("a.py", _varied_lines_content())])

    assert varied_result.avg_line_length_entropy >= uniform_result.avg_line_length_entropy


def test_score_repo_burst_commits_raises_suspicion():
    """Velocity burst in commits → higher suspicion score."""
    scorer     = CommitPatternScorer()
    burst      = _make_burst_commits(20, 0.90)
    no_burst   = _make_commits(20)
    files      = [("a.py", _varied_lines_content())]

    r_burst    = scorer.score_repo("uuid-burst", burst, files)
    r_no_burst = scorer.score_repo("uuid-no-burst", no_burst, files)

    assert r_burst.suspicion_score >= r_no_burst.suspicion_score


def test_score_repo_burst_flag_propagated():
    scorer = CommitPatternScorer()
    burst  = _make_burst_commits(20, 0.90)
    result = scorer.score_repo("uuid-burst-flag", burst, [])

    assert result.velocity_burst_detected is True


def test_score_repo_suspicion_in_unit_interval():
    scorer = CommitPatternScorer()
    for commits, files in [
        (_make_commits(10), [("a.py", _varied_lines_content())]),
        (_make_burst_commits(20), [("b.py", _uniform_lines_content())]),
        ([], []),
    ]:
        result = scorer.score_repo("uuid-range", commits, files)
        assert 0.0 <= result.suspicion_score <= 1.0


def test_score_repo_no_pii_in_result():
    scorer = CommitPatternScorer()
    result = scorer.score_repo("uuid-pii", _make_commits(5), [])

    assert not hasattr(result, "author_name")
    assert not hasattr(result, "author_email")
    assert not hasattr(result, "authors")


# ── Weight validation ──────────────────────────────────────────────────────────

def test_invalid_weights_raise():
    with pytest.raises(ValueError, match="sum to 1.0"):
        CommitPatternScorer(w_commit=0.6, w_line=0.6)


def test_valid_custom_weights_accepted():
    scorer = CommitPatternScorer(w_commit=0.7, w_line=0.3)
    assert scorer._w_commit == pytest.approx(0.7)
    assert scorer._w_line   == pytest.approx(0.3)
