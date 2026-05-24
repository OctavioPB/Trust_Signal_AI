"""Unit tests for ml/features/vocab_richness.py."""

from __future__ import annotations

import pytest

from ml.features.vocab_richness import (
    _HAP_MAX_SUSPICION,
    _HAP_MIN_SUSPICION,
    _MIN_WORDS,
    _TTR_MAX_SUSPICION,
    _TTR_MIN_SUSPICION,
    _linear_map,
    _tokenize,
    score_vocab_richness,
)

# ── Test fixtures ──────────────────────────────────────────────────────────────

# AI-like text: highly repetitive vocabulary — same "power words" recycled throughout.
_AI_TEXT = " ".join(
    ["implemented leveraged optimized developed leveraged implemented optimized"] * 25
)

# Human-like text: varied, natural vocabulary — distinct words throughout.
_HUMAN_TEXT = (
    "Designed and built a distributed caching layer that reduced database "
    "load by sixty percent during peak traffic conditions. Collaborated "
    "with product managers to define scalable architecture patterns for a "
    "microservices migration spanning six engineering teams. Mentored junior "
    "engineers through detailed code reviews and pair programming sessions, "
    "fostering a culture of technical excellence and shared ownership. "
    "Delivered quarterly performance benchmarks that informed infrastructure "
    "spending decisions and shaped the roadmap for the next fiscal year. "
    "Championed observability practices including distributed tracing, "
    "structured logging, and custom alerting dashboards used across the org."
)


# ── Regression fixtures ────────────────────────────────────────────────────────

def test_ai_text_high_suspicion():
    """AI-like text (repetitive vocabulary) must score ≥ 0.65."""
    result = score_vocab_richness("uuid-ai", _AI_TEXT)
    assert result.suspicion_score >= 0.65, (
        f"Expected ≥ 0.65 for AI-like text, got {result.suspicion_score:.4f}"
    )


def test_human_text_low_suspicion():
    """Human-like text (varied vocabulary) must score ≤ 0.35."""
    result = score_vocab_richness("uuid-human", _HUMAN_TEXT)
    assert result.suspicion_score <= 0.35, (
        f"Expected ≤ 0.35 for human-like text, got {result.suspicion_score:.4f}"
    )


# ── Short-text guard ───────────────────────────────────────────────────────────

def test_short_text_returns_zero_score():
    """Text with fewer than _MIN_WORDS tokens yields suspicion_score 0.0."""
    short = "hello world only three"
    result = score_vocab_richness("uuid-short", short)
    assert result.suspicion_score == 0.0
    assert result.total_words < _MIN_WORDS


def test_short_text_zero_metrics():
    """Short text also zeroes ttr, hapax_ratio, and component suspicion scores."""
    result = score_vocab_richness("uuid-short2", "too short")
    assert result.ttr == 0.0
    assert result.hapax_ratio == 0.0
    assert result.ttr_suspicion == 0.0
    assert result.hapax_suspicion == 0.0


# ── Score range ────────────────────────────────────────────────────────────────

def test_score_in_unit_interval_ai():
    result = score_vocab_richness("uuid-range-ai", _AI_TEXT)
    assert 0.0 <= result.suspicion_score <= 1.0


def test_score_in_unit_interval_human():
    result = score_vocab_richness("uuid-range-human", _HUMAN_TEXT)
    assert 0.0 <= result.suspicion_score <= 1.0


# ── Metric correctness ─────────────────────────────────────────────────────────

def test_ttr_computed_correctly():
    """TTR = unique_words / total_words."""
    # 4 unique words, each repeated 10 times = 40 total
    words = ["alpha"] * 10 + ["beta"] * 10 + ["gamma"] * 10 + ["delta"] * 10
    # 20 additional unique purely-alphabetic words (not repeated)
    extras = [
        "able", "boat", "care", "done", "even", "farm", "gate", "hope",
        "iron", "just", "kind", "lamp", "mist", "nest", "open", "pace",
        "quit", "rain", "salt", "tide",
    ]
    text = " ".join(words + extras)
    result = score_vocab_richness("uuid-ttr", text)
    # unique = 4 + 20 = 24; total = 40 + 20 = 60; ttr = 24/60 = 0.4
    assert abs(result.ttr - (24 / 60)) < 1e-4


