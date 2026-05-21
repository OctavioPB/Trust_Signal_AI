"""TrustScore aggregation engine.

Combines all five signal modules into a single TrustScore (0–100) with a
human-readable breakdown per signal. Weights are configurable via environment
or a YAML config file. Implemented in Sprint 7.

Default weights (must sum to 1.0):
  Response Latency     0.25
  Background Audio     0.20
  Perplexity           0.20
  Burstiness           0.20
  Semantic Similarity  0.15
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger(__name__)

# Default signal weights — must sum to 1.0
DEFAULT_WEIGHTS: dict[str, float] = {
    "latency": 0.25,
    "bg_audio": 0.20,
    "perplexity": 0.20,
    "burstiness": 0.20,
    "similarity": 0.15,
}


@dataclass
class SignalBreakdown:
    """Per-signal contribution to the TrustScore.

    Attributes:
        signal_name: Human-readable signal identifier.
        raw_score: Raw suspicion score from the signal module in [0, 1].
        weight: Configured weight for this signal.
        weighted_contribution: raw_score × weight.
        explanation: One-sentence explanation for the dashboard alert panel.
    """

    signal_name: str
    raw_score: float
    weight: float
    weighted_contribution: float
    explanation: str


@dataclass
class TrustScoreResult:
    """Final output of the TrustScore engine for a completed interview session.

    Attributes:
        session_id: UUID of the interview session.
        trust_score: Aggregated score in [0, 100]; higher = more trustworthy.
        suspicion_index: Weighted sum of all signal scores in [0, 1].
        signals: Per-signal breakdown for dashboard display.
        flagged: True if suspicion_index exceeds SUSPICION_THRESHOLD.
        flag_reason: Human-readable explanation (never empty when flagged=True).
    """

    session_id: str
    trust_score: float
    suspicion_index: float
    signals: list[SignalBreakdown] = field(default_factory=list)
    flagged: bool = False
    flag_reason: str = ""


class TrustScoreEngine:
    """Aggregates all signal scores into a final TrustScore.

    Args:
        weights: Per-signal weights dict. Defaults to DEFAULT_WEIGHTS.
        suspicion_threshold: Sessions above this index are flagged.
    """

    def __init__(
        self,
        weights: dict[str, float] | None = None,
        suspicion_threshold: float = 0.65,
    ) -> None:
        raise NotImplementedError  # Sprint 7

    def compute(
        self,
        session_id: str,
        latency_score: float,
        bg_audio_score: float,
        perplexity_score: float,
        burstiness_score: float,
        similarity_score: float,
    ) -> TrustScoreResult:
        """Aggregate five signal scores into a TrustScore.

        Args:
            session_id: UUID of the interview session.
            latency_score: Response latency suspicion score in [0, 1].
            bg_audio_score: Background audio suspicion score in [0, 1].
            perplexity_score: LM perplexity suspicion score in [0, 1].
            burstiness_score: Sentence burstiness suspicion score in [0, 1].
            similarity_score: Semantic similarity suspicion score in [0, 1].

        Returns:
            TrustScoreResult with trust_score in [0, 100] and full breakdown.
        """
        raise NotImplementedError  # Sprint 7
