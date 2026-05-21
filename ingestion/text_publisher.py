"""Kafka producer for interview-text-stream.

Serialises TranscriptionSegment objects to JSON and publishes them to the
text topic with session_id as the Kafka message key.

Payload schema (mirrors PLAN.md §3.3):
    {
        "session_id":  str,    # UUID only — no PII
        "chunk_seq":   int,    # first source audio chunk index for this window
        "start_ts":    float,  # absolute seconds from call start
        "end_ts":      float,
        "text":        str,
        "confidence":  float,  # [0, 1]
        "speaker":     str     # "RECRUITER" or "CANDIDATE"
    }
"""

from __future__ import annotations

import json

import structlog
from confluent_kafka import KafkaException, Producer

from transcription.whisper_service import TranscriptionSegment

logger = structlog.get_logger(__name__)


class TextPublisher:
    """Publishes transcription segments to interview-text-stream.

    Args:
        bootstrap_servers: Kafka broker address(es), e.g. "localhost:9092".
        topic: Target Kafka topic (interview-text-stream).
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
        self._log = logger.bind(component="TextPublisher", topic=topic)

    def publish_segment(self, segment: TranscriptionSegment) -> None:
        """Serialise and publish one transcription segment.

        Args:
            segment: Completed and speaker-tagged TranscriptionSegment.

        Raises:
            KafkaException: On broker communication failure.
        """
        payload = json.dumps(
            {
                "session_id": segment.session_id,    # UUID — no PII
                "chunk_seq": segment.chunk_seq,
                "start_ts": segment.start_ts,
                "end_ts": segment.end_ts,
                "text": segment.text,
                "confidence": segment.confidence,
                "speaker": segment.speaker,
            }
        ).encode()

        try:
            self._producer.produce(
                topic=self._topic,
                key=segment.session_id.encode(),
                value=payload,
            )
            self._producer.poll(0)
            self._log.debug(
                "segment_published",
                session_id=segment.session_id,   # UUID only
                speaker=segment.speaker,
                start_ts=segment.start_ts,
                end_ts=segment.end_ts,
            )
        except KafkaException as exc:
            self._log.error(
                "segment_publish_failed",
                session_id=segment.session_id,
                error=str(exc),
            )
            raise

    def flush(self, timeout_s: float = 30.0) -> None:
        """Block until all queued segments are delivered.

        Args:
            timeout_s: Maximum wait time in seconds.
        """
        remaining = self._producer.flush(timeout_s)
        if remaining:
            self._log.warning("flush_incomplete", remaining_messages=remaining)

    def close(self) -> None:
        """Flush pending messages and shut down the producer."""
        self.flush()
        self._log.info("text_publisher_closed")
