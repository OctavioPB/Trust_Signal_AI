"""Score the evaluation set with every text signal and gate on regressions.

Scorers (higher = more AI-like):
  perplexity       distilgpt2 perplexity signal          (ml/features/perplexity.py)
  binoculars       Binoculars observer/performer ratio   (ml/features/binoculars.py)
  burstiness       sentence-length variation             (ml/features/burstiness.py)
  vocab_richness   type-token / hapax richness           (ml/features/vocab_richness.py)
  similarity       cosine vs the LLM answer bank         (ml/embeddings/similarity.py)
  fused_current    TrustScoreEngine exactly as the API runs it on text alone: the two
                   audio signals are absent and count as 0
  fused_text_only  the same weights renormalised over the three text signals it uses
  calibrated_fusion  ml.fusion: non-negative logistic fusion with missing-signal
                   indicators and a conformal threshold (alpha = FUSION_ALPHA),
                   cross-fitted so no text is ever scored by a model that saw it
  calibrated_fusion_binoculars  the same, with Binoculars in the language-model slot

Metrics per scorer: AUROC; TPR at 1 % FPR (threshold read off the human scores);
FPR and TPR at the production flag threshold (SUSPICION_THRESHOLD, fused scorers);
expected calibration error (fused scorers); and the flag rate per group at the
threshold giving 5 % FPR overall, so groups are compared on equal footing.

Usage:
    python -m evals.run                       # score + print + write evals/results/latest.json
    python -m evals.run --check               # also fail (exit 1) on regression vs baseline
    python -m evals.run --update-baseline     # accept current numbers as the baseline
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

import config
from evals.metrics import (
    auroc,
    expected_calibration_error,
    rate_above,
    threshold_at_fpr,
    tpr_at_fpr,
)

ROOT = Path(__file__).parent
EVAL_SET = ROOT / "data" / "eval_set.jsonl"
RESULTS = ROOT / "results" / "latest.json"
BASELINE = ROOT / "baseline.json"

GROUP_ALPHA = 0.05       # per-group flag rates are read at the 5 %-FPR threshold
TOLERANCE = {            # allowed drop vs baseline before the gate fails
    "auroc": 0.01,
    "tpr_at_1pct_fpr": 0.03,
}
GROUP_FPR_TOLERANCE = 0.03   # allowed rise in any human group's flag rate
FUSION_ALPHA = 0.02          # target false-positive rate for the conformal threshold
CONFORMAL_SLACK = 0.02       # sampling noise allowed above alpha on the held-out humans
N_FOLDS = 5


def load_set(path: Path = EVAL_SET) -> list[dict]:
    if not path.exists():
        sys.exit(f"{path} not found — run `python -m evals.build_dataset` first")
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def fingerprint(rows: list[dict]) -> str:
    h = hashlib.sha256()
    for r in sorted(rows, key=lambda r: r["id"]):
        h.update(f"{r['id']}\t{r['label']}\t{r['text']}\n".encode())
    return h.hexdigest()[:16]


BASE_SIGNALS = ("perplexity", "binoculars", "burstiness", "vocab_richness", "similarity")
SIGNAL_CACHE = ROOT / "results" / "signal_cache.json"


def _text_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]


def score_signals(
    rows: list[dict], use_cache: bool = False
) -> tuple[dict[str, np.ndarray], dict[str, int], dict[str, np.ndarray]]:
    """Raw scores of the four text signals, plus how often each abstained.

    A signal abstains (raises ValueError, e.g. burstiness on < 3 sentences); it then
    counts as 0, exactly as the API treats a missing signal. ``use_cache`` reuses
    scores keyed by text hash: local iteration only, never in CI (a cache would hide
    a change to the signal code from the gate).
    """
    cache: dict[str, dict[str, float]] = {}
    if use_cache and SIGNAL_CACHE.exists():
        cache = json.loads(SIGNAL_CACHE.read_text(encoding="utf-8"))

    scorers: dict | None = None

    def _load() -> dict:
        from ml.embeddings.similarity import SemanticSimilarityScorer
        from ml.features.binoculars import BinocularsScorer
        from ml.features.burstiness import score_burstiness
        from ml.features.perplexity import PerplexityScorer
        from ml.features.vocab_richness import score_vocab_richness

        ppl, sim, bino = PerplexityScorer(), SemanticSimilarityScorer(), BinocularsScorer()
        return {
            "perplexity": lambda i, t: ppl.score(i, t).suspicion_score,
            "binoculars": lambda i, t: bino.score(i, t).suspicion_score,
            "burstiness": lambda i, t: score_burstiness(i, t).suspicion_score,
            "vocab_richness": lambda i, t: score_vocab_richness(i, t).suspicion_score,
            "similarity": lambda i, t: sim.score(i, t).suspicion_score,
        }

    out: dict[str, list[float]] = {k: [] for k in BASE_SIGNALS}
    missing: dict[str, list[bool]] = {k: [] for k in BASE_SIGNALS}
    abstained = dict.fromkeys(BASE_SIGNALS, 0)
    for r in rows:
        key = _text_key(r["text"])
        cached = cache.setdefault(key, {})
        # A key absent from the cache is "not computed yet"; a None value is "abstained".
        todo = [n for n in BASE_SIGNALS if n not in cached]
        if todo:
            if scorers is None:
                scorers = _load()
            for name in todo:
                try:
                    cached[name] = float(scorers[name](r["id"], r["text"]))
                except ValueError:
                    cached[name] = None  # type: ignore[assignment]
        for name in BASE_SIGNALS:
            val = cached.get(name)
            if val is None:
                abstained[name] += 1
            missing[name].append(val is None)
            out[name].append(0.0 if val is None else float(val))

    if use_cache:
        SIGNAL_CACHE.parent.mkdir(parents=True, exist_ok=True)
        SIGNAL_CACHE.write_text(json.dumps(cache), encoding="utf-8")
    return (
        {k: np.array(v) for k, v in out.items()},
        abstained,
        {k: np.array(v) for k, v in missing.items()},
    )


def fuse(signals: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Add the two fused scorers to the per-signal scores."""
    from ml.trust_score import DEFAULT_WEIGHTS, TrustScoreEngine

    engine = TrustScoreEngine()
    p, b, s = signals["perplexity"], signals["burstiness"], signals["similarity"]
    fused_current = np.array([
        engine.compute("eval", 0.0, 0.0, float(pi), float(bi), float(si)).suspicion_index
        for pi, bi, si in zip(p, b, s, strict=True)
    ])
    w = {k: DEFAULT_WEIGHTS[k] for k in ("perplexity", "burstiness", "similarity")}
    text_only = (w["perplexity"] * p + w["burstiness"] * b + w["similarity"] * s) / sum(w.values())
    return {**signals, "fused_current": fused_current, "fused_text_only": text_only}


