"""Unit tests for ml/cross_correlation.py."""

from __future__ import annotations

import math

import numpy as np
import pytest

from ml.cross_correlation import (
    CrossCorrelationFeatures,
    CrossCorrelationScorer,
    _W_COHERENCE,
    _W_STYLE,
    _cosine_similarity,
    _sentence_length_variance,
    _variance_delta,
)


# ── Stub model helper ──────────────────────────────────────────────────────────

def _mock_model(embeddings: dict[str, np.ndarray]):
    """Return a MagicMock whose .encode() returns a fixed embedding per call."""
    from unittest.mock import MagicMock
    model = MagicMock()
    calls = {"n": 0}
    values = list(embeddings.values())

    def encode_side_effect(text, *args, **kwargs):
        idx = calls["n"]
        calls["n"] += 1
        return values[idx % len(values)]

    model.encode.side_effect = encode_side_effect
    return model


def _unit(dim: int = 4) -> np.ndarray:
    v = np.ones(dim)
    return v / np.linalg.norm(v)


def _orthogonal(dim: int = 4) -> np.ndarray:
    v = np.zeros(dim)
    v[0] = 1.0
    return v


# ── _cosine_similarity ─────────────────────────────────────────────────────────

def test_cosine_similarity_identical_vectors():
    v = _unit()
    assert _cosine_similarity(v, v) == pytest.approx(1.0, abs=1e-6)


def test_cosine_similarity_orthogonal_vectors():
    a = np.array([1.0, 0.0, 0.0, 0.0])
    b = np.array([0.0, 1.0, 0.0, 0.0])
    assert _cosine_similarity(a, b) == pytest.approx(0.0, abs=1e-6)


def test_cosine_similarity_zero_vector_returns_zero():
    v  = _unit()
    z  = np.zeros(4)
    assert _cosine_similarity(v, z) == pytest.approx(0.0)
    assert _cosine_similarity(z, v) == pytest.approx(0.0)


def test_cosine_similarity_in_range():
    a = np.random.rand(8)
    b = np.random.rand(8)
    sim = _cosine_similarity(a, b)
    assert -1.0 <= sim <= 1.0


# ── _sentence_length_variance ──────────────────────────────────────────────────

def test_sentence_length_variance_single_sentence():
    assert _sentence_length_variance("Hello world.") == pytest.approx(0.0)


def test_sentence_length_variance_identical_lengths():
    text = "abc. abc. abc. abc."
    assert _sentence_length_variance(text) == pytest.approx(0.0, abs=1e-6)


def test_sentence_length_variance_varied():
    text = "A. " + "B" * 50 + ". " + "C" * 10 + "."
    var = _sentence_length_variance(text)
    assert var > 0.0


def test_sentence_length_variance_increases_with_diversity():
    uniform = "abc. abc. abc. abc. abc."
    varied  = "Hi. " + "x" * 80 + ". Short. " + "y" * 120 + "."
    assert _sentence_length_variance(varied) > _sentence_length_variance(uniform)


def test_sentence_length_variance_empty_string():
    assert _sentence_length_variance("") == pytest.approx(0.0)


# ── _variance_delta ────────────────────────────────────────────────────────────

def test_variance_delta_identical_variances():
    assert _variance_delta(5.0, 5.0) == pytest.approx(0.0, abs=1e-6)


def test_variance_delta_in_unit_interval():
    for a, b in [(0.0, 0.0), (1.0, 100.0), (50.0, 200.0)]:
        assert 0.0 <= _variance_delta(a, b) <= 1.0


def test_variance_delta_increases_with_difference():
    small_diff = _variance_delta(10.0, 12.0)
    large_diff = _variance_delta(10.0, 500.0)
    assert large_diff > small_diff


def test_variance_delta_symmetric():
    assert _variance_delta(10.0, 50.0) == pytest.approx(_variance_delta(50.0, 10.0))


# ── CrossCorrelationScorer.score ───────────────────────────────────────────────

def test_score_returns_dataclass():
    model = _mock_model({"a": _unit(), "b": _unit()})
    scorer = CrossCorrelationScorer(_model=model)
    result = scorer.score("uuid-1", "Python Go Rust", "Python Go", None, None)
    assert isinstance(result, CrossCorrelationFeatures)


def test_score_preserves_uuid():
    model = _mock_model({"a": _unit(), "b": _unit()})
    scorer = CrossCorrelationScorer(_model=model)
    result = scorer.score("my-uuid", "skills", "readme", None, None)
    assert result.candidate_uuid == "my-uuid"


