"""Fit the calibrated fusion model and write a versioned artifact.

Fits on the labelled evaluation set (``evals/``): 70 % of each group fits the
weights, the other 30 % sets the conformal threshold. The held-out quality of
this exact procedure is what ``python -m evals.run`` reports for the
``calibrated_fusion`` scorer (cross-fitted, so no text scores itself); those
numbers are copied into the artifact's metadata.

Once human-reviewed sessions accumulate (``storage/review_store.py``), the same
fit should move into the nightly DAG with reviews as labels — that is when the
audio signals get non-zero weights.

Usage:
    python -m ml.train_fusion                 # → ml/artifacts/YYYYMMDD_fusion.json
    FUSION_MODEL_PATH=ml/artifacts/<file> uvicorn api.main:app   # serve it
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

import config
from evals.run import (
    FUSION_ALPHA,
    RESULTS,
    _stratified_folds,
    fingerprint,
    fusion_features,
    load_set,
    score_signals,
)
from ml.fusion import FusionModel

ARTIFACTS = Path(__file__).parent / "artifacts"


def train(use_cache: bool = False, alpha: float = FUSION_ALPHA, seed: int = 11) -> FusionModel:
    rows = load_set()
    signals, _, missing = score_signals(rows, use_cache=use_cache)
    detector = config.TEXT_DETECTOR
    feats = fusion_features(signals, missing, detector)
    y = np.array([r["label"] for r in rows])
    groups = np.array([r["group"] for r in rows])

    split = _stratified_folds(groups, 10, seed)
    cal, fit = np.flatnonzero(split < 3), np.flatnonzero(split >= 3)
    model = FusionModel.fit(
        [feats[i] for i in fit], y[fit], [feats[i] for i in cal], y[cal],
        alpha=alpha,
        trained_on=f"evals set {fingerprint(rows)} ({len(rows)} texts), text detector {detector}",
    )

    meta: dict = {
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "text_detector": detector,
    }
    if detector == "binoculars":
        meta["binoculars"] = {
            "observer": config.BINOCULARS_OBSERVER,
            "performer": config.BINOCULARS_PERFORMER,
            "midpoint": config.BINOCULARS_MIDPOINT,
            "scale": config.BINOCULARS_SCALE,
        }
    if RESULTS.exists():
        held_out = json.loads(RESULTS.read_text(encoding="utf-8"))
        key = "calibrated_fusion_binoculars" if detector == "binoculars" else "calibrated_fusion"
        m = held_out["scorers"].get(key, {})
        conf = m.get("at_conformal_threshold", {})
        meta["held_out_cross_fit"] = {
            "auroc": m.get("auroc"),
            "ece": m.get("ece"),
            "fpr": conf.get("fpr"),
            "tpr": conf.get("tpr"),
            "group_flag_rate": conf.get("group_flag_rate"),
        }
    model.metadata = meta
    return model


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fit the calibrated fusion model")
    ap.add_argument("--cache", action="store_true", help="reuse evals signal cache")
    ap.add_argument("--alpha", type=float, default=FUSION_ALPHA)
    args = ap.parse_args(argv)

    model = train(use_cache=args.cache, alpha=args.alpha)
    out = ARTIFACTS / f"{datetime.now(UTC):%Y%m%d}_fusion.json"
    model.save(out)
    print(  # noqa: T201 - CLI output
        f"saved {out}\n  threshold={model.threshold:.4f} (alpha={model.alpha}, "
        f"{model.n_calibration_humans} calibration humans)\n  weights={model.weights}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