def _stratified_folds(groups: np.ndarray, k: int, seed: int) -> np.ndarray:
    """Fold id per row, balanced within every group."""
    rng = np.random.default_rng(seed)
    fold = np.empty(len(groups), dtype=int)
    for g in np.unique(groups):
        idx = np.flatnonzero(groups == g)
        rng.shuffle(idx)
        fold[idx] = np.arange(len(idx)) % k
    return fold


def fusion_features(
    signals: dict[str, np.ndarray],
    missing: dict[str, np.ndarray],
    text_detector: str = "perplexity",
) -> list[dict[str, float | None]]:
    """Per-row inputs for ml.fusion. Audio signals are absent from text: missing.

    ``text_detector`` chooses which language-model signal fills the "perplexity"
    slot (the API field keeps its name): "perplexity" or "binoculars".
    """
    n = len(next(iter(signals.values())))
    src = {"perplexity": text_detector, "burstiness": "burstiness", "similarity": "similarity"}

    def _val(slot: str, i: int) -> float | None:
        name = src[slot]
        return None if missing[name][i] else float(signals[name][i])

    return [
        {"latency": None, "bg_audio": None,
         **{slot: _val(slot, i) for slot in ("perplexity", "burstiness", "similarity")}}
        for i in range(n)
    ]


