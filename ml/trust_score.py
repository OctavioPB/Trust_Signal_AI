"""TrustScore aggregation engine.

Combines all five signal modules into a single TrustScore (0–100) with a
per-signal breakdown and human-readable explanation for the dashboard alert panel.

TrustScore = (1 − suspicion_index) × 100
suspicion_index = Σ (signal_score_i × weight_i)   ∈ [0, 1]

Higher TrustScore = more trustworthy candidate.

Default weights (configurable at construction time):
  Response Latency     0.25
  Background Audio     0.20
  Perplexity           0.20
  Burstiness           0.20
  Semantic Similarity  0.15
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

import config

logger = structlog.get_logger(__name__)

# ── Default weights ────────────────────────────────────────────────────────────

DEFAULT_WEIGHTS: dict[str, float] = {
    "latency":     0.25,
    "bg_audio":    0.20,
    "perplexity":  0.20,
    "burstiness":  0.20,
    "similarity":  0.15,
}

# Human-readable display names used in the dashboard
_SIGNAL_LABELS: dict[str, str] = {
    "latency":    "Response Latency",
    "bg_audio":   "Background Audio",
    "perplexity": "Perplexity",
    "burstiness": "Burstiness",
    "similarity": "Semantic Similarity",
}

# Score thresholds for explanation tier selection
_HIGH = 0.65
_MED  = 0.35


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class SignalBreakdown:
    """Per-signal contribution to the TrustScore.

    Attributes:
        signal_name: Human-readable signal identifier for the dashboard.
        raw_score: Raw suspicion score from the signal module in [0, 1].
        weight: Configured weight for this signal (sums to 1.0 across all signals).
        weighted_contribution: raw_score × weight; summed to produce suspicion_index.
        explanation: One-sentence explanation for the dashboard alert panel.
    """

    signal_name: str
    raw_score: float
    weight: float
    weighted_contribution: float
    explanation: str


@dataclass
class TrustScoreResult:
    """Final output of the TrustScore engine for an interview session.

    Attributes:
        session_id: UUID of the interview session (no PII).
        trust_score: Aggregated score in [0, 100]; higher = more trustworthy.
        suspicion_index: Weighted sum of all signal scores in [0, 1].
        signals: Per-signal breakdown ordered by weighted_contribution descending.
        flagged: True when suspicion_index ≥ suspicion_threshold.
        flag_reason: Non-empty human-readable explanation whenever flagged=True.
            Per CLAUDE.md §8: never suppressed silently.
    """

    session_id: str
    trust_score: float
    suspicion_index: float
    signals: list[SignalBreakdown] = field(default_factory=list)
    flagged: bool = False
    flag_reason: str = ""


# ── Engine ─────────────────────────────────────────────────────────────────────

class TrustScoreEngine:
    """Aggregates five suspicion signal scores into a final TrustScore.

    Args:
        weights: Per-signal weight overrides. Keys must be a subset of
            ``DEFAULT_WEIGHTS``. The full weight set must sum to 1.0 ± 1e-4.
        suspicion_threshold: Sessions above this index are flagged.
            Defaults to ``config.SUSPICION_THRESHOLD`` (env: SUSPICION_THRESHOLD).
    """

    def __init__(
        self,
        weights: dict[str, float] | None = None,
        suspicion_threshold: float | None = None,
    ) -> None:
        self._weights = dict(DEFAULT_WEIGHTS)
        if weights:
            for key, val in weights.items():
                if key not in DEFAULT_WEIGHTS:
                    raise ValueError(
                        f"Unknown signal key '{key}'. Valid keys: {list(DEFAULT_WEIGHTS)}"
                    )
                self._weights[key] = float(val)

        total = sum(self._weights.values())
        if abs(total - 1.0) > 1e-4:
            raise ValueError(
                f"Signal weights must sum to 1.0; got {total:.6f}. "
                "Adjust your weight overrides."
            )

        self._threshold = (
            suspicion_threshold
            if suspicion_threshold is not None
            else config.SUSPICION_THRESHOLD
        )
        self._log = logger.bind(component="TrustScoreEngine", threshold=self._threshold)

    # ── Public API ─────────────────────────────────────────────────────────────

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

        Each input score is clamped to [0, 1] before weighting so out-of-range
        values from upstream modules never corrupt the final result.

        Args:
            session_id: UUID of the interview session (no PII in logs).
            latency_score: Response latency suspicion score in [0, 1].
            bg_audio_score: Background audio suspicion score in [0, 1].
            perplexity_score: LM perplexity suspicion score in [0, 1].
            burstiness_score: Sentence burstiness suspicion score in [0, 1].
            similarity_score: Semantic similarity suspicion score in [0, 1].

        Returns:
            TrustScoreResult with ``trust_score`` in [0, 100] and a full
            per-signal breakdown sorted by weighted contribution descending.
        """
        raw_scores: dict[str, float] = {
            "latency":    float(max(0.0, min(1.0, latency_score))),
            "bg_audio":   float(max(0.0, min(1.0, bg_audio_score))),
            "perplexity": float(max(0.0, min(1.0, perplexity_score))),
            "burstiness": float(max(0.0, min(1.0, burstiness_score))),
            "similarity": float(max(0.0, min(1.0, similarity_score))),
        }

        signals: list[SignalBreakdown] = []
        suspicion_index = 0.0

        for key, raw in raw_scores.items():
            weight = self._weights[key]
            contribution = raw * weight
            suspicion_index += contribution
            signals.append(
                SignalBreakdown(
                    signal_name=_SIGNAL_LABELS[key],
                    raw_score=raw,
                    weight=weight,
                    weighted_contribution=contribution,
                    explanation=_explain(key, raw),
                )
            )

        # Sort by contribution descending so dashboard highlights the top drivers
        signals.sort(key=lambda s: s.weighted_contribution, reverse=True)

        suspicion_index = float(max(0.0, min(1.0, suspicion_index)))
        trust_score = round((1.0 - suspicion_index) * 100.0, 2)
        flagged = suspicion_index >= self._threshold

        # HARD RULE (CLAUDE.md §8): flag_reason must never be empty when flagged=True
        flag_reason = _build_flag_reason(signals, suspicion_index) if flagged else ""

        result = TrustScoreResult(
            session_id=session_id,
            trust_score=trust_score,
            suspicion_index=round(suspicion_index, 4),
            signals=signals,
            flagged=flagged,
            flag_reason=flag_reason,
        )

        self._log.info(
            "trust_score_computed",
            session_id=session_id,          # UUID — no PII
            trust_score=trust_score,
            suspicion_index=result.suspicion_index,
            flagged=flagged,
        )

        return result


