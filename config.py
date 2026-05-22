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
FALSE_POSITIVE_TARGET: float = float(os.getenv("FALSE_POSITIVE_TARGET", "0.02"))

# ── FastAPI ───────────────────────────────────────────────────────────────────
FASTAPI_SECRET_KEY: str = os.getenv("FASTAPI_SECRET_KEY", "dev-secret-replace-in-production")

# ── Airflow ───────────────────────────────────────────────────────────────────
AIRFLOW_HOME: str = os.getenv("AIRFLOW_HOME", "/opt/airflow")

# ── Notifications ─────────────────────────────────────────────────────────────
SLACK_WEBHOOK_URL: str = os.getenv("SLACK_WEBHOOK_URL", "")

# ── Observability / Error tracking ────────────────────────────────────────────
# Set SENTRY_DSN to activate Sentry error reporting in the FastAPI service.
# Leave empty (default) to disable — no external calls are made when unset.
SENTRY_DSN: str | None = os.getenv("SENTRY_DSN") or None
