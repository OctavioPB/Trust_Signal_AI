"""Burstiness scorer for transcript text.

Measures sentence-length variance in candidate speech. Humans speak
burstily (long sentences, short fillers, pauses). AI-generated text is
homogeneous with low sentence-length variance. Implemented in Sprint 6.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class BurstinessFeatures:
    """Computed burstiness statistics for a candidate's transcript turn.

    Attributes:
        session_id: UUID of the interview session.
        text: The candidate transcript segment analysed.
        sentence_lengths: Token counts per sentence.
        cv: Coefficient of Variation of sentence lengths.
        suspicion_score: Score in [0, 1]; low CV → high suspicion.
    """

    session_id: str
    text: str
    sentence_lengths: list[int]
    cv: float
    suspicion_score: float


def score_burstiness(session_id: str, candidate_text: str) -> BurstinessFeatures:
    """Compute burstiness suspicion score for a candidate transcript segment.

    Args:
        session_id: UUID of the interview session.
        candidate_text: Concatenated CANDIDATE speaker turns.

    Returns:
        BurstinessFeatures with suspicion_score in [0, 1].

    Raises:
        ValueError: If candidate_text contains fewer than 3 sentences.
    """
    raise NotImplementedError  # Sprint 6
