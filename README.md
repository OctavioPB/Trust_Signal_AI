# TrustSignal AI

**Interview authenticity scoring powered by hybrid streaming + batch analytics.**

TrustSignal AI detects AI-assisted interview fraud in real time and delivers a
**TrustScore (0–100)** to recruiters within 60 seconds of call end. Five independent
signal modules analyse the audio and transcript of each interview; a weighted
aggregation engine combines them into a single, explainable score.

> Built by **OPB — Octavio Pérez Bravo · Data & AI Strategy Architect**

---

## Business Case

| KPI | Target |
|-----|--------|
| Time-to-fraud-detection | Within the first 10 minutes of the interview |
| False positive rate | < 2 % (never penalise nervous-but-legitimate candidates) |
| TrustScore delivery | ≤ 60 s after `POST /session/{id}/end` |

---

## Architecture

```
WebRTC / WebSocket audio
          │
          ▼
  Kafka: interview-audio-stream  (24 h retention, 3 partitions)
          │
          ▼  (Python consumer — ThreadPoolExecutor STT)
  OpenAI Whisper STT
          │
          ├──► MinIO raw-audio/  (90-day lifecycle policy)
          │
          ▼
  Kafka: interview-text-stream  (7 d retention, 3 partitions)
          │
          ▼
  Delta Lake  ←── DeltaWriter (ACID upserts)
          │
          └──► ML Signal Pipeline
                  ├── latency.py       Response Latency    (weight 0.30)
                  ├── audio_bg.py      Background Audio    (weight 0.15)
                  ├── perplexity.py    LM Perplexity       (weight 0.20)
                  ├── burstiness.py    Burstiness          (weight 0.20)
                  └── similarity.py   Semantic Similarity  (weight 0.15)
                            │
                            ▼
                    trust_score.py → TrustScore 0–100
                            │
                            ▼
                    FastAPI (port 8000)
                            │
                    ┌───────┴────────┐
                    ▼               ▼
            React Dashboard    Streamlit (legacy)
            (Vite, port 5173)  (port 8501)
```

**Nightly Batch (Airflow DAG):**
Delta Lake → extract suspicious → embed → retrain classifiers → update answer bank → Slack notify

---

## Pre-Screening Architecture

Candidates are evaluated *before* the interview via resume and repository analysis.

```
Recruiter uploads resume / links GitHub repo
          │
          ├──► Kafka: candidate-resume-stream   (resume text + candidate_uuid)
          │              │
          │              ▼  (Airflow DAG: resume_scoring_dag)
          │         Resume AI Detector
          │           ├── LM Perplexity       (weight 0.40)
          │           ├── Burstiness          (weight 0.25)
          │           ├── Vocab Richness      (weight 0.20)
          │           └── Section Uniformity  (weight 0.15)
          │                     │
          │                     ▼  suspicion score 0–1
          │
          └──► Kafka: candidate-repo-stream    (repo contents + candidate_uuid)
                         │
                         ▼  (Airflow DAG: resume_scoring_dag)
                    Repo AI Detector
                      ├── Code-LM Perplexity  (weight 0.35)
                      ├── Commit Consistency  (weight 0.25)
                      ├── Comment Ratio       (weight 0.20)
                      └── Naming Entropy      (weight 0.20)
                                │
                                ▼  suspicion score 0–1
          │
          ▼  (both scores written to Delta Lake: candidate_prescreening)
    Pre-Screening Aggregator
      weighted_score = 0.60 × resume_score + 0.40 × repo_score
      flagged        = weighted_score ≥ PRESCREENING_THRESHOLD (default 0.50)
          │
          ├──► FastAPI  GET /candidates/{id}/report
          │
          └──► ATS Webhook (Greenhouse / Lever)
                  payload: { candidate_uuid, prescreening_score, flags }
                  retry:   3 retries × exponential back-off (10 s / 30 s / 90 s)
                  DLQ:     Delta Lake webhook_dlq on permanent failure
```

**No PII in any Kafka payload or webhook.** Only `candidate_uuid` travels through the pipeline; names and emails remain in the recruiter database only.

---

## Signal Modules

| Module | What it measures | High suspicion indicator |
|--------|-----------------|--------------------------|
| **Response Latency** | CV of inter-turn latency | CV < 0.15 (constant ≈ LLM + TTS delay) |
| **Background Audio** | MFCC-based keyboard detection | Keyboard detected during silence windows |
| **Perplexity** | LM perplexity of transcript | ppl < 30 (too predictable — AI-generated) |
| **Burstiness** | Sentence-length CV | CV < 0.20 (homogeneous — AI-generated) |
| **Semantic Similarity** | Max cosine vs. LLM answer bank | similarity > 0.65 |

