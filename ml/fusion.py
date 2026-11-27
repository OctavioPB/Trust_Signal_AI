"""Calibrated signal fusion with a conformal false-positive guarantee.

Replaces the hand-set weighted sum (``trust_score.DEFAULT_WEIGHTS``) with three
statistically grounded steps:

1. **Missing is not zero.** Each signal contributes its score *and* an indicator
   for "not available" (no audio, too few sentences). The legacy engine scored a
   missing signal as 0, which caps a text-only session's suspicion at 0.55, so it
   could never cross the 0.65 flag threshold.

2. **Fusion in log-odds space.** A logistic model

       logit P(AI | signals) = b + Σᵢ wᵢ·xᵢ + Σᵢ mᵢ·missingᵢ ,   wᵢ ≥ 0

   is fitted on labelled data. The output is a calibrated probability, each
   signal's contribution ``wᵢ·xᵢ`` is additive evidence (shown in the flag
   panel), and ``wᵢ ≥ 0`` keeps it monotone: raising any signal can never make a
   session look *less* suspicious. A signal that carries no signal gets weight 0.

3. **Conformal threshold.** The flag threshold τ is read off the scores of
   held-out *human* texts: with n of them, τ is the ⌈(n+1)(1-α)⌉-th smallest.
   For a new human session exchangeable with them, P(flagged) ≤ α — a
   finite-sample guarantee of the "false positives ≤ 2 %" target, not a hope.
   (Marginal over the human population the calibration set represents; it is
   not a per-group guarantee — per-group rates are reported by ``evals/``.)

Artifacts are plain JSON (no pickle), versioned ``YYYYMMDD_fusion.json``.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

SIGNALS: tuple[str, ...] = ("latency", "bg_audio", "perplexity", "burstiness", "similarity")


def conformal_threshold(human_scores: np.ndarray, alpha: float) -> float:
    """Split-conformal threshold: flag ``s > τ`` ⇒ P(false positive) ≤ alpha.

    Returns +inf when there are too few humans to certify alpha (n < 1/alpha - 1),
    i.e. the model must not flag anything rather than break the guarantee.
    """
    s = np.sort(np.asarray(human_scores, dtype=float))
    n = len(s)
    k = math.ceil((n + 1) * (1.0 - alpha))
    if n == 0 or k > n:
        return math.inf
    return float(s[k - 1])


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -35.0, 35.0)))


def design_matrix(rows: list[dict[str, float | None]], signals: tuple[str, ...]) -> np.ndarray:
    """[x_1..x_k, missing_1..missing_k] per row; a missing signal has x = 0."""
    out = np.zeros((len(rows), 2 * len(signals)))
    for r, row in enumerate(rows):
        for j, name in enumerate(signals):
            v = row.get(name)
            if v is None:
                out[r, len(signals) + j] = 1.0
            else:
                out[r, j] = min(1.0, max(0.0, float(v)))
    return out


def fit_logistic(
    X: np.ndarray, y: np.ndarray, n_nonneg: int, l2: float = 1.0
) -> tuple[np.ndarray, float]:
    """L2-regularised logistic regression; the first ``n_nonneg`` coefs are ≥ 0."""
    from scipy.optimize import minimize

    y = np.asarray(y, dtype=float)
    n, d = X.shape

    def loss(theta: np.ndarray) -> tuple[float, np.ndarray]:
        w, b = theta[:d], theta[d]
        z = X @ w + b
        p = _sigmoid(z)
        eps = 1e-12
        nll = -np.mean(y * np.log(p + eps) + (1 - y) * np.log(1 - p + eps))
        reg = 0.5 * l2 * float(w @ w) / n
        g = p - y
        grad_w = X.T @ g / n + l2 * w / n
        grad_b = float(g.mean())
        return nll + reg, np.concatenate([grad_w, [grad_b]])

    bounds = [(0.0, None)] * n_nonneg + [(None, None)] * (d - n_nonneg) + [(None, None)]
    res = minimize(loss, np.zeros(d + 1), jac=True, method="L-BFGS-B", bounds=bounds)
    if not res.success:
        raise RuntimeError(f"fusion fit did not converge: {res.message}")
    return res.x[:d], float(res.x[d])


@dataclass
class FusionModel:
    """Fitted fusion: weights, missing-indicator offsets, intercept and threshold."""

    signals: list[str]
    weights: dict[str, float]
    missing_offsets: dict[str, float]
    intercept: float
    threshold: float
    alpha: float
    n_calibration_humans: int
    trained_on: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    # ── Inference ─────────────────────────────────────────────────────────────

    def logit(self, scores: dict[str, float | None]) -> float:
        z = self.intercept
        for name in self.signals:
            v = scores.get(name)
            if v is None:
                z += self.missing_offsets[name]
            else:
                z += self.weights[name] * min(1.0, max(0.0, float(v)))
        return float(z)

    def predict_proba(self, scores: dict[str, float | None]) -> float:
        return float(_sigmoid(np.array(self.logit(scores))))

    def contributions(self, scores: dict[str, float | None]) -> dict[str, float]:
        """Each signal's additive log-odds evidence (0 for missing signals)."""
        return {
            name: (0.0 if scores.get(name) is None
                   else self.weights[name] * min(1.0, max(0.0, float(scores[name]))))  # type: ignore[arg-type]
            for name in self.signals
        }

    def flagged(self, scores: dict[str, float | None]) -> bool:
        return self.predict_proba(scores) > self.threshold

    # ── Fitting ───────────────────────────────────────────────────────────────

    @classmethod
    def fit(
        cls,
        fit_rows: list[dict[str, float | None]],
        fit_labels: np.ndarray,
        cal_rows: list[dict[str, float | None]],
        cal_labels: np.ndarray,
        alpha: float = 0.02,
        signals: tuple[str, ...] = SIGNALS,
        l2: float = 1.0,
        trained_on: str = "",
    ) -> FusionModel:
        """Fit weights on ``fit_*``; set the conformal threshold on ``cal_*`` humans."""
        k = len(signals)
        coef, b = fit_logistic(design_matrix(fit_rows, signals), np.asarray(fit_labels), k, l2)
        model = cls(
            signals=list(signals),
            weights={s: float(coef[j]) for j, s in enumerate(signals)},
            missing_offsets={s: float(coef[k + j]) for j, s in enumerate(signals)},
            intercept=b,
            threshold=math.inf,
            alpha=alpha,
            n_calibration_humans=0,
            trained_on=trained_on,
        )
        cal_labels = np.asarray(cal_labels)
        human = [r for r, lab in zip(cal_rows, cal_labels, strict=True) if lab == 0]
        model.threshold = conformal_threshold(
            np.array([model.predict_proba(r) for r in human]), alpha
        )
        model.n_calibration_humans = len(human)
        return model

    # ── Persistence (JSON, never pickle) ──────────────────────────────────────

    def to_json(self) -> str:
        d = asdict(self)
        d["threshold"] = None if math.isinf(self.threshold) else self.threshold
        return json.dumps(d, indent=2) + "\n"

    @classmethod
    def from_json(cls, text: str) -> FusionModel:
        d = json.loads(text)
        d["threshold"] = math.inf if d["threshold"] is None else float(d["threshold"])
        return cls(**d)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> FusionModel:
        return cls.from_json(path.read_text(encoding="utf-8"))