# ── Explanation helpers (pure, independently testable) ─────────────────────────

def _explain(signal_key: str, score: float) -> str:
    """Return a one-sentence dashboard explanation for a signal score.

    Args:
        signal_key: One of the five signal keys in DEFAULT_WEIGHTS.
        score: Raw suspicion score in [0, 1].

    Returns:
        Human-readable explanation string suitable for the alert panel.
    """
    tier = "high" if score >= _HIGH else ("medium" if score >= _MED else "low")
    return _EXPLANATIONS[signal_key][tier]


_EXPLANATIONS: dict[str, dict[str, str]] = {
    "latency": {
        "high": (
            "Response latency is suspiciously constant (CV < 0.15), consistent with a "
            "fixed LLM inference + text-to-speech pipeline rather than genuine human thinking."
        ),
        "medium": (
            "Response latency shows moderate uniformity. Some turns may have unusually "
            "consistent timing — worth monitoring across the full call."
        ),
        "low": "Response latency shows natural human variation across turns.",
    },
    "bg_audio": {
        "high": (
            "Mechanical keyboard typing was detected in multiple silence windows during "
            "candidate 'thinking' pauses, suggesting active use of an AI assistant."
        ),
        "medium": (
            "Possible keyboard activity detected in one or more silence windows. "
            "Confidence is moderate — ambient noise may be a factor."
        ),
        "low": "No keyboard activity detected in candidate silence windows.",
    },
    "perplexity": {
        "high": (
            "Transcript text has unusually low language-model perplexity, indicating "
            "highly predictable, AI-generated phrasing rather than spontaneous speech."
        ),
        "medium": (
            "Transcript perplexity is moderately low. Some responses appear more formulaic "
            "than typical spontaneous speech."
        ),
        "low": "Transcript perplexity is within the normal range for spontaneous human speech.",
    },
    "burstiness": {
        "high": (
            "Sentence-length variance is unusually low. AI-generated text tends to produce "
            "homogeneous sentence lengths; natural speech is significantly more bursty."
        ),
        "medium": (
            "Sentence-length variation is somewhat below average. The transcript may contain "
            "a mix of natural and AI-generated passages."
        ),
        "low": "Natural burstiness detected — sentence-length variance is within the human norm.",
    },
    "similarity": {
        "high": (
            "Candidate answers show high semantic similarity to canonical ChatGPT / GPT-4 "
            "responses in the reference bank, indicating likely AI-assisted answers."
        ),
        "medium": (
            "Moderate semantic overlap with the LLM answer bank detected. Candidate may be "
            "paraphrasing AI-generated content."
        ),
        "low": "Candidate answers show low similarity to known AI response patterns.",
    },
}


def _build_flag_reason(signals: list[SignalBreakdown], suspicion_index: float) -> str:
    """Build a non-empty flag reason string from the top contributing signals.

    Per CLAUDE.md §8: a flagged candidate must always have a human-readable
    explanation attached — this function guarantees that invariant.

    Args:
        signals: Signal list sorted by weighted_contribution descending.
        suspicion_index: The overall suspicion index that triggered the flag.

    Returns:
        Multi-line explanation string listing the top driving signals.
    """
    top = [s for s in signals if s.raw_score >= _MED][:3]
    if not top:
        top = signals[:2]   # fallback: always produce at least one line

    lines = [
        f"Session flagged (suspicion index: {suspicion_index:.2f}). "
        "Top contributing signals:"
    ]
    for i, sig in enumerate(top, 1):
        lines.append(
            f"  {i}. {sig.signal_name} (score={sig.raw_score:.2f}, "
            f"weight={sig.weight:.2f}): {sig.explanation}"
        )
    return "\n".join(lines)
