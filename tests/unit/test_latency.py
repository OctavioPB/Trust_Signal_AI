"""Regression tests for ml/features/latency.py.

All tests are pure (no I/O). Each fixture scenario specifies exact
timestamps; the expected suspicion_score is computed from the documented
CV → score mapping and asserted within ±0.01.

CV mapping (linear):
    score = clamp((0.60 - CV) / (0.60 - 0.15), 0, 1)
    CV ≤ 0.15 → 1.00
    CV = 0.375 → 0.50
    CV ≥ 0.60  → 0.00
"""

from __future__ import annotations

import math

import pytest

from ml.features.latency import (
    LatencyFeatures,
    _score_from_cv,
    extract_latency_features,
)

# ── _score_from_cv ────────────────────────────────────────────────────────────

class TestScoreFromCV:

    def test_cv_zero_returns_one(self) -> None:
        assert _score_from_cv(0.0) == pytest.approx(1.0, abs=1e-9)

    def test_cv_at_low_threshold_returns_one(self) -> None:
        # CV = 0.15 → (0.60 - 0.15) / 0.45 = 1.0
        assert _score_from_cv(0.15) == pytest.approx(1.0, abs=1e-9)

    def test_cv_midpoint_returns_half(self) -> None:
        # CV = 0.375 → (0.60 - 0.375) / 0.45 = 0.5
        assert _score_from_cv(0.375) == pytest.approx(0.5, abs=1e-6)

    def test_cv_at_high_threshold_returns_zero(self) -> None:
        assert _score_from_cv(0.60) == pytest.approx(0.0, abs=1e-9)

    def test_cv_above_high_threshold_clamped_to_zero(self) -> None:
        assert _score_from_cv(1.0) == pytest.approx(0.0)
        assert _score_from_cv(10.0) == pytest.approx(0.0)

    def test_score_is_in_unit_interval(self) -> None:
        for cv in [0.0, 0.1, 0.15, 0.3, 0.45, 0.6, 0.8, 1.5]:
            s = _score_from_cv(cv)
            assert 0.0 <= s <= 1.0, f"score={s} out of [0,1] for cv={cv}"


# ── extract_latency_features — fixture scenarios ──────────────────────────────

def _turns(*args) -> list[dict]:
    """Build turn list from alternating (speaker, start, end) tuples."""
    result = []
    for speaker, start, end in args:
        result.append({"speaker": speaker, "start_ts": start, "end_ts": end})
    return result


