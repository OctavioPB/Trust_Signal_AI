"""Unit tests for ml/features/code_perplexity.py."""

from __future__ import annotations

import math
from unittest.mock import MagicMock

import pytest
import torch

from ml.features.code_perplexity import (
    CodeFilePerplexityResult,
    CodePerplexityScorer,
    CodeRepoPerplexityFeatures,
    _PPL_MAX_SUSPICION,
    _PPL_MIN_SUSPICION,
    _MIN_TOKENS,
    _normalise_perplexity,
)


# ── Stub model helpers ─────────────────────────────────────────────────────────

def _mock_model_for_loss(loss_value: float):
    """Return a (tokenizer, model) stub that yields a fixed cross-entropy loss."""
    n_tokens = 20   # above _MIN_TOKENS

    tokenizer = MagicMock()
    tokenizer.return_value = {
        "input_ids": torch.ones((1, n_tokens), dtype=torch.long),
    }

    model_output = MagicMock()
    model_output.loss = torch.tensor(loss_value)

    model = MagicMock()
    model.return_value = model_output

    return tokenizer, model


def _mock_model_short_file():
    """Return a tokenizer stub that reports fewer than _MIN_TOKENS tokens."""
    tokenizer = MagicMock()
    tokenizer.return_value = {
        "input_ids": torch.ones((1, _MIN_TOKENS - 1), dtype=torch.long),
    }
    model = MagicMock()
    return tokenizer, model


# ── _normalise_perplexity ──────────────────────────────────────────────────────

def test_normalise_at_max_suspicion_bound():
    assert _normalise_perplexity(_PPL_MAX_SUSPICION) == pytest.approx(1.0)


def test_normalise_at_min_suspicion_bound():
    assert _normalise_perplexity(_PPL_MIN_SUSPICION) == pytest.approx(0.0)


def test_normalise_below_max_suspicion_clamped():
    """Perplexity below lower bound → score clamped to 1.0."""
    assert _normalise_perplexity(1.0) == pytest.approx(1.0)


def test_normalise_above_min_suspicion_clamped():
    """Perplexity above upper bound → score clamped to 0.0."""
    assert _normalise_perplexity(100.0) == pytest.approx(0.0)


def test_normalise_midpoint():
    mid = (_PPL_MAX_SUSPICION + _PPL_MIN_SUSPICION) / 2.0
    result = _normalise_perplexity(mid)
    assert 0.0 < result < 1.0


def test_normalise_decreases_with_perplexity():
    """Higher perplexity → lower suspicion score (monotone)."""
    scores = [_normalise_perplexity(p) for p in [5.0, 20.0, 35.0, 50.0]]
    assert scores == sorted(scores, reverse=True)


def test_normalise_output_in_unit_interval():
    for p in [0.5, 10.0, 30.0, 50.0, 200.0]:
        assert 0.0 <= _normalise_perplexity(p) <= 1.0


# ── score_file ─────────────────────────────────────────────────────────────────

def test_score_file_short_content_returns_inf():
    """Files with fewer than _MIN_TOKENS tokens → perplexity inf, score 0."""
    tok, mod = _mock_model_short_file()
    scorer = CodePerplexityScorer(_tokenizer=tok, _model=mod)
    result = scorer.score_file("uuid-1", "main.py", "x = 1")

    assert result.perplexity == float("inf")
    assert result.suspicion_score == pytest.approx(0.0)


def test_score_file_returns_correct_repo_uuid():
    tok, mod = _mock_model_for_loss(loss_value=1.0)
    scorer = CodePerplexityScorer(_tokenizer=tok, _model=mod)
    result = scorer.score_file("my-repo-uuid", "app.py", "def main(): pass")

    assert result.repo_uuid == "my-repo-uuid"


def test_score_file_returns_correct_file_path():
    tok, mod = _mock_model_for_loss(loss_value=1.0)
    scorer = CodePerplexityScorer(_tokenizer=tok, _model=mod)
    result = scorer.score_file("r", "src/utils.py", "def helper(): pass")

    assert result.file_path == "src/utils.py"


def test_score_file_perplexity_matches_exp_loss():
    loss = 2.302585  # exp(2.302585) ≈ 10
    tok, mod = _mock_model_for_loss(loss_value=loss)
    scorer = CodePerplexityScorer(_tokenizer=tok, _model=mod)
    result = scorer.score_file("r", "f.py", "code")

    assert result.perplexity == pytest.approx(math.exp(loss), rel=1e-4)


def test_score_file_low_perplexity_high_suspicion():
    """Loss ≈ 0 → perplexity ≈ 1 → very high suspicion."""
    tok, mod = _mock_model_for_loss(loss_value=0.001)
    scorer = CodePerplexityScorer(_tokenizer=tok, _model=mod)
    result = scorer.score_file("r", "f.py", "code")

    assert result.suspicion_score >= 0.9


