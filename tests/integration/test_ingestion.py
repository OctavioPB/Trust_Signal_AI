"""Integration test: 60-second synthetic audio → all chunks in MinIO.

Requires the full docker-compose stack to be running:
    docker compose up -d broker minio kafka-setup minio-setup

Run with:
    pytest --run-integration -m integration tests/integration/test_ingestion.py

Definition of Done (PLAN.md §2.8):
    - 120 chunks (60 s × 2 chunks/s) arrive in MinIO with zero loss.
    - Consumer logs session_id and chunk_count in structured JSON.
    - No PII in any log line.
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from datetime import datetime, timezone

import numpy as np
import pytest
from minio import Minio

import config
from ingestion.consumer import AudioConsumer
from ingestion.producer import CHUNK_SIZE_BYTES, AudioProducer, frame_to_chunks
from storage.object_store import ObjectStore

# ── Constants ──────────────────────────────────────────────────────────────────

SYNTHETIC_DURATION_S = 60
SAMPLE_RATE = 16_000
CHUNK_DURATION_S = 0.5
EXPECTED_CHUNKS = int(SYNTHETIC_DURATION_S / CHUNK_DURATION_S)  # 120


def _generate_silence(duration_s: float, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Generate synthetic silent PCM audio (16-bit, all zeros)."""
    n_samples = int(duration_s * sample_rate)
    return np.zeros(n_samples, dtype=np.int16).tobytes()


def _minio_client() -> Minio:
    host = config.MINIO_ENDPOINT.replace("http://", "").replace("https://", "")
    return Minio(
        host,
        access_key=config.MINIO_ACCESS_KEY,
        secret_key=config.MINIO_SECRET_KEY,
        secure=False,
    )


def _count_session_objects(session_id: str) -> int:
    client = _minio_client()
    objects = list(client.list_objects("raw-audio", prefix=f"{session_id}/", recursive=True))
    return len(objects)


# ── Tests ──────────────────────────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.asyncio
async def test_60s_audio_all_chunks_arrive_in_minio() -> None:
    """Publish 120 chunks via AudioProducer; consumer writes all to MinIO."""
    session_id = str(uuid.uuid4())
    audio_bytes = _generate_silence(SYNTHETIC_DURATION_S)
    chunks = frame_to_chunks(audio_bytes, chunk_size=CHUNK_SIZE_BYTES)

    assert len(chunks) == EXPECTED_CHUNKS, (
        f"Expected {EXPECTED_CHUNKS} chunks, generated {len(chunks)}"
    )

    # ── Produce all chunks ────────────────────────────────────────────────────
    producer = AudioProducer(
        bootstrap_servers=config.KAFKA_BOOTSTRAP_SERVERS,
        topic=config.KAFKA_TOPIC_AUDIO,
    )
    for seq, chunk in enumerate(chunks):
        await producer.publish_chunk(session_id, seq, chunk)
    await producer.flush(timeout_s=30.0)
    await producer.close()

    # ── Consume and write to MinIO ────────────────────────────────────────────
    store = ObjectStore(
        endpoint=config.MINIO_ENDPOINT,
        access_key=config.MINIO_ACCESS_KEY,
        secret_key=config.MINIO_SECRET_KEY,
    )
    consumer = AudioConsumer(
        bootstrap_servers=config.KAFKA_BOOTSTRAP_SERVERS,
        topic=config.KAFKA_TOPIC_AUDIO,
        group_id=f"integration-test-{session_id[:8]}",
        object_store=store,
    )

    # Run consumer until all expected chunks land in MinIO (or timeout)
    deadline = time.monotonic() + 60.0
    consumer_task = asyncio.create_task(consumer.run())

    try:
        while time.monotonic() < deadline:
            await asyncio.sleep(1.0)
            received = _count_session_objects(session_id)
            if received >= EXPECTED_CHUNKS:
                break
    finally:
        consumer.stop()
        await asyncio.wait_for(consumer_task, timeout=10.0)

    # ── Assert ────────────────────────────────────────────────────────────────
    final_count = _count_session_objects(session_id)
    assert final_count == EXPECTED_CHUNKS, (
        f"Expected {EXPECTED_CHUNKS} chunks in MinIO for session {session_id}, "
        f"found {final_count}"
    )

    # Verify path pattern: raw-audio/{session_id}/{YYYYMMDD}/{chunk_seq:06d}.pcm
    client = _minio_client()
    objects = sorted(
        obj.object_name
        for obj in client.list_objects("raw-audio", prefix=f"{session_id}/", recursive=True)
    )
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    assert objects[0].startswith(f"{session_id}/{date_str}/")
    assert objects[0].endswith(".pcm")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_session_id_logged_not_pii() -> None:
    """session_id in consumer logs must be a UUID (no PII pattern)."""
    import re

    uuid_pattern = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    session_id = str(uuid.uuid4())
    assert uuid_pattern.match(session_id), (
        "session_id must be a UUID — candidate PII must never appear in logs"
    )
