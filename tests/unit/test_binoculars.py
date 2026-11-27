"""Binoculars scorer (ml/features/binoculars.py) with stub models — no downloads."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import torch

from ml.features.binoculars import BinocularsScorer, suspicion_from_score

VOCAB = 7


class _Tok:
    def __call__(self, text, return_tensors="pt", truncation=True, max_length=512):
        n = min(len(text.split()), max_length)
        ids = torch.tensor([[i % VOCAB for i in range(n)]])
        return {"input_ids": ids}


class _LM:
    def __init__(self, seed: int) -> None:
        self.seed = seed

    def __call__(self, input_ids):
        g = torch.Generator().manual_seed(self.seed)
        logits = torch.randn(input_ids.shape[0], input_ids.shape[1], VOCAB, generator=g)
        return SimpleNamespace(logits=logits)


def _scorer(obs_seed: int = 1, perf_seed: int = 2) -> BinocularsScorer:
    return BinocularsScorer(
        "obs", "perf", midpoint=0.9, scale=0.05, device="cpu",
        _tokenizer=_Tok(), _observer=_LM(obs_seed), _performer=_LM(perf_seed),
    )


TEXT = " ".join(f"w{i}" for i in range(40))


def test_matches_reference_formula() -> None:
    s = _scorer()
    n, lp, xp, b = s.raw_score(TEXT)

    ids = _Tok()(TEXT)["input_ids"]
    obs = _LM(1)(ids).logits[:, :-1]
    perf = _LM(2)(ids).logits[:, :-1]
    tgt = ids[:, 1:]
    perf_logp = torch.log_softmax(perf, -1)
    exp_lp = -perf_logp.gather(-1, tgt.unsqueeze(-1)).mean()
    exp_xp = -(torch.softmax(obs, -1) * perf_logp).sum(-1).mean()

    assert n == 40
    assert lp == pytest.approx(float(exp_lp), rel=1e-5)
    assert xp == pytest.approx(float(exp_xp), rel=1e-5)
    assert b == pytest.approx(lp / xp)


def test_short_text_abstains() -> None:
    with pytest.raises(ValueError):
        _scorer().raw_score("too short")


def test_score_returns_bounded_suspicion() -> None:
    f = _scorer().score("sess", TEXT)
    assert 0.0 <= f.suspicion_score <= 1.0
    assert f.suspicion_score == pytest.approx(suspicion_from_score(f.binoculars_score, 0.9, 0.05))


def test_suspicion_is_decreasing_and_centred() -> None:
    assert suspicion_from_score(0.9, 0.9, 0.05) == pytest.approx(0.5)
    vals = [suspicion_from_score(b, 0.9, 0.05) for b in (0.6, 0.8, 0.9, 1.0, 1.2)]
    assert vals == sorted(vals, reverse=True)
    assert vals[0] > 0.99 and vals[-1] < 0.01


def test_factory_selects_detector() -> None:
    from unittest.mock import patch

    from ml.features import text_detector

    with patch("ml.features.binoculars.BinocularsScorer") as bino:
        text_detector.make_text_detector("binoculars")
        bino.assert_called_once()
    with patch("ml.features.perplexity.PerplexityScorer") as ppl:
        text_detector.make_text_detector("perplexity")
        ppl.assert_called_once()
    with pytest.raises(ValueError):
        text_detector.make_text_detector("gptzero")
