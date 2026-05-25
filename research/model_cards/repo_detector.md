# Model Card — Repository AI Detector

**Version:** 1.0.0 (2026-01-15)
**Owner:** Trust Signal AI ML Team
**Contact:** ml-team@trustsignalai.com

---

## Model Overview

| Field | Value |
|-------|-------|
| **Model type** | Ensemble: code-LM perplexity + commit-pattern classifier + style-consistency scorer |
| **Task** | Binary classification — human-authored vs. AI-generated repository code |
| **Output** | Suspicion score 0–1 (≥ 0.5 treated as flagged) |
| **Inference latency** | < 10 s per repository (top-20 files, CPU, 4-core 16 GB RAM) |
| **Artifact path** | `models/repo_detector/YYYYMMDD_repo_detector.pkl` |

---

## Features

| Feature | Description | Weight |
|---------|------------|--------|
| Code-LM perplexity | Cross-entropy of code under CodeBERT / StarCoder-3B | 0.35 |
| Commit authorship consistency | Variance of coding style across commits | 0.25 |
| Comment-to-code ratio | Unusually uniform, well-formed docstrings | 0.20 |
| Variable naming entropy | Low entropy → systematic AI naming patterns | 0.20 |

**Aggregation:** weighted mean; calibrated via Platt scaling on held-out set.

Code-LM: `bigcode/starcoderbase-3b` (loaded via `transformers`) for perplexity; `microsoft/codebert-base` for embedding-based style scoring.

---

## Training Data

| Split | N repos | Languages | Source |
|-------|---------|-----------|--------|
| Human repos | 3 800 | Python, JS/TS, Go, Java, Rust | GitHub public repos, filtered (CC0 / MIT) |
| AI-generated repos | 3 800 | Same distribution | GPT-4o, Claude 3.5, Copilot-workspace prompts |
| Validation | 800 | Balanced | Held out from all training |
| Test | 400 | Balanced | Blind hold-out |

All repositories were anonymised (owner, contributor info stripped) before ingestion. Only top-20 non-binary files by size are analysed per repo.

---

## Performance

| Metric | Value |
|--------|-------|
| AUROC | 0.91 |
| Precision @ threshold 0.50 | 0.88 |
| Recall @ threshold 0.50 | 0.85 |
| False-positive rate (human → flagged) | **1.9 %** |
| False-negative rate (AI → not flagged) | 5.1 % |

FP rate target: < 2 % on human baseline. This model meets the target.

---

## Bias Audit

Evaluated on stratified subsets of the human repository corpus:

| Subset | FP Rate |
|--------|---------|
| Python repos | 1.7 % |
| JavaScript / TypeScript repos | 2.0 % |
| Go / Rust repos | 1.5 % |
| Repos < 500 lines | 2.6 % |
| Repos > 5 000 lines | 1.4 % |
| Tutorial / educational style | 2.3 % |
| Library / framework style | 1.6 % |

Tutorial-style and small repos show slightly elevated FP. These are repos where clean, uniform code is intentional and does not indicate AI authorship.

---

## Limitations

1. **Small repos (< 500 LOC)**: insufficient signal; perplexity estimates have high variance. Score returned as `null` if fewer than 3 analysable files found.
2. **Educational / tutorial code**: deliberately clean, well-commented code can mimic AI patterns.
3. **Code style guides**: projects enforcing strict linters (e.g. `black`, `gofmt`) exhibit lower style variance, which can inflate suspicion slightly.
4. **Novel AI models**: a new code-generation model not in training data may evade detection until nightly DAG retraining.
5. **Private dependencies**: code that heavily references internal libraries not in the training corpus produces high perplexity even for human authors.
6. **Single-language assumption**: mixed-language repos (e.g. Python + Rust) are scored on the dominant language only.

---

## Intended Use

- **In scope:** Pre-screening aid for evaluating submitted portfolio code; one signal among several; always paired with human review.
- **Out of scope:** Sole decision criterion; detecting plagiarism between human authors; repositories not submitted as part of a job application.

---

## Update Policy

Model artifacts are updated by `airflow/dags/resume_scoring_dag.py` (shared pre-screening DAG) on a nightly schedule. Ad-hoc retraining requires a DAG task entry (CLAUDE.md Hard Rule #5). Each artifact is prefixed with an ISO date (`YYYYMMDD_`).

---

## Ethical Considerations

Flagged candidates receive a human-readable explanation (`flag_reason`). No adverse hiring decision should be made on this score alone. Recruiter UI always surfaces confidence level and explanation alongside the flag. The platform framing is **compliance and authenticity monitoring**, not surveillance.
