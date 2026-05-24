"""Kafka producer for candidate-repo-stream — Sprint 16.

Publishes one event per crawled source file, keyed by ``repo_uuid``.
Source code content is never included in the payload — only file metadata
and the content hash are published, keeping message sizes small and
avoiding sensitive content (credentials, PII) on the wire.

Payload schema (per file):
    {
        "repo_uuid":      str,   # uuid5(NAMESPACE_URL, repo_url) — no PII
        "candidate_uuid": str,   # UUID of the linked candidate
        "file_path":      str,   # relative path within the repository
        "language":       str,   # detected programming language
        "content_hash":   str,   # sha256 hex of file content
        "crawled_at":     str,   # ISO 8601 compact UTC timestamp
    }
"""

from __future__ import annotations

import json

import structlog
from confluent_kafka import KafkaException, Producer

import config

logger = structlog.get_logger(__name__)


def _on_delivery(err: Exception | None, msg: object) -> None:
    if err:
        logger.error("repo_event_delivery_failed", error=str(err))


class RepoProducer:
    """Publishes per-file crawl events to candidate-repo-stream.

    Follows the same synchronous pattern as ResumeProducer.

    Args:
        bootstrap_servers: Kafka broker address(es), e.g. "localhost:9092".
        topic: Target Kafka topic (candidate-repo-stream).
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
        self._log = logger.bind(component="RepoProducer", topic=topic)

    def publish_file(
        self,
        repo_uuid: str,
        candidate_uuid: str,
        file_path: str,
        language: str,
        content_hash: str,
        crawled_at: str,
    ) -> None:
        """Publish a single crawled-file event.

        Args:
            repo_uuid: UUID of the repository (uuid5, no PII).
            candidate_uuid: UUID of the linked candidate (no PII).
            file_path: Relative path within the repository.
            language: Detected programming language.
            content_hash: SHA-256 hex digest of file content.
            crawled_at: ISO 8601 compact UTC timestamp string.

        Raises:
            KafkaException: On broker communication failure.
        """
        payload = json.dumps(
            {
                "repo_uuid":      repo_uuid,       # UUID — no PII
                "candidate_uuid": candidate_uuid,  # UUID — no PII
                "file_path":      file_path,
                "language":       language,
                "content_hash":   content_hash,
                "crawled_at":     crawled_at,
            }
        ).encode()

        try:
            self._producer.produce(
                topic=self._topic,
                key=repo_uuid.encode(),
                value=payload,
                on_delivery=_on_delivery,
            )
            self._producer.poll(0)
            self._log.info(
                "repo_file_event_published",
                repo_uuid=repo_uuid,          # UUID — no PII
                candidate_uuid=candidate_uuid, # UUID — no PII
                language=language,
            )
        except KafkaException as exc:
            self._log.error(
                "repo_file_event_publish_failed",
                repo_uuid=repo_uuid,
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
        self._log.info("repo_producer_closed")
