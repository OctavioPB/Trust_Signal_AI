"""Prometheus metrics definitions for Trust Signal AI.

Wired into FastAPI via prometheus-fastapi-instrumentator (auto HTTP metrics)
plus custom gauges and histograms for ML pipeline observability.

Usage in main.py:
    from api.metrics import instrument_app, PRESCREENING_FLAGS_TOTAL
    instrument_app(app)
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram
from prometheus_fastapi_instrumentator import Instrumentator

# ── Gauges ─────────────────────────────────────────────────────────────────────

resume_scores_p95 = Gauge(
    "resume_scores_p95",
    "Rolling P95 of resume AI suspicion scores (0–1).",
)

repo_scores_p95 = Gauge(
    "repo_scores_p95",
    "Rolling P95 of repo AI suspicion scores (0–1).",
)

prescreening_flags_total = Counter(
    "prescreening_flags_total",
    "Cumulative number of candidates flagged by pre-screening.",
)

# ── Histograms ─────────────────────────────────────────────────────────────────

resume_pipeline_duration_seconds = Histogram(
    "resume_pipeline_duration_seconds",
    "End-to-end latency of the resume analysis pipeline.",
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

repo_pipeline_duration_seconds = Histogram(
    "repo_pipeline_duration_seconds",
    "End-to-end latency of the repository analysis pipeline.",
    buckets=(0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
)


# ── Instrumentator factory ─────────────────────────────────────────────────────

def instrument_app(app: object) -> None:
    """Attach prometheus-fastapi-instrumentator to *app* and expose /metrics."""
    Instrumentator().instrument(app).expose(app)  # type: ignore[arg-type]
