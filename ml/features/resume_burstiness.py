"""Burstiness scorer for resume sections.

Applies the transcript burstiness metric (sentence-length CV) to each resume
section independently. Sections with fewer than 3 sentences are skipped — CV
is unreliable on very short passages.

AI-generated resume bullet points tend to be homogeneous in length (low CV).
Human-written resumes are more variable — short summary bullets mixed with
longer experience descriptions.

Score interpretation (inherited from burstiness.py):
    CV ≤ 0.20 → section score 1.0  (uniform → AI-like)
    CV ≥ 0.80 → section score 0.0  (variable → human-like)

Aggregate: mean of per-section scores for sections that could be scored.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from ml.features.burstiness import score_burstiness

logger = structlog.get_logger(__name__)


@dataclass
class ResumeBurstinessFeatures:
    """Burstiness suspicion scores computed over resume sections.

    Attributes:
        candidate_uuid: UUID of the candidate (no PII).
        section_scores: Per-section suspicion scores (section → score in [0, 1]).
            Only sections with ≥ 3 sentences are included.
        suspicion_score: Mean score across all scorable sections; 0.0 if none.
    """

    candidate_uuid: str
    section_scores: dict[str, float] = field(default_factory=dict)
    suspicion_score: float = 0.0


def score_resume_burstiness(
    candidate_uuid: str,
    sections: dict[str, str],
) -> ResumeBurstinessFeatures:
    """Compute burstiness suspicion scores for each resume section.

    Args:
        candidate_uuid: UUID of the candidate (used only in logs — no PII).
        sections: Dict mapping section name to section text.

    Returns:
        ResumeBurstinessFeatures with per-section scores and an aggregate.
    """
    section_scores: dict[str, float] = {}

    for section_name, text in sections.items():
        text = text.strip()
        if not text:
            continue

        try:
            result = score_burstiness(session_id=candidate_uuid, candidate_text=text)
            section_scores[section_name] = result.suspicion_score
        except ValueError:
            # Fewer than 3 sentences — skip silently (not enough data for CV).
            pass

    aggregate = (
        sum(section_scores.values()) / len(section_scores)
        if section_scores
        else 0.0
    )

    logger.debug(
        "resume_burstiness_scored",
        candidate_uuid=candidate_uuid,  # UUID — no PII
        sections_scored=list(section_scores.keys()),
        suspicion_score=round(aggregate, 4),
    )

    return ResumeBurstinessFeatures(
        candidate_uuid=candidate_uuid,
        section_scores=section_scores,
        suspicion_score=float(aggregate),
    )
