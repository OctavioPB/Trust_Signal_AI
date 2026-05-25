"""Unit tests for ml/prescreening_score.py."""

from __future__ import annotations

import pytest

from ml.prescreening_score import (
    PreScreeningEngine,
    PreScreeningResult,
    PreScreeningSignalDetail,
    _W_INTERVIEW,
    _W_REPO,
    _W_RESUME,
    _build_flag_reason,
    _determine_severity,
    _explain,
    _resolve_weights,
)


# ── _resolve_weights ───────────────────────────────────────────────────────────

def test_resolve_weights_all_three_sum_to_one():
    w = _resolve_weights(0.5, 0.5, 0.5)
    total = sum(weight for _, weight in w.values())
    assert total == pytest.approx(1.0, abs=1e-6)


def test_resolve_weights_all_three_default_proportions():
    w = _resolve_weights(0.5, 0.5, 0.5)
    assert set(w.keys()) == {"resume", "repo", "interview"}
    # With default proportions (35/35/30) scaled by 1/1.0:
    assert w["resume"][1] == pytest.approx(_W_RESUME, rel=1e-4)
    assert w["repo"][1] == pytest.approx(_W_REPO, rel=1e-4)
    assert w["interview"][1] == pytest.approx(_W_INTERVIEW, rel=1e-4)


def test_resolve_weights_no_interview_sums_to_one():
    w = _resolve_weights(0.5, 0.5, None)
    total = sum(weight for _, weight in w.values())
    assert total == pytest.approx(1.0, abs=1e-6)


def test_resolve_weights_no_interview_equal_resume_repo():
    """Resume and repo should each get 50 % when interview absent."""
    w = _resolve_weights(0.5, 0.5, None)
    assert w["resume"][1] == pytest.approx(0.50, abs=1e-6)
    assert w["repo"][1]   == pytest.approx(0.50, abs=1e-6)
    assert "interview" not in w


def test_resolve_weights_no_repo_sums_to_one():
    w = _resolve_weights(0.5, None, 0.5)
    total = sum(weight for _, weight in w.values())
    assert total == pytest.approx(1.0, abs=1e-6)


def test_resolve_weights_no_repo_no_interview_resume_gets_all():
    w = _resolve_weights(0.7, None, None)
    assert set(w.keys()) == {"resume"}
    assert w["resume"][1] == pytest.approx(1.0, abs=1e-6)


def test_resolve_weights_suspicion_values_preserved():
    w = _resolve_weights(0.3, 0.7, None)
    assert w["resume"][0] == pytest.approx(0.3, abs=1e-6)
    assert w["repo"][0]   == pytest.approx(0.7, abs=1e-6)


# ── _determine_severity ────────────────────────────────────────────────────────

def test_severity_low_when_not_flagged():
    assert _determine_severity(False, None, 40.0) == "low"
    assert _determine_severity(False, 20.0, 40.0) == "low"


def test_severity_medium_when_flagged_no_interview():
    assert _determine_severity(True, None, 40.0) == "medium"


def test_severity_medium_when_flagged_interview_above_threshold():
    assert _determine_severity(True, 50.0, 40.0) == "medium"


def test_severity_high_when_flagged_and_interview_below_threshold():
    assert _determine_severity(True, 30.0, 40.0) == "high"


def test_severity_high_boundary_exclusive():
    """At exactly 40.0 the condition is trust < 40 → not high."""
    assert _determine_severity(True, 40.0, 40.0) == "medium"


def test_severity_high_boundary_just_below():
    assert _determine_severity(True, 39.9, 40.0) == "high"


# ── PreScreeningEngine.compute ─────────────────────────────────────────────────

def test_compute_returns_correct_type():
    engine = PreScreeningEngine()
    result = engine.compute("uuid-1", 50.0)
    assert isinstance(result, PreScreeningResult)


def test_compute_preserves_candidate_uuid():
    engine = PreScreeningEngine()
    result = engine.compute("my-uuid", 0.0)
    assert result.candidate_uuid == "my-uuid"


def test_compute_all_zero_scores():
    engine = PreScreeningEngine()
    result = engine.compute("uuid-zero", 0.0)
    assert result.prescreening_score == pytest.approx(0.0)
    assert result.suspicion_index    == pytest.approx(0.0)
    assert result.flagged is False
    assert result.flag_reason == ""
    assert result.severity == "low"


def test_compute_all_max_scores():
    engine = PreScreeningEngine()
    result = engine.compute("uuid-max", 100.0, 100.0, 0.0)   # trust=0 → interview_susp=1.0
    assert result.prescreening_score == pytest.approx(100.0)
    assert result.suspicion_index    == pytest.approx(1.0)
    assert result.flagged is True


def test_compute_prescreening_equals_index_times_100():
    engine = PreScreeningEngine()
    result = engine.compute("uuid-scale", 60.0, 40.0, 50.0)
    assert result.prescreening_score == pytest.approx(result.suspicion_index * 100.0, abs=0.01)


def test_compute_suspicion_index_in_unit_interval():
    engine = PreScreeningEngine()
    for r, repo, itv in [
        (0.0, None, None),
        (100.0, 100.0, 0.0),
        (50.0, 50.0, 50.0),
        (80.0, None, None),
    ]:
        result = engine.compute("uuid-range", r, repo, itv)
        assert 0.0 <= result.suspicion_index <= 1.0