TrustScore formula:

```
suspicion_index = Σ (signal_score_i × weight_i)   ∈ [0, 1]
TrustScore      = (1 − suspicion_index) × 100      ∈ [0, 100]
flagged         = suspicion_index ≥ 0.65
```

---

## Nightly Retraining DAG

`airflow/dags/retraining_dag.py` — scheduled daily at **02:00 UTC**.

### Task Dependency Graph

```
  ┌─────────────────────┐
  │  extract_suspicious  │  Query Delta Lake for suspicious_flag=true
  │  (DuckDB scan)       │  segments from the past 24 h
  └──────────┬──────────┘
             │
             ▼
  ┌──────────────────────┐
  │  compute_embeddings  │  Batch-embed CANDIDATE texts with
  │  (sentence-xformers) │  all-MiniLM-L6-v2; update vector store
  └──────────┬───────────┘
             │
             ▼
  ┌───────────────────────────┐        ┌──────────────────────┐
  │  retrain_bg_classifier    │──────► │  update_answer_bank  │
  │  (RandomForest + MFCC)    │        │  (append JSONL pairs) │
  │  → YYYYMMDD_bg_clf.pkl   │        └──────────┬───────────┘
  └──────────────┬────────────┘                   │
                 │                                │
                 └──────────────┬─────────────────┘
                                ▼
                       ┌──────────────┐
                       │    notify    │  Slack Block Kit summary:
                       │  (requests)  │  segments, embeddings, classifier,
                       └──────────────┘  answer bank pairs
```

### Task Details

| Task | Description |
|------|-------------|
| `extract_suspicious` | DuckDB `parquet_scan()` over `transcript_segments/**/*.parquet`; filters `suspicious_flag = true` in the 24 h window |
| `compute_embeddings` | Embeds CANDIDATE segment texts; appends to `VECTOR_STORE_PATH/{embeddings.npy, metadata.json}` |
| `retrain_bg_classifier` | Downloads suspicious-session audio from MinIO; extracts MFCC features; retrains `BackgroundAudioClassifier` if ≥ 10 new samples; uploads `YYYYMMDD_bg_classifier.pkl` to `model-artifacts/` |
| `update_answer_bank` | Extracts RECRUITER→CANDIDATE Q&A pairs; deduplicates; appends to `data/llm_answer_bank.jsonl` |
| `notify` | Sends Slack Block Kit payload to `SLACK_WEBHOOK_URL`; falls back to structured log if env var not set |

All tasks inherit `retries=2`, `retry_delay=timedelta(minutes=5)` from `DEFAULT_ARGS`.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Message broker | Apache Kafka (3 partitions, consumer-group horizontal scaling) |
| Object storage | MinIO (local) / AWS S3 (prod) |
| Table format | Delta Lake (PySpark + delta-spark) |
| Orchestration | Apache Airflow (`@daily` DAG) |
| STT | OpenAI Whisper (local, ThreadPoolExecutor) / Cloud Whisper fallback |
| Embeddings | Sentence-Transformers `all-MiniLM-L6-v2` |
| Audio classification | LibROSA (MFCC) + scikit-learn RandomForest |
| NLP scoring | HuggingFace `distilgpt2` (perplexity) |
| API | FastAPI + JWT HS256 + Pydantic + CORSMiddleware |
| React dashboard | React 18 + TypeScript 5.4 + Vite 5 + Zustand 4 |
| Legacy dashboard | Streamlit + Plotly (retained for reference) |
| Ad-hoc queries | DuckDB `parquet_scan()` over Delta tables |
| Observability | structlog (JSON) — no PII in logs; optional Sentry integration |

---

## Repository Structure

