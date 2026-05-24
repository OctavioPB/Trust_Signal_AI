"""Cross-section style uniformity scorer for resumes.

Embeds each non-empty section using Sentence-Transformers and measures
pairwise cosine distance between section embeddings. Low mean distance
indicates all sections read in the same style — a strong AI-generation signal,
as LLMs tend to produce stylistically homogeneous text across sections.

Suspicion score mapping:
    mean cosine distance ≤ 0.05 → score 1.0  (all sections sound identical)
    mean cosine distance ≥ 0.50 → score 0.0  (sections are stylistically distinct)

At least 2 non-empty sections are required; returns score 0.0 otherwise.

Default model: all-MiniLM-L6-v2 (matches the retraining DAG's embedding model).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

_DEFAULT_MODEL = "all-MiniLM-L6-v2"

# Cosine-distance normalisation bounds
_DIST_MAX_SUSPICION = 0.05   # at or below → score 1.0
_DIST_MIN_SUSPICION = 0.50   # at or above → score 0.0


@dataclass
class SectionUniformityFeatures:
    """Style uniformity scores computed from section embeddings.

    Attributes:
        candidate_uuid: UUID of the candidate (no PII).
        sections_embedded: Names of sections that were embedded.
        mean_cosine_distance: Average pairwise cosine distance across sections.
            0.0 = perfectly identical style; 1.0 = maximally different.
        suspicion_score: Score in [0, 1]; low distance → high suspicion.
    """

    candidate_uuid: str
    sections_embedded: list[str] = field(default_factory=list)
    mean_cosine_distance: float = 0.0
    suspicion_score: float = 0.0


def score_section_uniformity(
    candidate_uuid: str,
    sections: dict[str, str],
    _model: Any = None,
) -> SectionUniformityFeatures:
    """Compute section style uniformity for a parsed resume.

    Args:
        candidate_uuid: UUID of the candidate (used in logs — no PII).
        sections: Dict mapping section name to text content.
        _model: Optional pre-built SentenceTransformer (for testing — avoids
            model download). If None, ``all-MiniLM-L6-v2`` is loaded.

    Returns:
        SectionUniformityFeatures with suspicion_score in [0, 1].
        Returns score 0.0 when fewer than 2 sections have content.
    """
    non_empty = {k: v.strip() for k, v in sections.items() if v.strip()}

    if len(non_empty) < 2:
        logger.debug(
            "section_uniformity_skipped",
            candidate_uuid=candidate_uuid,
            reason="fewer_than_2_sections",
        )
        return SectionUniformityFeatures(candidate_uuid=candidate_uuid)

    if _model is None:
        from sentence_transformers import SentenceTransformer  # type: ignore[import]
        _model = SentenceTransformer(_DEFAULT_MODEL)

    names = list(non_empty.keys())
    texts = list(non_empty.values())

    embeddings: np.ndarray = _model.encode(
        texts,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    embeddings = np.asarray(embeddings, dtype=np.float32)

    mean_dist = _mean_pairwise_cosine_distance(embeddings)
    suspicion = _score_from_distance(mean_dist)

    logger.debug(
        "section_uniformity_scored",
        candidate_uuid=candidate_uuid,   # UUID — no PII
        sections_embedded=names,
        mean_cosine_distance=round(mean_dist, 4),
        suspicion_score=round(suspicion, 4),
    )

    return SectionUniformityFeatures(
        candidate_uuid=candidate_uuid,
        sections_embedded=names,
        mean_cosine_distance=float(mean_dist),
        suspicion_score=float(suspicion),
    )


# ── Pure helpers ───────────────────────────────────────────────────────────────

def _mean_pairwise_cosine_distance(embeddings: np.ndarray) -> float:
    """Compute the mean pairwise cosine distance across all embedding pairs.

    Assumes embeddings are L2-normalised (unit vectors), so cosine distance
    simplifies to: 1 - dot(a, b).

    Args:
        embeddings: float32 array of shape (n, d) with unit-norm rows.

    Returns:
        Mean cosine distance in [0, 1]; 0.0 if fewer than 2 embeddings.
    """
    n = embeddings.shape[0]
    if n < 2:
        return 0.0

    distances: list[float] = []
    for i, j in combinations(range(n), 2):
        cos_sim = float(np.dot(embeddings[i], embeddings[j]))
        cos_sim = max(-1.0, min(1.0, cos_sim))  # clamp for numerical safety
        distances.append(1.0 - cos_sim)

    return float(np.mean(distances))


def _score_from_distance(mean_distance: float) -> float:
    """Map mean cosine distance to a suspicion score in [0, 1].

    Args:
        mean_distance: Mean pairwise cosine distance in [0, 1].

    Returns:
        Suspicion score in [0, 1].
    """
    raw = (_DIST_MIN_SUSPICION - mean_distance) / (
        _DIST_MIN_SUSPICION - _DIST_MAX_SUSPICION
    )
    return float(max(0.0, min(1.0, raw)))
