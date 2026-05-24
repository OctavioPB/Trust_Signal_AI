"""Unit tests for ml/repo_score.py."""

from __future__ import annotations

import pytest

from ml.repo_score import (
    DEFAULT_WEIGHTS,
    RepoScoreEngine,
    RepoScoreResult,
    RepoSignalDetail,
    _build_flag_reason,
    _explain,
)


# ── Engine construction ────────────────────────────────────────────────────────

def test_default_weights_sum_to_one():
    assert abs(sum(DEFAULT_WEIGHTS.values()) - 1.0) < 1e-4


def test_engine_accepts_valid_weight_override():
    engine = RepoScoreEngine(weights={"code_perplexity": 0.40, "commit_pattern": 0.30, "code_style": 0.30})
    assert engine._weights["code_perplexity"] == pytest.approx(0.40)


def test_engine_raises_on_unknown_signal_key():
    with pytest.raises(ValueError, match="Unknown signal key"):
        RepoScoreEngine(weights={"nonexistent": 0.5})


def test_engine_raises_when_weights_do_not_sum_to_one():
    with pytest.raises(ValueError, match="sum to 1.0"):
        RepoScoreEngine(weights={"code_perplexity": 0.50, "commit_pattern": 0.50, "code_style": 0.50})


def test_engine_custom_threshold_accepted():
    engine = RepoScoreEngine(prescreening_threshold=0.80)
    assert engine._threshold == pytest.approx(0.80)


# ── compute() ─────────────────────────────────────────────────────────────────

def test_compute_returns_correct_type():
    engine = RepoScoreEngine()
    result = engine.compute("uuid-1", 0.5, 0.5, 0.5)
    assert isinstance(result, RepoScoreResult)


def test_compute_preserves_repo_uuid():
    engine = RepoScoreEngine()
    result = engine.compute("my-repo-uuid", 0.0, 0.0, 0.0)
    assert result.repo_uuid == "my-repo-uuid"


def test_compute_all_zero_scores():
    engine = RepoScoreEngine()
    result = engine.compute("uuid-zero", 0.0, 0.0, 0.0)

    assert result.repo_ai_score == pytest.approx(0.0)
    assert result.suspicion_index == pytest.approx(0.0)
    assert result.flagged is False
    assert result.flag_reason == ""


def test_compute_all_one_scores():
    engine = RepoScoreEngine()
    result = engine.compute("uuid-one", 1.0, 1.0, 1.0)

    assert result.repo_ai_score == pytest.approx(100.0)
    assert result.suspicion_index == pytest.approx(1.0)
    assert result.flagged is True
    assert len(result.flag_reason) > 0


def test_compute_ai_like_repo_flagged():
    """High signal scores → repo_ai_score ≥ 65, flagged = True."""
    engine = RepoScoreEngine(prescreening_threshold=0.65)
    result = engine.compute("uuid-ai", 0.90, 0.90, 0.85)

    assert result.repo_ai_score >= 65.0
    assert result.flagged is True


def test_compute_human_repo_not_flagged():
    """Low signal scores → repo_ai_score ≤ 35, flagged = False."""
    engine = RepoScoreEngine(prescreening_threshold=0.65)
    result = engine.compute("uuid-human", 0.10, 0.15, 0.10)

    assert result.repo_ai_score <= 35.0
    assert result.flagged is False