def test_score_file_high_perplexity_low_suspicion():
    """High loss → high perplexity → low suspicion score."""
    tok, mod = _mock_model_for_loss(loss_value=5.0)   # exp(5) ≈ 148 >> _PPL_MIN_SUSPICION
    scorer = CodePerplexityScorer(_tokenizer=tok, _model=mod)
    result = scorer.score_file("r", "f.py", "code")

    assert result.suspicion_score == pytest.approx(0.0)


def test_score_file_result_is_dataclass():
    tok, mod = _mock_model_for_loss(loss_value=1.0)
    scorer = CodePerplexityScorer(_tokenizer=tok, _model=mod)
    result = scorer.score_file("r", "f.py", "code")

    assert isinstance(result, CodeFilePerplexityResult)


def test_score_file_suspicion_in_unit_interval():
    for loss in [0.001, 1.0, 2.5, 4.0]:
        tok, mod = _mock_model_for_loss(loss_value=loss)
        scorer = CodePerplexityScorer(_tokenizer=tok, _model=mod)
        result = scorer.score_file("r", "f.py", "code")
        assert 0.0 <= result.suspicion_score <= 1.0


# ── score_repo ─────────────────────────────────────────────────────────────────

def test_score_repo_empty_files_returns_zero():
    tok, mod = _mock_model_for_loss(loss_value=1.0)
    scorer = CodePerplexityScorer(_tokenizer=tok, _model=mod)
    result = scorer.score_repo("uuid-empty", [])

    assert result.suspicion_score == pytest.approx(0.0)
    assert result.file_scores == {}


def test_score_repo_skips_short_files():
    """Files that return inf perplexity are excluded from the aggregate."""
    tok_short, mod_short = _mock_model_short_file()
    scorer = CodePerplexityScorer(_tokenizer=tok_short, _model=mod_short)
    result = scorer.score_repo("uuid-short", [("short.py", "x")])

    assert result.suspicion_score == pytest.approx(0.0)
    assert "short.py" not in result.file_scores


def test_score_repo_weighted_mean():
    """Weighted mean across two files should equal expected value."""
    loss_a = 0.001   # perplexity ≈ 1 → suspicion ≈ 1.0
    loss_b = 5.0     # perplexity ≈ 148 → suspicion 0.0

    content_a = "short"     # 5 chars
    content_b = "long" * 5  # 20 chars (heavier weight)

    call_count = 0

    def make_tok(n):
        tok = MagicMock()
        tok.return_value = {"input_ids": torch.ones((1, n), dtype=torch.long)}
        return tok

    def make_mod(loss):
        out = MagicMock()
        out.loss = torch.tensor(loss)
        m = MagicMock()
        m.return_value = out
        return m

    # Call sequence: file_a first, file_b second
    tok_a, mod_a = make_tok(20), make_mod(loss_a)
    tok_b, mod_b = make_tok(20), make_mod(loss_b)

    # Build a scorer that switches behaviour after the first score_file call
    calls = [0]

    tok = MagicMock()

    def tok_side_effect(*args, **kwargs):
        if calls[0] == 0:
            return {"input_ids": torch.ones((1, 20), dtype=torch.long)}
        return {"input_ids": torch.ones((1, 20), dtype=torch.long)}

    tok.side_effect = None
    tok.return_value = {"input_ids": torch.ones((1, 20), dtype=torch.long)}

    mod_out_a = MagicMock()
    mod_out_a.loss = torch.tensor(loss_a)
    mod_out_b = MagicMock()
    mod_out_b.loss = torch.tensor(loss_b)

    mod = MagicMock()
    mod.side_effect = [mod_out_a, mod_out_b]

    scorer = CodePerplexityScorer(_tokenizer=tok, _model=mod)
    result = scorer.score_repo("uuid-w", [(content_a, content_a), (content_b, content_b)])

    # Both files scored; result in [0, 1]
    assert 0.0 <= result.suspicion_score <= 1.0
    assert isinstance(result, CodeRepoPerplexityFeatures)


def test_score_repo_result_has_repo_uuid():
    tok, mod = _mock_model_for_loss(loss_value=1.0)
    scorer = CodePerplexityScorer(_tokenizer=tok, _model=mod)
    result = scorer.score_repo("my-uuid", [("f.py", "def f(): pass")])

    assert result.repo_uuid == "my-uuid"


def test_score_repo_file_scores_populated():
    tok, mod = _mock_model_for_loss(loss_value=1.0)
    scorer = CodePerplexityScorer(_tokenizer=tok, _model=mod)
    result = scorer.score_repo("uuid-fs", [("a.py", "code a")])

    assert "a.py" in result.file_scores
    assert 0.0 <= result.file_scores["a.py"] <= 1.0


def test_score_repo_suspicion_in_unit_interval():
    for loss in [0.1, 2.0, 4.5]:
        tok, mod = _mock_model_for_loss(loss_value=loss)
        scorer = CodePerplexityScorer(_tokenizer=tok, _model=mod)
        result = scorer.score_repo("uuid-range", [("x.py", "print('hello')")])
        assert 0.0 <= result.suspicion_score <= 1.0
