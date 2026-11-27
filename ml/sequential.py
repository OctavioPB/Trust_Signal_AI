"""Anytime-valid early detection across interview turns.

Problem: the live dashboard re-checks the score after every turn. Comparing a
running score to a fixed threshold at every look is a multiple-testing error —
each look is another chance to flag an honest candidate by luck, so the real
false-positive rate grows with the number of turns (``evals/sequential.py``
measures how much).

Method (Wald's SPRT idea, calibrated conformally so it needs no independence):

1. Evidence per turn. A one-feature logistic model maps a turn's text-detector
   score to log-odds; subtracting the training prior log-odds gives the turn's
   log-likelihood ratio  ℓ_t = log p(x_t | AI) / p(x_t | human)  (clipped to
   ±``clip`` so one extreme turn cannot decide alone).
2. Running evidence  S_t = ℓ_1 + … + ℓ_t.
3. Threshold τ from held-out *human sessions*: for each, take the path maximum
   M = max_{t ≤ T_max} S_t; τ is the ⌈(n+1)(1-α)⌉-th smallest M. Flag the first
   time S_t > τ. A human session is ever flagged iff its M > τ, so for sessions
   exchangeable with the calibration ones, P(ever flagged) ≤ α — no matter how
   often the score is checked and without assuming turns are independent (one
   person's turns are correlated, which would break a naive e-value product).

Evidence stops accumulating after ``max_turns`` (the calibration horizon), so
the guarantee covers the whole monitored part of a session.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ml.fusion import conformal_threshold, fit_logistic


@dataclass
class SequentialState:
    """Running evidence for one session."""

    turns: int = 0
    evidence: float = 0.0
    peak: float = -math.inf
    flagged_at_turn: int | None = None
    history: list[float] = field(default_factory=list)

    @property
    def flagged(self) -> bool:
        return self.flagged_at_turn is not None


@dataclass
class SequentialMonitor:
    """Fitted per-turn evidence model + conformal path-max threshold."""

    weight: float
    intercept: float
    prior_logit: float
    clip: float
    threshold: float
    alpha: float
    max_turns: int
    n_calibration_sessions: int
    detector: str = "binoculars"
    metadata: dict[str, Any] = field(default_factory=dict)

    # ── Evidence ──────────────────────────────────────────────────────────────

    def turn_llr(self, score: float) -> float:
        z = self.intercept + self.weight * min(1.0, max(0.0, float(score)))
        return float(np.clip(z - self.prior_logit, -self.clip, self.clip))

    def path(self, scores: list[float]) -> np.ndarray:
        """Running evidence S_1..S_T for a session's turn scores (capped at max_turns)."""
        llr = [self.turn_llr(s) for s in scores[: self.max_turns]]
        return np.cumsum(llr) if llr else np.zeros(0)

    def update(self, state: SequentialState, score: float) -> SequentialState:
        """Add one candidate turn. Past ``max_turns`` the evidence is frozen."""
        if state.turns >= self.max_turns:
            state.turns += 1
            return state
        state.turns += 1
        state.evidence += self.turn_llr(score)
        state.history.append(round(state.evidence, 4))
        state.peak = max(state.peak, state.evidence)
        if state.flagged_at_turn is None and state.evidence > self.threshold:
            state.flagged_at_turn = state.turns
        return state

    def flag_reason(self, state: SequentialState) -> str:
        return (
            f"Evidence of AI assistance accumulated over {state.flagged_at_turn} candidate "
            f"turn(s) crossed the sequential threshold (log-evidence {state.evidence:.2f} > "
            f"{self.threshold:.2f}). This rule keeps false positives at or below "
            f"{self.alpha:.0%} for human sessions however often the score is checked."
        )

    # ── Fitting ───────────────────────────────────────────────────────────────

    @classmethod
    def fit(
        cls,
        fit_sessions: list[list[float]],
        fit_labels: np.ndarray,
        cal_sessions: list[list[float]],
        cal_labels: np.ndarray,
        alpha: float = 0.02,
        max_turns: int = 12,
        clip: float = 3.0,
        l2: float = 1.0,
        detector: str = "binoculars",
    ) -> SequentialMonitor:
        """Fit turn evidence on ``fit_*`` turns; set τ on ``cal_*`` human sessions."""
        xs, ys = [], []
        for sess, lab in zip(fit_sessions, fit_labels, strict=True):
            for s in sess[:max_turns]:
                xs.append([min(1.0, max(0.0, float(s)))])
                ys.append(int(lab))
        X, y = np.array(xs), np.array(ys)
        coef, b = fit_logistic(X, y, n_nonneg=1, l2=l2)
        p = float(np.clip(y.mean(), 1e-6, 1 - 1e-6))
        model = cls(
            weight=float(coef[0]), intercept=b, prior_logit=math.log(p / (1 - p)),
            clip=clip, threshold=math.inf, alpha=alpha, max_turns=max_turns,
            n_calibration_sessions=0, detector=detector,
        )
        humans = [s for s, lab in zip(cal_sessions, cal_labels, strict=True) if lab == 0 and s]
        peaks = np.array([model.path(s).max() for s in humans])
        model.threshold = conformal_threshold(peaks, alpha)
        model.n_calibration_sessions = len(humans)
        return model

    # ── Persistence (JSON) ────────────────────────────────────────────────────

    def to_json(self) -> str:
        d = asdict(self)
        d["threshold"] = None if math.isinf(self.threshold) else self.threshold
        return json.dumps(d, indent=2) + "\n"

    @classmethod
    def from_json(cls, text: str) -> SequentialMonitor:
        d = json.loads(text)
        d["threshold"] = math.inf if d["threshold"] is None else float(d["threshold"])
        return cls(**d)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> SequentialMonitor:
        return cls.from_json(path.read_text(encoding="utf-8"))
