"""Semantic similarity scorer against the LLM answer bank.

Embeds CANDIDATE transcript turns using all-MiniLM-L6-v2 and computes
cosine similarity against a curated bank of canonical ChatGPT answers
stored in data/llm_answer_bank.jsonl. Implemented in Sprint 6.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

DEFAULT_MODEL = "all-MiniLM-L6-v2"
ANSWER_BANK_PATH = Path("data/llm_answer_bank.jsonl")


@dataclass
class SimilarityFeatures:
    """Semantic similarity result for a single candidate transcript segment.

    Attributes:
        session_id: UUID of the interview session.
        text: The candidate transcript segment evaluated.
        max_cosine_similarity: Maximum cosine similarity across the answer bank.
        matched_question: The question whose canonical answer matched most closely.
        suspicion_score: Score in [0, 1]; high similarity → high suspicion.
    """

    session_id: str
    text: str
    max_cosine_similarity: float
    matched_question: str
    suspicion_score: float


class SemanticSimilarityScorer:
    """Compares candidate answers against the canonical LLM answer bank.

    Args:
        model_name: Sentence-Transformers model identifier.
        answer_bank_path: Path to the JSONL file with Q&A pairs.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        answer_bank_path: Path = ANSWER_BANK_PATH,
    ) -> None:
        raise NotImplementedError  # Sprint 6

    def score(self, session_id: str, candidate_text: str) -> SimilarityFeatures:
        """Compute similarity between a candidate answer and the answer bank.

        Args:
            session_id: UUID of the interview session.
            candidate_text: Candidate transcript segment to evaluate.

        Returns:
            SimilarityFeatures with suspicion_score in [0, 1].
        """
        raise NotImplementedError  # Sprint 6

    def _load_answer_bank(self, path: Path) -> list[dict]:
        """Load and embed the canonical LLM answer bank.

        Args:
            path: Path to llm_answer_bank.jsonl.

        Returns:
            List of dicts with keys: question, answer, embedding.
        """
        raise NotImplementedError  # Sprint 6
