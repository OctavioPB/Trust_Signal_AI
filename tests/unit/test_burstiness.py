"""Regression and unit tests for ml/features/burstiness.py.

All tests are pure (no I/O, no model). Fixture texts are chosen so the expected
suspicion_score can be computed analytically from the documented CV→score mapping.

CV mapping (linear):
    score = clamp((0.80 - CV) / (0.80 - 0.20), 0, 1)
    CV ≤ 0.20 → 1.00  (uniform lengths → max suspicion)
    CV = 0.50 → 0.50  (midpoint)
    CV ≥ 0.80 → 0.00  (high variance → natural)
"""

from __future__ import annotations

import math

import pytest

from ml.features.burstiness import (
    BurstinessFeatures,
    _count_words,
    _score_from_cv,
    _split_sentences,
    score_burstiness,
)

SESSION = "test-session-001"


# ── _split_sentences ──────────────────────────────────────────────────────────

class TestSplitSentences:

    def test_period_boundary(self) -> None:
        result = _split_sentences("Hello world. This is a test. Done.")
        assert len(result) == 3

    def test_question_mark_boundary(self) -> None:
        result = _split_sentences("Is this right? Yes it is. Okay.")
        assert len(result) == 3

    def test_exclamation_boundary(self) -> None:
        result = _split_sentences("Wow! That is great. Indeed.")
        assert len(result) == 3

    def test_mixed_boundaries(self) -> None:
        result = _split_sentences("Really? Yes! And more.")
        assert len(result) == 3

    def test_empty_string_returns_empty(self) -> None:
        assert _split_sentences("") == []

    def test_whitespace_only_returns_empty(self) -> None:
        assert _split_sentences("   ") == []

    def test_no_boundary_returns_one_sentence(self) -> None:
        result = _split_sentences("This sentence has no ending punctuation")
        assert len(result) == 1

    def test_trailing_whitespace_stripped(self) -> None:
        sentences = _split_sentences("Hello world. Goodbye world.")
        for s in sentences:
            assert s == s.strip()


# ── _count_words ──────────────────────────────────────────────────────────────

class TestCountWords:

    def test_simple_sentence(self) -> None:
        assert _count_words("hello world foo") == 3

    def test_single_word(self) -> None:
        assert _count_words("hello") == 1

    def test_empty_string(self) -> None:
        assert _count_words("") == 0

    def test_extra_whitespace(self) -> None:
        assert _count_words("  hello   world  ") == 2


# ── _score_from_cv ────────────────────────────────────────────────────────────

class TestScoreFromCV:

    def test_cv_zero_returns_one(self) -> None:
        assert _score_from_cv(0.0) == pytest.approx(1.0)

    def test_cv_at_high_suspicion_threshold_returns_one(self) -> None:
        # CV = 0.20 → (0.80-0.20)/(0.80-0.20) = 1.0
        assert _score_from_cv(0.20) == pytest.approx(1.0, abs=1e-9)

    def test_cv_midpoint_returns_half(self) -> None:
        # CV = 0.50 → (0.80-0.50)/(0.60) = 0.5
        assert _score_from_cv(0.50) == pytest.approx(0.5, abs=1e-6)

    def test_cv_at_low_suspicion_threshold_returns_zero(self) -> None:
        assert _score_from_cv(0.80) == pytest.approx(0.0, abs=1e-9)

    def test_cv_above_threshold_clamped(self) -> None:
        assert _score_from_cv(1.5) == pytest.approx(0.0)
        assert _score_from_cv(100.0) == pytest.approx(0.0)

    def test_score_in_unit_interval(self) -> None:
        for cv in [0.0, 0.1, 0.2, 0.4, 0.6, 0.8, 1.0, 5.0]:
            s = _score_from_cv(cv)
            assert 0.0 <= s <= 1.0


# ── score_burstiness — error handling ────────────────────────────────────────

class TestScoreBurstinessErrors:

    def test_raises_on_empty_text(self) -> None:
        with pytest.raises(ValueError, match="3 sentences"):
            score_burstiness(SESSION, "")

    def test_raises_on_one_sentence(self) -> None:
        with pytest.raises(ValueError, match="3 sentences"):
            score_burstiness(SESSION, "This is a single sentence without others.")

    def test_raises_on_two_sentences(self) -> None:
        with pytest.raises(ValueError, match="3 sentences"):
            score_burstiness(SESSION, "First sentence. Second sentence.")

    def test_three_sentences_does_not_raise(self) -> None:
        result = score_burstiness(SESSION, "One word. Two words here. Three words in total.")
        assert isinstance(result, BurstinessFeatures)


# ── score_burstiness — computation ───────────────────────────────────────────