```
trustsignal/
├── api/main.py                  FastAPI endpoints (auth, session, signals, score, report, PDF)
├── airflow/
│   ├── dags/retraining_dag.py  Nightly retraining DAG (5 tasks)
│   └── sensors/
│       └── kafka_lag_sensor.py  Waits for Kafka consumer lag = 0
├── frontend/                    React 18 + TypeScript 5.4 + Vite 5 dashboard
│   ├── src/
│   │   ├── App.tsx              Nav + switch/case page routing (no router library)
│   │   ├── types.ts             TypeScript interfaces matching FastAPI Pydantic models
│   │   ├── services/api.ts      Typed fetch wrapper (9 functions, ApiError class)
│   │   ├── stores/
│   │   │   ├── demoStore.ts     Zustand: synthetic flagged-session payload
│   │   │   └── themeStore.ts    Zustand: light/dark toggle + localStorage persist
│   │   └── styles/tokens.css    CSS custom properties from BRAND.md
│   ├── index.html               Google Fonts (Fraunces + Plus Jakarta Sans)
│   └── vite.config.ts           /api proxy → http://localhost:8000
├── dashboard/
│   ├── legacy/app.py            Streamlit recruiter dashboard (legacy — Sprint 8)
│   ├── api_client.py            HTTP client for FastAPI
│   └── pdf_export.py            PDF report generation (fpdf2)
├── ingestion/
│   ├── producer.py              WebRTC/WS → Kafka
│   └── consumer.py              Kafka → STT (ThreadPoolExecutor) → interview-text-stream
├── ml/
│   ├── features/
│   │   ├── latency.py           Response latency CV scorer
│   │   ├── audio_bg.py          MFCC + RandomForest keyboard detector
│   │   ├── perplexity.py        distilgpt2 perplexity scorer
│   │   └── burstiness.py        Sentence-length CV scorer
│   ├── embeddings/
│   │   └── similarity.py        Cosine similarity vs. LLM answer bank
│   └── trust_score.py           Weighted aggregation → TrustScore
├── storage/
│   ├── delta_writer.py          PySpark + delta-spark ACID upserts
│   ├── object_store.py          MinIO audio + artifact persistence + GDPR deletion
│   └── lifecycle.py             MinIO 90-day lifecycle policy
├── transcription/
│   └── whisper_service.py       Whisper STT wrapper
├── data/
│   └── llm_answer_bank.jsonl    59+ canonical AI interview answer Q&A pairs
├── docs/
│   └── DPA_TEMPLATE.md          GDPR Data Processing Agreement template
├── research/notebooks/
│   ├── audio_bg_eda.ipynb       MFCC feature EDA + classifier training
│   └── nlp_signals_eda.ipynb    Perplexity + burstiness + similarity EDA
├── scripts/
│   ├── smoke_test.sh            Service health checks
│   ├── pii_audit.py             Scans source + logs for PII variable names
│   └── query_delta.py           DuckDB CLI for Delta Lake ad-hoc queries
├── tests/
│   ├── unit/                    Isolated tests; no I/O; models mocked
│   └── integration/             Full-stack tests (load, lifecycle, GDPR)
├── config.py                    Centralised env-var loading (python-dotenv)
├── docker-compose.yml           Kafka, MinIO, Airflow, Spark local stack
└── planning/

```

---

## How to Run Locally

### Prerequisites

- Docker & Docker Compose
- Python 3.11+
- Node.js 18+ and npm

### 1. Start the infrastructure stack

```bash
docker-compose up -d
```

| Service | Local port |
|---------|-----------|
| Kafka broker | 9095 |
| MinIO API | 9200 |
| MinIO console | 9201 |
| Airflow webserver | 8083 |
| Spark master UI | 8090 |

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
# Optional: PDF export and Streamlit dashboard
pip install fpdf2 streamlit plotly
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env — set FASTAPI_SECRET_KEY at minimum; defaults work for local dev
```

### 4. Run the API

```bash
uvicorn api.main:app --reload --port 8000
```

API docs: `http://localhost:8000/docs`

### 5. Run the React dashboard (primary UI)

```bash
cd frontend
npm install       # first time only — installs React, Vite, Zustand, Vitest, Playwright
npm run dev       # starts Vite dev server
```

Open **http://localhost:5173**

- Click **Load Demo** in the left sidebar to explore a synthetic flagged session (TrustScore 31.5, suspicion 0.685) — no API needed.
- To connect to a live session: enter a Recruiter ID → click **Load Session** → enter a Session ID.

> **Vite proxy:** all `/api/*` requests are forwarded to `http://localhost:8000` automatically. No manual CORS configuration is required during development.

#### Frontend scripts

| Command | What it does |
|---------|-------------|
| `npm run dev` | Vite HMR dev server on port 5173 |
| `npm run build` | Production build → `frontend/dist/` |
| `npm run preview` | Preview production build locally |
| `npm run lint` | ESLint (TypeScript strict) |
| `npm test` | Vitest unit tests (fetch mocked) |
| `npx playwright test` | Playwright e2e smoke tests (requires dev server) |

