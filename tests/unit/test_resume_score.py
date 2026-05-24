"""Unit tests for ml/resume_score.py."""

from __future__ import annotations

import time

import pytest

from ml.resume_score import (
    DEFAULT_WEIGHTS,
    ResumeScoreEngine,
    ResumeScoreResult,
    ResumeSignalDetail,
    _build_flag_reason,
    _explain,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

# Scores consistent with AI-generated resume: all signals elevated
_AI_SCORES: dict[str, float] = {
    "perplexity_score":         0.90,
    "burstiness_score":         0.90,
    "vocab_richness_score":     0.80,
    "section_uniformity_score": 0.85,
}

# Scores consistent with authentic human resume: all signals low
_HUMAN_SCORES: dict[str, float] = {
    "perplexity_score":         0.10,
    "burstiness_score":         0.20,
    "vocab_richness_score":     0.15,
    "section_uniformity_score": 0.25,
}

# suspicion_index for _AI_SCORES:
#   0.90×0.30 + 0.90×0.25 + 0.80×0.25 + 0.85×0.20 = 0.27+0.225+0.20+0.17 = 0.865 → score 86.5
# suspicion_index for _HUMAN_SCORES:
#   0.10×0.30 + 0.20×0.25 + 0.15×0.25 + 0.25×0.20 = 0.03+0.05+0.0375+0.05 = 0.1675 → score 16.75


# ── Regression: score bands ────────────────────────────────────────────────────

def test_ai_resume_score_above_65():
    """AI-like signals must produce resume_ai_score ≥ 65."""
    engine = ResumeScoreEngine()
    result = engine.compute("uuid-ai", **_AI_SCORES)
    assert result.resume_ai_score >= 65.0, (
        f"Expected ≥ 65 for AI resume, got {result.resume_ai_score}"
    )


def test_human_resume_score_below_35():
    """Human-like signals must produce resume_ai_score ≤ 35."""
    engine = ResumeScoreEngine()
    result = engine.compute("uuid-human", **_HUMAN_SCORES)
    assert result.resume_ai_score <= 35.0, (
        f"Expected ≤ 35 for human resume, got {result.resume_ai_score}"
    )


# ── Flagging behaviour ─────────────────────────────────────────────────────────

def test_flagged_when_above_threshold():
    """Resume is flagged when suspicion_index ≥ prescreening_threshold."""
    engine = ResumeScoreEngine(prescreening_threshold=0.65)
    result = engine.compute("uuid-flag", **_AI_SCORES)
    assert result.flagged is True


def test_not_flagged_when_below_threshold():
    """Resume is not flagged when suspicion_index < prescreening_threshold."""
    engine = ResumeScoreEngine(prescreening_threshold=0.65)
    result = engine.compute("uuid-noflag", **_HUMAN_SCORES)
    assert result.flagged is False


# ── CLAUDE.md §8.2 invariant ───────────────────────────────────────────────────

def test_flag_reason_non_empty_when_flagged():
    """Per CLAUDE.md §8.2: flag_reason must never be empty when flagged=True."""
    engine = ResumeScoreEngine(prescreening_threshold=0.65)
    result = engine.compute("uuid-reason", **_AI_SCORES)
    assert result.flagged is True
    assert result.flag_reason != "", "flag_reason must not be empty when flagged"
    assert len(result.flag_reason) > 20


def test_flag_reason_empty_when_not_flagged():
    """flag_reason must be an empty string when flagged=False."""
    engine = ResumeScoreEngine(prescreening_threshold=0.65)
    result = engine.compute("uuid-no-reason", **_HUMAN_SCORES)
    assert result.flagged is False
    assert result.flag_reason == ""


def test_flag_reason_mentions_suspicion_index():
    """flag_reason includes the suspicion index value."""
    engine = ResumeScoreEngine(prescreening_threshold=0.50)
    result = engine.compute("uuid-fr-idx", **_AI_SCORES)
    assert "suspicion index" in result.flag_reason.lower()


def test_flag_reason_includes_signal_details():
    """flag_reason includes signal name, score, and weight for top signals."""
    engine = ResumeScoreEngine(prescreening_threshold=0.50)
    result = engine.compute("uuid-fr-details", **_AI_SCORES)
    assert "score=" in result.flag_reason
    assert "weight=" in result.flag_reason


# ── Score range invariant ──────────────────────────────────────────────────────

def test_resume_ai_score_in_0_to_100():
    """resume_ai_score is always in [0, 100]."""
    engine = ResumeScoreEngine()
    for scores in [
        _AI_SCORES,
        _HUMAN_SCORES,
        {"perplexity_score": 0.0, "burstiness_score": 0.0,
         "vocab_richness_score": 0.0, "section_uniformity_score": 0.0},
    ]:
        result = engine.compute("uuid-range", **scores)
        assert 0.0 <= result.resume_ai_score <= 100.0


def test_suspicion_index_in_unit_interval():
    """suspicion_index is always in [0, 1]."""
    engine = ResumeScoreEngine()
    result = engine.compute("uuid-idx", **_AI_SCORES)
    assert 0.0 <= result.suspicion_index <= 1.0


def test_out_of_range_inputs_clamped():
    """Input scores outside [0, 1] are clamped before weighting."""
    engine = ResumeScoreEngine()
    result = engine.compute(
        "uuid-clamp",
        perplexity_score=5.0,       # above 1 → clamped to 1.0
        burstiness_score=-2.0,       # below 0 → clamped to 0.0
        vocab_richness_score=1.5,    # above 1 → clamped to 1.0
        section_uniformity_score=0.5,
    )
    assert 0.0 <= result.resume_ai_score <= 100.0
    assert 0.0 <= result.suspicion_index <= 1.0


# ── Signal breakdown ───────────────────────────────────────────────────────────

def test_signals_count_is_four():
    """Result always contains exactly 4 signal entries."""
    engine = ResumeScoreEngine()
    result = engine.compute("uuid-count", **_AI_SCORES)
    assert len(result.signals) == 4


def test_signal_names_all_present():
    """All four signal names appear in the breakdown."""
    engine = ResumeScoreEngine()
    result = engine.compute("uuid-names", **_AI_SCORES)
    names = {s.signal_name for s in result.signals}
    assert "Perplexity" in names
    assert "Burstiness" in names
    assert "Vocabulary Richness" in names
    assert "Section Style Uniformity" in names


def test_signals_sorted_by_contribution_descending():
    """Signals are sorted by weighted_contribution from highest to lowest."""
    engine = ResumeScoreEngine()
    result = engine.compute("uuid-sort", **_AI_SCORES)
    contributions = [s.weighted_contribution for s in result.signals]
    assert contributions == sorted(contributions, reverse=True)


def test_weighted_contributions_sum_to_suspicion_index():
    """Sum of weighted_contribution values equals suspicion_index (within rounding)."""
    engine = ResumeScoreEngine()
    result = engine.compute("uuid-sum", **_AI_SCORES)
    total = sum(s.weighted_contribution for s in result.signals)
    assert abs(total - result.suspicion_index) < 1e-3


def test_signal_detail_fields_populated():
    """Each ResumeSignalDetail has non-empty signal_name and explanation."""
    engine = ResumeScoreEngine()
    result = engine.compute("uuid-fields", **_AI_SCORES)
    for sig in result.signals:
        assert sig.signal_name
        assert sig.explanation
        assert 0.0 <= sig.raw_score <= 1.0
        assert 0.0 <= sig.weight <= 1.0
        assert sig.weighted_contribution == pytest.approx(
            sig.raw_score * sig.weight, abs=1e-6
        )


# ── Weight validation ──────────────────────────────────────────────────────────

def test_weights_not_summing_to_one_raises():
    """Custom weights that do not sum to 1.0 ± 1e-4 raise ValueError."""
    with pytest.raises(ValueError, match="sum to 1.0"):
        ResumeScoreEngine(weights={
            "perplexity": 0.99,
            "burstiness": 0.25,
            "vocab_richness": 0.25,
            "section_uniformity": 0.20,
        })


def test_unknown_weight_key_raises():
    """Unknown signal key in weight overrides raises ValueError."""
    with pytest.raises(ValueError, match="Unknown signal key"):
        ResumeScoreEngine(weights={"nonexistent_signal": 0.30})


def test_custom_weights_respected():
    """Custom weights change the weighted contributions proportionally."""
    engine = ResumeScoreEngine(weights={
        "perplexity":         0.40,
        "burstiness":         0.20,
        "vocab_richness":     0.20,
        "section_uniformity": 0.20,
    })
    result = engine.compute("uuid-custom-w", **_AI_SCORES)
    perp_signal = next(s for s in result.signals if s.signal_name == "Perplexity")
    assert abs(perp_signal.weight - 0.40) < 1e-6


def test_custom_threshold_respected():
    """prescreening_threshold at a very low value flags even low-scoring resumes."""
    engine = ResumeScoreEngine(prescreening_threshold=0.05)
    result = engine.compute("uuid-strict", **_HUMAN_SCORES)
    # suspicion_index ≈ 0.1675 which is > 0.05
    assert result.flagged is True


# ── Result metadata ────────────────────────────────────────────────────────────

def test_candidate_uuid_preserved():
    """candidate_uuid in result matches the input UUID."""
    engine = ResumeScoreEngine()
    result = engine.compute("uuid-preserve", **_AI_SCORES)
    assert result.candidate_uuid == "uuid-preserve"


def test_scored_at_is_recent_timestamp():
    """scored_at is a recent Unix timestamp (within 60 seconds of now)."""
    before = time.time()
    engine = ResumeScoreEngine()
    result = engine.compute("uuid-ts", **_AI_SCORES)
    after = time.time()
    assert before <= result.scored_at <= after + 1.0


def test_resume_ai_score_is_suspicion_index_times_100():
    """resume_ai_score == round(suspicion_index × 100, 2)."""
    engine = ResumeScoreEngine()
    result = engine.compute("uuid-formula", **_AI_SCORES)
    expected = round(result.suspicion_index * 100.0, 2)
    assert result.resume_ai_score == pytest.approx(expected, abs=1e-6)


# ── _explain ──────────────────────────────────────────────────────────────────

def test_explain_returns_different_strings_per_tier():
    """High / medium / low scores yield distinct explanation strings."""
    high = _explain("perplexity", 0.80)
    med = _explain("perplexity", 0.50)
    low = _explain("perplexity", 0.10)
    assert high != med
    assert med != low
    assert high != low


def test_explain_all_signal_keys():
    """_explain works for all four signal keys without raising."""
    for key in DEFAULT_WEIGHTS:
        _explain(key, 0.8)   # high tier
        _explain(key, 0.5)   # medium tier
        _explain(key, 0.1)   # low tier


# ── _build_flag_reason ────────────────────────────────────────────────────────

def test_build_flag_reason_non_empty():
    """_build_flag_reason always returns a non-empty string."""
    engine = ResumeScoreEngine(prescreening_threshold=0.50)
    result = engine.compute("uuid-bfr", **_AI_SCORES)
    reason = _build_flag_reason(result.signals, result.suspicion_index)
    assert reason != ""


def test_build_flag_reason_contains_signal_label():
    """_build_flag_reason output contains at least one signal label."""
    engine = ResumeScoreEngine(prescreening_threshold=0.50)
    result = engine.compute("uuid-bfr2", **_AI_SCORES)
    reason = _build_flag_reason(result.signals, result.suspicion_index)
    labels = {"Perplexity", "Burstiness", "Vocabulary Richness", "Section Style Uniformity"}
    assert any(label in reason for label in labels)
