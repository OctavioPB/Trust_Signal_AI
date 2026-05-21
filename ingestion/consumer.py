"""Kafka consumer: interview-audio-stream → MinIO + STT → interview-text-stream.

Sprint 2:  Reads 500 ms PCM chunks → MinIO raw-audio archive.
Sprint 3:  Accumulates 10 chunks (5 s window) → Whisper STT → speaker-turn
           detection → publishes TranscriptionSegments to interview-text-stream.

STT is optional: pass whisper_service=None to run in archive-only mode
(backward-compatible with Sprint 2 tests).

All log lines use UUIDs only — no candidate PII ever appears.

Usage:
    python -m ingestion.consumer
"""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timezone

import structlog
from confluent_kafka import Consumer, KafkaError, KafkaException

import config
from logging_setup import configure_structlog
from storage.object_store import ObjectStore

logger = structlog.get_logger(__name__)

# ── STT window constants ──────────────────────────────────────────────────────
STT_WINDOW_CHUNKS: int = 10           # 10 × 500 ms = 5 s per STT window
STT_WINDOW_DURATION_S: float = 5.0   # seconds per STT window


class AudioConsumer:
    """Reads from interview-audio-stream, archives to MinIO, and drives STT.

    Args:
        bootstrap_servers: Kafka broker address(es), e.g. "localhost:9092".
        topic: Source Kafka topic (interview-audio-stream).
        group_id: Consumer group ID for offset management.
        object_store: Injected ObjectStore (facilitates testing).
        whisper_service: Optional WhisperService for STT. If None, STT is
            disabled and the consumer operates in archive-only mode.
        text_publisher: Optional TextPublisher for interview-text-stream.
            Must be provided if whisper_service is provided.
    """

    def __init__(
        self,
        bootstrap_servers: str,
        topic: str,
        group_id: str = "audio-consumer-group",
        object_store: ObjectStore | None = None,
        whisper_service=None,
        text_publisher=None,
    ) -> None:
        self._topic = topic
        self._consumer = Consumer(
            {
                "bootstrap.servers": bootstrap_servers,
                "group.id": group_id,
                "auto.offset.reset": "earliest",
                "enable.auto.commit": False,
                "session.timeout.ms": 30_000,
            }
        )
        self._consumer.subscribe([topic])
        self._store = object_store or ObjectStore(
            endpoint=config.MINIO_ENDPOINT,
            access_key=config.MINIO_ACCESS_KEY,
            secret_key=config.MINIO_SECRET_KEY,
        )
        self._whisper = whisper_service
        self._text_pub = text_publisher
        self._stt_enabled: bool = whisper_service is not None and text_publisher is not None

        self._stop_event = threading.Event()
        # Per-session audit counters (UUID keys, no PII values)
        self._chunk_counts: dict[str, int] = {}

        # Per-session STT state (only used when _stt_enabled)
        # Structure: { session_id: {"buffer": list[bytes], "window_count": int,
        #                           "last_speaker": str} }
        self._stt_state: dict[str, dict] = {}

        self._log = logger.bind(
            component="AudioConsumer", topic=topic, group_id=group_id,
            stt_enabled=self._stt_enabled,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Start the consume loop in a thread pool executor.

        Runs until cancelled or stop() is called.

        Raises:
            KafkaException: On unrecoverable broker errors.
        """
        self._log.info("consumer_started")
        try:
            await asyncio.to_thread(self._consume_loop)
        finally:
            self._log_session_summaries()
            self._log.info("consumer_stopped")

    def stop(self) -> None:
        """Signal the consume loop to exit on the next poll cycle."""
        self._stop_event.set()

    # ── Synchronous consume loop (runs in thread executor) ────────────────────

    def _consume_loop(self) -> None:
        try:
            while not self._stop_event.is_set():
                msg = self._consumer.poll(timeout=1.0)
                if msg is None:
                    continue
                if msg.error():
                    self._handle_kafka_error(msg.error())
                    continue
                self._handle_chunk_message(msg)
                self._consumer.commit(message=msg)
        except KafkaException:
            self._log.exception("consume_loop_fatal_error")
            raise
        finally:
            self._consumer.close()

    def _handle_kafka_error(self, error: KafkaError) -> None:
        if error.code() == KafkaError._PARTITION_EOF:
            return
        self._log.error("kafka_error", code=error.code(), reason=error.str())
        raise KafkaException(error)

    def _handle_chunk_message(self, msg: object) -> None:
        """Extract headers, archive to MinIO, and feed the STT window buffer.

        Args:
            msg: Kafka message from consumer.poll().
        """
        raw_headers: list[tuple[str, bytes]] = msg.headers() or []  # type: ignore[union-attr]
        headers: dict[str, str] = {k: v.decode() for k, v in raw_headers}

        session_id: str = headers.get("session_id", "unknown")
        chunk_seq: int = int(headers.get("chunk_seq", "0"))
        audio_bytes: bytes = msg.value()  # type: ignore[union-attr]
        date_str: str = datetime.now(timezone.utc).strftime("%Y%m%d")

        self._chunk_counts[session_id] = self._chunk_counts.get(session_id, 0) + 1

        self._log.info(
            "chunk_received",
            session_id=session_id,       # UUID — no PII
            chunk_seq=chunk_seq,
            chunk_count=self._chunk_counts[session_id],
            size_bytes=len(audio_bytes),
        )

        # ── Archive to MinIO ──────────────────────────────────────────────────
        object_path = self._store.upload_audio_chunk(
            session_id=session_id,
            chunk_seq=chunk_seq,
            audio_bytes=audio_bytes,
            date_str=date_str,
        )
        self._log.debug("chunk_archived", session_id=session_id, path=object_path)

        # ── Accumulate for STT (Sprint 3) ─────────────────────────────────────
        if self._stt_enabled:
            self._accumulate_stt(session_id, audio_bytes)

    def _accumulate_stt(self, session_id: str, audio_bytes: bytes) -> None:
        """Buffer a chunk and trigger STT when a full 5 s window is ready.

        Args:
            session_id: UUID of the interview session.
            audio_bytes: 500 ms PCM chunk to add to the window buffer.
        """
        if session_id not in self._stt_state:
            self._stt_state[session_id] = {
                "buffer": [],
                "window_count": 0,
                "last_speaker": "RECRUITER",   # default: recruiter speaks first
            }

        state = self._stt_state[session_id]
        state["buffer"].append(audio_bytes)

        if len(state["buffer"]) >= STT_WINDOW_CHUNKS:
            self._process_stt_window(session_id)

    def _process_stt_window(self, session_id: str) -> None:
        """Run STT on the accumulated 5 s window and publish segments.

        Args:
            session_id: UUID of the interview session.
        """
        state = self._stt_state[session_id]
        window_audio = b"".join(state["buffer"])
        window_count = state["window_count"]
        start_ts_offset = window_count * STT_WINDOW_DURATION_S
        first_chunk_seq = window_count * STT_WINDOW_CHUNKS

        # Clear the buffer before STT so new chunks accumulate during inference
        state["buffer"] = []
        state["window_count"] += 1

        self._log.debug(
            "stt_window_started",
            session_id=session_id,
            window=window_count,
            start_ts_offset=start_ts_offset,
        )

        segments = self._whisper.transcribe(  # type: ignore[union-attr]
            audio_bytes=window_audio,
            session_id=session_id,
            chunk_seq=first_chunk_seq,
            chunk_duration_s=STT_WINDOW_DURATION_S,
            start_ts_offset=start_ts_offset,
        )

        if not segments:
            self._log.debug("stt_window_no_speech", session_id=session_id, window=window_count)
            return

        # Speaker-turn detection using state carried from previous window
        from transcription.whisper_service import WhisperService

        WhisperService.detect_speaker_turns(
            segments,
            initial_speaker=state["last_speaker"],
        )

        # Persist last speaker for continuity across windows
        state["last_speaker"] = segments[-1].speaker

        # Publish each segment to interview-text-stream
        for seg in segments:
            self._text_pub.publish_segment(seg)  # type: ignore[union-attr]

        self._log.info(
            "stt_window_published",
            session_id=session_id,
            window=window_count,
            segment_count=len(segments),
            last_speaker=state["last_speaker"],
        )

    def _log_session_summaries(self) -> None:
        """Emit a per-session summary on shutdown (session_id + chunk_count only)."""
        for session_id, count in self._chunk_counts.items():
            self._log.info(
                "session_summary",
                session_id=session_id,  # UUID — no PII
                chunk_count=count,
            )


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    configure_structlog()

    from transcription.whisper_service import WhisperService
    from ingestion.text_publisher import TextPublisher

    whisper_svc = WhisperService(
        model_size=config.WHISPER_MODEL_SIZE,
        openai_api_key=config.OPENAI_API_KEY,
    )
    text_pub = TextPublisher(
        bootstrap_servers=config.KAFKA_BOOTSTRAP_SERVERS,
        topic=config.KAFKA_TOPIC_TEXT,
    )
    consumer = AudioConsumer(
        bootstrap_servers=config.KAFKA_BOOTSTRAP_SERVERS,
        topic=config.KAFKA_TOPIC_AUDIO,
        whisper_service=whisper_svc,
        text_publisher=text_pub,
    )

    async def _main() -> None:
        try:
            await consumer.run()
        except KeyboardInterrupt:
            consumer.stop()

    asyncio.run(_main())