#### Playwright setup (first time)

```bash
cd frontend
npx playwright install chromium   # downloads Chromium browser
npx playwright test               # runs e2e/demo.spec.ts
```

### 6. Run the legacy Streamlit dashboard (optional)

```bash
streamlit run dashboard/legacy/app.py
```

Open `http://localhost:8501` → click **Load Demo Data**.

> The Streamlit dashboard is retained for reference only. The React app (`frontend/`) is the primary UI for all new work.

### 7. Run tests

```bash
pytest tests/unit/ -v
pytest tests/integration/ -v   # requires Docker stack
```

### 8. Trigger a manual DAG run (dev only)

```bash
airflow dags trigger trustsignal_nightly_retraining
```

> **CLAUDE.md §8**: ML model updates must run via the DAG — never ad-hoc in production.

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Liveness probe |
| `POST` | `/auth/token` | Issue JWT bearer token |
| `POST` | `/session/start` | Register new interview session |
| `POST` | `/session/{id}/signals` | Submit signal scores (ML pipeline) |
| `GET` | `/session/{id}/score` | Current TrustScore + signal breakdown |
| `GET` | `/session/{id}/report` | Full JSON report with per-turn analysis |
| `GET` | `/session/{id}/report/pdf` | Download PDF report |
| `POST` | `/session/{id}/end` | Close session and lock final score |
| `DELETE` | `/session/{id}` | GDPR erasure (Article 17) |

All session endpoints require `Authorization: Bearer <token>`.
Interactive docs: `http://localhost:8000/docs`

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9095` | Kafka broker address |
| `KAFKA_TOPIC_AUDIO` | `interview-audio-stream` | Raw audio topic |
| `KAFKA_TOPIC_TEXT` | `interview-text-stream` | Transcript topic |
| `MINIO_ENDPOINT` | `http://localhost:9200` | MinIO endpoint |
| `MINIO_ACCESS_KEY` | `minioadmin` | MinIO access key |
| `MINIO_SECRET_KEY` | `minioadmin` | MinIO secret key |
| `DELTA_LAKE_PATH` | `/delta` | Delta Lake base path |
| `WHISPER_MODEL_SIZE` | `base` | Whisper model size (`tiny`/`base`/`small`/`medium`/`large`) |
| `MAX_CONCURRENT_STT` | `2` | Max parallel Whisper calls per consumer process |
| `OPENAI_API_KEY` | _(empty)_ | Optional cloud Whisper fallback |
| `VECTOR_STORE_PATH` | `data/vector_store` | Embedding store path |
| `FASTAPI_SECRET_KEY` | `dev-secret-replace-in-production` | JWT signing key (`openssl rand -hex 32` for prod) |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:5173` | Comma-separated CORS origins |
| `SUSPICION_THRESHOLD` | `0.65` | Flag threshold (suspicion_index ≥ this) |
| `FALSE_POSITIVE_TARGET` | `0.02` | Target FP rate (2 %) |
| `SLACK_WEBHOOK_URL` | _(empty)_ | Slack Incoming Webhook for DAG notify |
| `SENTRY_DSN` | _(empty)_ | Sentry DSN for FastAPI error reporting |
| `AIRFLOW_HOME` | `/opt/airflow` | Airflow home directory |

---

## Key Design Decisions

1. **Append-only Kafka topics** — Interview data is never modified in the stream; corrections go to Delta Lake only.
2. **90-day MinIO lifecycle** — Audio is deleted automatically after 90 days (GDPR Article 17). Implemented in `storage/lifecycle.py`.
3. **UUID-only logging** — No PII (`candidate_name`, `email`) ever appears in logs or Kafka payloads. All identifiers are UUIDs.
4. **False positive guard** — Any flagged candidate receives a mandatory human-readable explanation (`flag_reason`). Silent suppression is prohibited (CLAUDE.md §8).
5. **Lazy infrastructure imports** — `minio` and `fpdf2` are imported at call-site, not module level; the API and dashboard start without those packages installed.
6. **DAG-gated model updates** — The `CLAUDE.md` hard rule: classifier retraining only runs via `trustsignal_nightly_retraining`; no ad-hoc triggers in production.
7. **React over Streamlit** — The primary dashboard is a React 18 + TypeScript 5.4 SPA (Sprint 11–13); Streamlit is retained under `dashboard/legacy/` for reference only and receives no new feature work.

---

*TrustSignal AI — OPB · Octavio Pérez Bravo · Data & AI Strategy Architect*
