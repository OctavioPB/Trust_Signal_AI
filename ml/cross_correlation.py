"""Cross-signal consistency scorer — Sprint 18.

Detects inconsistencies between a candidate's claimed skills (resume) and
demonstrated skills (repository code / README), and between their written
style (resume) and spoken style (interview transcript).

Two sub-signals:

1. **Skill coherence** (60 %):
   Embed the resume skills section and the repo README using
   ``all-MiniLM-L6-v2``; measure cosine similarity. High similarity = skills
   claimed in the resume align with repository work (coherent). Low similarity
   = gap between claimed and demonstrated skills (incoherent → suspicious).

   skill_coherence_score in [0, 1] (high = consistent).
   coherence_suspicion = 1.0 − skill_coherence_score.

2. **Writing-style bridge** (40 %):
   Compare sentence-length variance between the resume full text and the
   interview transcript. A large delta indicates the same person did not
   author both — style inconsistency raises suspicion.

   style_bridge_delta in [0, 1] (high = inconsistent).

When either input text is absent (no repo, no interview) the corresponding
sub-signal defaults to 0.0 (neutral — no additional suspicion).

Combined:
    coherence_suspicion_score = 0.60 × coherence_suspicion + 0.40 × style_bridge_delta
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

_DEFAULT_MODEL  = "all-MiniLM-L6-v2"
_W_COHERENCE    = 0.60
_W_STYLE        = 0.40


# ── Data class ─────────────────────────────────────────────────────────────────

@dataclass
class CrossCorrelationFeatures:
    """Cross-signal consistency features for a candidate.

    Attributes:
        candidate_uuid: UUID of the candidate (no PII).
        skill_coherence_score: Cosine similarity between resume skills embedding
            and repo README embedding, in [0, 1]. High = coherent. 0.5 when
            repo README is absent (neutral fallback).
        style_bridge_delta: Normalised sentence-length variance delta between
            resume prose and interview transcript, in [0, 1]. High = inconsistent.
            0.0 when interview transcript is absent (neutral fallback).
        coherence_suspicion_score: Weighted aggregate suspicion in [0, 1].
    """

    candidate_uuid: str
    skill_coherence_score: float
    style_bridge_delta: float
    coherence_suspicion_score: float


# ── Scorer ─────────────────────────────────────────────────────────────────────

class CrossCorrelationScorer:
    """Scores cross-signal consistency between resume, repo, and interview.

    Args:
        _model: Optional pre-built SentenceTransformer instance for test
            injection (avoids model download in unit tests).
    """

    def __init__(self, _model: Any = None) -> None:
        self._model = _model
        self._log = logger.bind(component="CrossCorrelationScorer")

    def _get_model(self) -> Any:
        if self._model is not None:
            return self._model
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(_DEFAULT_MODEL)
        return self._model

    def score(
        self,
        candidate_uuid: str,
        resume_skills_text: str,
        repo_readme_text: str | None,
        resume_full_text: str | None,
        interview_transcript: str | None,
    ) -> CrossCorrelationFeatures:
        """Compute cross-signal consistency features.

        Args:
            candidate_uuid: UUID of the candidate (no PII in logs).
            resume_skills_text: Text of the resume Skills / Technologies section.
            repo_readme_text: Plain text of the repo README, or None if absent.
            resume_full_text: Full resume text (for style comparison), or None.
            interview_transcript: Interview transcript text, or None.

        Returns:
            CrossCorrelationFeatures with coherence_suspicion_score in [0, 1].
        """
        # ── Skill coherence ────────────────────────────────────────────────────
        if repo_readme_text and repo_readme_text.strip():
            model = self._get_model()
            emb_skills = np.array(model.encode(resume_skills_text))
            emb_readme = np.array(model.encode(repo_readme_text))
            skill_coherence = float(_cosine_similarity(emb_skills, emb_readme))
            skill_coherence = max(0.0, min(1.0, skill_coherence))
        else:
            skill_coherence = 0.5   # neutral: no repo README available

        coherence_suspicion = 1.0 - skill_coherence

        # ── Style bridge ───────────────────────────────────────────────────────
        if resume_full_text and interview_transcript:
            var_resume    = _sentence_length_variance(resume_full_text)
            var_interview = _sentence_length_variance(interview_transcript)
            style_bridge  = _variance_delta(var_resume, var_interview)
        else:
            style_bridge = 0.0   # neutral: no transcript available

        # ── Combined score ─────────────────────────────────────────────────────
        combined = float(
            min(1.0, _W_COHERENCE * coherence_suspicion + _W_STYLE * style_bridge)
        )

        self._log.debug(
            "cross_correlation_scored",
            candidate_uuid=candidate_uuid,         # UUID — no PII
            skill_coherence=round(skill_coherence, 4),
            style_bridge_delta=round(style_bridge, 4),
            coherence_suspicion_score=round(combined, 4),
        )

        return CrossCorrelationFeatures(
            candidate_uuid=candidate_uuid,
            skill_coherence_score=round(skill_coherence, 4),
            style_bridge_delta=round(style_bridge, 4),
            coherence_suspicion_score=round(combined, 4),
        )


# ── Pure helpers ───────────────────────────────────────────────────────────────

def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors.

    Args:
        a: First embedding vector.
        b: Second embedding vector.

    Returns:
        Similarity in [-1, 1]; 0.0 when either vector is the zero vector.
    """
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def _sentence_length_variance(text: str) -> float:
    """Compute variance of sentence lengths (in characters) in a text.

    Args:
        text: Input text.

    Returns:
        Variance of sentence lengths (float ≥ 0.0); 0.0 for very short texts.
    """
    sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
    if len(sentences) < 2:
        return 0.0
    lengths = [len(s) for s in sentences]
    mean = sum(lengths) / len(lengths)
    return sum((ln - mean) ** 2 for ln in lengths) / len(lengths)


def _variance_delta(var_a: float, var_b: float) -> float:
    """Normalise the absolute difference between two variance values to [0, 1].

    Uses ratio normalisation: delta / (var_a + var_b + 1) to keep the result
    in [0, 1) without division by zero.

    Args:
        var_a: Variance of the first text (resume).
        var_b: Variance of the second text (transcript).

    Returns:
        Normalised delta in [0, 1]; 0.0 when both variances are identical.
    """
    return float(min(1.0, abs(var_a - var_b) / (var_a + var_b + 1.0)))
