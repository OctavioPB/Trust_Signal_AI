"""Unit tests for evals.metrics and the regression gate in evals.run (no models)."""

from __future__ import annotations

import copy

import numpy as np
import pytest

from evals.metrics import (
    auroc,
    expected_calibration_error,
    rate_above,
    threshold_at_fpr,
    tpr_at_fpr,
)
from evals.run import check, evaluate, fingerprint


class TestAuroc:
    def test_perfect_separation(self) -> None:
        assert auroc(np.array([0, 0, 1, 1]), np.array([0.1, 0.2, 0.8, 0.9])) == 1.0

    def test_inverted(self) -> None:
        assert auroc(np.array([0, 0, 1, 1]), np.array([0.9, 0.8, 0.2, 0.1])) == 0.0

    def test_all_ties_is_half(self) -> None:
        assert auroc(np.array([0, 1, 0, 1]), np.zeros(4)) == 0.5

    def test_matches_sklearn(self) -> None:
        from sklearn.metrics import roc_auc_score

        rng = np.random.default_rng(0)
        y = rng.integers(0, 2, 200)
        s = rng.random(200) + 0.3 * y
        assert auroc(y, s) == pytest.approx(roc_auc_score(y, s))

    def test_needs_both_classes(self) -> None:
        with pytest.raises(ValueError):
            auroc(np.array([1, 1]), np.array([0.2, 0.3]))


class TestThresholds:
    def test_fpr_bound_holds(self) -> None:
        rng = np.random.default_rng(1)
        human = rng.random(500)
        for alpha in (0.01, 0.05, 0.2):
            t = threshold_at_fpr(human, alpha)
            assert rate_above(human, t) <= alpha

    def test_ties_at_zero_never_exceed_alpha(self) -> None:
        human = np.array([0.0] * 95 + [0.5, 0.6, 0.7, 0.8, 0.9])
        t = threshold_at_fpr(human, 0.01)
        assert rate_above(human, t) <= 0.01

    def test_tpr_at_fpr(self) -> None:
        y = np.array([0] * 100 + [1] * 10)
        s = np.concatenate([np.linspace(0, 0.5, 100), np.full(10, 0.9)])
        tpr, fpr, _ = tpr_at_fpr(y, s, 0.01)
        assert tpr == 1.0 and fpr <= 0.01


class TestEce:
    def test_perfectly_calibrated_is_zero(self) -> None:
        y = np.array([0, 0, 1, 1])
        assert expected_calibration_error(y, y.astype(float)) == 0.0

    def test_overconfident_is_positive(self) -> None:
        y = np.array([0, 1, 0, 1])
        assert expected_calibration_error(y, np.full(4, 0.95)) == pytest.approx(0.45)


def _rows() -> list[dict]:
    rows = []
    for i in range(40):
        rows.append({"id": f"h{i}", "text": f"h{i}", "label": 0,
                     "group": "non_native_essay" if i % 2 else "native_essay"})
        rows.append({"id": f"a{i}", "text": f"a{i}", "label": 1, "group": "chatgpt_qa"})
    return rows


def _scores(rows: list[dict], shift: float = 0.5) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(2)
    s = np.array([rng.random() * 0.5 + (shift if r["label"] else 0.0) for r in rows])
    return {"fused_current": s, "perplexity": s}


class TestGate:
    def test_same_numbers_pass(self) -> None:
        rows = _rows()
        report = evaluate(rows, _scores(rows))
        assert check(report, copy.deepcopy(report)) == []

    def test_auroc_drop_fails(self) -> None:
        rows = _rows()
        base = evaluate(rows, _scores(rows, shift=0.5))
        worse = evaluate(rows, _scores(rows, shift=0.0))
        problems = check(worse, base)
        assert any("auroc" in p for p in problems)

    def test_human_group_flag_rate_rise_fails(self) -> None:
        rows = _rows()
        base = evaluate(rows, _scores(rows))
        cur = copy.deepcopy(base)
        cur["scorers"]["perplexity"]["group_flag_rate_at_5pct_fpr"]["non_native_essay"] += 0.2
        assert any("non_native_essay" in p for p in check(cur, base))

    def test_ai_group_changes_do_not_count_as_fpr(self) -> None:
        rows = _rows()
        base = evaluate(rows, _scores(rows))
        cur = copy.deepcopy(base)
        cur["scorers"]["perplexity"]["group_flag_rate_at_5pct_fpr"]["chatgpt_qa"] += 0.3
        assert check(cur, base) == []

    def test_changed_dataset_fails_loudly(self) -> None:
        rows = _rows()
        base = evaluate(rows, _scores(rows))
        rows2 = rows + [{"id": "x", "text": "x", "label": 0, "group": "native_essay"}]
        cur = evaluate(rows2, _scores(rows2))
        assert fingerprint(rows) != fingerprint(rows2)
        assert "evaluation set changed" in check(cur, base)[0]
