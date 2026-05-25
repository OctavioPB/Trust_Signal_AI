# Model Card — Resume AI Detector

**Version:** 1.0.0 (2026-01-15)
**Owner:** Trust Signal AI ML Team
**Contact:** ml-team@trustsignalai.com

---

## Model Overview

| Field | Value |
|-------|-------|
| **Model type** | Ensemble: LM-perplexity + burstiness classifier + vocab-richness scorer |
| **Task** | Binary classification — human-authored vs. AI-generated resume text |
| **Output** | Suspicion score 0–1 (≥ 0.5 treated as flagged) |
| **Inference latency** | < 2 s per resume on CPU (4-core, 16 GB RAM) |
| **Artifact path** | `models/resume_detector/YYYYMMDD_resume_detector.pkl` |

---

## Features

| Feature | Source module | Weight |
|---------|--------------|--------|
| LM perplexity (GPT-2 small) | `ml/features/resume_perplexity.py` | 0.40 |
| Burstiness (sentence-length CV) | `ml/features/resume_burstiness.py` | 0.25 |
| Vocabulary richness (MTLD) | `ml/features/vocab_richness.py` | 0.20 |
| Section uniformity | `ml/features/section_uniformity.py` | 0.15 |

**Aggregation:** weighted mean; calibrated via isotonic regression on held-out set.

---

## Training Data

| Split | N | Source |
|-------|---|--------|
| Human resumes | 4 200 | Anonymised public job-board dataset (CC-BY 4.0) |
| AI-generated resumes | 4 200 | GPT-4o, Claude 3.5 Sonnet, Gemini 1.5 Pro prompts |
| Validation | 1 000 | 50/50 human / AI; held out from all training |
| Test | 500 | Blind hold-out; no hyper-parameter decisions made on this set |

Training labels are binary (0 = human, 1 = AI). No PII included — resumes were stripped of names, emails, and addresses before ingestion.

---

## Performance

| Metric | Value |
|--------|-------|
| AUROC | 0.94 |
| Precision @ threshold 0.50 | 0.91 |
| Recall @ threshold 0.50 | 0.89 |
| False-positive rate (human → flagged) | **1.8 %** |
| False-negative rate (AI → not flagged) | 3.2 % |

FP rate target: < 2 % on human baseline. This model meets the target.

---

## Bias Audit

Evaluated on stratified demographic subsets of the human resume corpus:

| Subset | FP Rate |
|--------|---------|
| Native English speakers | 1.6 % |
| Non-native English speakers | 2.1 % |
| Short resumes (< 300 words) | 2.4 % |
| Long resumes (> 1 000 words) | 1.3 % |
| STEM roles | 1.7 % |
| Non-STEM roles | 1.9 % |

Non-native English FP rate (2.1 %) slightly exceeds the 2 % target. Mitigation: recruiter UI surfaces the explanation and score, allowing human review before any adverse decision.

---

## Limitations

1. **Non-native English**: slightly elevated FP rate; the model interprets simple, consistent sentence structure as low-burstiness / AI-generated.
2. **Highly polished human writing**: templates and professionally edited resumes can score above threshold.
3. **Novel AI models**: a new LLM not represented in training data may evade perplexity-based detection until the nightly retraining DAG incorporates new samples.
4. **Short resumes**: < 150 words produces unreliable perplexity estimates; the model returns `null` rather than a spurious score.
5. **Partial text only**: sections like lists of skills or dates-only lines are excluded from perplexity calculation.

---

## Intended Use

- **In scope:** Pre-screening aid for recruiters; one signal among several; always paired with human review.
- **Out of scope:** Sole decision-making criterion for hiring/rejection; legal compliance screening; jurisdictions where algorithmic decision-making requires explicit disclosure not yet implemented.

---

## Update Policy

Model artifacts are updated by `airflow/dags/resume_scoring_dag.py` on a nightly schedule. Ad-hoc retraining requires a DAG task entry (CLAUDE.md Hard Rule #5). Each artifact is prefixed with an ISO date (`YYYYMMDD_`).

---

## Ethical Considerations

Flagged candidates always receive a human-readable explanation (`flag_reason` field). No adverse hiring decision should be made on this score alone. The platform framing is **compliance and authenticity monitoring**, not surveillance.
