"""Semantic similarity scorer against the LLM answer bank.

Embeds CANDIDATE transcript turns using ``all-MiniLM-L6-v2`` (or any
Sentence-Transformers model) and computes cosine similarity against a curated
bank of canonical ChatGPT / GPT-4 answers stored in
``data/llm_answer_bank.jsonl``.

The maximum cosine similarity across the entire bank becomes the
``similarity_suspicion_score``. High similarity to a canonical AI answer pattern
increases suspicion.

Cosine similarities from sentence-transformers over unit-normalised embeddings
are already in [0, 1] for semantically related text, so no further scaling is
needed — the raw max similarity IS the suspicion score.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
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

    The answer bank is loaded and embedded once at construction time.
    Re-use the same instance across all segments of a session.

    Args:
        model_name: Sentence-Transformers model identifier.
        answer_bank_path: Path to ``llm_answer_bank.jsonl``.
        _model: Optional pre-built SentenceTransformer (for testing — avoids
            model download). Must implement ``encode(texts) -> np.ndarray``.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        answer_bank_path: Path = ANSWER_BANK_PATH,
        _model=None,
    ) -> None:
        self._log = logger.bind(component="SemanticSimilarityScorer", model=model_name)

        if _model is not None:
            self._model = _model
        else:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(model_name)
            self._log.info("similarity_model_loaded")

        self._bank = self._load_answer_bank(Path(answer_bank_path))
        answers = [entry["answer"] for entry in self._bank]
        self._bank_embeddings: np.ndarray = self._model.encode(
            answers, convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False
        )
        self._log.info("answer_bank_embedded", n_entries=len(self._bank))

    # ── Public API ─────────────────────────────────────────────────────────────

    def score(self, session_id: str, candidate_text: str) -> SimilarityFeatures:
        """Compute similarity between a candidate answer and the answer bank.

        Args:
            session_id: UUID of the interview session (no PII in logs).
            candidate_text: Candidate transcript segment to evaluate.

        Returns:
            SimilarityFeatures with ``suspicion_score`` in [0, 1].
        """
        candidate_text = candidate_text.strip()
        candidate_emb: np.ndarray = self._model.encode(
            [candidate_text],
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )[0]

        # Cosine similarity = dot product of unit-norm vectors
        sims: np.ndarray = self._bank_embeddings @ candidate_emb
        max_idx = int(sims.argmax())
        max_sim = float(sims[max_idx])

        # Clamp to [0, 1]: unit-norm dot products are in [-1, 1] but rarely negative
        suspicion_score = float(np.clip(max_sim, 0.0, 1.0))

        self._log.debug(
            "similarity_scored",
            session_id=session_id,
            max_cosine_similarity=round(max_sim, 4),
            matched_question=self._bank[max_idx]["question"][:60],
            suspicion_score=round(suspicion_score, 4),
        )

        return SimilarityFeatures(
            session_id=session_id,
            text=candidate_text,
            max_cosine_similarity=max_sim,
            matched_question=self._bank[max_idx]["question"],
            suspicion_score=suspicion_score,
        )

    # ── Internal ───────────────────────────────────────────────────────────────

    def _load_answer_bank(self, path: Path) -> list[dict]:
        """Load the canonical LLM answer bank from a JSONL file.

        Each line must be a JSON object with at least ``question`` and
        ``answer`` string fields.

        Args:
            path: Path to ``llm_answer_bank.jsonl``.

        Returns:
            List of dicts, each with keys ``question`` and ``answer``.

        Raises:
            FileNotFoundError: If the JSONL file does not exist.
            ValueError: If the file contains no valid entries.
        """
        if not path.exists():
            raise FileNotFoundError(
                f"Answer bank not found at {path}. "
                "Run Sprint 6 data build step to generate data/llm_answer_bank.jsonl."
            )

        entries: list[dict] = []
        with path.open(encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if "question" not in obj or "answer" not in obj:
                        raise ValueError(f"Line {lineno}: missing 'question' or 'answer' key")
                    entries.append({"question": obj["question"], "answer": obj["answer"]})
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Line {lineno}: invalid JSON — {exc}") from exc

        if not entries:
            raise ValueError(f"Answer bank at {path} contains no valid entries.")

        self._log.info("answer_bank_loaded", n_entries=len(entries), path=str(path))
        return entries
