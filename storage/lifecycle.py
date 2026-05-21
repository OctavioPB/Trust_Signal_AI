"""MinIO lifecycle policy: auto-delete raw audio after 90 days.

Implements CLAUDE.md Hard Rule #7 — all audio in the raw-audio bucket must be
deleted within 90 days unless the customer opts into extended retention.

Call apply_raw_audio_lifecycle() once during service initialisation or as part
of the infrastructure bootstrap (smoke_test.sh can verify it's set).
"""

from __future__ import annotations

import structlog
from minio import Minio
from minio.commonconfig import ENABLED, Filter
from minio.lifecycleconfig import Expiration, LifecycleConfig, Rule

from storage.object_store import BUCKET_RAW_AUDIO, _strip_protocol

logger = structlog.get_logger(__name__)

DEFAULT_RETENTION_DAYS = 90   # CLAUDE.md §8 rule 7


def apply_raw_audio_lifecycle(
    endpoint: str,
    access_key: str,
    secret_key: str,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    secure: bool = False,
) -> None:
    """Apply a 90-day expiry lifecycle rule to the raw-audio bucket.

    Safe to call repeatedly — MinIO replaces the existing lifecycle config
    on each call, so this operation is idempotent.

    Args:
        endpoint: MinIO endpoint URL, e.g. "http://localhost:9000".
        access_key: MinIO root user / AWS access key.
        secret_key: MinIO root password / AWS secret key.
        retention_days: Days before automatic object deletion (default 90).
        secure: Use TLS; set True for HTTPS endpoints in production.

    Raises:
        ValueError: If retention_days is not a positive integer.
        Exception: On MinIO API failure.
    """
    if not isinstance(retention_days, int) or retention_days < 1:
        raise ValueError(
            f"retention_days must be a positive integer, got {retention_days!r}"
        )

    client = Minio(
        _strip_protocol(endpoint),
        access_key=access_key,
        secret_key=secret_key,
        secure=secure,
    )

    lifecycle = LifecycleConfig(
        [
            Rule(
                ENABLED,
                rule_filter=Filter(prefix=""),   # applies to all objects in the bucket
                rule_id="raw-audio-auto-expire",
                expiration=Expiration(days=retention_days),
            )
        ]
    )

    client.set_bucket_lifecycle(BUCKET_RAW_AUDIO, lifecycle)

    logger.info(
        "lifecycle_applied",
        bucket=BUCKET_RAW_AUDIO,
        retention_days=retention_days,
        endpoint=endpoint,
    )
