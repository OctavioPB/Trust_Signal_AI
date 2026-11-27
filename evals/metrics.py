"""Detection metrics for the evaluation harness (pure numpy; unit-tested).

Conventions: ``y`` is 1 for AI-written/assisted and 0 for human; ``s`` is a
suspicion score where higher means "more likely AI". A text is flagged when
``s > threshold`` (strict), so a threshold read off the human scores bounds the
false-positive rate even when many humans tie at the same score (e.g. 0.0).
"""

from __future__ import annotations

import numpy as np


def auroc(y: np.ndarray, s: np.ndarray) -> float:
    """Area under the ROC curve via the rank-sum (Mann-Whitney) form; ties count 0.5."""
    y = np.asarray(y, dtype=int)
    s = np.asarray(s, dtype=float)
    pos, neg = s[y == 1], s[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        raise ValueError("AUROC needs both classes")
    greater = (pos[:, None] > neg[None, :]).sum()
    ties = (pos[:, None] == neg[None, :]).sum()
    return float((greater + 0.5 * ties) / (len(pos) * len(neg)))


def threshold_at_fpr(s_human: np.ndarray, alpha: float) -> float:
    """Smallest threshold t whose false-positive rate ``mean(s_human > t)`` is ≤ alpha."""
    s_human = np.sort(np.asarray(s_human, dtype=float))
    n = len(s_human)
    if n == 0:
        raise ValueError("need human scores")
    k = int(np.floor(alpha * n))          # at most k humans may lie strictly above t
    return float(s_human[n - k - 1]) if k < n else float(s_human[0]) - 1e-12


def rate_above(s: np.ndarray, threshold: float) -> float:
    s = np.asarray(s, dtype=float)
    return float((s > threshold).mean()) if len(s) else float("nan")


def tpr_at_fpr(y: np.ndarray, s: np.ndarray, alpha: float) -> tuple[float, float, float]:
    """(TPR, achieved FPR, threshold) at the threshold that keeps FPR ≤ alpha."""
    y = np.asarray(y, dtype=int)
    s = np.asarray(s, dtype=float)
    t = threshold_at_fpr(s[y == 0], alpha)
    return rate_above(s[y == 1], t), rate_above(s[y == 0], t), t


def expected_calibration_error(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    """ECE of scores read as probabilities, equal-width bins over [0, 1]."""
    y = np.asarray(y, dtype=float)
    p = np.clip(np.asarray(p, dtype=float), 0.0, 1.0)
    idx = np.minimum((p * bins).astype(int), bins - 1)
    ece = 0.0
    for b in range(bins):
        m = idx == b
        if m.any():
            ece += m.mean() * abs(y[m].mean() - p[m].mean())
    return float(ece)
