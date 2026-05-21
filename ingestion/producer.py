"""WebRTC/WebSocket → Kafka audio producer.

Accepts binary audio frames (16-bit PCM, 16 kHz) from browser clients over a
WebSocket connection and publishes fixed-size 500 ms chunks to
interview-audio-stream with session metadata in Kafka message headers.

Usage:
    python -m ingestion.producer          # starts WebSocket server on 0.0.0.0:8765
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import AsyncIterator

import structlog
import websockets
import websockets.exceptions
from confluent_kafka import KafkaException, Producer

import config
from logging_setup import configure_structlog

logger = structlog.get_logger(__name__)

# ── Audio constants ───────────────────────────────────────────────────────────
SAMPLE_RATE: int = 16_000        # Hz (16 kHz)
SAMPLE_WIDTH_BYTES: int = 2      # 16-bit PCM
CHUNK_DURATION_MS: int = 500     # ms per Kafka message
CHUNK_SIZE_BYTES: int = int(SAMPLE_RATE * SAMPLE_WIDTH_BYTES * CHUNK_DURATION_MS / 1000)
# = 16_000 bytes per chunk

# ── Retry constants ───────────────────────────────────────────────────────────
MAX_RETRIES: int = 5             # max publish attempts (including the initial one)


# ── Pure helper — testable without Kafka ─────────────────────────────────────

def frame_to_chunks(audio_bytes: bytes, chunk_size: int = CHUNK_SIZE_BYTES) -> list[bytes]:
    """Split a continuous audio frame into fixed-size chunks.

    The last chunk is zero-padded to `chunk_size` if the frame does not divide
    evenly, ensuring every published message has a uniform byte length.

    Args:
        audio_bytes: Raw 16-bit PCM audio of any length.
        chunk_size: Target chunk size in bytes (default 500 ms at 16 kHz).

    Returns:
        List of equal-length byte chunks; empty list if audio_bytes is empty.
    """
    if not audio_bytes:
        return []

    chunks: list[bytes] = []
    for i in range(0, len(audio_bytes), chunk_size):
        chunk = audio_bytes[i : i + chunk_size]
        if len(chunk) < chunk_size:
            chunk = chunk + b"\x00" * (chunk_size - len(chunk))
        chunks.append(chunk)
    return chunks


# ── Kafka producer wrapper ────────────────────────────────────────────────────

class AudioProducer:
    """Publishes 500 ms PCM chunks to interview-audio-stream.

    Args:
        bootstrap_servers: Kafka broker address(es), e.g. "localhost:9092".
        topic: Target Kafka topic name.
    """

    def __init__(self, bootstrap_servers: str, topic: str) -> None:
        self._topic = topic
        self._producer = Producer(
            {
                "bootstrap.servers": bootstrap_servers,
                "acks": "all",
                "linger.ms": 5,              # small batching window
                "retries": 0,                # we handle retries manually
                "enable.idempotence": False,  # disabled; we retry manually
            }
        )
        self._log = logger.bind(component="AudioProducer", topic=topic)

    async def publish_chunk(
        self,
        session_id: str,
        chunk_seq: int,
        audio_bytes: bytes,
    ) -> None:
        """Publish a single 500 ms PCM chunk with retry + exponential back-off.

        Args:
            session_id: UUID of the interview session (no PII).
            chunk_seq: Monotonically increasing chunk counter for this session.
            audio_bytes: Exactly CHUNK_SIZE_BYTES of raw 16-bit PCM at 16 kHz.

        Raises:
            KafkaException: After MAX_RETRIES failed attempts.
        """
        headers: list[tuple[str, bytes]] = [
            ("session_id", session_id.encode()),
            ("chunk_seq", str(chunk_seq).encode()),
            ("timestamp_ms", str(int(time.time() * 1000)).encode()),
        ]

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                self._producer.produce(
                    topic=self._topic,
                    key=session_id.encode(),
                    value=audio_bytes,
                    headers=headers,
                )
                self._producer.poll(0)  # trigger delivery callbacks without blocking
                self._log.debug(
                    "chunk_queued",
                    session_id=session_id,
                    chunk_seq=chunk_seq,
                    size_bytes=len(audio_bytes),
                )
                return

            except (KafkaException, BufferError) as exc:
                if attempt == MAX_RETRIES:
                    self._log.error(
                        "chunk_publish_failed",
                        session_id=session_id,
                        chunk_seq=chunk_seq,
                        total_attempts=attempt,
                        error=str(exc),
                    )
                    raise KafkaException(str(exc)) from exc

                backoff_s = 2 ** (attempt - 1)  # 1, 2, 4, 8 s
                self._log.warning(
                    "chunk_publish_retry",
                    session_id=session_id,
                    chunk_seq=chunk_seq,
                    attempt=attempt,
                    backoff_s=backoff_s,
                    error=str(exc),
                )
                await asyncio.sleep(backoff_s)

    async def flush(self, timeout_s: float = 30.0) -> int:
        """Flush all queued messages to the broker.

        Args:
            timeout_s: Maximum seconds to wait for delivery.

        Returns:
            Number of messages still in the queue after the timeout.
        """
        remaining: int = await asyncio.to_thread(self._producer.flush, timeout_s)
        if remaining:
            self._log.warning("flush_incomplete", remaining_messages=remaining)
        return remaining

    async def close(self) -> None:
        """Flush pending messages and close the producer cleanly."""
        remaining = await self.flush()
        self._log.info("producer_closed", unflushed_messages=remaining)


# ── WebSocket server ──────────────────────────────────────────────────────────

async def _handle_connection(
    websocket: websockets.WebSocketServerProtocol,
    producer: AudioProducer,
) -> None:
    """Handle a single browser WebSocket connection.

    Each connection gets a fresh session UUID. Incoming binary frames are
    accumulated in a buffer and dispatched as CHUNK_SIZE_BYTES Kafka messages.

    Args:
        websocket: Active WebSocket connection.
        producer: Shared AudioProducer instance.
    """
    session_id = str(uuid.uuid4())
    chunk_seq = 0
    buffer = b""
    log = logger.bind(session_id=session_id)
    log.info("ws_session_started")

    try:
        async for message in websocket:
            if not isinstance(message, bytes):
                continue

            buffer += message

            # Drain all complete chunks from the buffer
            while len(buffer) >= CHUNK_SIZE_BYTES:
                chunk = buffer[:CHUNK_SIZE_BYTES]
                buffer = buffer[CHUNK_SIZE_BYTES:]
                await producer.publish_chunk(session_id, chunk_seq, chunk)
                chunk_seq += 1

    except websockets.exceptions.ConnectionClosedOK:
        log.info("ws_session_closed_ok", chunk_count=chunk_seq)
    except websockets.exceptions.ConnectionClosedError as exc:
        log.warning("ws_session_closed_error", error=str(exc), chunk_count=chunk_seq)
    except KafkaException:
        log.exception("ws_session_kafka_error", chunk_count=chunk_seq)
    finally:
        # Flush any remaining partial buffer (zero-padded)
        if buffer:
            padded = buffer + b"\x00" * (CHUNK_SIZE_BYTES - len(buffer))
            try:
                await producer.publish_chunk(session_id, chunk_seq, padded)
                chunk_seq += 1
            except KafkaException:
                log.warning("ws_session_final_chunk_lost", chunk_seq=chunk_seq)

        log.info("ws_session_ended", total_chunks=chunk_seq)


async def start_websocket_server(
    host: str = "0.0.0.0",
    port: int = 8765,
    bootstrap_servers: str | None = None,
    topic: str | None = None,
) -> None:
    """Start the WebSocket audio ingestion server.

    Args:
        host: Bind address.
        port: Bind port.
        bootstrap_servers: Kafka broker(s); defaults to KAFKA_BOOTSTRAP_SERVERS env var.
        topic: Kafka topic; defaults to KAFKA_TOPIC_AUDIO env var.
    """
    if bootstrap_servers is None:
        bootstrap_servers = config.KAFKA_BOOTSTRAP_SERVERS
    if topic is None:
        topic = config.KAFKA_TOPIC_AUDIO

    producer = AudioProducer(bootstrap_servers, topic)

    async def handler(websocket: websockets.WebSocketServerProtocol) -> None:
        await _handle_connection(websocket, producer)

    async with websockets.serve(handler, host, port):
        logger.info("ws_server_started", host=host, port=port, topic=topic)
        await asyncio.Future()  # run until cancelled


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    configure_structlog()
    asyncio.run(start_websocket_server())
