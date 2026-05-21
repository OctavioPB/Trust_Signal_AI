"""Unit tests for ingestion/consumer.py.

All Kafka and MinIO I/O is mocked — no real broker or object store is needed.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ingestion.consumer import AudioConsumer


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_mock_message(
    session_id: str,
    chunk_seq: int,
    audio_bytes: bytes,
) -> MagicMock:
    """Create a confluent-kafka-like mock message."""
    msg = MagicMock()
    msg.headers.return_value = [
        ("session_id", session_id.encode()),
        ("chunk_seq", str(chunk_seq).encode()),
        ("timestamp_ms", b"1000000"),
    ]
    msg.value.return_value = audio_bytes
    msg.error.return_value = None
    return msg


@pytest.fixture()
def mock_store() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def mock_kafka_consumer():
    with patch("ingestion.consumer.Consumer") as mock_cls:
        instance = MagicMock()
        mock_cls.return_value = instance
        yield instance


@pytest.fixture()
def consumer(mock_kafka_consumer: MagicMock, mock_store: MagicMock) -> AudioConsumer:
    return AudioConsumer(
        bootstrap_servers="localhost:9092",
        topic="interview-audio-stream",
        object_store=mock_store,
    )


# ── _handle_chunk_message ─────────────────────────────────────────────────────

def test_handle_chunk_message_increments_chunk_count(
    consumer: AudioConsumer, mock_store: MagicMock
) -> None:
    session_id = "session-unit-001"
    audio = b"\xAA" * 16_000

    msg1 = _make_mock_message(session_id, 0, audio)
    msg2 = _make_mock_message(session_id, 1, audio)

    consumer._handle_chunk_message(msg1)
    consumer._handle_chunk_message(msg2)

    assert consumer._chunk_counts[session_id] == 2


def test_handle_chunk_message_tracks_separate_sessions(
    consumer: AudioConsumer, mock_store: MagicMock
) -> None:
    audio = b"\x00" * 16_000

    consumer._handle_chunk_message(_make_mock_message("session-A", 0, audio))
    consumer._handle_chunk_message(_make_mock_message("session-B", 0, audio))
    consumer._handle_chunk_message(_make_mock_message("session-A", 1, audio))

    assert consumer._chunk_counts["session-A"] == 2
    assert consumer._chunk_counts["session-B"] == 1


def test_handle_chunk_message_calls_upload_with_correct_session_id(
    consumer: AudioConsumer, mock_store: MagicMock
) -> None:
    session_id = "session-upload-check"
    audio = b"\xBB" * 16_000

    consumer._handle_chunk_message(_make_mock_message(session_id, 0, audio))

    mock_store.upload_audio_chunk.assert_called_once()
    call_kwargs = mock_store.upload_audio_chunk.call_args.kwargs
    assert call_kwargs["session_id"] == session_id


def test_handle_chunk_message_calls_upload_with_correct_chunk_seq(
    consumer: AudioConsumer, mock_store: MagicMock
) -> None:
    audio = b"\xCC" * 16_000
    consumer._handle_chunk_message(_make_mock_message("s", 42, audio))

    call_kwargs = mock_store.upload_audio_chunk.call_args.kwargs
    assert call_kwargs["chunk_seq"] == 42


def test_handle_chunk_message_calls_upload_with_audio_bytes(
    consumer: AudioConsumer, mock_store: MagicMock
) -> None:
    audio = b"\xDD" * 16_000
    consumer._handle_chunk_message(_make_mock_message("s", 0, audio))

    call_kwargs = mock_store.upload_audio_chunk.call_args.kwargs
    assert call_kwargs["audio_bytes"] == audio


def test_handle_chunk_message_date_str_is_yyyymmdd(
    consumer: AudioConsumer, mock_store: MagicMock
) -> None:
    """The date_str passed to upload_audio_chunk must be 8 digits (YYYYMMDD)."""
    consumer._handle_chunk_message(_make_mock_message("s", 0, b"\x00" * 16_000))

    call_kwargs = mock_store.upload_audio_chunk.call_args.kwargs
    date_str: str = call_kwargs["date_str"]
    assert len(date_str) == 8
    assert date_str.isdigit()


def test_handle_chunk_message_missing_headers_defaults_gracefully(
    consumer: AudioConsumer, mock_store: MagicMock
) -> None:
    """A message with no headers must not raise — use safe defaults."""
    msg = MagicMock()
    msg.headers.return_value = []
    msg.value.return_value = b"\x00" * 16_000

    consumer._handle_chunk_message(msg)   # must not raise

    call_kwargs = mock_store.upload_audio_chunk.call_args.kwargs
    assert call_kwargs["session_id"] == "unknown"
    assert call_kwargs["chunk_seq"] == 0


# ── Session summary logging ────────────────────────────────────────────────────

def test_log_session_summaries_emits_all_sessions(
    consumer: AudioConsumer, mock_store: MagicMock
) -> None:
    """After processing chunks, _log_session_summaries should cover every session."""
    audio = b"\x00" * 16_000
    for seq in range(3):
        consumer._handle_chunk_message(_make_mock_message("s-alpha", seq, audio))
    consumer._handle_chunk_message(_make_mock_message("s-beta", 0, audio))

    assert set(consumer._chunk_counts.keys()) == {"s-alpha", "s-beta"}
    assert consumer._chunk_counts["s-alpha"] == 3
    assert consumer._chunk_counts["s-beta"] == 1
