"""Factory for the language-model text detector behind the "perplexity" signal slot.

The API keeps the field name ``perplexity_score`` for compatibility; what fills it
is chosen by ``TEXT_DETECTOR``:

  binoculars (default)  ml/features/binoculars.py — AUROC 0.912 vs 0.726 on evals/
  perplexity            ml/features/perplexity.py — the original distilgpt2 signal

Both return an object whose ``.suspicion_score`` is in [0, 1]. Binoculars raises
ValueError on texts under 10 tokens: callers should then submit the signal as
missing rather than 0 (the calibrated fusion model treats missing explicitly).
"""

from __future__ import annotations

from typing import Any, Protocol

import config


class TextDetector(Protocol):
    def score(self, session_id: str, text: str) -> Any: ...


def make_text_detector(kind: str | None = None) -> TextDetector:
    kind = (kind or config.TEXT_DETECTOR).lower()
    if kind == "binoculars":
        from ml.features.binoculars import BinocularsScorer

        return BinocularsScorer()
    if kind == "perplexity":
        from ml.features.perplexity import PerplexityScorer

        return PerplexityScorer()
    raise ValueError(f"TEXT_DETECTOR must be 'binoculars' or 'perplexity', got {kind!r}")
