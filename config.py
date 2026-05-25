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
