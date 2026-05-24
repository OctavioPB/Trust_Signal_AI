"""RepoAIScore aggregation engine — Sprint 17.

Combines three repository signal modules into a single RepoAIScore (0–100)
with a per-signal breakdown and human-readable explanation.

RepoAIScore      = suspicion_index × 100
suspicion_index  = Σ (signal_score_i × weight_i)   ∈ [0, 1]

Higher RepoAIScore = more likely AI-generated repository content.

Default weights:
  Code Perplexity  0.35
  Commit Pattern   0.35
  Code Style       0.30

Per CLAUDE.md §8.2: any repository flagged above the threshold must include
a human-readable explanation per contributing signal in the flag_reason field.
This invariant is enforced in RepoScoreEngine.compute() and must never be
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
    "code_perplexity": 0.35,
    "commit_pattern":  0.35,
    "code_style":      0.30,
}

_SIGNAL_LABELS: dict[str, str] = {
    "code_perplexity": "Code Perplexity",
    "commit_pattern":  "Commit Pattern",
    "code_style":      "Code Style Uniformity",
}

_HIGH = 0.65
_MED  = 0.35


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class RepoSignalDetail:
    """Per-signal contribution to the RepoAIScore.

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
class RepoScoreResult:
    """Output of the RepoScoreEngine for a single repository.

    Attributes:
        repo_uuid: UUID of the repository (no PII).
        repo_ai_score: Aggregated score in [0, 100]; higher = more suspicious.
        suspicion_index: Weighted sum of all signal scores in [0, 1].
        signals: Per-signal breakdown sorted by weighted_contribution descending.
        flagged: True when suspicion_index ≥ prescreening_threshold.
        flag_reason: Non-empty human-readable explanation whenever flagged=True.
            Per CLAUDE.md §8.2: never suppressed silently.
        scored_at: Unix timestamp of when the score was computed.
    """

    repo_uuid: str
    repo_ai_score: float
    suspicion_index: float
    signals: list[RepoSignalDetail] = field(default_factory=list)
    flagged: bool = False
    flag_reason: str = ""
    scored_at: float = field(default_factory=time.time)


# ── Engine ─────────────────────────────────────────────────────────────────────

class RepoScoreEngine:
    """Aggregates three repository signal scores into a RepoAIScore.

    Args:
        weights: Per-signal weight overrides. Keys must be a subset of
            ``DEFAULT_WEIGHTS``. The full weight set must sum to 1.0 ± 1e-4.
        prescreening_threshold: Repositories above this suspicion_index are
            flagged. Defaults to ``config.SUSPICION_THRESHOLD``.
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
            component="RepoScoreEngine", threshold=self._threshold
        )

    def compute(
        self,
        repo_uuid: str,
        code_perplexity_score: float,
        commit_pattern_score: float,
        code_style_score: float,
    ) -> RepoScoreResult:
        """Aggregate three repository signal scores into a RepoAIScore.

        Each input score is clamped to [0, 1] before weighting.

        Args:
            repo_uuid: UUID of the repository (no PII in logs).
            code_perplexity_score: LM perplexity suspicion score in [0, 1].
            commit_pattern_score: Commit-pattern suspicion score in [0, 1].
            code_style_score: Code style uniformity suspicion score in [0, 1].

        Returns:
            RepoScoreResult with repo_ai_score in [0, 100] and a full
            per-signal breakdown sorted by weighted contribution descending.
        """
        raw: dict[str, float] = {
            "code_perplexity": float(max(0.0, min(1.0, code_perplexity_score))),
            "commit_pattern":  float(max(0.0, min(1.0, commit_pattern_score))),
            "code_style":      float(max(0.0, min(1.0, code_style_score))),
        }

        signals: list[RepoSignalDetail] = []
        suspicion_index = 0.0

        for key, score in raw.items():
            weight       = self._weights[key]
            contribution = score * weight
            suspicion_index += contribution
            signals.append(
                RepoSignalDetail(
                    signal_name=_SIGNAL_LABELS[key],
                    raw_score=score,
                    weight=weight,
                    weighted_contribution=contribution,
                    explanation=_explain(key, score),
                )
            )

        signals.sort(key=lambda s: s.weighted_contribution, reverse=True)
        suspicion_index = float(max(0.0, min(1.0, suspicion_index)))
        repo_ai_score   = round(suspicion_index * 100.0, 2)
        flagged         = suspicion_index >= self._threshold

        # HARD RULE (CLAUDE.md §8.2): flag_reason must never be empty when flagged.
        flag_reason = _build_flag_reason(signals, suspicion_index) if flagged else ""

        result = RepoScoreResult(
            repo_uuid=repo_uuid,
            repo_ai_score=repo_ai_score,
            suspicion_index=round(suspicion_index, 4),
            signals=signals,
            flagged=flagged,
            flag_reason=flag_reason,
        )

        self._log.info(
            "repo_score_computed",
            repo_uuid=repo_uuid,           # UUID — no PII
            repo_ai_score=repo_ai_score,
            suspicion_index=result.suspicion_index,
            flagged=flagged,
        )

        return result


# ── Explanation helpers ────────────────────────────────────────────────────────

def _explain(signal_key: str, score: float) -> str:
    tier = "high" if score >= _HIGH else ("medium" if score >= _MED else "low")
    return _EXPLANATIONS[signal_key][tier]


_EXPLANATIONS: dict[str, dict[str, str]] = {
    "code_perplexity": {
        "high": (
            "Repository code has unusually low language-model perplexity, indicating "
            "highly predictable, formulaic source code consistent with AI generation "
            "rather than organic human authorship."
        ),
        "medium": (
            "Code perplexity is moderately low. Some files appear more templated than "
            "typical human-authored source code."
        ),
        "low": "Code perplexity is within the normal range for human-authored repositories.",
    },
    "commit_pattern": {
        "high": (
            "Commit history shows strong AI-generation indicators: highly uniform "
            "commit message lengths and/or a velocity burst where the majority of "
            "commits were pushed in a single session."
        ),
        "medium": (
            "Commit message variety is below the human average. Some burst activity "
            "detected that may indicate batch uploading of pre-written code."
        ),
        "low": "Commit history shows natural variation consistent with ongoing human development.",
    },
    "code_style": {
        "high": (
            "Code style analysis detected AI-correlated patterns: high comment density "
            "with formulaic phrasing, unusually uniform identifier naming, and/or "
            "excessive boilerplate injection across files."
        ),
        "medium": (
            "Code style shows moderate AI-correlated patterns. Identifier naming is "
            "more uniform than typical and comment density is elevated."
        ),
        "low": "Code style metrics are consistent with natural human coding patterns.",
    },
}


def _build_flag_reason(signals: list[RepoSignalDetail], suspicion_index: float) -> str:
    """Build a non-empty flag reason from the top contributing signals.

    Per CLAUDE.md §8.2: a flagged repository must always have a human-readable
    explanation attached — this function guarantees that invariant.
    """
    top = [s for s in signals if s.raw_score >= _MED][:3]
    if not top:
        top = signals[:2]

    lines = [
        f"Repository flagged (AI suspicion index: {suspicion_index:.2f}). "
        "Top contributing signals:"
    ]
    for i, sig in enumerate(top, 1):
        lines.append(
            f"  {i}. {sig.signal_name} (score={sig.raw_score:.2f}, "
            f"weight={sig.weight:.2f}): {sig.explanation}"
        )
    return "\n".join(lines)
