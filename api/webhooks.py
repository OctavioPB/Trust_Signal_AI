"""ATS webhook delivery for pre-screening reports — Sprint 20.

Delivers a pre-screening result to every configured ATS endpoint. Supported
platforms: Greenhouse (ATS_WEBHOOK_GREENHOUSE), Lever (ATS_WEBHOOK_LEVER).

Retry strategy: up to _MAX_RETRIES retry attempts after the initial call,
with exponential back-off (10 s → 30 s → 90 s).  Permanently failed
deliveries are written to the ``webhook_dlq`` Delta Lake table.

Payload schema (no PII — CLAUDE.md Hard Rule #1):
    {
        "candidate_uuid":      str,   # UUID — no names or emails
        "prescreening_score":  float | None,
        "flags": [
            {"signal": str, "explanation": str, "score": float}
        ],
        "delivered_at": float          # Unix timestamp
    }
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx
import structlog

import config

logger = structlog.get_logger(__name__)

TABLE_WEBHOOK_DLQ = "webhook_dlq"

_MAX_RETRIES: int = 3
_BACKOFF_SECONDS: tuple[int, ...] = (10, 30, 90)


# ── Payload ────────────────────────────────────────────────────────────────────

@dataclass
class WebhookFlag:
    signal: str
    explanation: str
    score: float


@dataclass
class WebhookPayload:
    """Immutable pre-screening report payload. Contains no PII."""

    candidate_uuid: str
    prescreening_score: float | None
    flags: list[WebhookFlag]
    delivered_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_uuid":     self.candidate_uuid,
            "prescreening_score": self.prescreening_score,
            "flags": [
                {
                    "signal":      f.signal,
                    "explanation": f.explanation,
                    "score":       f.score,
                }
                for f in self.flags
            ],
            "delivered_at": self.delivered_at,
        }


# ── Delivery ───────────────────────────────────────────────────────────────────

class WebhookDelivery:
    """Delivers a WebhookPayload to a single ATS endpoint with retry and DLQ.

    Args:
        ats_name:         Logical ATS name (e.g. ``"greenhouse"``).
        webhook_url:      Destination endpoint URL.
        delta_lake_path:  Base path for Delta Lake tables.
        _http_client:     Injected ``httpx.Client`` (tests only).
        _spark:           Injected ``SparkSession`` (tests only).
        _sleep_fn:        Injected sleep callable (tests only; default ``time.sleep``).
    """

    def __init__(
        self,
        ats_name: str,
        webhook_url: str,
        delta_lake_path: str,
        _http_client: httpx.Client | None = None,
        _spark: Any = None,
        _sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        self._ats_name        = ats_name
        self._webhook_url     = webhook_url
        self._delta_lake_path = delta_lake_path
        self._http_client     = _http_client
        self._spark           = _spark
        self._sleep           = _sleep_fn if _sleep_fn is not None else time.sleep
        self._log             = logger.bind(component="WebhookDelivery", ats=ats_name)

    def _get_http_client(self) -> httpx.Client:
        if self._http_client is not None:
            return self._http_client
        return httpx.Client(timeout=15.0)

    def _get_spark(self) -> Any:
        if self._spark is not None:
            return self._spark
        from pyspark.sql import SparkSession
        return (
            SparkSession.builder
            .master("local[1]")
            .appName("TrustSignal-WebhookDLQ")
            .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
            .config(
                "spark.sql.catalog.spark_catalog",
                "org.apache.spark.sql.delta.catalog.DeltaCatalog",
            )
            .getOrCreate()
        )

    def deliver(self, payload: WebhookPayload) -> bool:
        """Attempt delivery; retry up to _MAX_RETRIES times with back-off.

        Returns:
            True on success; False on permanent failure (DLQ record written).
        """
        last_error = ""
        client = self._get_http_client()
        total_attempts = _MAX_RETRIES + 1  # 1 initial + MAX_RETRIES retries

        for attempt in range(1, total_attempts + 1):
            try:
                resp = client.post(
                    self._webhook_url,
                    json=payload.to_dict(),
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                self._log.info(
                    "webhook_delivered",
                    candidate_uuid=payload.candidate_uuid,
                    attempt=attempt,
                    status_code=resp.status_code,
                )
                return True
            except Exception as exc:
                last_error = str(exc)
                self._log.warning(
                    "webhook_attempt_failed",
                    candidate_uuid=payload.candidate_uuid,
                    attempt=attempt,
                    error=last_error,
                )
                if attempt < total_attempts:
                    self._sleep(_BACKOFF_SECONDS[attempt - 1])

        self._write_dlq(payload, last_error)
        return False

    def _write_dlq(self, payload: WebhookPayload, error: str) -> None:
        """Append a dead-letter record to the webhook_dlq Delta Lake table."""
        from pyspark.sql.types import (
            DoubleType,
            IntegerType,
            StringType,
            StructField,
            StructType,
        )

        schema = StructType([
            StructField("candidate_uuid", StringType(),  False),
            StructField("ats_name",       StringType(),  False),
            StructField("webhook_url",    StringType(),  False),
            StructField("payload_json",   StringType(),  False),
            StructField("error",          StringType(),  False),
            StructField("attempts",       IntegerType(), False),
            StructField("failed_at",      DoubleType(),  False),
        ])

        row = [(
            payload.candidate_uuid,
            self._ats_name,
            self._webhook_url,
            json.dumps(payload.to_dict()),
            error,
            _MAX_RETRIES + 1,
            time.time(),
        )]

        spark      = self._get_spark()
        table_path = f"{self._delta_lake_path}/{TABLE_WEBHOOK_DLQ}"
        df         = spark.createDataFrame(row, schema=schema)
        df.write.format("delta").mode("append").save(table_path)

        self._log.error(
            "webhook_dlq_written",
            candidate_uuid=payload.candidate_uuid,
            ats=self._ats_name,
            error=error,
        )


# ── Helpers ────────────────────────────────────────────────────────────────────

def build_payload_from_result(
    candidate_uuid: str,
    prescreening_score: float | None,
    signals: list[dict[str, Any]],
) -> WebhookPayload:
    """Build a WebhookPayload from pre-screening result data.

    Only signals with ``raw_suspicion >= 0.5`` are included as flags.
    Payload contains no PII per CLAUDE.md Hard Rule #1.
    """
    flags = [
        WebhookFlag(
            signal=s.get("signal_name", ""),
            explanation=s.get("explanation", ""),
            score=float(s.get("raw_suspicion", 0.0)),
        )
        for s in signals
        if float(s.get("raw_suspicion", 0.0)) >= 0.5
    ]
    return WebhookPayload(
        candidate_uuid=candidate_uuid,
        prescreening_score=prescreening_score,
        flags=flags,
    )


def dispatch_to_configured_ats(
    payload: WebhookPayload,
    delta_lake_path: str,
    _http_client: httpx.Client | None = None,
    _spark: Any = None,
    _sleep_fn: Callable[[float], None] | None = None,
) -> dict[str, bool]:
    """Deliver payload to all configured ATS endpoints.

    Reads endpoint URLs from ``config.ATS_WEBHOOK_GREENHOUSE`` /
    ``config.ATS_WEBHOOK_LEVER``. Skips any ATS whose URL is not configured.

    Returns:
        Mapping of ATS name → delivery success boolean.
    """
    ats_urls: list[tuple[str, str]] = []
    if config.ATS_WEBHOOK_GREENHOUSE:
        ats_urls.append(("greenhouse", config.ATS_WEBHOOK_GREENHOUSE))
    if config.ATS_WEBHOOK_LEVER:
        ats_urls.append(("lever", config.ATS_WEBHOOK_LEVER))

    results: dict[str, bool] = {}
    for ats_name, url in ats_urls:
        delivery = WebhookDelivery(
            ats_name=ats_name,
            webhook_url=url,
            delta_lake_path=delta_lake_path,
            _http_client=_http_client,
            _spark=_spark,
            _sleep_fn=_sleep_fn,
        )
        results[ats_name] = delivery.deliver(payload)

    return results
