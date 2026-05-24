"""Vocabulary richness scorer for resume text.

Two complementary metrics quantify lexical diversity:

Type-Token Ratio (TTR):
    unique_words / total_words.
    AI-generated resumes often repeat the same "power words" (implemented,
    developed, leveraged, optimized) heavily, reducing TTR below human norms.

    Normalisation (higher suspicion = lower TTR):
        TTR ≤ 0.35 → score 1.0  (highly repetitive)
        TTR ≥ 0.65 → score 0.0  (naturally varied)

Hapax Ratio:
    words appearing exactly once / total_words.
    Low hapax ratio correlates with formulaic vocabulary patterns typical of
    AI writing, where the same functional vocabulary dominates.

    Normalisation:
        hapax ≤ 0.20 → score 1.0  (low unique diversity)
        hapax ≥ 0.55 → score 0.0  (rich unique vocabulary)

Combined:
    suspicion_score = 0.6 × ttr_suspicion + 0.4 × hapax_suspicion

Minimum 20 words required; shorter text returns suspicion_score 0.0.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)

# Normalisation bounds
_TTR_MAX_SUSPICION  = 0.35   # at or below → ttr_suspicion 1.0
_TTR_MIN_SUSPICION  = 0.65   # at or above → ttr_suspicion 0.0
_HAP_MAX_SUSPICION  = 0.20   # at or below → hapax_suspicion 1.0
_HAP_MIN_SUSPICION  = 0.55   # at or above → hapax_suspicion 0.0

_MIN_WORDS = 20

_WORD_RE = re.compile(r"[a-z]+", re.IGNORECASE)


@dataclass
class VocabRichnessFeatures:
    """Lexical diversity metrics for resume full-text.

    Attributes:
        candidate_uuid: UUID of the candidate (no PII).
        total_words: Token count after lowercasing and stripping punctuation.
        unique_words: Number of distinct lowercase word types.
        hapax_count: Words that appear exactly once.
        ttr: Type-Token Ratio = unique_words / total_words.
        hapax_ratio: hapax_count / total_words.
        ttr_suspicion: Suspicion score derived from TTR in [0, 1].
        hapax_suspicion: Suspicion score derived from hapax ratio in [0, 1].
        suspicion_score: Combined score in [0, 1]; higher → more AI-like.
    """

    candidate_uuid: str
    total_words: int
    unique_words: int
    hapax_count: int
    ttr: float
    hapax_ratio: float
    ttr_suspicion: float
    hapax_suspicion: float
    suspicion_score: float


def score_vocab_richness(
    candidate_uuid: str,
    text: str,
) -> VocabRichnessFeatures:
    """Compute vocabulary richness suspicion score for resume text.

    Args:
        candidate_uuid: UUID of the candidate (used in logs — no PII).
        text: Full resume text (all sections concatenated or individual section).

    Returns:
        VocabRichnessFeatures with suspicion_score in [0, 1].
        Returns score 0.0 (no suspicion) for text below _MIN_WORDS.
    """
    tokens = _tokenize(text)
    total = len(tokens)

    if total < _MIN_WORDS:
        logger.debug(
            "vocab_richness_skipped_short",
            candidate_uuid=candidate_uuid,
            total_words=total,
        )
        return VocabRichnessFeatures(
            candidate_uuid=candidate_uuid,
            total_words=total,
            unique_words=0,
            hapax_count=0,
            ttr=0.0,
            hapax_ratio=0.0,
            ttr_suspicion=0.0,
            hapax_suspicion=0.0,
            suspicion_score=0.0,
        )

    counts = Counter(tokens)
    unique = len(counts)
    hapax = sum(1 for c in counts.values() if c == 1)

    ttr   = unique / total
    hapax_ratio = hapax / total

    ttr_susp   = _linear_map(ttr,        _TTR_MAX_SUSPICION, _TTR_MIN_SUSPICION)
    hapax_susp = _linear_map(hapax_ratio, _HAP_MAX_SUSPICION, _HAP_MIN_SUSPICION)
    combined   = 0.6 * ttr_susp + 0.4 * hapax_susp

    logger.debug(
        "vocab_richness_scored",
        candidate_uuid=candidate_uuid,  # UUID — no PII
        total_words=total,
        ttr=round(ttr, 4),
        hapax_ratio=round(hapax_ratio, 4),
        suspicion_score=round(combined, 4),
    )

    return VocabRichnessFeatures(
        candidate_uuid=candidate_uuid,
        total_words=total,
        unique_words=unique,
        hapax_count=hapax,
        ttr=ttr,
        hapax_ratio=hapax_ratio,
        ttr_suspicion=ttr_susp,
        hapax_suspicion=hapax_susp,
        suspicion_score=float(combined),
    )


# ── Pure helpers ───────────────────────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    """Lowercase and extract alphabetic tokens (strips punctuation + numbers).

    Args:
        text: Raw resume text.

    Returns:
        List of lowercase alphabetic tokens.
    """
    return _WORD_RE.findall(text.lower())


def _linear_map(value: float, max_susp: float, min_susp: float) -> float:
    """Map a metric value to a suspicion score in [0, 1].

    Values at or below max_susp yield score 1.0 (maximum suspicion).
    Values at or above min_susp yield score 0.0 (no suspicion).
    Linear interpolation in between; clamped at the boundaries.

    Args:
        value: The metric value to map.
        max_susp: Metric threshold for maximum suspicion.
        min_susp: Metric threshold for zero suspicion.

    Returns:
        Suspicion score in [0, 1].
    """
    if min_susp == max_susp:
        return 0.0
    raw = (min_susp - value) / (min_susp - max_susp)
    return float(max(0.0, min(1.0, raw)))
