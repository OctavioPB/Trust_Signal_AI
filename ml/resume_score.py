"""ResumeAIScore aggregation engine.

Combines four signal modules into a single ResumeAIScore (0–100) with a
per-signal breakdown and human-readable explanation.

ResumeAIScore = suspicion_index × 100
suspicion_index = Σ (signal_score_i × weight_i)   ∈ [0, 1]

Higher ResumeAIScore = more likely AI-generated resume content.

Default weights:
  Perplexity         0.30
  Burstiness         0.25
  Vocab Richness     0.25
  Section Uniformity 0.20

Per CLAUDE.md §8.2: any resume flagged above the threshold must include a
human-readable explanation per contributing signal in the flag_reason field.
This invariant is enforced in ResumeScoreEngine.compute() and must never be
silently suppressed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import structlog

import config

logger = structlog.get_logger(__name__)

# ── Default weights ────────────────────────────────────────────────────────────

DEFAULT_WEIGHTS: dict[str, float] = {
    "perplexity":         0.30,
    "burstiness":         0.25,
    "vocab_richness":     0.25,
    "section_uniformity": 0.20,
}

_SIGNAL_LABELS: dict[str, str] = {
    "perplexity":         "Perplexity",
    "burstiness":         "Burstiness",
    "vocab_richness":     "Vocabulary Richness",
    "section_uniformity": "Section Style Uniformity",
}

_HIGH = 0.65
_MED  = 0.35


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class ResumeSignalDetail:
    """Per-signal contribution to the ResumeAIScore.

    Attributes:
        signal_name: Human-readable signal label for the dashboard.
        raw_score: Raw suspicion score from the signal module in [0, 1].
        weight: Configured weight for this signal.
        weighted_contribution: raw_score × weight.
        explanation: One-sentence human-readable explanation (CLAUDE.md §8.2).
    """

    signal_name: str
    raw_score: float
    weight: float
    weighted_contribution: float
    explanation: str


@dataclass
class ResumeScoreResult:
    """Output of the ResumeScoreEngine for a single candidate.

    Attributes:
        candidate_uuid: UUID of the candidate (no PII).
        resume_ai_score: Aggregated score in [0, 100]; higher = more suspicious.
        suspicion_index: Weighted sum of all signal scores in [0, 1].
        signals: Per-signal breakdown sorted by weighted_contribution descending.
        flagged: True when suspicion_index ≥ prescreening_threshold.
        flag_reason: Non-empty human-readable explanation whenever flagged=True.
            Per CLAUDE.md §8.2: never suppressed silently.
        scored_at: Unix timestamp of when the score was computed.
    """

    candidate_uuid: str
    resume_ai_score: float
    suspicion_index: float
    signals: list[ResumeSignalDetail] = field(default_factory=list)
    flagged: bool = False
    flag_reason: str = ""
    scored_at: float = field(default_factory=time.time)


# ── Engine ─────────────────────────────────────────────────────────────────────

class ResumeScoreEngine:
    """Aggregates four resume signal scores into a ResumeAIScore.

    Args:
        weights: Per-signal weight overrides. Keys must be a subset of
            ``DEFAULT_WEIGHTS``. The full weight set must sum to 1.0 ± 1e-4.
        prescreening_threshold: Resumes above this suspicion_index are flagged.
            Defaults to ``config.SUSPICION_THRESHOLD``.
    """

    def __init__(
        self,
        weights: dict[str, float] | None = None,
        prescreening_threshold: float | None = None,
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
                f"Signal weights must sum to 1.0; got {total:.6f}."
            )

        self._threshold = (
            prescreening_threshold
            if prescreening_threshold is not None
            else config.SUSPICION_THRESHOLD
        )
        self._log = logger.bind(
            component="ResumeScoreEngine", threshold=self._threshold
        )

    def compute(
        self,
        candidate_uuid: str,
        perplexity_score: float,
        burstiness_score: float,
        vocab_richness_score: float,
        section_uniformity_score: float,
    ) -> ResumeScoreResult:
        """Aggregate four resume signal scores into a ResumeAIScore.

        Each input score is clamped to [0, 1] before weighting.

        Args:
            candidate_uuid: UUID of the candidate (no PII in logs).
            perplexity_score: LM perplexity suspicion score in [0, 1].
            burstiness_score: Sentence burstiness suspicion score in [0, 1].
            vocab_richness_score: Vocabulary richness suspicion score in [0, 1].
            section_uniformity_score: Section style uniformity score in [0, 1].

        Returns:
            ResumeScoreResult with resume_ai_score in [0, 100] and a full
            per-signal breakdown sorted by weighted contribution descending.
        """
        raw: dict[str, float] = {
            "perplexity":         float(max(0.0, min(1.0, perplexity_score))),
            "burstiness":         float(max(0.0, min(1.0, burstiness_score))),
            "vocab_richness":     float(max(0.0, min(1.0, vocab_richness_score))),
            "section_uniformity": float(max(0.0, min(1.0, section_uniformity_score))),
        }

        signals: list[ResumeSignalDetail] = []
        suspicion_index = 0.0

        for key, score in raw.items():
            weight = self._weights[key]
            contribution = score * weight
            suspicion_index += contribution
            signals.append(
                ResumeSignalDetail(
                    signal_name=_SIGNAL_LABELS[key],
                    raw_score=score,
                    weight=weight,
                    weighted_contribution=contribution,
                    explanation=_explain(key, score),
                )
            )

        signals.sort(key=lambda s: s.weighted_contribution, reverse=True)
        suspicion_index = float(max(0.0, min(1.0, suspicion_index)))
        resume_ai_score = round(suspicion_index * 100.0, 2)
        flagged = suspicion_index >= self._threshold

        # HARD RULE (CLAUDE.md §8.2): flag_reason must never be empty when flagged.
        flag_reason = _build_flag_reason(signals, suspicion_index) if flagged else ""

        result = ResumeScoreResult(
            candidate_uuid=candidate_uuid,
            resume_ai_score=resume_ai_score,
            suspicion_index=round(suspicion_index, 4),
            signals=signals,
            flagged=flagged,
            flag_reason=flag_reason,
        )

        self._log.info(
            "resume_score_computed",
            candidate_uuid=candidate_uuid,   # UUID — no PII
            resume_ai_score=resume_ai_score,
            suspicion_index=result.suspicion_index,
            flagged=flagged,
        )

        return result


# ── Explanation helpers ────────────────────────────────────────────────────────

def _explain(signal_key: str, score: float) -> str:
    tier = "high" if score >= _HIGH else ("medium" if score >= _MED else "low")
    return _EXPLANATIONS[signal_key][tier]


_EXPLANATIONS: dict[str, dict[str, str]] = {
    "perplexity": {
        "high": (
            "Resume text has unusually low language-model perplexity, indicating "
            "highly predictable phrasing consistent with AI-generated content rather "
            "than authentic personal writing."
        ),
        "medium": (
            "Resume perplexity is moderately low. Some sections appear more formulaic "
            "than typical human-authored writing."
        ),
        "low": "Resume perplexity is within the normal range for human-authored text.",
    },
    "burstiness": {
        "high": (
            "Sentence-length variance across resume sections is unusually low, indicating "
            "homogeneous structure consistent with AI-generated bullet points."
        ),
        "medium": (
            "Sentence-length variation is below the human average. The resume may contain "
            "a mix of natural and AI-generated passages."
        ),
        "low": "Sentence-length variation is within the human norm for resume writing.",
    },
    "vocab_richness": {
        "high": (
            "Vocabulary richness (type-token and hapax ratios) is significantly below "
            "human norms, suggesting formulaic repetition of industry keywords consistent "
            "with AI generation."
        ),
        "medium": (
            "Vocabulary diversity is moderately low. Repeated use of specific power words "
            "across sections may indicate AI-assisted drafting."
        ),
        "low": "Vocabulary richness is consistent with natural human writing.",
    },
    "section_uniformity": {
        "high": (
            "All resume sections are stylistically near-identical (low cross-section "
            "cosine distance), which is a strong indicator of AI generation — humans "
            "write differently across Summary, Experience, and Skills."
        ),
        "medium": (
            "Resume sections show moderate stylistic overlap. Some style convergence "
            "detected that may indicate AI-assisted editing."
        ),
        "low": "Resume sections show natural stylistic variation across content types.",
    },
}


def _build_flag_reason(signals: list[ResumeSignalDetail], suspicion_index: float) -> str:
    """Build a non-empty flag reason from the top contributing signals.

    Per CLAUDE.md §8.2: a flagged resume must always have a human-readable
    explanation attached — this function guarantees that invariant.
    """
    top = [s for s in signals if s.raw_score >= _MED][:3]
    if not top:
        top = signals[:2]

    lines = [
        f"Resume flagged (AI suspicion index: {suspicion_index:.2f}). "
        "Top contributing signals:"
    ]
    for i, sig in enumerate(top, 1):
        lines.append(
            f"  {i}. {sig.signal_name} (score={sig.raw_score:.2f}, "
            f"weight={sig.weight:.2f}): {sig.explanation}"
        )
    return "\n".join(lines)
