"""Commit-pattern and line-diversity feature extractor — Sprint 17.

Combines two signals:

1. **Commit suspicion** (60 %): Re-uses ``analyze_commits`` from the
   ingestion layer. Low message-length entropy or a velocity burst (>80 %
   commits in one ISO week) raises suspicion.

2. **Line-length entropy** (40 %): Shannon entropy of code-line lengths per
   file, averaged across all repo files. AI-generated code often has very
   uniform line lengths; human code shows greater natural variation.

Suspicion score mapping for line-length entropy:
    entropy ≤ 1.0 → score 1.0  (very uniform — AI-like)
    entropy ≥ 4.0 → score 0.0  (naturally varied — human-like)

PII discipline: CommitSummary objects contain no author names or email
addresses. CommitPatternFeatures likewise exposes no author PII.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

import structlog

from ingestion.commit_analyzer import CommitAnalysisResult, analyze_commits

logger = structlog.get_logger(__name__)

# ── Normalisation bounds ───────────────────────────────────────────────────────

_LINE_ENTROPY_HIGH_SUSPICION = 1.0   # ≤ 1.0 bits → line suspicion 1.0
_LINE_ENTROPY_LOW_SUSPICION  = 4.0   # ≥ 4.0 bits → line suspicion 0.0

# Combined-score weights (must sum to 1.0)
_W_COMMIT = 0.60
_W_LINE   = 0.40


# ── Data class ─────────────────────────────────────────────────────────────────

@dataclass
class CommitPatternFeatures:
    """Commit-pattern and line-diversity suspicion features for a repository.

    Attributes:
        repo_uuid: UUID of the repository (no PII).
        message_length_entropy: Shannon entropy (bits) of commit message
            lengths. Low entropy → uniform messages → AI-like.
        velocity_burst_detected: True when > 80 % of commits fall in a single
            ISO calendar week (copy-paste / AI-dump signal).
        avg_line_length_entropy: Mean Shannon entropy (bits) of code-line
            lengths across scored files. Low entropy → AI-like.
        suspicion_score: Weighted aggregate in [0, 1]; higher → more AI-like.
    """

    repo_uuid: str
    message_length_entropy: float
    velocity_burst_detected: bool
    avg_line_length_entropy: float
    suspicion_score: float


# ── Scorer ─────────────────────────────────────────────────────────────────────

class CommitPatternScorer:
    """Scores a repository's commit patterns and code line-length diversity.

    Args:
        w_commit: Weight assigned to the commit-pattern signal (default 0.60).
        w_line: Weight assigned to the line-length entropy signal (default 0.40).
    """

    def __init__(
        self,
        w_commit: float = _W_COMMIT,
        w_line: float   = _W_LINE,
    ) -> None:
        if abs(w_commit + w_line - 1.0) > 1e-4:
            raise ValueError(
                f"Weights must sum to 1.0; got {w_commit + w_line:.6f}."
            )
        self._w_commit = w_commit
        self._w_line   = w_line
        self._log = logger.bind(component="CommitPatternScorer")

    def score_repo(
        self,
        repo_uuid: str,
        commits: list,                       # list[CommitSummary]
        files: list[tuple[str, str]],        # [(file_path, content), ...]
    ) -> CommitPatternFeatures:
        """Compute commit-pattern and line-diversity suspicion for a repository.

        When ``commits`` is empty the commit signal defaults to 0.5 (neutral
        fallback) so the scorer can still contribute line-diversity information.

        Args:
            repo_uuid: UUID of the repository (no PII in logs).
            commits: CommitSummary objects from the crawler. May be empty.
            files: List of (file_path, content) tuples for all source files.

        Returns:
            CommitPatternFeatures with suspicion_score in [0, 1].
        """
        # ── commit signal ──────────────────────────────────────────────────────
        if commits:
            commit_result: CommitAnalysisResult = analyze_commits(repo_uuid, commits)
            commit_susp   = commit_result.suspicion_score
            msg_entropy   = commit_result.message_length_entropy
            burst         = commit_result.velocity_burst_detected
        else:
            commit_susp = 0.5   # neutral fallback when no commit data available
            msg_entropy = 0.0
            burst       = False

        # ── line-length entropy signal ─────────────────────────────────────────
        line_entropies: list[float] = []
        for _file_path, content in files:
            ent = _line_length_entropy(content)
            if ent is not None:
                line_entropies.append(ent)

        if line_entropies:
            avg_line_ent  = sum(line_entropies) / len(line_entropies)
            line_susp     = _normalise_line_entropy(avg_line_ent)
        else:
            avg_line_ent = 0.0
            line_susp    = 0.0

        suspicion = float(
            min(1.0, self._w_commit * commit_susp + self._w_line * line_susp)
        )

        self._log.debug(
            "commit_pattern_scored",
            repo_uuid=repo_uuid,           # UUID — no PII
            commit_suspicion=round(commit_susp, 4),
            line_entropy_suspicion=round(line_susp, 4),
            avg_line_length_entropy=round(avg_line_ent, 4),
            suspicion_score=round(suspicion, 4),
        )

        return CommitPatternFeatures(
            repo_uuid=repo_uuid,
            message_length_entropy=round(msg_entropy, 6),
            velocity_burst_detected=burst,
            avg_line_length_entropy=round(avg_line_ent, 4),
            suspicion_score=round(suspicion, 4),
        )


# ── Pure helpers ───────────────────────────────────────────────────────────────

def _line_length_entropy(content: str) -> float | None:
    """Compute Shannon entropy (bits) of line lengths in a source file.

    Args:
        content: Decoded source-file text.

    Returns:
        Entropy in bits, or None when the file has fewer than 5 non-empty
        lines (too few for a reliable estimate).
    """
    lines = [len(ln) for ln in content.splitlines() if ln.strip()]
    if len(lines) < 5:
        return None
    counter = Counter(lines)
    total   = len(lines)
    return float(
        -sum((c / total) * math.log2(c / total) for c in counter.values())
    )


def _normalise_line_entropy(entropy: float) -> float:
    """Map raw line-length entropy to a suspicion score in [0, 1].

    Args:
        entropy: Shannon entropy (bits) of per-file line lengths.

    Returns:
        Suspicion score in [0, 1]; low entropy → high suspicion.
    """
    span = _LINE_ENTROPY_LOW_SUSPICION - _LINE_ENTROPY_HIGH_SUSPICION
    raw  = (_LINE_ENTROPY_LOW_SUSPICION - entropy) / span
    return float(max(0.0, min(1.0, raw)))