class TestScoreBurstiness:

    def test_uniform_sentences_max_suspicion(self) -> None:
        """All sentences same length → std=0 → CV=0 → score=1.0."""
        # 5 sentences, each exactly 5 words
        text = (
            "Alpha beta gamma delta epsilon. "
            "Zeta eta theta iota kappa. "
            "Lambda mu nu xi omicron. "
            "Pi rho sigma tau upsilon. "
            "Phi chi psi omega alpha."
        )
        result = score_burstiness(SESSION, text)
        assert result.cv == pytest.approx(0.0, abs=1e-9)
        assert result.suspicion_score == pytest.approx(1.0, abs=0.01)

    def test_highly_variable_sentences_low_suspicion(self) -> None:
        """Extreme length variation → high CV → score approaches 0."""
        # lengths: 1, 20, 1, 20, 1 → very high CV
        text = (
            "Hi. "
            "I have extensive experience in software engineering and have worked across "
            "multiple domains including infrastructure, data engineering, and machine learning. "
            "Yes. "
            "My background includes leading cross-functional teams through complex multi-month "
            "technical migrations while maintaining alignment with senior stakeholders across the org. "
            "Sure."
        )
        result = score_burstiness(SESSION, text)
        assert result.suspicion_score < 0.5

    def test_sentence_lengths_match_word_counts(self) -> None:
        text = "One. Two words. Three word sentence."
        result = score_burstiness(SESSION, text)
        assert result.sentence_lengths == [1, 2, 3]

    def test_cv_equals_std_over_mean(self) -> None:
        text = "One word. Two words here. Three full words now."
        result = score_burstiness(SESSION, text)
        import numpy as np
        arr = np.array(result.sentence_lengths, dtype=float)
        expected_cv = arr.std(ddof=1) / arr.mean()
        assert result.cv == pytest.approx(expected_cv, rel=1e-6)

    def test_suspicion_score_in_unit_interval(self) -> None:
        text = "Short. A bit longer now. This one is quite a lot longer than the previous ones."
        result = score_burstiness(SESSION, text)
        assert 0.0 <= result.suspicion_score <= 1.0

    def test_session_id_preserved(self) -> None:
        text = "Alpha beta. Gamma delta epsilon. Zeta eta theta iota."
        result = score_burstiness("my-session-uuid", text)
        assert result.session_id == "my-session-uuid"

    def test_text_preserved(self) -> None:
        text = "Alpha beta. Gamma delta epsilon. Zeta eta theta iota."
        result = score_burstiness(SESSION, text)
        assert result.text == text

    def test_returns_burstiness_features_instance(self) -> None:
        text = "One. Two words. Three words here."
        result = score_burstiness(SESSION, text)
        assert isinstance(result, BurstinessFeatures)

    # -- Regression fixtures (expected scores within ±0.05) --

    def test_ai_response_high_suspicion(self) -> None:
        """Canonical AI answer: uniform sentence structure → high suspicion."""
        ai_text = (
            "I am a highly motivated professional with extensive experience in the field. "
            "I have consistently delivered results across diverse and challenging environments. "
            "I pride myself on my ability to communicate clearly and collaborate effectively. "
            "I am passionate about continuous learning and professional development. "
            "I believe I would be a strong contributor to your organization and team."
        )
        result = score_burstiness(SESSION, ai_text)
        # AI text tends to have moderate-to-low CV → moderate-to-high suspicion
        assert result.suspicion_score > 0.3, (
            f"Expected AI text suspicion > 0.3, got {result.suspicion_score:.3f}"
        )

    def test_human_response_lower_suspicion_than_ai(self) -> None:
        """Human speech should score lower than uniform AI text."""
        ai_text = (
            "I am a highly motivated professional with extensive experience in the field. "
            "I have consistently delivered results across diverse and challenging environments. "
            "I pride myself on my ability to communicate clearly and collaborate effectively. "
            "I am passionate about continuous learning and professional development. "
            "I believe I would be a strong contributor to your organization and team."
        )
        human_text = (
            "Yeah so I started out kind of randomly. Um, did some web stuff. "
            "Then backend. I guess I just stuck with it. "
            "Honestly the first job was mostly figuring out how not to break things — "
            "like huge embarrassing bugs that you'd find on Friday at 5pm when everyone's trying to leave, "
            "and your manager's looking at you and you're looking at the logs and nothing makes sense. "
            "Fun times. "
            "But yeah, I learned a lot from that."
        )
        ai_result = score_burstiness(SESSION, ai_text)
        human_result = score_burstiness(SESSION, human_text)
        assert human_result.suspicion_score <= ai_result.suspicion_score, (
            f"Human text should have ≤ suspicion than AI: "
            f"human={human_result.suspicion_score:.3f}, ai={ai_result.suspicion_score:.3f}"
        )
