"""Shared configuration loaded from environment variables via python-dotenv.

All modules import from here instead of calling os.getenv directly.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

# ── Kafka ─────────────────────────────────────────────────────────────────────
KAFKA_BOOTSTRAP_SERVERS: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC_AUDIO: str = os.getenv("KAFKA_TOPIC_AUDIO", "interview-audio-stream")
KAFKA_TOPIC_TEXT: str = os.getenv("KAFKA_TOPIC_TEXT", "interview-text-stream")

# ── MinIO / S3 ────────────────────────────────────────────────────────────────
MINIO_ENDPOINT: str = os.getenv("MINIO_ENDPOINT", "http://localhost:9000")
MINIO_ACCESS_KEY: str = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY: str = os.getenv("MINIO_SECRET_KEY", "minioadmin")

# ── Delta Lake ────────────────────────────────────────────────────────────────
DELTA_LAKE_PATH: str = os.getenv("DELTA_LAKE_PATH", "/delta")

# ── Whisper STT ───────────────────────────────────────────────────────────────
WHISPER_MODEL_SIZE: str = os.getenv("WHISPER_MODEL_SIZE", "base")
# Max concurrent STT calls per consumer process (bounds CPU at peak).
# 1 = sequential (safest); 2 = default; raise for GPU deployments.
MAX_CONCURRENT_STT: int = int(os.getenv("MAX_CONCURRENT_STT", "2"))

# ── OpenAI (optional cloud Whisper fallback) ──────────────────────────────────
OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY") or None

# ── ML ────────────────────────────────────────────────────────────────────────
VECTOR_STORE_PATH: str = os.getenv("VECTOR_STORE_PATH", "data/vector_store")
SUSPICION_THRESHOLD: float = float(os.getenv("SUSPICION_THRESHOLD", "0.65"))
# Calibrated fusion artifact (ml/fusion.py). Empty = legacy weighted sum.
# Trained on text only so far: audio signals get weight 0 until reviewed sessions
# with audio are available (see evals/ and README "Detection Evaluation").
FUSION_MODEL_PATH: str = os.getenv("FUSION_MODEL_PATH", "")

# ── Text AI-detector (ml/features/binoculars.py) ──────────────────────────────
# Binoculars (Hans et al. 2024): observer = base model, performer = its instruct
# tune; they must share a tokenizer. MIDPOINT/SCALE map the Binoculars score to a
# [0, 1] suspicion (score == MIDPOINT → 0.5); set from the evals/ class medians.
# SmolLM2-135M pair: human median 0.978, AI median 0.778 on evals/ (2026-11-26)
# → midpoint 0.878, scale (0.978 - 0.778) / 4 = 0.05. Re-derive when changing pair
# (python -m evals.compare_binoculars). SmolLM2-360M scores 54.5% vs 49.5% TPR at
# 1% FPR but costs 2.4x CPU; set both IDs to the 360M pair to use it.
BINOCULARS_OBSERVER: str = os.getenv("BINOCULARS_OBSERVER", "HuggingFaceTB/SmolLM2-135M")
BINOCULARS_PERFORMER: str = os.getenv(
    "BINOCULARS_PERFORMER", "HuggingFaceTB/SmolLM2-135M-Instruct"
)
BINOCULARS_MIDPOINT: float = float(os.getenv("BINOCULARS_MIDPOINT", "0.878"))
BINOCULARS_SCALE: float = float(os.getenv("BINOCULARS_SCALE", "0.05"))
# Language-model signal behind the API's "perplexity" slot: binoculars | perplexity
TEXT_DETECTOR: str = os.getenv("TEXT_DETECTOR", "binoculars")
# Anytime-valid early detection across turns (ml/sequential.py). Empty = disabled.
SEQUENTIAL_MODEL_PATH: str = os.getenv("SEQUENTIAL_MODEL_PATH", "")

# ── Local LLM routing (Ollama: Gemma / Qwen) ──────────────────────────────────
# Profile "gemma": generation on Gemma, falling back to Qwen; utility on Qwen.
# Profile "qwen":  every task on Qwen, no fallback (lighter hardware).
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
LLM_PROFILE: str = os.getenv("LLM_PROFILE", "gemma")
LLM_MODEL_GEMMA: str = os.getenv("LLM_MODEL_GEMMA", "gemma4:26b-a4b-it-qat")
LLM_MODEL_QWEN: str = os.getenv("LLM_MODEL_QWEN", "qwen3:4b-instruct-2507-q4_K_M")
LLM_TIMEOUT_S: float = float(os.getenv("LLM_TIMEOUT_S", "300"))
# Nightly DAG: max bank questions answered by the routed LLM per run. 0 disables the task.
LLM_ANSWER_GEN_MAX: int = int(os.getenv("LLM_ANSWER_GEN_MAX", "10"))

# ── FastAPI ───────────────────────────────────────────────────────────────────
FASTAPI_SECRET_KEY: str = os.getenv("FASTAPI_SECRET_KEY", "dev-secret-replace-in-production")
# Comma-separated allowed CORS origins; dev default includes the Vite dev server.
CORS_ALLOWED_ORIGINS: list[str] = [
    o.strip()
    for o in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173").split(",")
    if o.strip()
]

# ── Notifications ─────────────────────────────────────────────────────────────
SLACK_WEBHOOK_URL: str = os.getenv("SLACK_WEBHOOK_URL", "")

# ── Observability / Error tracking ────────────────────────────────────────────
# Set SENTRY_DSN to activate Sentry error reporting in the FastAPI service.
# Leave empty (default) to disable — no external calls are made when unset.
SENTRY_DSN: str | None = os.getenv("SENTRY_DSN") or None

# ── Pre-screening (Sprint 14+) ─────────────────────────────────────────────────
KAFKA_TOPIC_RESUME: str = os.getenv("RESUME_KAFKA_TOPIC", "candidate-resume-stream")
RESUME_MAX_MB: int = int(os.getenv("RESUME_MAX_MB", "10"))

# ── GitHub repository crawling (Sprint 16+) ────────────────────────────────────
GITHUB_API_TOKEN: str | None = os.getenv("GITHUB_API_TOKEN") or None
CODE_LM_MODEL: str = os.getenv("CODE_LM_MODEL", "microsoft/codebert-base")

# ── Pre-screening aggregation (Sprint 18+) ─────────────────────────────────────
KAFKA_TOPIC_PROFILE: str = os.getenv("PROFILE_KAFKA_TOPIC", "candidate-profile-stream")
# Interview TrustScore below this value triggers severity="high" when combined with a
# prescreening flag (CLAUDE.md §8.2 compound-alert rule).
INTERVIEW_HIGH_SUSPICION_THRESHOLD: float = float(
    os.getenv("INTERVIEW_HIGH_SUSPICION_THRESHOLD", "40.0")
)

# ── API hardening (Sprint 20+) ─────────────────────────────────────────────────
# Requests per minute per API key before a 429 is returned. Set 0 to disable.
RATE_LIMIT_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "100"))
# Ad-hoc pre-screening trigger guard — disabled in production per CLAUDE.md §8.5.
# Set ALLOW_ADHOC_TRIGGER=true in staging/QA environments only.
ALLOW_ADHOC_TRIGGER: bool = os.getenv("ALLOW_ADHOC_TRIGGER", "false").lower() == "true"

# ── ATS webhook delivery (Sprint 20+) ─────────────────────────────────────────
# Configure one or both to enable automatic pre-screening report delivery.
ATS_WEBHOOK_GREENHOUSE: str | None = os.getenv("ATS_WEBHOOK_GREENHOUSE") or None
ATS_WEBHOOK_LEVER: str | None = os.getenv("ATS_WEBHOOK_LEVER") or None