class TestExtractLatencyFeatures:

    # -- error handling --

    def test_raises_on_zero_candidate_turns(self) -> None:
        turns = _turns(("RECRUITER", 0, 5))
        with pytest.raises(ValueError, match="2 CANDIDATE turns"):
            extract_latency_features("s1", turns)

    def test_raises_on_one_candidate_turn(self) -> None:
        turns = _turns(("RECRUITER", 0, 5), ("CANDIDATE", 8, 15))
        with pytest.raises(ValueError, match="2 CANDIDATE turns"):
            extract_latency_features("s1", turns)

    def test_raises_on_only_recruiter_turns(self) -> None:
        turns = _turns(("RECRUITER", 0, 5), ("RECRUITER", 6, 10))
        with pytest.raises(ValueError):
            extract_latency_features("s1", turns)

    # -- latency extraction --

    def test_latency_is_start_minus_end_of_prior_recruiter(self) -> None:
        # RECRUITER ends at 5.0, CANDIDATE starts at 8.2 → latency = 3.2
        # RECRUITER ends at 16.0, CANDIDATE starts at 19.5 → latency = 3.5
        turns = _turns(
            ("RECRUITER", 0.0, 5.0),
            ("CANDIDATE", 8.2, 15.0),
            ("RECRUITER", 16.0, 22.0),
            ("CANDIDATE", 25.5, 35.0),
        )
        result = extract_latency_features("s1", turns)
        assert result.latencies_s[0] == pytest.approx(3.2, abs=1e-9)
        assert result.latencies_s[1] == pytest.approx(3.5, abs=1e-9)

    def test_negative_latency_clamped_to_zero(self) -> None:
        """Overlapping turns (candidate starts before recruiter ends) must clamp to 0."""
        turns = _turns(
            ("RECRUITER", 0.0, 10.0),
            ("CANDIDATE", 8.0, 18.0),  # overlaps by 2 s
            ("RECRUITER", 19.0, 25.0),
            ("CANDIDATE", 28.0, 35.0),
        )
        result = extract_latency_features("s1", turns)
        assert result.latencies_s[0] == pytest.approx(0.0)

    def test_recruiter_turn_consumed_after_matching(self) -> None:
        """Two consecutive CANDIDATE turns should only pair with their preceding RECRUITER."""
        turns = _turns(
            ("RECRUITER", 0.0, 5.0),
            ("CANDIDATE", 8.0, 12.0),
            ("CANDIDATE", 13.0, 17.0),   # no preceding RECRUITER — should not produce a latency
            ("RECRUITER", 18.0, 23.0),
            ("CANDIDATE", 26.0, 30.0),
        )
        result = extract_latency_features("s1", turns)
        # Only 2 valid RECRUITER→CANDIDATE pairs
        assert len(result.latencies_s) == 2
        assert result.latencies_s[0] == pytest.approx(3.0)
        assert result.latencies_s[1] == pytest.approx(3.0)

    # -- statistical computations --

    def test_mean_computation(self) -> None:
        # latencies: 3.0, 4.0, 5.0 → mean = 4.0
        turns = _turns(
            ("RECRUITER", 0.0, 5.0), ("CANDIDATE", 8.0, 15.0),
            ("RECRUITER", 16.0, 20.0), ("CANDIDATE", 24.0, 32.0),
            ("RECRUITER", 33.0, 37.0), ("CANDIDATE", 42.0, 50.0),
        )
        result = extract_latency_features("s", turns)
        assert result.mean_s == pytest.approx(4.0, abs=1e-9)

    def test_std_uses_ddof1(self) -> None:
        # latencies: 2.0, 4.0 → std (ddof=1) = sqrt(2) ≈ 1.4142
        turns = _turns(
            ("RECRUITER", 0.0, 5.0), ("CANDIDATE", 7.0, 12.0),
            ("RECRUITER", 13.0, 17.0), ("CANDIDATE", 21.0, 28.0),
        )
        result = extract_latency_features("s", turns)
        assert result.std_s == pytest.approx(math.sqrt(2.0), rel=1e-5)

    def test_cv_equals_std_over_mean(self) -> None:
        turns = _turns(
            ("RECRUITER", 0.0, 5.0), ("CANDIDATE", 8.0, 12.0),
            ("RECRUITER", 13.0, 17.0), ("CANDIDATE", 21.0, 26.0),
            ("RECRUITER", 27.0, 31.0), ("CANDIDATE", 35.0, 40.0),
        )
        result = extract_latency_features("s", turns)
        expected_cv = result.std_s / result.mean_s
        assert result.cv == pytest.approx(expected_cv, rel=1e-6)

    # -- suspicion score regression fixtures --

    def test_constant_latency_max_suspicion(self) -> None:
        """All latencies equal → CV = 0 → score = 1.0."""
        turns = _turns(
            ("RECRUITER", 0.0, 5.0), ("CANDIDATE", 8.2, 15.0),
            ("RECRUITER", 16.0, 21.0), ("CANDIDATE", 24.2, 30.0),
            ("RECRUITER", 31.0, 36.0), ("CANDIDATE", 39.2, 46.0),
        )
        result = extract_latency_features("s", turns)
        assert result.suspicion_score == pytest.approx(1.0, abs=0.01)

    def test_high_variance_latency_zero_suspicion(self) -> None:
        """Highly varied latencies → CV > 0.60 → score = 0.0."""
        # latencies: 0.3, 5.0, 0.2, 4.8, 0.4  → high variance
        turns = _turns(
            ("RECRUITER", 0.0, 2.0), ("CANDIDATE", 2.3, 8.0),
            ("RECRUITER", 9.0, 12.0), ("CANDIDATE", 17.0, 25.0),
            ("RECRUITER", 26.0, 30.0), ("CANDIDATE", 30.2, 38.0),
            ("RECRUITER", 39.0, 42.0), ("CANDIDATE", 46.8, 55.0),
            ("RECRUITER", 56.0, 60.0), ("CANDIDATE", 60.4, 68.0),
        )
        result = extract_latency_features("s", turns)
        assert result.suspicion_score == pytest.approx(0.0, abs=0.01)

    def test_five_question_interview_suspicion_score(self) -> None:
        """Fixture: 5-question AI-assisted interview with nearly constant 3 s latency.

        Expected latencies ≈ [3.0, 3.0, 3.0, 3.0, 3.0]
        CV = 0.0 → suspicion_score = 1.0  (within ±0.01)
        """
        times = [
            ("RECRUITER", 0.0, 5.0), ("CANDIDATE", 8.0, 18.0),
            ("RECRUITER", 20.0, 25.0), ("CANDIDATE", 28.0, 40.0),
            ("RECRUITER", 42.0, 47.0), ("CANDIDATE", 50.0, 63.0),
            ("RECRUITER", 65.0, 70.0), ("CANDIDATE", 73.0, 85.0),
            ("RECRUITER", 87.0, 92.0), ("CANDIDATE", 95.0, 108.0),
        ]
        result = extract_latency_features("session-ai", _turns(*times))
        assert result.suspicion_score == pytest.approx(1.0, abs=0.01)
        assert len(result.latencies_s) == 5

    def test_natural_human_interview_low_suspicion(self) -> None:
        """Fixture: natural interview with irregular response gaps.

        latencies: 0.5, 4.2, 1.1, 3.8, 0.8, 5.1
        mean ≈ 2.58, std ≈ 1.92, CV ≈ 0.74 → score = 0.0
        """
        times = [
            ("RECRUITER", 0.0, 5.0), ("CANDIDATE", 5.5, 14.0),
            ("RECRUITER", 15.0, 20.0), ("CANDIDATE", 24.2, 34.0),
            ("RECRUITER", 35.0, 40.0), ("CANDIDATE", 41.1, 51.0),
            ("RECRUITER", 52.0, 57.0), ("CANDIDATE", 60.8, 70.0),
            ("RECRUITER", 71.0, 76.0), ("CANDIDATE", 76.8, 85.0),
            ("RECRUITER", 86.0, 91.0), ("CANDIDATE", 96.1, 107.0),
        ]
        result = extract_latency_features("session-human", _turns(*times))
        assert result.suspicion_score == pytest.approx(0.0, abs=0.01)

    # -- return type and fields --

    def test_returns_latency_features_instance(self) -> None:
        turns = _turns(
            ("RECRUITER", 0.0, 5.0), ("CANDIDATE", 8.0, 14.0),
            ("RECRUITER", 15.0, 20.0), ("CANDIDATE", 23.0, 30.0),
        )
        result = extract_latency_features("s", turns)
        assert isinstance(result, LatencyFeatures)

    def test_session_id_preserved(self) -> None:
        turns = _turns(
            ("RECRUITER", 0.0, 5.0), ("CANDIDATE", 8.0, 14.0),
            ("RECRUITER", 15.0, 20.0), ("CANDIDATE", 23.0, 30.0),
        )
        result = extract_latency_features("my-uuid-123", turns)
        assert result.session_id == "my-uuid-123"

    def test_suspicion_score_always_in_unit_interval(self) -> None:
        turns = _turns(
            ("RECRUITER", 0.0, 5.0), ("CANDIDATE", 8.0, 14.0),
            ("RECRUITER", 15.0, 20.0), ("CANDIDATE", 23.0, 30.0),
        )
        result = extract_latency_features("s", turns)
        assert 0.0 <= result.suspicion_score <= 1.0