def cross_fit_fusion(
    rows: list[dict],
    signals: dict[str, np.ndarray],
    missing: dict[str, np.ndarray],
    alpha: float = FUSION_ALPHA,
    k: int = N_FOLDS,
    seed: int = 7,
    text_detector: str = "perplexity",
) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    """Out-of-fold calibrated probabilities and conformal flags for every row.

    Per fold: fit on 70 % of the other folds, set the threshold on the remaining
    30 % (stratified by group), then score the held-out fold. Audio signals are
    absent from text, so they enter as missing — exactly what the API sees.
    """
    from ml.fusion import FusionModel

    y = np.array([r["label"] for r in rows])
    groups = np.array([r["group"] for r in rows])
    feats = fusion_features(signals, missing, text_detector)
    fold = _stratified_folds(groups, k, seed)
    proba = np.zeros(len(rows))
    flags = np.zeros(len(rows), dtype=bool)
    fold_info: list[dict] = []
    for f in range(k):
        test = np.flatnonzero(fold == f)
        train = np.flatnonzero(fold != f)
        inner = _stratified_folds(groups[train], 10, seed + f)
        cal, fit = train[inner < 3], train[inner >= 3]
        model = FusionModel.fit(
            [feats[i] for i in fit], y[fit], [feats[i] for i in cal], y[cal], alpha=alpha
        )
        for i in test:
            proba[i] = model.predict_proba(feats[i])
            flags[i] = model.flagged(feats[i])
        fold_info.append({
            "threshold": round(model.threshold, 4),
            "n_calibration_humans": model.n_calibration_humans,
            "weights": {s_: round(w, 3) for s_, w in model.weights.items()},
        })
    return proba, flags, fold_info


def evaluate(
    rows: list[dict],
    scores: dict[str, np.ndarray],
    abstained: dict[str, int] | None = None,
    conformal: dict | None = None,
) -> dict:
    y = np.array([r["label"] for r in rows])
    groups = np.array([r["group"] for r in rows])
    prod_t = float(config.SUSPICION_THRESHOLD)
    report: dict = {
        "dataset": {
            "fingerprint": fingerprint(rows),
            "n": len(rows),
            "groups": {g: int((groups == g).sum()) for g in sorted(set(groups))},
            "human_groups": sorted(set(groups[y == 0])),
        },
        "abstained": abstained or {},
        "scorers": {},
    }
    for name, s in scores.items():
        tpr1, fpr1, t1 = tpr_at_fpr(y, s, 0.01)
        t5 = threshold_at_fpr(s[y == 0], GROUP_ALPHA)
        m = {
            "auroc": round(auroc(y, s), 4),
            "tpr_at_1pct_fpr": round(tpr1, 4),
            "fpr_achieved_at_1pct": round(fpr1, 4),
            "group_flag_rate_at_5pct_fpr": {
                g: round(rate_above(s[groups == g], t5), 4) for g in sorted(set(groups))
            },
        }
        if name.startswith("fused"):
            m["at_production_threshold"] = {
                "threshold": prod_t,
                "fpr": round(rate_above(s[y == 0], prod_t), 4),
                "tpr": round(rate_above(s[y == 1], prod_t), 4),
            }
            m["ece"] = round(expected_calibration_error(y, s), 4)
        if name.startswith("calibrated_fusion"):
            m["ece"] = round(expected_calibration_error(y, s), 4)
            if conformal is not None and name in conformal:
                fl = conformal[name]["flags"]
                m["at_conformal_threshold"] = {
                    "alpha": conformal[name]["alpha"],
                    "fpr": round(float(fl[y == 0].mean()), 4),
                    "tpr": round(float(fl[y == 1].mean()), 4),
                    "group_flag_rate": {
                        g: round(float(fl[groups == g].mean()), 4) for g in sorted(set(groups))
                    },
                    "folds": conformal[name]["folds"],
                }
        report["scorers"][name] = m
    return report