def test_compute_interview_trust_inverted():
    """TrustScore 0 → suspicion 1.0; TrustScore 100 → suspicion 0.0."""
    engine = PreScreeningEngine()
    low_trust  = engine.compute("uuid-lt", 50.0, interview_trust_score=0.0)
    high_trust = engine.compute("uuid-ht", 50.0, interview_trust_score=100.0)
    assert low_trust.prescreening_score > high_trust.prescreening_score


def test_compute_flagged_when_above_threshold():
    engine = PreScreeningEngine(prescreening_threshold=0.30)
    result = engine.compute("uuid-flag", 80.0)
    assert result.flagged is True


def test_compute_not_flagged_when_below_threshold():
    engine = PreScreeningEngine(prescreening_threshold=0.80)
    result = engine.compute("uuid-noflag", 20.0)
    assert result.flagged is False


def test_compute_flag_reason_nonempty_when_flagged():
    """CLAUDE.md §8.2: flag_reason never empty when flagged=True."""
    engine = PreScreeningEngine(prescreening_threshold=0.10)
    result = engine.compute("uuid-fr", 80.0)
    assert result.flagged is True
    assert len(result.flag_reason) > 0


def test_compute_flag_reason_empty_when_not_flagged():
    engine = PreScreeningEngine(prescreening_threshold=0.95)
    result = engine.compute("uuid-nofr", 20.0)
    assert result.flagged is False
    assert result.flag_reason == ""


def test_compute_severity_high_with_low_interview_trust():
    engine = PreScreeningEngine(prescreening_threshold=0.10, interview_high_threshold=40.0)
    result = engine.compute("uuid-high", 80.0, interview_trust_score=20.0)
    assert result.severity == "high"


def test_compute_severity_medium_without_interview():
    engine = PreScreeningEngine(prescreening_threshold=0.10)
    result = engine.compute("uuid-med", 80.0)
    assert result.severity == "medium"


def test_compute_interview_available_flag():
    engine = PreScreeningEngine()
    with_interview    = engine.compute("u1", 50.0, interview_trust_score=60.0)
    without_interview = engine.compute("u2", 50.0)
    assert with_interview.interview_available is True
    assert without_interview.interview_available is False


def test_compute_repo_available_flag():
    engine = PreScreeningEngine()
    with_repo    = engine.compute("u1", 50.0, repo_ai_score=40.0)
    without_repo = engine.compute("u2", 50.0)
    assert with_repo.repo_available is True
    assert without_repo.repo_available is False


def test_compute_signals_sorted_by_contribution():
    engine = PreScreeningEngine()
    result = engine.compute("uuid-sort", 90.0, 10.0)
    contribs = [s.weighted_contribution for s in result.signals]
    assert contribs == sorted(contribs, reverse=True)


def test_compute_signal_names_human_readable():
    engine = PreScreeningEngine()
    result = engine.compute("uuid-names", 50.0, 50.0, 50.0)
    names  = {s.signal_name for s in result.signals}
    assert "Resume AI Score" in names
    assert "Repo AI Score" in names
    assert "Interview Trust (inverted)" in names


def test_compute_resume_only_has_one_signal():
    engine = PreScreeningEngine()
    result = engine.compute("uuid-resume-only", 60.0)
    assert len(result.signals) == 1
    assert result.signals[0].signal_name == "Resume AI Score"
    assert result.signals[0].weight == pytest.approx(1.0, abs=1e-4)


def test_compute_input_scores_clamped():
    engine = PreScreeningEngine()
    above  = engine.compute("uuid-above", 200.0)
    below  = engine.compute("uuid-below", -50.0)
    assert above.suspicion_index == pytest.approx(1.0)
    assert below.suspicion_index == pytest.approx(0.0)


def test_compute_scored_at_is_recent():
    import time
    before = time.time()
    engine = PreScreeningEngine()
    result = engine.compute("uuid-ts", 50.0)
    after  = time.time()
    assert before <= result.scored_at <= after


# ── AI / human regression bands ───────────────────────────────────────────────

def test_ai_candidate_score_above_65():
    """All high-suspicion signals → prescreening_score ≥ 65."""
    engine = PreScreeningEngine(prescreening_threshold=0.65)
    result = engine.compute("uuid-ai", 90.0, 88.0, 15.0)   # trust=15 → susp=0.85
    assert result.prescreening_score >= 65.0
    assert result.flagged is True


def test_human_candidate_score_below_35():
    """All low-suspicion signals → prescreening_score ≤ 35."""
    engine = PreScreeningEngine(prescreening_threshold=0.65)
    result = engine.compute("uuid-human", 10.0, 12.0, 85.0)  # trust=85 → susp=0.15
    assert result.prescreening_score <= 35.0
    assert result.flagged is False


# ── PII invariant ─────────────────────────────────────────────────────────────

def test_result_has_no_pii_fields():
    engine = PreScreeningEngine()
    result = engine.compute("uuid-pii", 50.0)
    assert not hasattr(result, "name")
    assert not hasattr(result, "email")
    assert not hasattr(result, "author_name")
