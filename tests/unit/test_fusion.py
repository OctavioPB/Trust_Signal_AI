"""Calibrated fusion (ml/fusion.py) and the engine's calibrated mode."""

from __future__ import annotations

import math
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ml.fusion import SIGNALS, FusionModel, conformal_threshold
from ml.trust_score import TrustScoreEngine, load_engine_from_config

# ── Fixtures ───────────────────────────────────────────────────────────────────


def _synthetic(n: int, seed: int) -> tuple[list[dict], np.ndarray]:
    """'perplexity' carries signal, 'similarity' is anti-correlated noise, audio missing."""
    rng = np.random.default_rng(seed)
    y = rng.integers(0, 2, n)
    rows = []
    for lab in y:
        rows.append({
            "latency": None,
            "bg_audio": None,
            "perplexity": float(np.clip(rng.normal(0.3 + 0.4 * lab, 0.15), 0, 1)),
            "burstiness": None if rng.random() < 0.2 else float(rng.random()),
            "similarity": float(np.clip(rng.normal(0.6 - 0.3 * lab, 0.15), 0, 1)),
        })
    return rows, y


@pytest.fixture(scope="module")
def model() -> FusionModel:
    rows, y = _synthetic(800, 0)
    return FusionModel.fit(rows[:560], y[:560], rows[560:], y[560:], alpha=0.05)


# ── Conformal threshold ────────────────────────────────────────────────────────


class TestConformal:
    def test_false_positive_rate_is_controlled(self) -> None:
        """Averaged over many calibration draws, FPR on fresh humans stays ≤ alpha."""
        rng = np.random.default_rng(3)
        alpha, fprs = 0.05, []
        for _ in range(300):
            t = conformal_threshold(rng.random(99), alpha)
            fprs.append(float((rng.random(2000) > t).mean()))
        assert np.mean(fprs) <= alpha + 0.005

    def test_too_few_humans_never_flags(self) -> None:
        assert math.isinf(conformal_threshold(np.random.default_rng(0).random(10), 0.02))
        assert math.isinf(conformal_threshold(np.array([]), 0.02))


# ── Fitting ────────────────────────────────────────────────────────────────────


class TestFit:
    def test_weights_are_non_negative_and_informative(self, model: FusionModel) -> None:
        assert all(w >= 0 for w in model.weights.values())
        assert model.weights["perplexity"] > 1.0
        # anti-correlated signal is clipped to 0 instead of being inverted
        assert model.weights["similarity"] == pytest.approx(0.0, abs=1e-6)

    def test_probabilities_separate_classes(self, model: FusionModel) -> None:
        rows, y = _synthetic(400, 9)
        p = np.array([model.predict_proba(r) for r in rows])
        assert p[y == 1].mean() > p[y == 0].mean() + 0.2

    def test_held_out_fpr_near_alpha(self, model: FusionModel) -> None:
        rows, y = _synthetic(2000, 5)
        flags = np.array([model.flagged(r) for r in rows])
        assert flags[y == 0].mean() <= model.alpha + 0.03

    def test_missing_is_not_zero(self, model: FusionModel) -> None:
        base = {"latency": None, "bg_audio": None, "perplexity": 0.5, "similarity": 0.5}
        p_missing = model.predict_proba({**base, "burstiness": None})
        p_zero = model.predict_proba({**base, "burstiness": 0.0})
        assert p_missing != pytest.approx(p_zero)


@settings(max_examples=60, deadline=None)
@given(
    scores=st.fixed_dictionaries({s: st.floats(0, 1) for s in SIGNALS}),
    which=st.sampled_from(SIGNALS),
    bump=st.floats(0, 1),
)
def test_raising_a_signal_never_lowers_suspicion(scores, which, bump) -> None:
    m = FusionModel(
        signals=list(SIGNALS),
        weights={"latency": 0.5, "bg_audio": 1.0, "perplexity": 2.0, "burstiness": 3.0,
                 "similarity": 0.0},
        missing_offsets=dict.fromkeys(SIGNALS, 0.0),
        intercept=-3.0, threshold=0.8, alpha=0.02, n_calibration_humans=100,
    )
    higher = {**scores, which: min(1.0, scores[which] + bump)}
    assert m.predict_proba(higher) >= m.predict_proba(scores)


# ── Persistence ────────────────────────────────────────────────────────────────


def test_json_round_trip(tmp_path: Path, model: FusionModel) -> None:
    path = tmp_path / "20261126_fusion.json"
    model.save(path)
    loaded = FusionModel.load(path)
    row = {"latency": None, "bg_audio": None, "perplexity": 0.7, "burstiness": 0.4,
           "similarity": 0.2}
    assert loaded.predict_proba(row) == pytest.approx(model.predict_proba(row))
    assert loaded.threshold == model.threshold


def test_infinite_threshold_survives_json() -> None:
    m = FusionModel(list(SIGNALS), dict.fromkeys(SIGNALS, 0.0), dict.fromkeys(SIGNALS, 0.0),
                    0.0, math.inf, 0.02, 5)
    assert math.isinf(FusionModel.from_json(m.to_json()).threshold)


# ── Engine integration ─────────────────────────────────────────────────────────


class TestEngineCalibratedMode:
    def test_flag_always_has_reason(self, model: FusionModel) -> None:
        r = TrustScoreEngine(fusion=model).compute("s", None, None, 1.0, 1.0, 0.0)
        assert r.flagged
        assert "calibrated threshold" in r.flag_reason
        assert r.trust_score == pytest.approx((1 - r.suspicion_index) * 100, abs=0.01)

    def test_missing_signals_are_explained(self, model: FusionModel) -> None:
        r = TrustScoreEngine(fusion=model).compute("s", None, None, 0.2, None, 0.1)
        audio = next(s for s in r.signals if s.signal_name == "Background Audio")
        assert "Not available" in audio.explanation
        assert audio.weighted_contribution == 0.0

    def test_legacy_treats_none_as_zero(self) -> None:
        e = TrustScoreEngine()
        assert e.compute("s", None, None, 0.5, 0.5, 0.5).suspicion_index == \
            e.compute("s", 0.0, 0.0, 0.5, 0.5, 0.5).suspicion_index

    def test_config_selects_mode(self, tmp_path: Path, model: FusionModel) -> None:
        path = tmp_path / "f.json"
        model.save(path)
        with patch("ml.trust_score.config.FUSION_MODEL_PATH", str(path)):
            assert load_engine_from_config()._fusion is not None
        with patch("ml.trust_score.config.FUSION_MODEL_PATH", ""):
            assert load_engine_from_config()._fusion is None
