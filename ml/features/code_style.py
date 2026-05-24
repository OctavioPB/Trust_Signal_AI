"""Code style uniformity feature extractor — Sprint 17.

Combines three signals to detect AI-generated source code style patterns:

1. **Comment density** (35 %): Ratio of comment lines to total non-blank
   lines. AI-generated code is often over-commented with formulaic inline
   explanations; unusually high ratios raise suspicion.

2. **Identifier naming uniformity** (35 %): Mean pairwise Levenshtein
   distance between extracted identifiers. AI tends to produce very consistent
   naming patterns (low edit distance between names); high uniformity →
   high suspicion.

3. **Boilerplate ratio** (30 %): Fraction of lines matching structural
   boilerplate patterns (shebang, ``if __name__ == '__main__'``, copyright
   headers). AI generation frequently injects canonical boilerplate; unusually
   high ratios raise suspicion.

Suspicion score mappings:
    Comment density  ≥ 0.30 → suspicion 1.0  |  ≤ 0.05 → suspicion 0.0
    Naming Levenshtein ≤ 3  → suspicion 1.0  |  ≥ 10   → suspicion 0.0
    Boilerplate ratio  ≥ 0.15 → suspicion 1.0 |  ≤ 0.02  → suspicion 0.0
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import islice
from random import Random

import structlog

logger = structlog.get_logger(__name__)

# ── Normalisation bounds ───────────────────────────────────────────────────────

_COMMENT_MAX_SUSPICION    = 0.30   # ≥ 30 % comment lines → suspicion 1.0
_COMMENT_MIN_SUSPICION    = 0.05   # ≤  5 % comment lines → suspicion 0.0

_NAMING_MAX_SUSPICION     = 3.0    # avg pairwise edit distance ≤ 3 → suspicion 1.0
_NAMING_MIN_SUSPICION     = 10.0   # avg pairwise edit distance ≥ 10 → suspicion 0.0

_BOILERPLATE_MAX_SUSPICION = 0.15  # ≥ 15 % boilerplate lines → suspicion 1.0
_BOILERPLATE_MIN_SUSPICION = 0.02  # ≤  2 % boilerplate lines → suspicion 0.0

# Performance cap on identifier-pair sampling
_MAX_IDENTIFIER_PAIRS = 50

# Combined-score weights (must sum to 1.0)
_W_COMMENT     = 0.35
_W_NAMING      = 0.35
_W_BOILERPLATE = 0.30

# Regex patterns
_IDENTIFIER_RE  = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]{2,})\b")
_COMMENT_LINE_RE = re.compile(
    r"^\s*(?:#|//|/\*|\*|<!--)"
)
_BOILERPLATE_RE = re.compile(
    r"(?:"
    r"^#!\s*/usr/bin/env\s+"          # shebang
    r"|^#!\s*/usr/bin/python"
    r"|^\s*if\s+__name__\s*==\s*['\"]__main__['\"]"   # Python entry guard
    r"|copyright\s+\(c\)"             # copyright
    r"|all\s+rights\s+reserved"
    r"|spdx-license-identifier"       # SPDX header
    r"|auto-generated"                # generic generated marker
    r"|do\s+not\s+edit"
    r")",
    re.IGNORECASE,
)


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class CodeFileStyleResult:
    """Per-file style metrics.

    Attributes:
        file_path: Relative path within the repository.
        comment_density: Fraction of comment lines to total non-blank lines.
        avg_identifier_edit_distance: Mean pairwise Levenshtein distance across
            sampled identifier pairs.
        boilerplate_ratio: Fraction of lines matching boilerplate patterns.
        suspicion_score: Weighted aggregate in [0, 1] for this file.
    """

    file_path: str
    comment_density: float
    avg_identifier_edit_distance: float
    boilerplate_ratio: float
    suspicion_score: float


@dataclass
class CodeStyleFeatures:
    """Aggregated code-style suspicion features for a repository.

    Attributes:
        repo_uuid: UUID of the repository (no PII).
        file_results: Per-file style results (file_path → CodeFileStyleResult).
        avg_comment_density: Character-count-weighted mean comment density.
        avg_identifier_edit_distance: Character-count-weighted mean Levenshtein
            distance across all files.
        avg_boilerplate_ratio: Character-count-weighted mean boilerplate ratio.
        suspicion_score: Weighted aggregate in [0, 1].
    """

    repo_uuid: str
    file_results: dict[str, CodeFileStyleResult] = field(default_factory=dict)
    avg_comment_density: float = 0.0
    avg_identifier_edit_distance: float = 0.0
    avg_boilerplate_ratio: float = 0.0
    suspicion_score: float = 0.0


# ── Scorer ─────────────────────────────────────────────────────────────────────

class CodeStyleScorer:
    """Scores source code files for AI-generation-correlated style patterns.

    Args:
        seed: Random seed for identifier-pair sampling (default 42, deterministic).
    """

    def __init__(self, seed: int = 42) -> None:
        self._rng = Random(seed)
        self._log = logger.bind(component="CodeStyleScorer")

    def score_file(
        self,
        file_path: str,
        content: str,
    ) -> CodeFileStyleResult:
        """Compute style suspicion metrics for a single source file.

        Args:
            file_path: Relative path within the repository.
            content: Decoded UTF-8 source text.

        Returns:
            CodeFileStyleResult with suspicion_score in [0, 1].
        """
        comment_density  = _comment_density(content)
        avg_edit_dist    = _avg_identifier_edit_distance(content, self._rng)
        boilerplate_ratio = _boilerplate_ratio(content)

        comment_susp     = _normalise(comment_density,   _COMMENT_MAX_SUSPICION,    _COMMENT_MIN_SUSPICION,    inverse=False)
        naming_susp      = _normalise(avg_edit_dist,     _NAMING_MAX_SUSPICION,     _NAMING_MIN_SUSPICION,     inverse=True)
        boilerplate_susp = _normalise(boilerplate_ratio, _BOILERPLATE_MAX_SUSPICION, _BOILERPLATE_MIN_SUSPICION, inverse=False)

        suspicion = float(
            min(1.0, _W_COMMENT * comment_susp + _W_NAMING * naming_susp + _W_BOILERPLATE * boilerplate_susp)
        )

        return CodeFileStyleResult(
            file_path=file_path,
            comment_density=round(comment_density, 4),
            avg_identifier_edit_distance=round(avg_edit_dist, 4),
            boilerplate_ratio=round(boilerplate_ratio, 4),
            suspicion_score=round(suspicion, 4),
        )

    def score_repo(
        self,
        repo_uuid: str,
        files: list[tuple[str, str]],
    ) -> CodeStyleFeatures:
        """Score all source files and compute a character-count-weighted aggregate.

        Args:
            repo_uuid: UUID of the repository (no PII).
            files: List of (file_path, content) tuples.

        Returns:
            CodeStyleFeatures with suspicion_score in [0, 1].
            Returns 0.0 when no files have enough content to score.
        """
        file_results: dict[str, CodeFileStyleResult] = {}
        total_weight   = 0.0
        w_comment_sum  = 0.0
        w_naming_sum   = 0.0
        w_bplate_sum   = 0.0
        w_susp_sum     = 0.0

        for file_path, content in files:
            if not content.strip():
                continue
            result = self.score_file(file_path, content)
            weight = float(len(content))

            file_results[file_path] = result
            total_weight  += weight
            w_comment_sum += result.comment_density * weight
            w_naming_sum  += result.avg_identifier_edit_distance * weight
            w_bplate_sum  += result.boilerplate_ratio * weight
            w_susp_sum    += result.suspicion_score * weight

        if total_weight == 0.0:
            return CodeStyleFeatures(repo_uuid=repo_uuid)

        aggregate = CodeStyleFeatures(
            repo_uuid=repo_uuid,
            file_results=file_results,
            avg_comment_density=round(w_comment_sum / total_weight, 4),
            avg_identifier_edit_distance=round(w_naming_sum / total_weight, 4),
            avg_boilerplate_ratio=round(w_bplate_sum / total_weight, 4),
            suspicion_score=round(w_susp_sum / total_weight, 4),
        )

        self._log.debug(
            "code_style_repo_scored",
            repo_uuid=repo_uuid,           # UUID — no PII
            files_scored=len(file_results),
            suspicion_score=aggregate.suspicion_score,
        )

        return aggregate


# ── Pure helpers ───────────────────────────────────────────────────────────────

def _comment_density(content: str) -> float:
    """Return fraction of non-blank lines that are comment lines.

    Args:
        content: Source file text.

    Returns:
        Ratio in [0, 1]; 0.0 for empty or all-blank files.
    """
    lines = [ln for ln in content.splitlines() if ln.strip()]
    if not lines:
        return 0.0
    comment_count = sum(1 for ln in lines if _COMMENT_LINE_RE.match(ln))
    return comment_count / len(lines)


def _avg_identifier_edit_distance(content: str, rng: Random) -> float:
    """Return mean pairwise Levenshtein distance for sampled identifiers.

    Extracts all identifiers (≥ 3 chars) from the file, samples up to
    ``_MAX_IDENTIFIER_PAIRS`` random pairs, and returns the mean edit distance.
    Returns 0.0 when fewer than 2 unique identifiers are found.

    Args:
        content: Source file text.
        rng: Random instance for deterministic pair sampling.

    Returns:
        Mean pairwise Levenshtein distance (float ≥ 0.0).
    """
    identifiers = list(set(_IDENTIFIER_RE.findall(content)))
    if len(identifiers) < 2:
        return 0.0

    pairs: list[tuple[str, str]] = []
    n = len(identifiers)
    all_pairs = [
        (identifiers[i], identifiers[j])
        for i in range(n)
        for j in range(i + 1, n)
    ]
    if len(all_pairs) > _MAX_IDENTIFIER_PAIRS:
        pairs = rng.sample(all_pairs, _MAX_IDENTIFIER_PAIRS)
    else:
        pairs = all_pairs

    if not pairs:
        return 0.0

    total = sum(_levenshtein(a, b) for a, b in pairs)
    return total / len(pairs)


def _boilerplate_ratio(content: str) -> float:
    """Return fraction of lines matching boilerplate patterns.

    Args:
        content: Source file text.

    Returns:
        Ratio in [0, 1]; 0.0 for empty files.
    """
    lines = content.splitlines()
    if not lines:
        return 0.0
    boilerplate_count = sum(1 for ln in lines if _BOILERPLATE_RE.search(ln))
    return boilerplate_count / len(lines)


def _normalise(
    value: float,
    max_susp: float,
    min_susp: float,
    inverse: bool = False,
) -> float:
    """Map a metric to a suspicion score in [0, 1] (clamped).

    When ``inverse=False`` (default): value ≥ max_susp → 1.0; value ≤ min_susp → 0.0.
    When ``inverse=True``: value ≤ max_susp → 1.0; value ≥ min_susp → 0.0
        (used for metrics where *low* values are suspicious, e.g. edit distance).

    Args:
        value: The metric value to normalise.
        max_susp: Metric threshold for maximum suspicion.
        min_susp: Metric threshold for zero suspicion.
        inverse: Flip the mapping direction.

    Returns:
        Suspicion score in [0, 1].
    """
    if max_susp == min_susp:
        return 0.0
    if inverse:
        # lower value → higher suspicion
        raw = (min_susp - value) / (min_susp - max_susp)
    else:
        # higher value → higher suspicion
        raw = (value - min_susp) / (max_susp - min_susp)
    return float(max(0.0, min(1.0, raw)))


def _levenshtein(a: str, b: str) -> int:
    """Compute Levenshtein edit distance between two strings.

    Pure Python implementation; no external dependency.

    Args:
        a: Source string.
        b: Target string.

    Returns:
        Minimum number of single-character edits to transform a into b.
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            curr[j] = min(
                prev[j] + 1,           # deletion
                curr[j - 1] + 1,       # insertion
                prev[j - 1] + (ca != cb),  # substitution
            )
        prev = curr
    return prev[len(b)]
