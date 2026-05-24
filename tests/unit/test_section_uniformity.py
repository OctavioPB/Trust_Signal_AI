"""Unit tests for ml/features/section_uniformity.py."""

from __future__ import annotations

import numpy as np
import pytest
from unittest.mock import MagicMock

from ml.features.section_uniformity import (
    _DIST_MAX_SUSPICION,
    _DIST_MIN_SUSPICION,
    _mean_pairwise_cosine_distance,
    _score_from_distance,
    score_section_uniformity,
)


# ── Mock helper ────────────────────────────────────────────────────────────────

def _mock_model(embeddings: np.ndarray) -> MagicMock:
    """Return a SentenceTransformer stub that yields fixed embeddings."""
    model = MagicMock()
    model.encode.return_value = embeddings
    return model


# ── Fewer-than-two-sections guard ──────────────────────────────────────────────

def test_single_section_returns_zero():
    """Only one non-empty section → score 0.0 (can't compute pairwise distance)."""
    result = score_section_uniformity(
        "uuid-single", {"summary": "I am a developer"}
    )
    assert result.suspicion_score == 0.0
    assert result.sections_embedded == []


def test_all_empty_sections_returns_zero():
    """All sections empty → score 0.0."""
    result = score_section_uniformity(
        "uuid-empty", {"summary": "", "experience": "", "skills": ""}
    )
    assert result.suspicion_score == 0.0


def test_one_non_empty_returns_zero():
    """Exactly one non-empty section → score 0.0."""
    result = score_section_uniformity(
        "uuid-one", {"summary": "text here", "experience": "", "skills": ""}
    )
    assert result.suspicion_score == 0.0


# ── Embedding-based scoring (mocked model) ────────────────────────────────────

def test_identical_embeddings_yield_score_one():
    """Sections with identical unit embeddings → distance 0 → score 1.0."""
    e = np.array([[1.0, 0.0], [1.0, 0.0]], dtype=np.float32)
    result = score_section_uniformity(
        "uuid-identical",
        {"summary": "same text", "experience": "same text"},
        _model=_mock_model(e),
    )
    assert result.suspicion_score == pytest.approx(1.0, abs=1e-5)


def test_orthogonal_embeddings_yield_score_zero():
    """Orthogonal unit vectors → distance 1.0 → score clamped to 0.0."""
    e = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    result = score_section_uniformity(
        "uuid-orthogonal",
        {"summary": "technical stuff", "experience": "completely different"},
        _model=_mock_model(e),
    )
    assert result.suspicion_score == pytest.approx(0.0, abs=1e-5)


def test_similar_embeddings_mid_range_suspicion():
    """Moderately similar embeddings (30° apart) yield score in (0, 1)."""
    # cos(30°) ≈ 0.866 → distance ≈ 0.134 → in (DIST_MAX=0.05, DIST_MIN=0.50)
    a = np.array([1.0, 0.0], dtype=np.float32)
    b = np.array(
        [float(np.cos(np.radians(30))), float(np.sin(np.radians(30)))],
        dtype=np.float32,
    )
    e = np.array([a, b], dtype=np.float32)
    result = score_section_uniformity(
        "uuid-mid",
        {"summary": "some text", "experience": "other text"},
        _model=_mock_model(e),
    )
    assert 0.0 < result.suspicion_score < 1.0


def test_sections_embedded_list_matches_input_keys():
    """sections_embedded contains the names of sections that were scored."""
    e = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    result = score_section_uniformity(
        "uuid-names",
        {"summary": "text a", "experience": "text b"},
        _model=_mock_model(e),
    )
    assert set(result.sections_embedded) == {"summary", "experience"}


def test_three_section_scoring():
    """Scoring works with more than two sections."""
    e = np.array(
        [[1.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 0.0, 0.0]], dtype=np.float32
    )
    result = score_section_uniformity(
        "uuid-three",
        {"summary": "a", "experience": "b", "skills": "c"},
        _model=_mock_model(e),
    )
    assert result.suspicion_score == pytest.approx(1.0, abs=1e-5)
    assert len(result.sections_embedded) == 3


