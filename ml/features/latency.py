"""Response-latency signal extractor.

Measures the time between recruiter question end and candidate speech onset.
Suspiciously constant latency (CV < 0.15) suggests a fixed LLM inference +
text-to-speech read-aloud pipeline. CV > 0.60 indicates natural human variance.

Suspicion score mapping (linear):
    CV = 0.00 → 1.00  (perfectly constant → maximum suspicion)
    CV = 0.15 → 1.00  (threshold; above this score starts to fall)
    CV = 0.60 → 0.00  (natural variance → no suspicion)
    CV > 0.60 → 0.00  (clamped)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# Coefficient of Variation boundaries for the suspicion score mapping
_CV_HIGH_SUSPICION = 0.15   # at or below this → score = 1.0
_CV_LOW_SUSPICION = 0.60    # at or above this → score = 0.0


@dataclass
class LatencyFeatures:
    """Computed latency statistics for a completed interview session.

    Attributes:
        session_id: UUID of the interview session.
        latencies_s: Per-turn response latencies (seconds), one per RECRUITER→CANDIDATE turn.
        mean_s: Mean latency across all measured turns.
        std_s: Standard deviation of latencies.
        cv: Coefficient of Variation (std / mean); low CV → suspicious.
        suspicion_score: Normalised score in [0, 1]; 1.0 = highly suspicious.
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

    Latency is defined as: ``candidate.start_ts − recruiter.end_ts`` for each
    consecutive RECRUITER → CANDIDATE transition. Overlapping turns (negative
    latency) are clamped to 0.

    Args:
        session_id: UUID of the interview session.
        turn_timestamps: Ordered list of dicts, each with keys:
            ``speaker`` ("RECRUITER" | "CANDIDATE"), ``start_ts`` (float),
            ``end_ts`` (float). Values are seconds from call start.

    Returns:
        LatencyFeatures with ``suspicion_score`` in [0, 1].

    Raises:
        ValueError: If fewer than 2 CANDIDATE turns are found (CV undefined on
            a single data point).
    """
    latencies: list[float] = []
    last_recruiter_end: float | None = None

    for turn in turn_timestamps:
        speaker = turn.get("speaker", "")
        if speaker == "RECRUITER":
            last_recruiter_end = float(turn["end_ts"])
        elif speaker == "CANDIDATE" and last_recruiter_end is not None:
            gap = float(turn["start_ts"]) - last_recruiter_end
            latencies.append(max(0.0, gap))
            last_recruiter_end = None   # consume; don't reuse for the next CANDIDATE

    if len(latencies) < 2:
        raise ValueError(
            f"extract_latency_features requires at least 2 CANDIDATE turns "
            f"(session_id={session_id}); found {len(latencies)}."
        )

    arr = np.array(latencies, dtype=np.float64)
    mean_s = float(arr.mean())
    std_s = float(arr.std(ddof=1))
    cv = (std_s / mean_s) if mean_s > 0.0 else 0.0

    suspicion_score = _score_from_cv(cv)

    log = logger.bind(component="latency", session_id=session_id)
    log.debug(
        "latency_features_computed",
        turn_count=len(latencies),
        mean_s=round(mean_s, 3),
        std_s=round(std_s, 3),
        cv=round(cv, 4),
        suspicion_score=round(suspicion_score, 4),
    )

    return LatencyFeatures(
        session_id=session_id,
        latencies_s=latencies,
        mean_s=mean_s,
        std_s=std_s,
        cv=cv,
        suspicion_score=suspicion_score,
    )


def _score_from_cv(cv: float) -> float:
    """Map Coefficient of Variation to a suspicion score in [0, 1].

    Linear interpolation between the two CV bounds; clamped at [0, 1].

    Args:
        cv: Non-negative coefficient of variation.

    Returns:
        Suspicion score in [0, 1].
    """
    raw = (_CV_LOW_SUSPICION - cv) / (_CV_LOW_SUSPICION - _CV_HIGH_SUSPICION)
    return float(max(0.0, min(1.0, raw)))
