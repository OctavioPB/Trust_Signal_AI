"""Binoculars zero-shot detector of LLM-generated text (Hans et al., ICML 2024).

Plain perplexity asks "is this text predictable?" — but human text on a
predictable topic, or by a writer with a smaller vocabulary, is predictable too
(the non-native-writer bias, Liang et al. 2023). Binoculars normalises perplexity
by how surprising one model finds *another model's* predictions for the same text:

    B(s) = log PPL_performer(s) / X-PPL_{observer, performer}(s)

    log PPL      = -1/L Σᵢ log p_perf(xᵢ | x<ᵢ)
    X-PPL        = -1/L Σᵢ Σ_v p_obs(v | x<ᵢ) · log p_perf(v | x<ᵢ)

Low B ⇒ the text is about as predictable as an LLM's own continuation ⇒ AI-like.
Observer and performer must share a tokenizer (a base model and its instruct
tune). This module follows the reference implementation
(github.com/ahans30/Binoculars): observer = base, performer = instruct.

The paper used Falcon-7B; TrustSignal defaults to a small pair that runs on CPU
in CI (see BINOCULARS_* in config.py). ``suspicion_score`` maps B onto [0, 1]
with a logistic curve (no hard saturation, unlike the old perplexity mapping),
centred on ``midpoint`` — set from the evaluation set's class medians and
recorded in config so it is versioned with the code.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_MIN_TOKENS = 10          # below this the ratio is too noisy to score: abstain


@dataclass
class BinocularsFeatures:
    """Binoculars output for one text.

    Attributes:
        session_id: UUID of the session (no PII).
        n_tokens: Tokens scored (after truncation).
        log_ppl: Performer log-perplexity.
        x_ppl: Observer→performer cross-perplexity.
        binoculars_score: log_ppl / x_ppl (lower = more AI-like).
        suspicion_score: Logistic map of the score onto [0, 1]; higher = more AI-like.
    """

    session_id: str
    n_tokens: int
    log_ppl: float
    x_ppl: float
    binoculars_score: float
    suspicion_score: float


def suspicion_from_score(score: float, midpoint: float, scale: float) -> float:
    """Monotone decreasing logistic map: score == midpoint → 0.5."""
    return 1.0 / (1.0 + math.exp((score - midpoint) / scale))


class BinocularsScorer:
    """Scores text with an observer/performer model pair.

    Args:
        observer: HF model id of the base model.
        performer: HF model id of its instruct tune (same tokenizer).
        midpoint, scale: logistic mapping of the Binoculars score to suspicion.
        max_tokens: texts are truncated to this many tokens.
        device: "cpu", "cuda", or None to pick CUDA when available.
        _tokenizer, _observer, _performer: injected stubs (tests).

    Raises (from ``score``):
        ValueError: text shorter than ``_MIN_TOKENS`` tokens — the signal abstains,
        which the fusion model treats as missing.
    """

    def __init__(
        self,
        observer: str | None = None,
        performer: str | None = None,
        midpoint: float | None = None,
        scale: float | None = None,
        max_tokens: int = 512,
        device: str | None = None,
        _tokenizer: Any = None,
        _observer: Any = None,
        _performer: Any = None,
    ) -> None:
        import torch

        import config

        self._torch = torch
        self.observer_id = observer or config.BINOCULARS_OBSERVER
        self.performer_id = performer or config.BINOCULARS_PERFORMER
        self.midpoint = config.BINOCULARS_MIDPOINT if midpoint is None else midpoint
        self.scale = config.BINOCULARS_SCALE if scale is None else scale
        self.max_tokens = max_tokens
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._log = logger.bind(component="BinocularsScorer", observer=self.observer_id)

        if _tokenizer is not None:
            self._tok, self._obs, self._perf = _tokenizer, _observer, _performer
            return

        from transformers import AutoModelForCausalLM, AutoTokenizer

        dtype = torch.bfloat16 if self.device == "cuda" else torch.float32
        self._tok = AutoTokenizer.from_pretrained(self.observer_id)
        perf_tok = AutoTokenizer.from_pretrained(self.performer_id)
        if self._tok.get_vocab() != perf_tok.get_vocab():
            raise ValueError("observer and performer must share a tokenizer")
        self._obs = AutoModelForCausalLM.from_pretrained(self.observer_id, dtype=dtype)
        self._perf = AutoModelForCausalLM.from_pretrained(self.performer_id, dtype=dtype)
        self._obs.to(self.device).eval()
        self._perf.to(self.device).eval()

    def raw_score(self, text: str) -> tuple[int, float, float, float]:
        """(n_tokens, log_ppl, x_ppl, binoculars_score) for ``text``."""
        torch = self._torch
        enc = self._tok(
            text.strip(), return_tensors="pt", truncation=True, max_length=self.max_tokens
        )
        ids = enc["input_ids"].to(self.device)
        n = int(ids.shape[1])
        if n < _MIN_TOKENS:
            raise ValueError(f"binoculars needs at least {_MIN_TOKENS} tokens; got {n}")

        with torch.no_grad():
            obs_logits = self._obs(input_ids=ids).logits[:, :-1].float()
            perf_logits = self._perf(input_ids=ids).logits[:, :-1].float()
        targets = ids[:, 1:]

        perf_logp = torch.log_softmax(perf_logits, dim=-1)
        log_ppl = -perf_logp.gather(-1, targets.unsqueeze(-1)).squeeze(-1).mean()
        obs_p = torch.softmax(obs_logits, dim=-1)
        x_ppl = -(obs_p * perf_logp).sum(-1).mean()
        lp, xp = float(log_ppl), float(x_ppl)
        return n, lp, xp, lp / xp

    def score(self, session_id: str, text: str) -> BinocularsFeatures:
        n, lp, xp, b = self.raw_score(text)
        suspicion = suspicion_from_score(b, self.midpoint, self.scale)
        self._log.debug("binoculars_scored", session_id=session_id, n_tokens=n,
                        score=round(b, 4), suspicion=round(suspicion, 4))
        return BinocularsFeatures(
            session_id=session_id, n_tokens=n, log_ppl=lp, x_ppl=xp,
            binoculars_score=b, suspicion_score=suspicion,
        )
