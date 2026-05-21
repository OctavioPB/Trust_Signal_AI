"""Unit tests for ingestion/producer.py.

Tests pure functions and Kafka interaction logic with mocked broker.
No real Kafka connection is made.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from ingestion.producer import (
    CHUNK_SIZE_BYTES,
    CHUNK_DURATION_MS,
    MAX_RETRIES,
    SAMPLE_RATE,
    SAMPLE_WIDTH_BYTES,
    AudioProducer,
    frame_to_chunks,
)


# ── Constants ──────────────────────────────────────────────────────────────────

def test_chunk_size_bytes_calculation() -> None:
    """500 ms of 16-bit PCM at 16 kHz must be exactly 16 000 bytes."""
    expected = int(SAMPLE_RATE * SAMPLE_WIDTH_BYTES * CHUNK_DURATION_MS / 1000)
    assert CHUNK_SIZE_BYTES == expected == 16_000


def test_max_retries_is_five() -> None:
    assert MAX_RETRIES == 5


# ── frame_to_chunks (pure function) ──────────────────────────────────────────

def test_frame_to_chunks_empty() -> None:
    assert frame_to_chunks(b"") == []


def test_frame_to_chunks_exact_one_chunk() -> None:
    audio = b"\x01" * CHUNK_SIZE_BYTES
    chunks = frame_to_chunks(audio)
    assert len(chunks) == 1
    assert chunks[0] == audio


def test_frame_to_chunks_exact_multiple() -> None:
    n = 5
    audio = b"\xAB" * (CHUNK_SIZE_BYTES * n)
    chunks = frame_to_chunks(audio)
    assert len(chunks) == n
    assert all(len(c) == CHUNK_SIZE_BYTES for c in chunks)


def test_frame_to_chunks_partial_tail_is_zero_padded() -> None:
    """A frame shorter than chunk_size must be padded with silence (zeros)."""
    partial = b"\xFF" * (CHUNK_SIZE_BYTES // 2)
    chunks = frame_to_chunks(partial)
    assert len(chunks) == 1
    assert len(chunks[0]) == CHUNK_SIZE_BYTES
    assert chunks[0].startswith(partial)
    assert chunks[0][len(partial) :] == b"\x00" * (CHUNK_SIZE_BYTES - len(partial))


def test_frame_to_chunks_multi_with_partial_tail() -> None:
    """Three full chunks + a partial tail → four chunks, last one padded."""
    audio = b"\x11" * (CHUNK_SIZE_BYTES * 3 + 100)
    chunks = frame_to_chunks(audio)
    assert len(chunks) == 4
    assert len(chunks[3]) == CHUNK_SIZE_BYTES   # last chunk is padded
    assert chunks[3][100:] == b"\x00" * (CHUNK_SIZE_BYTES - 100)


def test_frame_to_chunks_custom_size() -> None:
    audio = b"\x22" * 12
    chunks = frame_to_chunks(audio, chunk_size=5)
    assert len(chunks) == 3  # [5, 5, 2+3 zeros]
    assert chunks[2] == b"\x22" * 2 + b"\x00" * 3


# ── AudioProducer.publish_chunk ───────────────────────────────────────────────

@pytest.fixture()
def mock_kafka_producer():
    """Return a mocked confluent_kafka.Producer instance and patch the class."""
    with patch("ingestion.producer.Producer") as mock_cls:
        instance = MagicMock()
        mock_cls.return_value = instance
        yield instance


@pytest.mark.asyncio
async def test_publish_chunk_calls_produce_with_correct_topic(
    mock_kafka_producer: MagicMock,
) -> None:
    producer = AudioProducer("localhost:9092", "test-topic")
    await producer.publish_chunk("session-abc", 0, b"\x00" * CHUNK_SIZE_BYTES)

    mock_kafka_producer.produce.assert_called_once()
    kwargs = mock_kafka_producer.produce.call_args.kwargs
    assert kwargs["topic"] == "test-topic"


@pytest.mark.asyncio
async def test_publish_chunk_embeds_session_id_in_headers(
    mock_kafka_producer: MagicMock,
) -> None:
    session_id = "session-xyz-789"
    producer = AudioProducer("localhost:9092", "test-topic")
    await producer.publish_chunk(session_id, 7, b"\x00" * CHUNK_SIZE_BYTES)

    kwargs = mock_kafka_producer.produce.call_args.kwargs
    headers_dict = dict(kwargs["headers"])
    assert headers_dict["session_id"] == session_id.encode()
    assert headers_dict["chunk_seq"] == b"7"


@pytest.mark.asyncio
async def test_publish_chunk_uses_session_id_as_kafka_key(
    mock_kafka_producer: MagicMock,
) -> None:
    session_id = "session-key-test"
    producer = AudioProducer("localhost:9092", "test-topic")
    await producer.publish_chunk(session_id, 0, b"\x00" * CHUNK_SIZE_BYTES)

    kwargs = mock_kafka_producer.produce.call_args.kwargs
    assert kwargs["key"] == session_id.encode()


@pytest.mark.asyncio
@patch("ingestion.producer.asyncio.sleep", new_callable=AsyncMock)
async def test_publish_chunk_retries_on_kafka_exception(
    mock_sleep: AsyncMock,
    mock_kafka_producer: MagicMock,
) -> None:
    """publish_chunk must retry MAX_RETRIES times then re-raise."""
    from confluent_kafka import KafkaException

    mock_kafka_producer.produce.side_effect = KafkaException("broker down")

    producer = AudioProducer("localhost:9092", "test-topic")
    with pytest.raises(KafkaException):
        await producer.publish_chunk("session-retry", 0, b"\x00" * CHUNK_SIZE_BYTES)

    assert mock_kafka_producer.produce.call_count == MAX_RETRIES


@pytest.mark.asyncio
@patch("ingestion.producer.asyncio.sleep", new_callable=AsyncMock)
async def test_publish_chunk_exponential_backoff_delays(
    mock_sleep: AsyncMock,
    mock_kafka_producer: MagicMock,
) -> None:
    """Sleep durations must follow 2^(attempt-1): 1, 2, 4, 8 s."""
    from confluent_kafka import KafkaException

    mock_kafka_producer.produce.side_effect = KafkaException("broker down")

    producer = AudioProducer("localhost:9092", "test-topic")
    with pytest.raises(KafkaException):
        await producer.publish_chunk("session-backoff", 0, b"\x00" * CHUNK_SIZE_BYTES)

    # 4 sleep calls for 5 attempts (no sleep on final attempt before raise)
    expected_delays = [1.0, 2.0, 4.0, 8.0]
    actual_delays = [c.args[0] for c in mock_sleep.call_args_list]
    assert actual_delays == expected_delays


@pytest.mark.asyncio
@patch("ingestion.producer.asyncio.sleep", new_callable=AsyncMock)
async def test_publish_chunk_succeeds_on_second_attempt(
    mock_sleep: AsyncMock,
    mock_kafka_producer: MagicMock,
) -> None:
    """If produce() fails once then succeeds, no exception should escape."""
    from confluent_kafka import KafkaException

    mock_kafka_producer.produce.side_effect = [KafkaException("transient"), None]

    producer = AudioProducer("localhost:9092", "test-topic")
    await producer.publish_chunk("session-recover", 0, b"\x00" * CHUNK_SIZE_BYTES)  # no raise

    assert mock_kafka_producer.produce.call_count == 2
    mock_sleep.assert_called_once_with(1)   # one backoff of 2^0 = 1 s


@pytest.mark.asyncio
async def test_publish_chunk_retries_on_buffer_error(
    mock_kafka_producer: MagicMock,
) -> None:
    """BufferError (queue full) must also trigger retry logic."""
    mock_kafka_producer.produce.side_effect = BufferError("queue full")

    producer = AudioProducer("localhost:9092", "test-topic")
    with patch("ingestion.producer.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(Exception):
            await producer.publish_chunk("session-buf", 0, b"\x00" * CHUNK_SIZE_BYTES)

    assert mock_kafka_producer.produce.call_count == MAX_RETRIES