def check(current: dict, baseline: dict) -> list[str]:
    """Regressions of ``current`` against ``baseline`` (empty list = pass)."""
    if current["dataset"]["fingerprint"] != baseline["dataset"]["fingerprint"]:
        return [
            "evaluation set changed (fingerprint "
            f"{baseline['dataset']['fingerprint']} → {current['dataset']['fingerprint']}); "
            "numbers are not comparable — rerun with --update-baseline and commit it"
        ]
    problems: list[str] = []
    human_groups = set(current["dataset"]["human_groups"])
    for sname, sm in current["scorers"].items():
        conf = sm.get("at_conformal_threshold")
        if conf and conf["fpr"] > conf["alpha"] + CONFORMAL_SLACK:
            problems.append(
                f"{sname}: held-out FPR {conf['fpr']} breaks the conformal target "
                f"{conf['alpha']} (+{CONFORMAL_SLACK} sampling slack)"
            )
    for name, base in baseline["scorers"].items():
        cur = current["scorers"].get(name)
        if cur is None:
            problems.append(f"{name}: scorer missing from current run")
            continue
        for metric, tol in TOLERANCE.items():
            if cur[metric] < base[metric] - tol:
                problems.append(
                    f"{name}.{metric}: {base[metric]} → {cur[metric]} (tolerance {tol})"
                )
        for g, base_rate in base["group_flag_rate_at_5pct_fpr"].items():
            if g in human_groups:
                cur_rate = cur["group_flag_rate_at_5pct_fpr"].get(g, base_rate)
                if cur_rate > base_rate + GROUP_FPR_TOLERANCE:
                    problems.append(
                        f"{name}: human group '{g}' flag rate {base_rate} → {cur_rate}"
                    )
    return problems


def _print_summary(report: dict) -> None:
    ds = report["dataset"]
    print(f"Evaluation set: {ds['n']} texts, fingerprint {ds['fingerprint']}")  # noqa: T201
    print(f"{'scorer':<30}{'AUROC':>7}{'TPR@1%FPR':>11}  non-native vs native flag rate @5% FPR")  # noqa: T201
    for name, m in report["scorers"].items():
        g = m["group_flag_rate_at_5pct_fpr"]
        nn, na = g.get("non_native_essay", float("nan")), g.get("native_essay", float("nan"))
        print(  # noqa: T201
            f"{name:<30}{m['auroc']:>7.3f}{m['tpr_at_1pct_fpr']:>11.3f}  {nn:.2f} vs {na:.2f}"
        )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="TrustSignal detection evaluation")
    ap.add_argument("--check", action="store_true", help="fail on regression vs baseline")
    ap.add_argument("--update-baseline", action="store_true", help="write baseline.json")
    ap.add_argument("--cache", action="store_true", help="reuse signal scores (local only)")
    args = ap.parse_args(argv)

    rows = load_set()
    signals, abstained, missing = score_signals(rows, use_cache=args.cache)
    scores = fuse(signals)
    conformal: dict = {}
    for name, detector in (("calibrated_fusion", "perplexity"),
                           ("calibrated_fusion_binoculars", "binoculars")):
        proba, flags, folds = cross_fit_fusion(rows, signals, missing, text_detector=detector)
        scores[name] = proba
        conformal[name] = {"alpha": FUSION_ALPHA, "flags": flags, "folds": folds}
    report = evaluate(rows, scores, abstained, conformal=conformal)
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    _print_summary(report)

    if args.update_baseline:
        BASELINE.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"baseline updated: {BASELINE}")  # noqa: T201
        return 0
    if args.check:
        if not BASELINE.exists():
            print("no baseline.json — run with --update-baseline first")  # noqa: T201
            return 1
        problems = check(report, json.loads(BASELINE.read_text(encoding="utf-8")))
        for p in problems:
            print(f"REGRESSION: {p}")  # noqa: T201
        print("gate: FAIL" if problems else "gate: PASS")  # noqa: T201
        return 1 if problems else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
