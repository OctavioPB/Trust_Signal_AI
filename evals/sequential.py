"""Evaluate anytime-valid early detection (ml/sequential.py) on turn-level sessions.

Sessions are built from the evaluation set: each text becomes one session and is
split into "turns" of two sentences (a turn under 12 words is merged into the
previous one). Turns of one session share an author, so the within-session
dependence that breaks naive sequential tests is present.

Each turn is scored by the Binoculars detector. Cross-fitted by session (5 folds,
stratified by group): fit the turn-evidence model on 70 % of the training
sessions, set the conformal path-max threshold on the other 30 %, test on the
held-out fold. Reported:

  sequential   P(human session ever flagged), detection rate, turns to detection
  naive        thresholds calibrated for ONE look at the end of the session but
               checked after every turn, for two running statistics: the summed
               evidence, and the running average of per-turn suspicion (what a live
               dashboard typically shows). Their any-look false-positive rates show
               the inflation the sequential rule removes.

Usage:
    python -m evals.sequential [--cache] [--check] [--update-baseline]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys

import numpy as np

from evals.run import ROOT, _stratified_folds, fingerprint, load_set
from ml.fusion import conformal_threshold
from ml.sequential import SequentialMonitor

ALPHA = 0.02
SLACK = 0.02
MAX_TURNS = 12
SENTENCES_PER_TURN = 2
MIN_TURN_WORDS = 12
TURN_CACHE = ROOT / "results" / "turn_cache.json"
RESULTS = ROOT / "results" / "sequential.json"
BASELINE = ROOT / "baseline_sequential.json"
TPR_TOLERANCE = 0.03


def split_turns(text: str) -> list[str]:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    turns: list[str] = []
    for i in range(0, len(sentences), SENTENCES_PER_TURN):
        chunk = " ".join(sentences[i:i + SENTENCES_PER_TURN])
        if turns and len(chunk.split()) < MIN_TURN_WORDS:
            turns[-1] = f"{turns[-1]} {chunk}"
        else:
            turns.append(chunk)
    return turns


def score_turns(rows: list[dict], use_cache: bool) -> list[list[float]]:
    """Binoculars suspicion per turn; abstaining turns are dropped from the session."""
    cache: dict[str, float | None] = {}
    if use_cache and TURN_CACHE.exists():
        cache = json.loads(TURN_CACHE.read_text(encoding="utf-8"))
    scorer = None
    sessions: list[list[float]] = []
    for r in rows:
        sess: list[float] = []
        for turn in split_turns(r["text"]):
            key = hashlib.sha256(turn.encode("utf-8")).hexdigest()[:20]
            if key not in cache:
                if scorer is None:
                    from ml.features.binoculars import BinocularsScorer

                    scorer = BinocularsScorer()
                try:
                    cache[key] = float(scorer.score(r["id"], turn).suspicion_score)
                except ValueError:
                    cache[key] = None
            if cache[key] is not None:
                sess.append(cache[key])  # type: ignore[arg-type]
        sessions.append(sess)
    if use_cache:
        TURN_CACHE.parent.mkdir(parents=True, exist_ok=True)
        TURN_CACHE.write_text(json.dumps(cache), encoding="utf-8")
    return sessions


def evaluate(rows: list[dict], sessions: list[list[float]], k: int = 5, seed: int = 7) -> dict:
    y = np.array([r["label"] for r in rows])
    groups = np.array([r["group"] for r in rows])
    keep = np.array([len(s) > 0 for s in sessions])
    fold = _stratified_folds(groups, k, seed)

    seq_flag_turn = np.full(len(rows), -1)        # first turn flagged, -1 = never
    naive_any = np.zeros(len(rows), dtype=bool)   # one-look threshold, checked every turn
    naive_final = np.zeros(len(rows), dtype=bool) # one-look threshold, checked once at end
    mean_any = np.zeros(len(rows), dtype=bool)    # running mean, one-look threshold
    mean_final = np.zeros(len(rows), dtype=bool)
    folds_info = []
    for f in range(k):
        test = np.flatnonzero((fold == f) & keep)
        train = np.flatnonzero((fold != f) & keep)
        inner = _stratified_folds(groups[train], 10, seed + f)
        cal, fit = train[inner < 3], train[inner >= 3]
        mon = SequentialMonitor.fit(
            [sessions[i] for i in fit], y[fit], [sessions[i] for i in cal], y[cal],
            alpha=ALPHA, max_turns=MAX_TURNS,
        )
        finals = np.array([mon.path(sessions[i])[-1] for i in cal if y[i] == 0])
        tau_one_look = conformal_threshold(finals, ALPHA)

        def _running_mean(sess: list[float]) -> np.ndarray:
            x = np.asarray(sess[:MAX_TURNS], dtype=float)
            return np.cumsum(x) / np.arange(1, len(x) + 1)

        tau_mean = conformal_threshold(
            np.array([_running_mean(sessions[i])[-1] for i in cal if y[i] == 0]), ALPHA
        )
        for i in test:
            path = mon.path(sessions[i])
            over = np.flatnonzero(path > mon.threshold)
            seq_flag_turn[i] = int(over[0]) + 1 if len(over) else -1
            naive_any[i] = bool((path > tau_one_look).any())
            naive_final[i] = bool(path[-1] > tau_one_look)
            rm = _running_mean(sessions[i])
            mean_any[i] = bool((rm > tau_mean).any())
            mean_final[i] = bool(rm[-1] > tau_mean)
        folds_info.append({"threshold": round(mon.threshold, 3),
                           "one_look_threshold": round(tau_one_look, 3),
                           "weight": round(mon.weight, 3),
                           "n_calibration_sessions": mon.n_calibration_sessions})

    h, a = keep & (y == 0), keep & (y == 1)
    flagged = seq_flag_turn > 0
    detect_turns = seq_flag_turn[a & flagged]
    lengths = np.array([len(s) for s in sessions])
    return {
        "dataset": {"fingerprint": fingerprint(rows), "sessions": int(keep.sum()),
                    "median_turns": float(np.median(lengths[keep])),
                    "max_turns_monitored": MAX_TURNS},
        "alpha": ALPHA,
        "sequential": {
            "fpr": round(float(flagged[h].mean()), 4),
            "tpr": round(float(flagged[a].mean()), 4),
            "tpr_by_turn": {
                str(t): round(float(((seq_flag_turn > 0) & (seq_flag_turn <= t))[a].mean()), 4)
                for t in (1, 2, 3, 5)
            },
            "median_turns_to_detection": (
                float(np.median(detect_turns)) if len(detect_turns) else None
            ),
            "group_flag_rate": {
                g: round(float(flagged[keep & (groups == g)].mean()), 4)
                for g in sorted(set(groups))
            },
        },
        "naive_every_turn": {
            "fpr_checked_every_turn": round(float(naive_any[h].mean()), 4),
            "fpr_checked_once_at_end": round(float(naive_final[h].mean()), 4),
            "tpr_checked_every_turn": round(float(naive_any[a].mean()), 4),
        },
        "naive_running_mean": {
            "fpr_checked_every_turn": round(float(mean_any[h].mean()), 4),
            "fpr_checked_once_at_end": round(float(mean_final[h].mean()), 4),
            "tpr_checked_every_turn": round(float(mean_any[a].mean()), 4),
        },
        "folds": folds_info,
    }


def check(cur: dict, base: dict) -> list[str]:
    if cur["dataset"]["fingerprint"] != base["dataset"]["fingerprint"]:
        return ["evaluation set changed — rerun with --update-baseline and commit it"]
    problems = []
    if cur["sequential"]["fpr"] > cur["alpha"] + SLACK:
        problems.append(f"sequential FPR {cur['sequential']['fpr']} breaks alpha {cur['alpha']}")
    if cur["sequential"]["tpr"] < base["sequential"]["tpr"] - TPR_TOLERANCE:
        problems.append(
            f"sequential TPR {base['sequential']['tpr']} → {cur['sequential']['tpr']}"
        )
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Sequential early-detection evaluation")
    ap.add_argument("--cache", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--update-baseline", action="store_true")
    args = ap.parse_args(argv)

    rows = load_set()
    report = evaluate(rows, score_turns(rows, args.cache))
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    s, ds = report["sequential"], report["dataset"]
    print(f"sessions={ds['sessions']} median turns={ds['median_turns']}")  # noqa: T201
    print(  # noqa: T201
        f"sequential: FPR {s['fpr']} (alpha {ALPHA}), TPR {s['tpr']}, by turn {s['tpr_by_turn']}, "
        f"median turns to detection {s['median_turns_to_detection']}"
    )
    for label in ("naive_every_turn", "naive_running_mean"):
        n = report[label]
        print(  # noqa: T201
            f"{label}: FPR once-at-end {n['fpr_checked_once_at_end']} vs every-turn "
            f"{n['fpr_checked_every_turn']} (TPR {n['tpr_checked_every_turn']})"
        )
    if args.update_baseline:
        BASELINE.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"baseline updated: {BASELINE}")  # noqa: T201
        return 0
    if args.check:
        if not BASELINE.exists():
            print("no baseline_sequential.json — run with --update-baseline first")  # noqa: T201
            return 1
        problems = check(report, json.loads(BASELINE.read_text(encoding="utf-8")))
        for p in problems:
            print(f"REGRESSION: {p}")  # noqa: T201
        print("gate: FAIL" if problems else "gate: PASS")  # noqa: T201
        return 1 if problems else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
