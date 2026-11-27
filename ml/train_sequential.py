"""Fit the anytime-valid sequential monitor and write a versioned artifact.

Turn-level sessions come from the evaluation set (``evals/sequential.py``): 70 %
of each group fits the per-turn evidence model, 30 % sets the conformal path-max
threshold. Held-out numbers from the cross-fitted evaluation are copied into the
artifact's metadata.

Usage:
    python -m ml.train_sequential [--cache]   # → ml/artifacts/YYYYMMDD_sequential.json
    SEQUENTIAL_MODEL_PATH=ml/artifacts/<file> uvicorn api.main:app
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

import config
from evals.run import _stratified_folds, fingerprint, load_set
from evals.sequential import ALPHA, MAX_TURNS, RESULTS, score_turns
from ml.sequential import SequentialMonitor

ARTIFACTS = Path(__file__).parent / "artifacts"


def train(use_cache: bool = False, seed: int = 11) -> SequentialMonitor:
    rows = load_set()
    sessions = score_turns(rows, use_cache)
    keep = np.array([len(s) > 0 for s in sessions])
    y = np.array([r["label"] for r in rows])
    groups = np.array([r["group"] for r in rows])
    split = _stratified_folds(groups, 10, seed)
    cal = np.flatnonzero((split < 3) & keep)
    fit = np.flatnonzero((split >= 3) & keep)
    mon = SequentialMonitor.fit(
        [sessions[i] for i in fit], y[fit], [sessions[i] for i in cal], y[cal],
        alpha=ALPHA, max_turns=MAX_TURNS, detector=config.TEXT_DETECTOR,
    )
    mon.metadata = {
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "trained_on": f"evals set {fingerprint(rows)}, turn sessions",
        "binoculars": {"observer": config.BINOCULARS_OBSERVER,
                       "performer": config.BINOCULARS_PERFORMER},
    }
    if RESULTS.exists():
        r = json.loads(RESULTS.read_text(encoding="utf-8"))
        mon.metadata["held_out_cross_fit"] = {
            "fpr": r["sequential"]["fpr"],
            "tpr": r["sequential"]["tpr"],
            "tpr_by_turn": r["sequential"]["tpr_by_turn"],
            "naive_running_mean_fpr_every_turn": r["naive_running_mean"]["fpr_checked_every_turn"],
        }
    return mon


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fit the sequential early-detection monitor")
    ap.add_argument("--cache", action="store_true")
    args = ap.parse_args(argv)
    mon = train(use_cache=args.cache)
    out = ARTIFACTS / f"{datetime.now(UTC):%Y%m%d}_sequential.json"
    mon.save(out)
    print(  # noqa: T201
        f"saved {out}\n  threshold={mon.threshold:.3f} over {mon.n_calibration_sessions} "
        f"human calibration sessions (alpha={mon.alpha}), turn weight={mon.weight:.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
