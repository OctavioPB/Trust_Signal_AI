"""Kafka producer for candidate-resume-stream.

Publishes a resume-uploaded event when a resume is stored in MinIO.
The Sprint 15 consumer reads this topic to trigger text extraction and
AI-signal scoring.

Payload schema:
    {
        "candidate_uuid": str,   # UUID only — no PII (CLAUDE.md §8 rule 6)
        "minio_path":     str,   # resumes/{uuid}/{timestamp}.{ext}
        "file_ext":       str,   # "pdf" | "docx" | "txt"
        "uploaded_at":    str,   # ISO 8601 compact UTC, e.g. "20260523T100000Z"
    }
"""

from __future__ import annotations

import json

import structlog
from confluent_kafka import KafkaException, Producer

logger = structlog.get_logger(__name__)


class ResumeProducer:
    """Publishes resume-uploaded events to candidate-resume-stream.

    Args:
        bootstrap_servers: Kafka broker address(es), e.g. "localhost:9092".
        topic: Target Kafka topic (candidate-resume-stream).
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
        self._log = logger.bind(component="ResumeProducer", topic=topic)

    def publish_uploaded(
        self,
        candidate_uuid: str,
        minio_path: str,
        file_ext: str,
        uploaded_at: str,
    ) -> None:
        """Publish a resume-uploaded event.

        Args:
            candidate_uuid: UUID of the candidate (no PII).
            minio_path: Full MinIO object path (resumes/{uuid}/{ts}.{ext}).
            file_ext: File extension without leading dot.
            uploaded_at: ISO 8601 compact UTC timestamp string.

        Raises:
            KafkaException: On broker communication failure.
        """
        payload = json.dumps(
            {
                "candidate_uuid": candidate_uuid,  # UUID — no PII
                "minio_path":     minio_path,
                "file_ext":       file_ext,
                "uploaded_at":    uploaded_at,
            }
        ).encode()

        try:
            self._producer.produce(
                topic=self._topic,
                key=candidate_uuid.encode(),
                value=payload,
            )
            self._producer.poll(0)
            self._log.info(
                "resume_event_published",
                candidate_uuid=candidate_uuid,  # UUID — no PII
                file_ext=file_ext,
            )
        except KafkaException as exc:
            self._log.error(
                "resume_event_publish_failed",
                candidate_uuid=candidate_uuid,
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
        self._log.info("resume_producer_closed")
