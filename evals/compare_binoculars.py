"""Compare Binoculars model pairs on the evaluation set (local, needs model downloads).

Prints AUROC, TPR at 1% FPR and the non-native vs native flag rate for each pair,
plus CPU seconds per text (what CI pays), and the class medians used to set
BINOCULARS_MIDPOINT / BINOCULARS_SCALE.

Usage:
    python -m evals.compare_binoculars [--pairs smol135,smol360,qwen05]
"""

from __future__ import annotations

import argparse
import json
import time

import numpy as np

from evals.metrics import auroc, rate_above, threshold_at_fpr, tpr_at_fpr
from evals.run import ROOT, load_set

PAIRS = {
    "smol135": ("HuggingFaceTB/SmolLM2-135M", "HuggingFaceTB/SmolLM2-135M-Instruct"),
    "smol360": ("HuggingFaceTB/SmolLM2-360M", "HuggingFaceTB/SmolLM2-360M-Instruct"),
    "qwen05": ("Qwen/Qwen2.5-0.5B", "Qwen/Qwen2.5-0.5B-Instruct"),
}


def main() -> None:
    from ml.features.binoculars import BinocularsScorer

    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default=",".join(PAIRS))
    args = ap.parse_args()

    rows = load_set()
    y = np.array([r["label"] for r in rows])
    groups = np.array([r["group"] for r in rows])
    summary = {}
    for key in args.pairs.split(","):
        obs, perf = PAIRS[key]
        scorer = BinocularsScorer(obs, perf)
        raw = np.full(len(rows), np.nan)
        for i, r in enumerate(rows):
            try:
                raw[i] = scorer.raw_score(r["text"])[3]
            except ValueError:
                pass
        ok = ~np.isnan(raw)
        s = -np.where(ok, raw, np.nanmax(raw))      # missing → least suspicious
        tpr, _, _ = tpr_at_fpr(y, s, 0.01)
        t5 = threshold_at_fpr(s[y == 0], 0.05)

        cpu = BinocularsScorer(obs, perf, device="cpu")
        t0 = time.perf_counter()
        for r in rows[:10]:
            try:
                cpu.raw_score(r["text"])
            except ValueError:
                pass
        cpu_s = (time.perf_counter() - t0) / 10

        def _rate(group: str, s=s, t5=t5) -> float:
            return round(rate_above(s[groups == group], t5), 4)

        summary[key] = {
            "auroc": round(auroc(y, s), 4),
            "tpr_at_1pct_fpr": round(tpr, 4),
            "non_native_flag_rate_at_5pct": _rate("non_native_essay"),
            "native_flag_rate_at_5pct": _rate("native_essay"),
            "abstained": int((~ok).sum()),
            "median_human": round(float(np.nanmedian(raw[y == 0])), 4),
            "median_ai": round(float(np.nanmedian(raw[y == 1])), 4),
            "cpu_seconds_per_text": round(cpu_s, 3),
        }
        print(key, json.dumps(summary[key]))  # noqa: T201
        del scorer, cpu
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "binoculars_pairs.json").write_text(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
