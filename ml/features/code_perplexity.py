"""LM perplexity scorer for source code files — Sprint 17.

Uses a code-aware language model (default: ``microsoft/codebert-base``) to
compute pseudo-perplexity per file. Low perplexity indicates predictable,
formulaic code — a signal of AI generation.

Suspicion score mapping:
    perplexity ≤  10 → score 1.0  (extremely predictable — AI-like)
    perplexity ≥  50 → score 0.0  (natural human code variance)

Repo-level aggregate: character-count-weighted mean across scored files.
Files with fewer than _MIN_TOKENS tokens are skipped (perplexity unreliable).

Model is loaded lazily; inject _tokenizer / _model for tests to avoid downloads.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import structlog
import torch

import config

logger = structlog.get_logger(__name__)

# ── Normalisation bounds ───────────────────────────────────────────────────────

_PPL_MAX_SUSPICION = 10.0    # at or below → suspicion_score 1.0
_PPL_MIN_SUSPICION = 50.0    # at or above → suspicion_score 0.0

DEFAULT_MODEL = config.CODE_LM_MODEL

_MIN_TOKENS = 10              # skip files shorter than this many tokens


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class CodeFilePerplexityResult:
    """Perplexity score for a single source file.

    Attributes:
        repo_uuid: UUID of the parent repository (no PII).
        file_path: Relative path within the repository.
        perplexity: Raw model pseudo-perplexity (≥ 1.0); inf when skipped.
        suspicion_score: Normalised score in [0, 1]; low perplexity → high suspicion.
    """

    repo_uuid: str
    file_path: str
    perplexity: float
    suspicion_score: float


@dataclass
class CodeRepoPerplexityFeatures:
    """Aggregated perplexity suspicion scores for a repository.

    Attributes:
        repo_uuid: UUID of the repository (no PII).
        file_scores: Per-file suspicion scores (file_path → score in [0, 1]).
            Only files that exceeded _MIN_TOKENS are included.
        suspicion_score: Character-count-weighted mean across all scored files.
    """

    repo_uuid: str
    file_scores: dict[str, float] = field(default_factory=dict)
    suspicion_score: float = 0.0


# ── Scorer ─────────────────────────────────────────────────────────────────────

class CodePerplexityScorer:
    """Scores source code files using token-level LM pseudo-perplexity.

    The model is loaded once at construction time; reuse the same instance
    for all files in a repository to avoid repeated startup cost.

    Args:
        model_name: Hugging Face model identifier. Defaults to ``CODE_LM_MODEL``
            (config default: ``microsoft/codebert-base``).
        device: Torch device string — ``"cpu"`` or ``"cuda"``.
        _tokenizer: Optional pre-built tokenizer (for testing — avoids download).
        _model: Optional pre-built model (for testing — avoids download).
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        device: str = "cpu",
        _tokenizer: Any = None,
        _model: Any = None,
    ) -> None:
        self._device = device
        self._log = logger.bind(component="CodePerplexityScorer", model=model_name)

        if _tokenizer is not None and _model is not None:
            self._tokenizer = _tokenizer
            self._model = _model
        else:
            from transformers import AutoModelForMaskedLM, AutoTokenizer

            self._tokenizer = AutoTokenizer.from_pretrained(model_name)
            self._model = AutoModelForMaskedLM.from_pretrained(model_name)
            self._model.eval()
            self._model.to(device)
            self._log.info("code_perplexity_model_loaded")

    def score_file(
        self,
        repo_uuid: str,
        file_path: str,
        content: str,
    ) -> CodeFilePerplexityResult:
        """Compute pseudo-perplexity and suspicion score for one source file.

        Files shorter than ``_MIN_TOKENS`` are returned with perplexity=inf
        and suspicion_score=0.0 (not enough context for reliable scoring).

        Args:
            repo_uuid: UUID of the repository (no PII in logs).
            file_path: Relative path within the repository.
            content: Decoded UTF-8 text of the source file.

        Returns:
            CodeFilePerplexityResult with suspicion_score in [0, 1].
        """
        tokens = self._tokenizer(
            content,
            return_tensors="pt",
            truncation=True,
            max_length=512,
        )
        n_tokens = tokens["input_ids"].shape[1]

        if n_tokens < _MIN_TOKENS:
            self._log.debug(
                "code_perplexity_skipped_short_file",
                repo_uuid=repo_uuid,    # UUID — no PII
                file_path=file_path,
                n_tokens=n_tokens,
            )
            return CodeFilePerplexityResult(
                repo_uuid=repo_uuid,
                file_path=file_path,
                perplexity=float("inf"),
                suspicion_score=0.0,
            )

        input_ids = tokens["input_ids"].to(self._device)
        with torch.no_grad():
            outputs = self._model(input_ids=input_ids, labels=input_ids)
            loss = outputs.loss

        perplexity = float(math.exp(float(loss.item())))
        suspicion = _normalise_perplexity(perplexity)

        self._log.debug(
            "code_file_perplexity_scored",
            repo_uuid=repo_uuid,         # UUID — no PII
            file_path=file_path,
            n_tokens=n_tokens,
            perplexity=round(perplexity, 2),
            suspicion_score=round(suspicion, 4),
        )

        return CodeFilePerplexityResult(
            repo_uuid=repo_uuid,
            file_path=file_path,
            perplexity=perplexity,
            suspicion_score=suspicion,
        )

    def score_repo(
        self,
        repo_uuid: str,
        files: list[tuple[str, str]],
    ) -> CodeRepoPerplexityFeatures:
        """Score all source files in a repository and compute a weighted aggregate.

        Args:
            repo_uuid: UUID of the repository (no PII).
            files: List of (file_path, content) tuples.

        Returns:
            CodeRepoPerplexityFeatures with a character-count-weighted mean
            suspicion_score. Returns 0.0 if no files could be scored.
        """
        file_scores: dict[str, float] = {}
        total_weight = 0.0
        weighted_sum = 0.0

        for file_path, content in files:
            result = self.score_file(repo_uuid, file_path, content)
            if result.perplexity == float("inf"):
                continue
            weight = float(len(content))
            file_scores[file_path] = result.suspicion_score
            weighted_sum += result.suspicion_score * weight
            total_weight += weight

        aggregate = (weighted_sum / total_weight) if total_weight > 0.0 else 0.0

        self._log.debug(
            "code_repo_perplexity_scored",
            repo_uuid=repo_uuid,         # UUID — no PII
            files_scored=len(file_scores),
            suspicion_score=round(aggregate, 4),
        )

        return CodeRepoPerplexityFeatures(
            repo_uuid=repo_uuid,
            file_scores=file_scores,
            suspicion_score=float(aggregate),
        )


# ── Pure helper ────────────────────────────────────────────────────────────────

def _normalise_perplexity(perplexity: float) -> float:
    """Map raw perplexity to a suspicion score in [0, 1].

    Args:
        perplexity: Raw model perplexity (≥ 1.0).

    Returns:
        Suspicion score in [0, 1]; low perplexity → high suspicion.
    """
    raw = (_PPL_MIN_SUSPICION - perplexity) / (_PPL_MIN_SUSPICION - _PPL_MAX_SUSPICION)
    return float(max(0.0, min(1.0, raw)))
