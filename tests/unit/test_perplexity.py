"""Regression and unit tests for ml/features/perplexity.py.

PerplexityScorer loads a real LM which is too slow for unit tests.
We inject stub tokenizer + model objects so no download is required.
Pure functions (_normalise_perplexity) are tested directly.
"""

from __future__ import annotations

import math
from unittest.mock import MagicMock, patch

import pytest
import torch

from ml.features.perplexity import (
    DEFAULT_MODEL,
    PerplexityFeatures,
    PerplexityScorer,
    _PPL_MAX_SUSPICION,
    _PPL_MIN_SUSPICION,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_scorer(fake_loss: float = 0.0) -> PerplexityScorer:
    """Return a PerplexityScorer backed by a stub tokenizer + model.

    The stub model always returns a forward pass with cross-entropy loss equal
    to ``fake_loss``, so perplexity = exp(fake_loss).

    Args:
        fake_loss: The mean NLL-per-token the stub model will report.
    """
    # Tokenizer stub: returns a dict with input_ids of length 10 so _MIN_TOKENS passes
    tokenizer_stub = MagicMock(name="tokenizer")
    tokenizer_stub.return_value = {
        "input_ids": torch.ones(1, 10, dtype=torch.long)
    }

    # Model stub: forward returns an object with .loss == fake_loss tensor
    model_output = MagicMock(name="ModelOutput")
    model_output.loss = torch.tensor(fake_loss)
    model_stub = MagicMock(name="model")
    model_stub.return_value = model_output

    return PerplexityScorer(_tokenizer=tokenizer_stub, _model=model_stub)


def _make_short_scorer() -> PerplexityScorer:
    """Return a scorer whose tokenizer reports only 3 tokens (below _MIN_TOKENS)."""
    tokenizer_stub = MagicMock(name="tokenizer")
    tokenizer_stub.return_value = {
        "input_ids": torch.ones(1, 3, dtype=torch.long)
    }
    model_stub = MagicMock(name="model")
    return PerplexityScorer(_tokenizer=tokenizer_stub, _model=model_stub)


# ── _normalise_perplexity ─────────────────────────────────────────────────────

class TestNormalisePerplexity:

    def test_at_low_boundary_returns_one(self) -> None:
        assert PerplexityScorer._normalise_perplexity(_PPL_MAX_SUSPICION) == pytest.approx(1.0)

    def test_below_low_boundary_clamped_to_one(self) -> None:
        assert PerplexityScorer._normalise_perplexity(1.0) == pytest.approx(1.0)
        assert PerplexityScorer._normalise_perplexity(0.0) == pytest.approx(1.0)

    def test_at_high_boundary_returns_zero(self) -> None:
        assert PerplexityScorer._normalise_perplexity(_PPL_MIN_SUSPICION) == pytest.approx(0.0)

    def test_above_high_boundary_clamped_to_zero(self) -> None:
        assert PerplexityScorer._normalise_perplexity(500.0) == pytest.approx(0.0)

    def test_midpoint(self) -> None:
        mid = (_PPL_MAX_SUSPICION + _PPL_MIN_SUSPICION) / 2   # 65.0
        assert PerplexityScorer._normalise_perplexity(mid) == pytest.approx(0.5, abs=1e-6)

    def test_score_in_unit_interval(self) -> None:
        for ppl in [1.0, 10.0, 30.0, 50.0, 65.0, 100.0, 200.0, 1000.0]:
            s = PerplexityScorer._normalise_perplexity(ppl)
            assert 0.0 <= s <= 1.0, f"score={s} out of [0,1] for ppl={ppl}"

    def test_monotonically_decreasing(self) -> None:
        """Higher perplexity → lower suspicion score."""
        ppls = [10.0, 30.0, 50.0, 65.0, 80.0, 100.0, 150.0]
        scores = [PerplexityScorer._normalise_perplexity(p) for p in ppls]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1], (
                f"score[{ppls[i]}]={scores[i]} < score[{ppls[i+1]}]={scores[i+1]}: not monotone"
            )


# ── PerplexityScorer.score ─────────────────────────────────────────────────────

class TestScore:

    def test_returns_perplexity_features(self) -> None:
        scorer = _make_scorer(fake_loss=0.5)
        result = scorer.score("sess-001", "This is a test sentence with enough tokens.")
        assert isinstance(result, PerplexityFeatures)

    def test_session_id_preserved(self) -> None:
        scorer = _make_scorer()
        result = scorer.score("uuid-xyz", "This is a test sentence with enough tokens.")
        assert result.session_id == "uuid-xyz"

    def test_text_preserved(self) -> None:
        scorer = _make_scorer()
        text = "Some candidate response text here."
        result = scorer.score("s", text)
        assert result.text == text

    def test_perplexity_equals_exp_loss(self) -> None:
        """perplexity = exp(model.loss)"""
        fake_loss = 3.5
        scorer = _make_scorer(fake_loss=fake_loss)
        result = scorer.score("s", "This is a test sentence with enough tokens.")
        assert result.perplexity == pytest.approx(math.exp(fake_loss), rel=1e-5)

    def test_suspicion_score_derived_from_perplexity(self) -> None:
        """suspicion_score must equal _normalise_perplexity(perplexity)."""
        fake_loss = 2.0
        scorer = _make_scorer(fake_loss=fake_loss)
        result = scorer.score("s", "This is a test sentence with enough tokens.")
        expected = PerplexityScorer._normalise_perplexity(result.perplexity)
        assert result.suspicion_score == pytest.approx(expected, rel=1e-6)

    def test_suspicion_score_in_unit_interval(self) -> None:
        for fake_loss in [0.0, 1.0, 3.5, 5.0, 10.0]:
            scorer = _make_scorer(fake_loss=fake_loss)
            result = scorer.score("s", "This is a test sentence with enough tokens.")
            assert 0.0 <= result.suspicion_score <= 1.0

    def test_low_loss_high_suspicion(self) -> None:
        """Loss ≈ 0 → perplexity ≈ 1.0 → very high suspicion."""
        scorer = _make_scorer(fake_loss=0.01)
        result = scorer.score("s", "This is a test sentence with enough tokens.")
        assert result.suspicion_score > 0.9

    def test_high_loss_low_suspicion(self) -> None:
        """Loss ≈ ln(500) → perplexity ≈ 500 → score = 0.0."""
        scorer = _make_scorer(fake_loss=math.log(500))
        result = scorer.score("s", "This is a test sentence with enough tokens.")
        assert result.suspicion_score == pytest.approx(0.0)

    def test_short_text_returns_zero_suspicion(self) -> None:
        """Text below _MIN_TOKENS must return suspicion_score = 0.0."""
        scorer = _make_short_scorer()
        result = scorer.score("s", "OK")
        assert result.suspicion_score == pytest.approx(0.0)
        assert math.isinf(result.perplexity)

    def test_injected_model_skips_download(self) -> None:
        """Constructor with _tokenizer and _model must not load from HuggingFace."""
        with patch("ml.features.perplexity.GPT2TokenizerFast") as mock_tok:
            with patch("ml.features.perplexity.GPT2LMHeadModel") as mock_mdl:
                _ = _make_scorer()
                mock_tok.from_pretrained.assert_not_called()
                mock_mdl.from_pretrained.assert_not_called()
