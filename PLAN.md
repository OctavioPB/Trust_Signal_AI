# PLAN.md — TrustSignal AI · Sprint Roadmap

> Authoritative sprint tracker. Update task checkboxes as work completes.
> Hard rules from `planning/CLAUDE.md §8` apply to every sprint without exception.

---

## Sprints 1–13 — Interview Analysis Platform ✅ Complete

| Sprint | Deliverable |
|--------|-------------|
| S1  | Repo scaffold, Docker Compose (Kafka, MinIO, Airflow), `logging_setup.py` |
| S2  | `ingestion/producer.py` — WebRTC/WS → `interview-audio-stream` |
| S3  | `transcription/whisper_service.py` + `ingestion/text_publisher.py` |
| S4  | `storage/lifecycle.py` (MinIO 90-day policy) + `storage/delta_writer.py` |
| S5  | `ml/features/latency.py` — response-latency extractor |
| S6  | `ml/features/burstiness.py` + `ml/features/perplexity.py` |
| S7  | `ml/features/audio_bg.py` — keyboard-detection classifier |
| S8  | `ml/embeddings/similarity.py` — cosine similarity vs. LLM answer bank |
| S9  | `ml/trust_score.py` — weighted aggregate → TrustScore 0–100 |
| S10 | `api/main.py` — FastAPI: ingest, score, report endpoints + JWT auth |
| S11 | `airflow/dags/retraining_dag.py` — nightly retrain (retries=2) |
| S12 | Frontend: React 19 + Vite — Sessions, Analytics, Models, Settings pages |
| S13 | Frontend: Info page (Instructions / Business / Engineering tabs) + TopBar UserChip |

---

## New Scope — AI Usage Detection in Resumes & Repositories

The platform expands from real-time interview monitoring into **pre-screening**.
Before a recruiter schedules an interview, TrustSignal AI ingests the candidate's
resume and public GitHub repositories and scores them for AI-generation signals.
The resulting **Pre-Screening Score** combines with the eventual **Interview TrustScore**
into a unified **Candidate Authenticity Profile**.

### Framing discipline (CLAUDE.md §8.3)
This module is a *skills authenticity verification* tool. All API responses, copy,
and documentation must reflect that framing. It is not surveillance.

### New data topology

| Kafka Topic | Append-only | Key | Value |
|-------------|-------------|-----|-------|
| `candidate-resume-stream` | ✅ | `candidate_uuid` | UTF-8 text chunk (no PII) |
| `candidate-repo-stream`   | ✅ | `repo_uuid`      | code chunk + language tag |
| `candidate-profile-stream`| ✅ | `candidate_uuid` | aggregated signal event |

### New environment variables

| Variable | Description | Default |
|----------|-------------|---------|
| `RESUME_KAFKA_TOPIC` | Resume text topic | `candidate-resume-stream` |
| `REPO_KAFKA_TOPIC` | Code chunk topic | `candidate-repo-stream` |
| `PROFILE_KAFKA_TOPIC` | Signal event topic | `candidate-profile-stream` |
| `GITHUB_API_TOKEN` | GitHub REST API token (OAuth) | — |
| `GITHUB_RATE_LIMIT_PER_HOUR` | Max API calls/hr | `5000` |
| `RESUME_MAX_MB` | Max resume upload size | `10` |
| `PRESCREENING_THRESHOLD` | Flag threshold (0–1) | `0.65` |
| `CODE_LM_MODEL` | Code perplexity LM | `microsoft/codebert-base` |

---

## Sprint 14 — Candidate Profile & Document Ingestion

**Goal:** Establish the candidate profile entity, resume upload pipeline, and GitHub repo linking.

### Backend
- [x] `storage/candidate_store.py` — DeltaLake schema: `candidate_uuid`, `status` (`pending` | `screened` | `flagged`), `created_at`, `resume_path`, `repo_urls[]`
- [x] `FastAPI POST /candidates` — create profile; returns `{ candidate_uuid }` only (no PII in response)
- [x] `FastAPI POST /candidates/{id}/resume` — multipart upload (PDF, DOCX, TXT); validate MIME + size ≤ `RESUME_MAX_MB`
  - Store to MinIO: `resumes/{candidate_uuid}/{iso_timestamp}.{ext}`
  - Publish text-extraction job to `candidate-resume-stream`
