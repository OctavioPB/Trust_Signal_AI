"""LM perplexity scorer for resume sections.

Wraps the interview-transcript PerplexityScorer and applies it per resume
section, returning both per-section scores and a weighted aggregate.

Higher suspicion_score → more AI-like (low perplexity) text.

Score interpretation (inherited from PerplexityScorer):
    perplexity ≤  30 → section score 1.0  (very predictable)
    perplexity ≥ 100 → section score 0.0  (natural human variance)

Aggregate: weighted mean over sections present, weighted by character count
so longer sections contribute more to the overall signal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class ResumePerplexityFeatures:
    """Perplexity suspicion scores computed over resume sections.

    Attributes:
        candidate_uuid: UUID of the candidate (no PII).
        section_scores: Per-section suspicion scores (section → score in [0, 1]).
        suspicion_score: Character-count-weighted mean across all scored sections.
    """

    candidate_uuid: str
    section_scores: dict[str, float] = field(default_factory=dict)
    suspicion_score: float = 0.0


def score_resume_perplexity(
    candidate_uuid: str,
    sections: dict[str, str],
    _scorer: Any = None,
) -> ResumePerplexityFeatures:
    """Compute perplexity suspicion scores for each resume section.

    Sections with fewer than 5 tokens (too short for reliable scoring) are
    silently skipped and do not contribute to the aggregate.

    Args:
        candidate_uuid: UUID of the candidate (used only in logs — no PII).
        sections: Dict mapping section name to section text.
        _scorer: Optional pre-built PerplexityScorer (for testing, avoids
            model download). If None, a scorer is instantiated with defaults.

    Returns:
        ResumePerplexityFeatures with per-section scores and an aggregate.
    """
    if _scorer is None:
        from ml.features.perplexity import PerplexityScorer
        _scorer = PerplexityScorer()

    section_scores: dict[str, float] = {}
    total_weight = 0.0
    weighted_sum = 0.0

    for section_name, text in sections.items():
        text = text.strip()
        if not text:
            continue

        result = _scorer.score(session_id=candidate_uuid, text=text)

        # Skip sections that were too short to score reliably (score == 0.0 from short-text guard)
        # We check perplexity == inf as the sentinel set by PerplexityScorer for short text.
        if result.perplexity == float("inf"):
            continue

        weight = float(len(text))
        section_scores[section_name] = result.suspicion_score
        weighted_sum += result.suspicion_score * weight
        total_weight += weight

    aggregate = (weighted_sum / total_weight) if total_weight > 0.0 else 0.0

    logger.debug(
        "resume_perplexity_scored",
        candidate_uuid=candidate_uuid,  # UUID — no PII
        sections_scored=list(section_scores.keys()),
        suspicion_score=round(aggregate, 4),
    )

    return ResumePerplexityFeatures(
        candidate_uuid=candidate_uuid,
        section_scores=section_scores,
        suspicion_score=float(aggregate),
    )
