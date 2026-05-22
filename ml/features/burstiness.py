"""Burstiness scorer for transcript text.

Measures sentence-length variance in candidate speech. Humans speak
burstily — long sentences, short fillers, hesitations. AI-generated text is
homogeneous with low sentence-length variance.

Suspicion score mapping (linear, mirroring the latency CV scale):
    CV ≤ 0.20 → 1.00  (uniform sentence lengths → maximum suspicion)
    CV = 0.50 → 0.50  (midpoint)
    CV ≥ 0.80 → 0.00  (highly variable → natural speech)

CV bounds are wider than the latency module because sentence-length distributions
naturally have higher variance than response-time distributions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# CV bounds for score mapping
_CV_HIGH_SUSPICION = 0.20   # at or below this → score = 1.0
_CV_LOW_SUSPICION = 0.80    # at or above this → score = 0.0

# Minimum sentence count for a reliable CV estimate
_MIN_SENTENCES = 3

# Sentence boundary pattern: split on . ! ? followed by whitespace or end-of-string
_SENTENCE_RE = re.compile(r"(?<=[.!?])(?:\s+|$)")


@dataclass
class BurstinessFeatures:
    """Computed burstiness statistics for a candidate's transcript turn.

    Attributes:
        session_id: UUID of the interview session.
        text: The candidate transcript segment analysed.
        sentence_lengths: Word-token count per sentence.
        cv: Coefficient of Variation of sentence lengths (std / mean).
        suspicion_score: Score in [0, 1]; low CV → high suspicion.
    """

    session_id: str
    text: str
    sentence_lengths: list[int]
    cv: float
    suspicion_score: float


def score_burstiness(session_id: str, candidate_text: str) -> BurstinessFeatures:
    """Compute burstiness suspicion score for a candidate transcript segment.

    Tokenizes the text into sentences, counts whitespace-delimited words per
    sentence, then applies a CV-to-score mapping identical in structure to the
    latency module's ``_score_from_cv``.

    Args:
        session_id: UUID of the interview session.
        candidate_text: Concatenated CANDIDATE speaker turns to evaluate.

    Returns:
        BurstinessFeatures with ``suspicion_score`` in [0, 1].

    Raises:
        ValueError: If the text contains fewer than ``_MIN_SENTENCES`` sentences
            (CV is unreliable on very short passages).
    """
    sentences = _split_sentences(candidate_text)

    if len(sentences) < _MIN_SENTENCES:
        raise ValueError(
            f"score_burstiness requires at least {_MIN_SENTENCES} sentences "
            f"(session_id={session_id}); found {len(sentences)}."
        )

    lengths = [_count_words(s) for s in sentences]
    arr = np.array(lengths, dtype=np.float64)

    mean = float(arr.mean())
    std = float(arr.std(ddof=1))
    cv = (std / mean) if mean > 0.0 else 0.0

    suspicion_score = _score_from_cv(cv)

    log = logger.bind(component="burstiness", session_id=session_id)
    log.debug(
        "burstiness_scored",
        n_sentences=len(sentences),
        mean_length=round(mean, 2),
        cv=round(cv, 4),
        suspicion_score=round(suspicion_score, 4),
    )

    return BurstinessFeatures(
        session_id=session_id,
        text=candidate_text,
        sentence_lengths=lengths,
        cv=cv,
        suspicion_score=suspicion_score,
    )


# ── Pure helpers (testable independently) ─────────────────────────────────────

def _split_sentences(text: str) -> list[str]:
    """Split text into sentences on . ! ? boundaries.

    Args:
        text: Raw transcript text.

    Returns:
        Non-empty sentence strings (stripped).
    """
    parts = _SENTENCE_RE.split(text.strip())
    return [s.strip() for s in parts if s.strip()]


def _count_words(sentence: str) -> int:
    """Count whitespace-delimited tokens in a sentence.

    Args:
        sentence: A single sentence string.

    Returns:
        Number of whitespace-separated tokens (≥ 0).
    """
    return len(sentence.split())


def _score_from_cv(cv: float) -> float:
    """Map sentence-length CV to a burstiness suspicion score in [0, 1].

    Linear interpolation between the two CV bounds; clamped at [0, 1].

    Args:
        cv: Non-negative coefficient of variation of sentence lengths.

    Returns:
        Suspicion score in [0, 1].
    """
    raw = (_CV_LOW_SUSPICION - cv) / (_CV_LOW_SUSPICION - _CV_HIGH_SUSPICION)
    return float(max(0.0, min(1.0, raw)))