def test_hapax_count_matches_expectation():
    """hapax_count equals the number of words appearing exactly once."""
    hapax_words = [
        "able", "best", "calm", "deep", "echo",
        "fade", "glow", "haze", "idle", "just",
        "keen", "loft", "mist", "note", "open",
    ]                                                       # 15 purely-alphabetic hapax words
    repeated = ["common"] * 15 + ["frequent"] * 10         # 2 repeated words, not hapax
    text = " ".join(hapax_words + repeated)
    result = score_vocab_richness("uuid-hapax", text)
    assert result.hapax_count == 15


def test_total_words_matches_token_count():
    """total_words equals the number of alphabetic tokens."""
    text = "one two three four five six seven eight nine ten eleven twenty"
    result = score_vocab_richness("uuid-words", text)
    assert result.total_words == 12


def test_unique_words_excludes_duplicates():
    """unique_words counts distinct lowercase types."""
    extra_unique = [
        "able", "best", "calm", "deep", "echo", "fade", "glow", "haze",
        "idle", "just", "keen", "loft", "mist", "note", "open", "pace",
        "quit", "rain", "salt", "tide",
    ]  # 20 distinct purely-alphabetic words (no digits)
    text = " ".join(["apple"] * 5 + ["banana"] * 3 + ["cherry"] * 4 + extra_unique)
    result = score_vocab_richness("uuid-unique", text)
    assert result.unique_words == 3 + 20


def test_combined_score_formula():
    """suspicion_score = 0.6 × ttr_suspicion + 0.4 × hapax_suspicion."""
    result = score_vocab_richness("uuid-formula", _AI_TEXT)
    expected = 0.6 * result.ttr_suspicion + 0.4 * result.hapax_suspicion
    assert abs(result.suspicion_score - expected) < 1e-6


# ── candidate_uuid passthrough ─────────────────────────────────────────────────

def test_candidate_uuid_in_result():
    result = score_vocab_richness("uuid-check-pass", _HUMAN_TEXT)
    assert result.candidate_uuid == "uuid-check-pass"


# ── _tokenize ──────────────────────────────────────────────────────────────────

def test_tokenize_all_tokens_alphabetic():
    """All tokens returned by _tokenize consist solely of alphabetic characters."""
    tokens = _tokenize("Hello, world! 100% great — it's #1.")
    for t in tokens:
        assert t.isalpha(), f"Non-alphabetic token: {t!r}"


def test_tokenize_lowercases():
    """Tokens are lowercased."""
    tokens = _tokenize("Hello WORLD")
    assert "hello" in tokens
    assert "world" in tokens
    assert "Hello" not in tokens
    assert "WORLD" not in tokens


def test_tokenize_strips_numbers():
    """Numeric characters are not included in tokens."""
    tokens = _tokenize("agent007 3000 turbo")
    assert "007" not in tokens
    assert "3000" not in tokens


def test_tokenize_empty_string():
    """Empty string yields empty list."""
    assert _tokenize("") == []


# ── _linear_map ────────────────────────────────────────────────────────────────

def test_linear_map_at_max_suspicion_boundary():
    """Value at or below max_susp → 1.0."""
    assert _linear_map(_TTR_MAX_SUSPICION, _TTR_MAX_SUSPICION, _TTR_MIN_SUSPICION) == 1.0
    assert _linear_map(0.0, _TTR_MAX_SUSPICION, _TTR_MIN_SUSPICION) == 1.0


def test_linear_map_at_min_suspicion_boundary():
    """Value at or above min_susp → 0.0."""
    assert _linear_map(_TTR_MIN_SUSPICION, _TTR_MAX_SUSPICION, _TTR_MIN_SUSPICION) == 0.0
    assert _linear_map(1.0, _TTR_MAX_SUSPICION, _TTR_MIN_SUSPICION) == 0.0


def test_linear_map_midpoint():
    """Midpoint value maps to approximately 0.5."""
    midpoint = (_TTR_MAX_SUSPICION + _TTR_MIN_SUSPICION) / 2.0
    result = _linear_map(midpoint, _TTR_MAX_SUSPICION, _TTR_MIN_SUSPICION)
    assert abs(result - 0.5) < 1e-6


def test_linear_map_hapax_boundaries():
    """Same boundary semantics hold for hapax thresholds."""
    assert _linear_map(_HAP_MAX_SUSPICION, _HAP_MAX_SUSPICION, _HAP_MIN_SUSPICION) == 1.0
    assert _linear_map(_HAP_MIN_SUSPICION, _HAP_MAX_SUSPICION, _HAP_MIN_SUSPICION) == 0.0


def test_linear_map_equal_bounds_returns_zero():
    """Degenerate case (max_susp == min_susp) returns 0.0."""
    assert _linear_map(0.5, 0.5, 0.5) == 0.0
