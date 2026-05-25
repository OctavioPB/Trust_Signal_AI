"""Pre-Screening Score aggregation engine — Sprint 18.

Fuses three upstream scores into a single PreScreeningScore (0–100):

    Score source          Default weight   Notes
    ─────────────────     ──────────────   ──────────────────────────────────
    ResumeAIScore         35 %             Always required
    RepoAIScore           35 %             Optional; absent when no repo linked
    InterviewTrustScore   30 %             Optional; absent before interview

Graceful weight re-scaling when optional scores are unavailable:

    Available signals     Resume   Repo    Interview
    ───────────────────   ──────   ──────  ─────────
    All three             35 %     35 %    30 %
    Resume + Repo         50 %     50 %     —
    Resume + Interview    50 %      —      50 %
    Resume only          100 %      —       —

InterviewTrustScore is **inverted** before weighting: a TrustScore of 20
(low trust in human authorship) becomes a suspicion contribution of 0.80.

Severity levels (CLAUDE.md §8.2 compound-alert rule):
    "high"   — flagged AND interview_trust_score is not None AND < threshold
    "medium" — flagged, but severity condition for "high" not met
    "low"    — not flagged
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import structlog

import config

logger = structlog.get_logger(__name__)

# ── Default weights (proportional; re-scaled at runtime) ──────────────────────

_W_RESUME    = 0.35
_W_REPO      = 0.35
_W_INTERVIEW = 0.30

_HIGH = 0.65
_MED  = 0.35

_SIGNAL_LABELS: dict[str, str] = {
    "resume":    "Resume AI Score",
    "repo":      "Repo AI Score",
    "interview": "Interview Trust (inverted)",
}


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class PreScreeningSignalDetail:
    """Per-signal contribution to the PreScreeningScore.

    Attributes:
        signal_name: Human-readable label for the dashboard.
        raw_suspicion: Normalised suspicion in [0, 1] fed into weighting.
        weight: Effective weight used for this run (may differ from default
            when optional signals are absent).
        weighted_contribution: raw_suspicion × weight.
        explanation: One-sentence human-readable explanation (CLAUDE.md §8.2).
    """

    signal_name: str
    raw_suspicion: float
    weight: float
    weighted_contribution: float
    explanation: str


@dataclass
class PreScreeningResult:
    """Output of PreScreeningEngine for a single candidate.

    Attributes:
        candidate_uuid: UUID of the candidate (no PII).
        prescreening_score: Aggregated score in [0, 100]; higher = more suspicious.
        suspicion_index: Weighted sum of signal contributions in [0, 1].
        signals: Per-signal breakdown sorted by weighted_contribution descending.
        flagged: True when suspicion_index ≥ prescreening_threshold.
        severity: "high" / "medium" / "low" per CLAUDE.md compound-alert rule.
        flag_reason: Non-empty human-readable explanation whenever flagged=True.
            Per CLAUDE.md §8.2: never suppressed silently.
        interview_available: True when interview_trust_score was provided.
        repo_available: True when repo_ai_score was provided.
        scored_at: Unix timestamp of score computation.
    """

    candidate_uuid: str
    prescreening_score: float
    suspicion_index: float
    signals: list[PreScreeningSignalDetail] = field(default_factory=list)
    flagged: bool = False
    severity: str = "low"
    flag_reason: str = ""
    interview_available: bool = False
    repo_available: bool = False
    scored_at: float = field(default_factory=time.time)


# ── Engine ─────────────────────────────────────────────────────────────────────

class PreScreeningEngine:
    """Aggregates resume, repo, and interview signals into a PreScreeningScore.

    Args:
        prescreening_threshold: Suspicion index at or above which candidates
            are flagged. Defaults to ``config.SUSPICION_THRESHOLD``.
        interview_high_threshold: InterviewTrustScore below which a compound
            "high" severity alert is triggered. Defaults to
            ``config.INTERVIEW_HIGH_SUSPICION_THRESHOLD`` (40.0).
    """

    def __init__(
        self,
        prescreening_threshold: float | None = None,
        interview_high_threshold: float | None = None,
    ) -> None:
        self._threshold = (
            prescreening_threshold
            if prescreening_threshold is not None
            else config.SUSPICION_THRESHOLD
        )
        self._interview_high_threshold = (
            interview_high_threshold
            if interview_high_threshold is not None
            else config.INTERVIEW_HIGH_SUSPICION_THRESHOLD
        )
        self._log = logger.bind(
            component="PreScreeningEngine", threshold=self._threshold
        )

    def compute(
        self,
        candidate_uuid: str,
        resume_ai_score: float,
        repo_ai_score: float | None = None,
        interview_trust_score: float | None = None,
    ) -> PreScreeningResult:
        """Aggregate available signals into a PreScreeningScore.

        Each input is normalised to [0, 1] before weighting. Scores outside
        [0, 100] are clamped. InterviewTrustScore is **inverted** (lower trust
        = higher suspicion) before entering the weighted sum.

        Args:
            candidate_uuid: UUID of the candidate (no PII in logs).
            resume_ai_score: Resume AI suspicion score in [0, 100].
            repo_ai_score: Repo AI suspicion score in [0, 100], or None.
            interview_trust_score: Interview TrustScore in [0, 100], or None.
                Inverted internally: TrustScore=20 → suspicion contribution 0.80.

        Returns:
            PreScreeningResult with prescreening_score in [0, 100].
        """
        resume_susp = float(max(0.0, min(1.0, resume_ai_score / 100.0)))
        repo_susp = (
            float(max(0.0, min(1.0, repo_ai_score / 100.0)))
            if repo_ai_score is not None else None
        )
        interview_susp = (
            float(max(0.0, min(1.0, (100.0 - interview_trust_score) / 100.0)))
            if interview_trust_score is not None else None
        )

        effective = _resolve_weights(resume_susp, repo_susp, interview_susp)

        signals: list[PreScreeningSignalDetail] = []
        suspicion_index = 0.0

        for key, (susp, weight) in effective.items():
            contribution = susp * weight
            suspicion_index += contribution
            signals.append(
                PreScreeningSignalDetail(
                    signal_name=_SIGNAL_LABELS[key],
                    raw_suspicion=round(susp, 4),
                    weight=round(weight, 4),
                    weighted_contribution=round(contribution, 4),
                    explanation=_explain(key, susp),
                )
            )

        signals.sort(key=lambda s: s.weighted_contribution, reverse=True)
        suspicion_index    = float(max(0.0, min(1.0, suspicion_index)))
        prescreening_score = round(suspicion_index * 100.0, 2)
        flagged            = suspicion_index >= self._threshold

        # HARD RULE (CLAUDE.md §8.2): flag_reason must never be empty when flagged.
        flag_reason = _build_flag_reason(signals, suspicion_index) if flagged else ""
        severity    = _determine_severity(
            flagged=flagged,
            interview_trust_score=interview_trust_score,
            high_threshold=self._interview_high_threshold,
        )

        result = PreScreeningResult(
            candidate_uuid=candidate_uuid,
            prescreening_score=prescreening_score,
            suspicion_index=round(suspicion_index, 4),
            signals=signals,
            flagged=flagged,
            severity=severity,
            flag_reason=flag_reason,
            interview_available=interview_susp is not None,
            repo_available=repo_susp is not None,
        )

        self._log.info(
            "prescreening_score_computed",
            candidate_uuid=candidate_uuid,   # UUID — no PII
            prescreening_score=prescreening_score,
            suspicion_index=result.suspicion_index,
            flagged=flagged,
            severity=severity,
            interview_available=result.interview_available,
            repo_available=result.repo_available,
        )
        return result


# ── Pure helpers ───────────────────────────────────────────────────────────────

def _resolve_weights(
    resume_susp: float,
    repo_susp: float | None,
    interview_susp: float | None,
) -> dict[str, tuple[float, float]]:
    """Return {signal_key: (suspicion, effective_weight)} for each present signal.

    Weights from _W_RESUME / _W_REPO / _W_INTERVIEW are re-scaled
    proportionally so they always sum to 1.0 across the returned entries.

    Args:
        resume_susp: Normalised resume suspicion in [0, 1].
        repo_susp: Normalised repo suspicion in [0, 1], or None.
        interview_susp: Normalised interview suspicion in [0, 1], or None.

    Returns:
        Ordered dict of {key: (suspicion, scaled_weight)}.
    """
    raw: dict[str, float] = {"resume": _W_RESUME}
    if repo_susp is not None:
        raw["repo"] = _W_REPO
    if interview_susp is not None:
        raw["interview"] = _W_INTERVIEW

    total = sum(raw.values())
    scaled = {k: v / total for k, v in raw.items()}

    susp_map: dict[str, float] = {"resume": resume_susp}
    if repo_susp is not None:
        susp_map["repo"] = repo_susp
    if interview_susp is not None:
        susp_map["interview"] = interview_susp

    return {k: (susp_map[k], scaled[k]) for k in scaled}


def _determine_severity(
    flagged: bool,
    interview_trust_score: float | None,
    high_threshold: float,
) -> str:
    """Return compound-alert severity level per CLAUDE.md §8.2.

    Args:
        flagged: Whether the candidate is flagged.
        interview_trust_score: Raw interview trust score (0–100), or None.
        high_threshold: TrustScore below which severity escalates to "high".

    Returns:
        "high", "medium", or "low".
    """
    if not flagged:
        return "low"
    if interview_trust_score is not None and interview_trust_score < high_threshold:
        return "high"
    return "medium"


def _explain(signal_key: str, suspicion: float) -> str:
    tier = "high" if suspicion >= _HIGH else ("medium" if suspicion >= _MED else "low")
    return _EXPLANATIONS[signal_key][tier]


_EXPLANATIONS: dict[str, dict[str, str]] = {
    "resume": {
        "high": (
            "Resume AI score is highly elevated, indicating strong signals of "
            "AI-generated or machine-assisted resume content."
        ),
        "medium": (
            "Resume AI score is moderately elevated. Some sections may have been "
            "drafted or polished with AI assistance."
        ),
        "low": "Resume AI score is within normal human-authored ranges.",
    },
    "repo": {
        "high": (
            "Repository AI score is highly elevated: code perplexity, commit patterns, "
            "and style metrics all indicate AI-generated or templated source code."
        ),
        "medium": (
            "Repository AI score is moderately elevated. Some code patterns are "
            "consistent with AI generation or heavy copy-paste from boilerplate."
        ),
        "low": "Repository AI score is within normal human-authored ranges.",
    },
    "interview": {
        "high": (
            "Interview TrustScore is very low, indicating strong signals of "
            "non-authentic responses during the recorded session."
        ),
        "medium": (
            "Interview TrustScore is below average. Some response patterns suggest "
            "possible AI-assisted or non-spontaneous answers."
        ),
        "low": "Interview TrustScore is within the expected range for authentic responses.",
    },
}


def _build_flag_reason(
    signals: list[PreScreeningSignalDetail],
    suspicion_index: float,
) -> str:
    """Build a non-empty flag reason from top contributing signals.

    Per CLAUDE.md §8.2: never empty when flagged=True.
    """
    top = [s for s in signals if s.raw_suspicion >= _MED][:3]
    if not top:
        top = signals[:2]

    lines = [
        f"Candidate flagged (pre-screening suspicion index: {suspicion_index:.2f}). "
        "Top contributing signals:"
    ]
    for i, sig in enumerate(top, 1):
        lines.append(
            f"  {i}. {sig.signal_name} (suspicion={sig.raw_suspicion:.2f}, "
            f"weight={sig.weight:.2f}): {sig.explanation}"
        )
    return "\n".join(lines)