- [x] `FastAPI POST /candidates/{id}/repos` — accept `{ repo_url: string }`; validate GitHub URL format
- [x] `storage/lifecycle.py` update — extend 90-day MinIO lifecycle to `resumes/` bucket (CLAUDE.md §8.7)
- [x] `ingestion/resume_producer.py` — Kafka producer for `candidate-resume-stream`; UUID key; no PII in payload

### Tests
- [x] `tests/unit/test_resume_upload.py` — happy path, oversized file rejection, bad MIME rejection
- [x] `tests/unit/test_lifecycle_resume.py` — verify 90-day policy applied to resumes bucket
- [x] `tests/integration/test_candidate_api.py` — create → upload → verify DeltaLake row

---

## Sprint 15 — Resume Text Extraction & AI Detection Pipeline

**Goal:** Parse resume documents and compute AI-generation signal scores per section.

### Extraction
- [x] `ingestion/resume_parser.py`
  - PDF: `PyMuPDF` (fitz)
  - DOCX: `python-docx`
  - Plain text: UTF-8 passthrough
  - Section splitter: heuristic regex for Summary / Experience / Skills / Education headings
  - Strip candidate name, email, phone before any log output (CLAUDE.md §8.6 — no PII in logs)

### ML signals
- [x] `ml/features/resume_perplexity.py` — GPT-2 perplexity per section; reuse `perplexity.py` interface
- [x] `ml/features/resume_burstiness.py` — sentence-length variance per section; reuse `burstiness.py`
- [x] `ml/features/vocab_richness.py` — type-token ratio + hapax ratio; low TTR → AI signal
- [x] `ml/features/section_uniformity.py` — cross-section style variance via embedding cosine distance; uniform style → AI signal

### Aggregation
- [x] `ml/resume_score.py` — weighted aggregate → `ResumeAIScore` (0–100, higher = more suspicious)
  - Default weights: perplexity 30%, burstiness 25%, vocab_richness 25%, section_uniformity 20%
  - Write result to DeltaLake `resume_scores` table (versioned: `YYYYMMDD_resume_model.pkl`)
- [x] Alert payload: if `ResumeAIScore ≥ PRESCREENING_THRESHOLD` → attach human-readable explanation per signal (CLAUDE.md §8.2)

### Orchestration
- [x] `airflow/dags/resume_scoring_dag.py` — nightly batch; `retries=2`, `retry_delay=timedelta(minutes=5)`; DAG-gated — no ad-hoc triggers in production (CLAUDE.md §8.5)

### Tests
- [x] `tests/unit/test_resume_parser.py` — section splitting, PII strip
- [x] `tests/unit/test_vocab_richness.py` — fixture: low-TTR AI paragraph vs. high-TTR human paragraph
- [x] `tests/unit/test_section_uniformity.py` — fixture: uniform AI sections vs. varied human sections
- [x] `tests/unit/test_resume_score.py` — fixture regression: AI resume scores ≥ 65, human resume ≤ 35

---

## Sprint 16 — GitHub Repository Crawling

**Goal:** Crawl public repos via GitHub REST API and stage code artifacts for ML scoring.

### Crawler
- [x] `ingestion/github_crawler.py`
  - Auth: `Authorization: Bearer {GITHUB_API_TOKEN}` (token from env; never hardcoded)
  - Fetch: repo metadata, commit history (last 12 months), file tree
  - Filter: source extensions `.py .js .ts .tsx .go .java .rb .rs .cpp .md`
  - Limits: max 500 files/repo, max 10 MB/file; truncate silently, log warning
  - Rate limiting: respect `X-RateLimit-Remaining`; exponential back-off on 429/403
  - UUID assignment: `repo_uuid = uuid5(NAMESPACE_URL, repo_url)` — deterministic, no PII
