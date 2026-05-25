"""Kafka producer for candidate-profile-stream — Sprint 18.

Publishes one event per completed pre-screening run, keyed by
``candidate_uuid``. The payload carries aggregated suspicion scores and alert
metadata — no PII, no source content.

Payload schema:
    {
        "candidate_uuid":        str,          # UUID — no PII
        "prescreening_score":    float,        # 0–100
        "resume_ai_score":       float,        # 0–100
        "repo_ai_score":         float | null,
        "interview_trust_score": float | null,
        "flagged":               bool,
        "severity":              str,          # "low" | "medium" | "high"
        "flag_reason":           str,          # empty string when not flagged
        "scored_at":             str,          # ISO 8601 compact UTC
    }
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import structlog
from confluent_kafka import KafkaException, Producer

import config

logger = structlog.get_logger(__name__)


def _on_delivery(err: Exception | None, msg: object) -> None:
    if err:
        logger.error("profile_event_delivery_failed", error=str(err))


class ProfileProducer:
    """Publishes pre-screening result events to candidate-profile-stream.

    Args:
        bootstrap_servers: Kafka broker address(es), e.g. ``"localhost:9092"``.
        topic: Target Kafka topic (``candidate-profile-stream``).
    """

    def __init__(self, bootstrap_servers: str, topic: str) -> None:
        self._topic = topic
        self._producer = Producer(
            {
                "bootstrap.servers": bootstrap_servers,
                "acks": "all",
                "linger.ms": 5,
            }
        )
        self._log = logger.bind(component="ProfileProducer", topic=topic)

    def publish_prescreening_result(
        self,
        candidate_uuid: str,
        prescreening_score: float,
        resume_ai_score: float,
        repo_ai_score: float | None,
        interview_trust_score: float | None,
        flagged: bool,
        severity: str,
        flag_reason: str,
        scored_at: float,
    ) -> None:
        """Publish a pre-screening result event.

        Args:
            candidate_uuid: UUID of the candidate (no PII).
            prescreening_score: Aggregated suspicion score in [0, 100].
            resume_ai_score: Resume signal score in [0, 100].
            repo_ai_score: Repo signal score in [0, 100], or None.
            interview_trust_score: Interview trust score in [0, 100], or None.
            flagged: True when suspicion_index ≥ threshold.
            severity: "low", "medium", or "high".
            flag_reason: Non-empty explanation string when flagged (CLAUDE.md §8.2).
            scored_at: Unix timestamp of score computation.

        Raises:
            KafkaException: On broker communication failure.
        """
        iso_ts = datetime.fromtimestamp(scored_at, tz=timezone.utc).strftime(
            "%Y%m%dT%H%M%SZ"
        )
        payload = json.dumps(
            {
                "candidate_uuid":        candidate_uuid,       # UUID — no PII
                "prescreening_score":    round(prescreening_score, 2),
                "resume_ai_score":       round(resume_ai_score, 2),
                "repo_ai_score":         round(repo_ai_score, 2) if repo_ai_score is not None else None,
                "interview_trust_score": round(interview_trust_score, 2) if interview_trust_score is not None else None,
                "flagged":               flagged,
                "severity":              severity,
                "flag_reason":           flag_reason,
                "scored_at":             iso_ts,
            }
        ).encode()

        try:
            self._producer.produce(
                topic=self._topic,
                key=candidate_uuid.encode(),
                value=payload,
                on_delivery=_on_delivery,
            )
            self._producer.poll(0)
            self._log.info(
                "profile_event_published",
                candidate_uuid=candidate_uuid,   # UUID — no PII
                prescreening_score=round(prescreening_score, 2),
                flagged=flagged,
                severity=severity,
            )
        except KafkaException as exc:
            self._log.error(
                "profile_event_publish_failed",
                candidate_uuid=candidate_uuid,   # UUID — no PII
                error=str(exc),
            )
            raise

    def flush(self, timeout_s: float = 30.0) -> None:
        """Block until all queued events are delivered.

        Args:
            timeout_s: Maximum wait time in seconds.
        """
        remaining = self._producer.flush(timeout_s)
        if remaining:
            self._log.warning("flush_incomplete", remaining_messages=remaining)

    def close(self) -> None:
        """Flush pending messages and shut down the producer."""
        self.flush()
        self._log.info("profile_producer_closed")