def test_score_coherent_candidate_low_suspicion():
    """Identical embeddings → cosine sim 1.0 → coherence_suspicion ≈ 0."""
    v = _unit()
    model = _mock_model({"a": v, "b": v})
    scorer = CrossCorrelationScorer(_model=model)
    result = scorer.score("uuid-coh", "Python", "Python code repo", None, None)

    assert result.skill_coherence_score == pytest.approx(1.0, abs=1e-4)
    assert result.coherence_suspicion_score == pytest.approx(0.0, abs=0.05)


def test_score_incoherent_candidate_high_suspicion():
    """Orthogonal embeddings → cosine sim 0 → coherence_suspicion ≈ 1."""
    skills_emb = np.array([1.0, 0.0, 0.0, 0.0])
    readme_emb = np.array([0.0, 1.0, 0.0, 0.0])
    model = _mock_model({"a": skills_emb, "b": readme_emb})
    scorer = CrossCorrelationScorer(_model=model)
    result = scorer.score("uuid-incoh", "Management Excel", "Deep C++ kernel code", None, None)

    assert result.skill_coherence_score == pytest.approx(0.0, abs=1e-4)
    assert result.coherence_suspicion_score >= 0.5


def test_score_no_repo_readme_neutral_coherence():
    """Absent repo README → skill_coherence defaults to 0.5 (neutral)."""
    scorer = CrossCorrelationScorer(_model=None)
    result = scorer.score("uuid-noreadme", "Python", None, None, None)
    assert result.skill_coherence_score == pytest.approx(0.5, abs=1e-6)


def test_score_empty_repo_readme_neutral_coherence():
    scorer = CrossCorrelationScorer(_model=None)
    result = scorer.score("uuid-emptyreadme", "Python", "   ", None, None)
    assert result.skill_coherence_score == pytest.approx(0.5, abs=1e-6)


def test_score_no_transcript_zero_style_bridge():
    """Absent interview transcript → style_bridge_delta = 0.0 (neutral)."""
    v = _unit()
    model = _mock_model({"a": v, "b": v})
    scorer = CrossCorrelationScorer(_model=model)
    result = scorer.score("uuid-noint", "Python", "Python repo", "My resume text.", None)
    assert result.style_bridge_delta == pytest.approx(0.0, abs=1e-6)


def test_score_style_bridge_uniform_texts_low_delta():
    """Same sentence structure → low variance delta → low style suspicion."""
    uniform_resume    = "I worked there. I did this. I achieved that. Good results." * 5
    uniform_interview = "I said this. I thought that. I did it. Good outcome." * 5
    v = _unit()
    model = _mock_model({"a": v, "b": v})
    scorer = CrossCorrelationScorer(_model=model)
    result = scorer.score("uuid-uniform-style", "Python", "readme", uniform_resume, uniform_interview)
    # Both have similar variance → small delta
    assert result.style_bridge_delta < 0.5


def test_score_style_bridge_inconsistent_texts_higher_delta():
    """Very different sentence lengths → higher variance delta."""
    short_sentences = "Hi. Ok. Go. Run. Yes." * 5
    long_sentences  = ("This is a very elaborate and detailed explanation of my experience. " * 10)
    v = _unit()
    model = _mock_model({"a": v, "b": v})
    scorer = CrossCorrelationScorer(_model=model)
    result = scorer.score("uuid-inconsistent", "Python", "readme", short_sentences, long_sentences)
    assert result.style_bridge_delta > 0.1


def test_score_suspicion_in_unit_interval():
    v = _unit()
    model = _mock_model({"a": v, "b": v})
    scorer = CrossCorrelationScorer(_model=model)
    for readme in ["readme", None]:
        for transcript in ["interview text.", None]:
            result = scorer.score("uuid-range", "skills", readme, "resume.", transcript)
            assert 0.0 <= result.coherence_suspicion_score <= 1.0


def test_score_no_pii_in_result():
    scorer = CrossCorrelationScorer(_model=None)
    result = scorer.score("uuid-pii", "Python", None, None, None)
    assert not hasattr(result, "name")
    assert not hasattr(result, "email")
    assert not hasattr(result, "author_name")


def test_score_combined_weight_formula():
    """coherence_suspicion = _W_COHERENCE × (1-coh) + _W_STYLE × bridge."""
    skills_emb = np.array([1.0, 0.0, 0.0, 0.0])
    readme_emb = np.array([0.0, 1.0, 0.0, 0.0])   # cosine sim = 0 → coherence = 0
    model = _mock_model({"a": skills_emb, "b": readme_emb})
    scorer = CrossCorrelationScorer(_model=model)

    # No transcript → bridge = 0.0
    result = scorer.score("uuid-formula", "skills", "readme", None, None)

    expected = _W_COHERENCE * (1.0 - result.skill_coherence_score) + _W_STYLE * result.style_bridge_delta
    assert result.coherence_suspicion_score == pytest.approx(min(1.0, expected), abs=1e-4)