- [x] `ingestion/commit_analyzer.py`
  - Metrics per repo: commit velocity (commits/week), message length entropy, diff size distribution
  - No author names in output — author_uuid only (CLAUDE.md §8.6)
- [x] `ingestion/repo_producer.py` — Kafka producer for `candidate-repo-stream`; chunk by file; `repo_uuid` key
- [x] DeltaLake `repo_artifacts` table: `repo_uuid`, `file_path`, `language`, `content_hash`, `commit_count`, `crawled_at`

### Tests
- [x] `tests/unit/test_github_crawler.py` — mock `httpx` responses; rate-limit back-off; oversized file skip
- [x] `tests/unit/test_commit_analyzer.py` — fixture: high-entropy human commits vs. low-entropy uniform AI commits
- [x] `tests/integration/test_repo_ingestion.py` — mock API → Kafka → DeltaLake round-trip

---

## Sprint 17 — Code AI Detection ML Pipeline ✅ Complete

**Goal:** Score code files and commit patterns for AI-generation signals.

### ML signals
- [x] `ml/features/code_perplexity.py`
  - Model: `CODE_LM_MODEL` (default: `microsoft/codebert-base`)
  - Score per file; average across repo weighted by file size
  - Low perplexity = predictable = AI signal
- [x] `ml/features/commit_pattern.py`
  - Message uniformity: Shannon entropy of commit message character lengths
  - Velocity burst: detect repos with >80% of commits in a single week (copy-paste signal)
  - Line-length entropy: low-entropy line lengths → AI-like → suspicion signal
- [x] `ml/features/code_style.py`
  - Comment density ratio: lines with comments / total lines
  - Naming uniformity: average Levenshtein distance between identifier names in a file (AI: high uniformity)
  - Boilerplate ratio: proportion of lines matching common AI-generated scaffolding patterns

### Aggregation
- [x] `ml/repo_score.py` — weighted aggregate → `RepoAIScore` (0–100)
  - Default weights: code_perplexity 35%, commit_pattern 35%, code_style 30%
  - Alert payload on threshold breach: human-readable per-signal explanation (CLAUDE.md §8.2)

### Orchestration
- [x] `airflow/dags/repo_scoring_dag.py` — nightly 04:00 UTC; `retries=2`; DAG-gated

### Tests (112/112 passing)
- [x] `tests/unit/test_code_perplexity.py` — 27 tests; injected tokenizer/model stubs
- [x] `tests/unit/test_commit_pattern.py` — 23 tests; burst detection, line entropy, PII invariant
- [x] `tests/unit/test_code_style.py` — 30 tests; Levenshtein, comment density, boilerplate
- [x] `tests/unit/test_repo_score.py` — 32 tests; AI repo ≥ 65, human repo ≤ 35, §8.2 invariant

---

## Sprint 18 — Cross-Signal Correlation & Unified Pre-Screening Score

**Goal:** Fuse resume + repo signals into a Candidate Authenticity Profile; optionally incorporate the interview TrustScore when available.

### Aggregation
- [ ] `ml/prescreening_score.py`
  - Weighted composite:
    - `ResumeAIScore`: 35%
    - `RepoAIScore`: 35%
    - `InterviewTrustScore` (inverted — lower trust = higher suspicion): 30%
  - Graceful fallback: if interview not yet complete, re-weight to 50/50 resume/repo
  - Output: `PreScreeningScore` (0–100, higher = more suspicious)

### Cross-signal consistency
- [ ] `ml/cross_correlation.py`
  - Skill vocabulary coherence: embed skills section of resume + repo README; cosine similarity (high = consistent; low = gap between claimed and demonstrated)
  - Writing style bridge: resume prose vs. interview transcript — burstiness + perplexity delta (large delta → inconsistency signal)

### Output
- [ ] DeltaLake `candidate_prescreening` table: `candidate_uuid`, `resume_score`, `repo_score`, `interview_score`, `prescreening_score`, `flags[]`, `scored_at`
- [ ] Compound alert: if `prescreening_score ≥ threshold` AND `interview_trust_score < 40` → `severity: high` flag with stacked explanation (one sentence per contributing signal)
- [ ] Publish to `candidate-profile-stream`

