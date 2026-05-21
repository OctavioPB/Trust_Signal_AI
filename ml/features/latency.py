"""Response-latency signal extractor.

Measures the time between recruiter question end and candidate speech onset.
Suspiciously constant latency (CV < 0.15) suggests a fixed LLM inference +
text-to-speech read-aloud pipeline. Implemented in Sprint 5.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)

# Coefficient of Variation threshold below which latency is flagged suspicious
CV_SUSPICION_THRESHOLD = 0.15


@dataclass
class LatencyFeatures:
    """Computed latency statistics for a completed interview session.

    Attributes:
        session_id: UUID of the interview session.
        latencies_s: List of per-turn response latencies (seconds).
        mean_s: Mean latency across all CANDIDATE turns.
        std_s: Standard deviation of latencies.
        cv: Coefficient of Variation (std / mean); low CV → suspicious.
        suspicion_score: Normalised score in [0, 1]; 1 = highly suspicious.
    """

    session_id: str
    latencies_s: list[float]
    mean_s: float
    std_s: float
    cv: float
    suspicion_score: float


def extract_latency_features(
    session_id: str,
    turn_timestamps: list[dict],
) -> LatencyFeatures:
    """Compute response-latency statistics from speaker-turn timestamps.

    Args:
        session_id: UUID of the interview session.
        turn_timestamps: List of dicts with keys:
            speaker ("RECRUITER" | "CANDIDATE"), start_ts, end_ts (seconds).

    Returns:
        LatencyFeatures with suspicion_score in [0, 1].

    Raises:
        ValueError: If fewer than 2 CANDIDATE turns are present.
    """
    raise NotImplementedError  # Sprint 5


def _score_from_cv(cv: float) -> float:
    """Map Coefficient of Variation to a suspicion score in [0, 1].

    CV < 0.15 → score approaches 1.0 (very suspicious).
    CV > 0.60 → score approaches 0.0 (natural human variance).

    Args:
        cv: Non-negative coefficient of variation.

    Returns:
        Suspicion score in [0, 1].
    """
    raise NotImplementedError  # Sprint 5