def test_empty_sections_excluded_from_scoring():
    """Empty sections are excluded; only non-empty sections are embedded."""
    e = np.array([[1.0, 0.0], [1.0, 0.0]], dtype=np.float32)
    model = _mock_model(e)
    result = score_section_uniformity(
        "uuid-filter",
        {
            "summary": "filled section",
            "experience": "also filled",
            "skills": "",
            "education": "",
        },
        _model=model,
    )
    # Only 2 sections embedded
    assert set(result.sections_embedded) == {"summary", "experience"}


def test_candidate_uuid_preserved():
    """candidate_uuid in result matches the input UUID."""
    e = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    result = score_section_uniformity(
        "uuid-passthrough",
        {"summary": "text", "experience": "more text"},
        _model=_mock_model(e),
    )
    assert result.candidate_uuid == "uuid-passthrough"


def test_score_in_unit_interval():
    """suspicion_score is always in [0, 1]."""
    e = np.array([[0.6, 0.8], [0.8, 0.6]], dtype=np.float32)
    result = score_section_uniformity(
        "uuid-range",
        {"summary": "text a", "skills": "text b"},
        _model=_mock_model(e),
    )
    assert 0.0 <= result.suspicion_score <= 1.0


# ── _mean_pairwise_cosine_distance ────────────────────────────────────────────

def test_mean_distance_single_embedding():
    """Single embedding returns 0.0 (no pairs)."""
    e = np.array([[1.0, 0.0]], dtype=np.float32)
    assert _mean_pairwise_cosine_distance(e) == 0.0


def test_mean_distance_two_identical_unit_vectors():
    """Two identical unit vectors → distance 0.0."""
    e = np.array([[1.0, 0.0], [1.0, 0.0]], dtype=np.float32)
    assert _mean_pairwise_cosine_distance(e) == pytest.approx(0.0, abs=1e-5)


def test_mean_distance_two_orthogonal_vectors():
    """Two orthogonal unit vectors → distance 1.0."""
    e = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    assert _mean_pairwise_cosine_distance(e) == pytest.approx(1.0, abs=1e-5)


def test_mean_distance_three_orthogonal_vectors():
    """Three mutually orthogonal unit vectors → mean distance 1.0."""
    e = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=np.float32)
    assert _mean_pairwise_cosine_distance(e) == pytest.approx(1.0, abs=1e-5)


def test_mean_distance_symmetry():
    """Distance is symmetric: order of rows does not change the result."""
    a = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    b = np.array([[0.0, 1.0], [1.0, 0.0]], dtype=np.float32)
    assert _mean_pairwise_cosine_distance(a) == pytest.approx(
        _mean_pairwise_cosine_distance(b), abs=1e-6
    )


# ── _score_from_distance ──────────────────────────────────────────────────────

def test_score_from_distance_at_max_suspicion_bound():
    """Distance ≤ DIST_MAX → score 1.0."""
    assert _score_from_distance(_DIST_MAX_SUSPICION) == pytest.approx(1.0, abs=1e-5)
    assert _score_from_distance(0.0) == pytest.approx(1.0, abs=1e-5)


def test_score_from_distance_at_min_suspicion_bound():
    """Distance ≥ DIST_MIN → score 0.0."""
    assert _score_from_distance(_DIST_MIN_SUSPICION) == pytest.approx(0.0, abs=1e-5)
    assert _score_from_distance(1.0) == pytest.approx(0.0, abs=1e-5)


def test_score_from_distance_midpoint():
    """Midpoint distance maps to approximately 0.5."""
    mid = (_DIST_MAX_SUSPICION + _DIST_MIN_SUSPICION) / 2.0
    result = _score_from_distance(mid)
    assert abs(result - 0.5) < 1e-5


def test_score_from_distance_clamped_below_zero():
    """Score is clamped to 0.0 for distances beyond DIST_MIN."""
    assert _score_from_distance(2.0) == pytest.approx(0.0, abs=1e-5)


def test_score_from_distance_clamped_above_one():
    """Score is clamped to 1.0 for distances below 0."""
    assert _score_from_distance(-1.0) == pytest.approx(1.0, abs=1e-5)