### Tests
- [ ] `tests/unit/test_prescreening_score.py` — weight arithmetic, fallback when interview absent
- [ ] `tests/unit/test_cross_correlation.py` — fixture: coherent candidate vs. inconsistent candidate
- [ ] `tests/integration/test_full_prescreening.py` — synthetic fixture: PDF resume + mock repo → final score

---

## Sprint 19 — Frontend: Candidates Page

**Goal:** New UI page for the pre-screening workflow, integrated into the existing nav and routing.

### Routing
- [ ] `TopBar.tsx` — add `"candidates"` to `TopBarPage` union; add `{ key: "candidates", label: "Candidates" }` to `LINKS` (insert before "Info")
- [ ] `App.tsx` — import `CandidatesPage`; add `{page === "candidates" && <CandidatesPage />}`

### Store
- [ ] `frontend/src/stores/candidatesStore.ts` — Zustand:
  - State: `candidates[]`, `selectedId`, `loadingUpload`, `loadingScreen`
  - Actions: `fetchCandidates`, `selectCandidate`, `uploadResume`, `linkRepo`, `runPreScreen`

### Page: `frontend/src/pages/CandidatesPage.tsx`
- [ ] Hero section — title "Candidate *Pre-Screening*", subtitle, tab bar (All / Pending / Flagged filter)
- [ ] KPI row — Total Candidates · Screened · Flagged · Avg Score
- [ ] 2-column layout (260px list + 1fr detail panel):
  - **Left — Candidate list**
    - Card per candidate: anonymous label (Candidate #UUID-short), status chip, pre-screening score badge
    - Status chips: `pending` (navy), `screened` (verde), `flagged` (rojo)
    - Click → select + load detail
  - **Right — Candidate detail**
    - Three mini gauges: Resume AI Score · Repo AI Score · Pre-Screening Score
    - Signal breakdown: horizontal bars per sub-signal (same pattern as SignalBreakdownChart)
    - **Resume upload zone**: dashed border, "Drop PDF/DOCX here or click to browse"; shows filename on upload; POST to `/candidates/{id}/resume`
    - **Repo linker**: text input (GitHub URL) + "Link Repo" ghost button; POST to `/candidates/{id}/repos`; list of linked repos below
    - **"Run Pre-Screen" CTA** — primary button; POST to `/candidates/{id}/trigger` (dev-only guard; shows disabled state in production with tooltip)
    - **Alert callout** (if flagged): gold left-border card listing each flag with human-readable explanation
    - **Empty state** (no candidate selected): centered prompt with "Select a candidate or add a new one"
- [ ] Add candidate: "+" FAB or header button → modal with name label (display only) + resume upload + repo URL

### Info page updates
- [ ] `InfoPage.tsx` — Engineering tab:
  - Update `KAFKA_TOPICS` table: add `candidate-resume-stream`, `candidate-repo-stream`, `candidate-profile-stream`
  - Update `ML_MODELS` table: add Resume Detector, Repo Detector, Pre-Screening Aggregator, Cross-Correlator
  - Update `ArchDiagram`: add Resume Parser and Repo Crawler boxes; connect to Kafka and ML pipeline
- [ ] `InfoPage.tsx` — Business tab: add "Pre-Screening" to pain points and value proposition
- [ ] `InfoPage.tsx` — Instructions tab: add pre-screening workflow as Step 0 (before interview)

### TypeScript
- [ ] `npx tsc --noEmit` — zero errors

---

## Sprint 20 — API Hardening & ATS Integration

**Goal:** Production-grade REST surface, ATS webhook delivery, and rate limiting.

### API
- [ ] `FastAPI GET /candidates` — paginated (`limit`, `offset`); response: UUID + status + scores only; no PII
- [ ] `FastAPI GET /candidates/{id}` — full signal detail; UUID only
- [ ] `FastAPI GET /candidates/{id}/report` — JSON pre-screening report with all flags + explanations
- [ ] `FastAPI POST /candidates/{id}/trigger` — on-demand screening; guarded by `ALLOW_ADHOC_TRIGGER=true` env flag (off in production per CLAUDE.md §8.5)
- [ ] `api/rate_limiter.py` — `slowapi` middleware: 100 req/min per API key; 429 with `Retry-After` header

### ATS Webhooks
- [ ] `api/webhooks.py` — deliver pre-screening report to configured ATS endpoints (Greenhouse, Lever)
  - Payload: `{ candidate_uuid, prescreening_score, flags: [{ signal, explanation, score }] }` — no PII
  - Retry: 3 attempts, exponential back-off (10s, 30s, 90s)
  - Dead-letter: failed deliveries → DeltaLake `webhook_dlq` table
  - Extend `SettingsPage.tsx` ATS integrations UI: add "Pre-screening webhook URL" field per ATS

### Tests
- [ ] `tests/unit/test_rate_limiter.py` — burst rejection at 101st request
- [ ] `tests/integration/test_webhooks.py` — mock ATS server; verify payload structure, retry behaviour, DLQ write

---

## Sprint 21 — Observability, Bias Audit & Documentation

**Goal:** Production hardening, bias mitigation, full documentation update.

### Observability
- [ ] `logging_setup.py` update — structlog context fields: `module` (`resume|repo|interview`), `candidate_uuid`, `signal_name`; never log PII
- [ ] `api/metrics.py` — `prometheus-fastapi-instrumentator` on `/metrics`:
  - Gauges: `resume_scores_p95`, `repo_scores_p95`, `prescreening_flags_total`
  - Histograms: pipeline latency per module (`resume_pipeline_duration_seconds`, `repo_pipeline_duration_seconds`)

### Bias Audit
- [ ] `research/notebooks/bias_audit.ipynb`
  - Fixture set: diverse writing styles, non-native English samples, multiple coding styles
  - Assert: AI detection score is not correlated with stylistic diversity or language background
  - Document: per-signal FP rate on human baseline; target < 2% (CLAUDE.md §Core KPIs)
  - Flag any signal with FP > 2% for re-weighting before production release

### Model cards
- [ ] `research/model_cards/resume_detector.md` — model, features, training data, FP rate, limitations
- [ ] `research/model_cards/repo_detector.md` — same structure

### Documentation
- [ ] `planning/CLAUDE.md` — env vars table: add `GITHUB_API_TOKEN`, `RESUME_KAFKA_TOPIC`, `REPO_KAFKA_TOPIC`, `PROFILE_KAFKA_TOPIC`, `PRESCREENING_THRESHOLD`, `CODE_LM_MODEL`, `ALLOW_ADHOC_TRIGGER`
- [ ] `InfoPage.tsx` — sync all three tabs with final architecture after S19 updates are verified
- [ ] README update: add Pre-Screening Architecture section with data flow summary

---

## Dependency Map

```
S14 ─────────────────────► S15 ─────► S18 ─► S19
  └──────────────► S16 ─► S17 ─────► S18
                                            └──► S20 ─► S21
```

S18 (correlation) depends on S15 + S17. S19 (frontend) depends on S18 for the full signal model but
can be stubbed with mock scores from S14 onwards. S20 (API hardening) depends on all backend sprints.
S21 (observability + docs) runs after all other sprints are stable.

---

## Hard Rules (all sprints — CLAUDE.md §8)

| # | Rule | Enforcement |
|---|------|-------------|
| 1 | No PII in logs | UUID only in all log lines and Kafka payloads |
| 2 | No silent FP suppression | Every flag carries a human-readable explanation |
| 3 | Framing discipline | "Authenticity verification", not surveillance |
| 4 | Kafka append-only | No delete/update on any topic |
| 5 | DAG-gated ML updates | No ad-hoc model triggers in production |
| 6 | No secrets in code | All tokens/keys via `.env` + `python-dotenv` |
| 7 | 90-day data retention | Resume files lifecycle-managed in MinIO |
| 8 | UI decisions in BRAND.md | No design tokens in Python/YAML |
