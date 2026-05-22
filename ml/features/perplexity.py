"""LM perplexity scorer for transcript text.

Low perplexity indicates predictable, AI-generated text. Uses a small causal
language model (distilgpt2 by default) via Hugging Face transformers.

Suspicion score mapping (linear):
    perplexity ≤  30 → 1.00  (very predictable → maximum suspicion)
    perplexity = 65  → 0.50  (midpoint)
    perplexity ≥ 100 → 0.00  (natural human variance → no suspicion)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import structlog
import torch

logger = structlog.get_logger(__name__)

# Normalisation boundaries
_PPL_MAX_SUSPICION = 30.0   # at or below this → score = 1.0
_PPL_MIN_SUSPICION = 100.0  # at or above this → score = 0.0

# Default model — small enough to run on CPU in < 100 ms per segment
DEFAULT_MODEL = "distilgpt2"

# Minimum token count below which scoring is skipped (unreliable on < 5 tokens)
_MIN_TOKENS = 5


@dataclass
class PerplexityFeatures:
    """Computed perplexity metrics for a candidate transcript segment.

    Attributes:
        session_id: UUID of the interview session.
        text: The transcript segment analysed.
        perplexity: Raw model perplexity score (≥ 1.0).
        suspicion_score: Normalised score in [0, 1]; low perplexity → high suspicion.
    """

    session_id: str
    text: str
    perplexity: float
    suspicion_score: float


class PerplexityScorer:
    """Scores candidate transcript segments using token-level LM perplexity.

    The model is loaded once at construction time; reuse the same instance
    for all segments in a session to avoid repeated startup cost.

    Args:
        model_name: Hugging Face model identifier (default: ``distilgpt2``).
        device: Torch device string — ``"cpu"`` or ``"cuda"``.
        _tokenizer: Optional pre-built tokenizer (for testing, avoids model download).
        _model: Optional pre-built model (for testing, avoids model download).
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        device: str = "cpu",
        _tokenizer=None,
        _model=None,
    ) -> None:
        self._device = device
        self._log = logger.bind(component="PerplexityScorer", model=model_name)

        if _tokenizer is not None and _model is not None:
            self._tokenizer = _tokenizer
            self._model = _model
        else:
            from transformers import GPT2LMHeadModel, GPT2TokenizerFast

            self._tokenizer = GPT2TokenizerFast.from_pretrained(model_name)
            self._model = GPT2LMHeadModel.from_pretrained(model_name)
            self._model.eval()
            self._model.to(device)
            self._log.info("perplexity_model_loaded")

    # ── Public API ─────────────────────────────────────────────────────────────

    def score(self, session_id: str, text: str) -> PerplexityFeatures:
        """Compute perplexity and suspicion score for a transcript segment.

        For segments shorter than ``_MIN_TOKENS`` the model returns a score
        of 0.0 (no suspicion) to avoid spurious penalties on filler phrases.

        Args:
            session_id: UUID of the interview session (no PII in logs).
            text: Candidate transcript text to evaluate.

        Returns:
            PerplexityFeatures with ``suspicion_score`` in [0, 1].
        """
        text = text.strip()
        tokens = self._tokenizer(text, return_tensors="pt")
        n_tokens = tokens["input_ids"].shape[1]

        if n_tokens < _MIN_TOKENS:
            self._log.debug(
                "perplexity_skipped_short_text",
                session_id=session_id,
                n_tokens=n_tokens,
            )
            return PerplexityFeatures(
                session_id=session_id,
                text=text,
                perplexity=float("inf"),
                suspicion_score=0.0,
            )

        perplexity = self._compute_perplexity(tokens)
        suspicion = self._normalise_perplexity(perplexity)

        self._log.debug(
            "perplexity_scored",
            session_id=session_id,
            n_tokens=n_tokens,
            perplexity=round(perplexity, 2),
            suspicion_score=round(suspicion, 4),
        )

        return PerplexityFeatures(
            session_id=session_id,
            text=text,
            perplexity=perplexity,
            suspicion_score=suspicion,
        )

    @staticmethod
    def _normalise_perplexity(perplexity: float) -> float:
        """Map raw perplexity to a suspicion score in [0, 1].

        perplexity ≤  30 → score approaches 1.0 (AI-like predictability).
        perplexity ≥ 100 → score approaches 0.0 (natural human variance).

        Args:
            perplexity: Raw language-model perplexity (≥ 1.0).

        Returns:
            Suspicion score in [0, 1].
        """
        raw = (_PPL_MIN_SUSPICION - perplexity) / (_PPL_MIN_SUSPICION - _PPL_MAX_SUSPICION)
        return float(max(0.0, min(1.0, raw)))

    # ── Internal ───────────────────────────────────────────────────────────────

    def _compute_perplexity(self, tokens: dict) -> float:
        """Run a forward pass and compute perplexity from cross-entropy loss.

        Args:
            tokens: Tokenizer output dict with ``input_ids`` tensor.

        Returns:
            Perplexity as exp(mean negative log-likelihood per token).
        """
        input_ids = tokens["input_ids"].to(self._device)
        with torch.no_grad():
            outputs = self._model(input_ids=input_ids, labels=input_ids)
            loss: torch.Tensor = outputs.loss   # mean NLL per token

        return float(math.exp(loss.item()))