def test_compute_suspicion_index_in_unit_interval():
    engine = RepoScoreEngine()
    for ppl, commit, style in [(0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (0.5, 0.3, 0.8)]:
        result = engine.compute("uuid-range", ppl, commit, style)
        assert 0.0 <= result.suspicion_index <= 1.0


def test_compute_repo_ai_score_equals_index_times_100():
    engine = RepoScoreEngine()
    result = engine.compute("uuid-scale", 0.60, 0.40, 0.50)

    expected = result.suspicion_index * 100.0
    assert result.repo_ai_score == pytest.approx(expected, abs=0.01)


def test_compute_scores_clamped_to_unit_interval():
    """Input scores > 1.0 or < 0.0 are clamped before weighting."""
    engine = RepoScoreEngine()
    result_high = engine.compute("uuid-clamp-h", 2.0, 2.0, 2.0)
    result_low  = engine.compute("uuid-clamp-l", -1.0, -1.0, -1.0)

    assert result_high.suspicion_index == pytest.approx(1.0)
    assert result_low.suspicion_index  == pytest.approx(0.0)


def test_compute_signals_sorted_by_contribution_descending():
    engine = RepoScoreEngine()
    result = engine.compute("uuid-sort", 0.9, 0.3, 0.1)

    contribs = [s.weighted_contribution for s in result.signals]
    assert contribs == sorted(contribs, reverse=True)


def test_compute_three_signals_present():
    engine = RepoScoreEngine()
    result = engine.compute("uuid-3sig", 0.5, 0.5, 0.5)

    assert len(result.signals) == 3


def test_compute_signal_names_are_human_readable():
    engine = RepoScoreEngine()
    result = engine.compute("uuid-labels", 0.5, 0.5, 0.5)

    names = {s.signal_name for s in result.signals}
    assert "Code Perplexity" in names
    assert "Commit Pattern" in names
    assert "Code Style Uniformity" in names


def test_compute_flag_reason_nonempty_when_flagged():
    """CLAUDE.md §8.2: flag_reason must never be empty when flagged=True."""
    engine = RepoScoreEngine(prescreening_threshold=0.20)
    result = engine.compute("uuid-flag", 0.5, 0.5, 0.5)

    assert result.flagged is True
    assert len(result.flag_reason) > 0


def test_compute_flag_reason_empty_when_not_flagged():
    engine = RepoScoreEngine(prescreening_threshold=0.95)
    result = engine.compute("uuid-noflag", 0.3, 0.3, 0.3)

    assert result.flagged is False
    assert result.flag_reason == ""


def test_compute_scored_at_is_recent_timestamp():
    import time
    before = time.time()
    engine = RepoScoreEngine()
    result = engine.compute("uuid-ts", 0.5, 0.5, 0.5)
    after  = time.time()

    assert before <= result.scored_at <= after


# ── RepoSignalDetail ───────────────────────────────────────────────────────────

def test_signal_detail_weighted_contribution():
    engine = RepoScoreEngine()
    result = engine.compute("uuid-wd", 0.8, 0.0, 0.0)

    ppl_signal = next(s for s in result.signals if s.signal_name == "Code Perplexity")
    expected = 0.8 * DEFAULT_WEIGHTS["code_perplexity"]
    assert ppl_signal.weighted_contribution == pytest.approx(expected, rel=1e-4)


def test_signal_detail_explanation_nonempty():
    engine = RepoScoreEngine()
    result = engine.compute("uuid-exp", 0.5, 0.5, 0.5)

    for sig in result.signals:
        assert len(sig.explanation) > 0


# ── _explain ──────────────────────────────────────────────────────────────────

def test_explain_high_tier():
    explanation = _explain("code_perplexity", 0.9)
    assert "low" in explanation.lower() or "predictable" in explanation.lower()


def test_explain_medium_tier():
    explanation = _explain("code_perplexity", 0.5)
    assert "moderately" in explanation.lower() or "medium" in explanation.lower() or "moderate" in explanation.lower()


def test_explain_low_tier():
    explanation = _explain("code_perplexity", 0.1)
    assert "normal" in explanation.lower() or "natural" in explanation.lower() or "within" in explanation.lower()


def test_explain_all_signals_all_tiers():
    for key in ["code_perplexity", "commit_pattern", "code_style"]:
        for score in [0.1, 0.5, 0.9]:
            result = _explain(key, score)
            assert isinstance(result, str) and len(result) > 0


# ── _build_flag_reason ─────────────────────────────────────────────────────────

def test_build_flag_reason_nonempty():
    engine = RepoScoreEngine(prescreening_threshold=0.10)
    result = engine.compute("uuid-fr", 0.5, 0.5, 0.5)

    assert result.flagged is True
    reason = _build_flag_reason(result.signals, result.suspicion_index)
    assert len(reason) > 0


def test_build_flag_reason_contains_suspicion_index():
    engine = RepoScoreEngine(prescreening_threshold=0.10)
    result = engine.compute("uuid-si", 0.5, 0.5, 0.5)

    reason = _build_flag_reason(result.signals, result.suspicion_index)
    assert str(result.suspicion_index)[:4] in reason or "suspicion" in reason.lower()


def test_build_flag_reason_lists_top_signals():
    engine = RepoScoreEngine(prescreening_threshold=0.10)
    result = engine.compute("uuid-top", 0.9, 0.9, 0.9)

    reason = _build_flag_reason(result.signals, result.suspicion_index)
    assert "1." in reason


# ── PII invariant ─────────────────────────────────────────────────────────────

def test_result_has_no_pii_fields():
    engine = RepoScoreEngine()
    result = engine.compute("uuid-pii", 0.5, 0.5, 0.5)

    assert not hasattr(result, "author_name")
    assert not hasattr(result, "author_email")
    assert not hasattr(result, "candidate_name")
    assert not hasattr(result, "repo_owner")
