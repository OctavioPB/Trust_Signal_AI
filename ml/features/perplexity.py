"""LM perplexity scorer for transcript text.

Low perplexity indicates predictable, AI-generated text. Uses a small causal
language model (distilgpt2 by default) from Hugging Face transformers.
Implemented in Sprint 6.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)

# Perplexity threshold below which a segment is flagged as suspicious
LOW_PERPLEXITY_THRESHOLD = 30.0

# Default Hugging Face model for perplexity scoring
DEFAULT_MODEL = "distilgpt2"


@dataclass
class PerplexityFeatures:
    """Computed perplexity metrics for a candidate transcript segment.

    Attributes:
        session_id: UUID of the interview session.
        text: The transcript segment analysed.
        perplexity: Raw model perplexity score.
        suspicion_score: Normalised score in [0, 1]; low perplexity → high suspicion.
    """

    session_id: str
    text: str
    perplexity: float
    suspicion_score: float


class PerplexityScorer:
    """Scores candidate transcript segments using token-level language model perplexity.

    Args:
        model_name: Hugging Face model identifier.
        device: "cpu" or "cuda".
    """

    def __init__(self, model_name: str = DEFAULT_MODEL, device: str = "cpu") -> None:
        raise NotImplementedError  # Sprint 6

    def score(self, session_id: str, text: str) -> PerplexityFeatures:
        """Compute perplexity and suspicion score for a transcript segment.

        Args:
            session_id: UUID of the interview session.
            text: Candidate transcript text to evaluate.

        Returns:
            PerplexityFeatures with suspicion_score in [0, 1].
        """
        raise NotImplementedError  # Sprint 6

    @staticmethod
    def _normalise_perplexity(perplexity: float) -> float:
        """Map raw perplexity to a suspicion score in [0, 1].

        perplexity ≤ 30  → score approaches 1.0 (very suspicious).
        perplexity ≥ 100 → score approaches 0.0 (natural variance).

        Args:
            perplexity: Raw language-model perplexity (≥ 1).

        Returns:
            Suspicion score in [0, 1].
        """
        raise NotImplementedError  # Sprint 6
