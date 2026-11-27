"""Human review log for flagged sessions — the only source of training labels.

The nightly retraining DAG must never learn from the system's own flags (that is a
feedback loop: a false positive would be trained in as a true positive and make
similar honest answers look more suspicious the next night). Instead, a recruiter
or reviewer adjudicates each flag through ``POST /session/{id}/review`` and the DAG
trains only on sessions that carry a review:

    confirmed  → AI assistance confirmed by a human  → positive label
    cleared    → flag was a false positive            → negative label

Storage: an append-only log of one small Parquet file per review under
``{DELTA_LAKE_PATH}/session_reviews/date=YYYY-MM-DD/``. It is written with DuckDB
(no Spark session in the API process) and read by the DAG with ``parquet_scan``,
exactly as it reads ``transcript_segments``. A later review of the same session
supersedes the earlier one; nothing is ever updated in place.

Schema (one row per file):
    session_id    VARCHAR  UUID — no PII
    verdict       VARCHAR  "confirmed" | "cleared"
    reviewer_key  VARCHAR  first 16 hex chars of sha256(reviewer id) — pseudonymous,
                           so audits can count reviewers without storing identities
    reviewed_at   DOUBLE   Unix timestamp
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, get_args

import structlog

logger = structlog.get_logger(__name__)

TABLE_REVIEWS = "session_reviews"

Verdict = Literal["confirmed", "cleared"]
VERDICTS: tuple[Verdict, ...] = get_args(Verdict)


def reviewer_key(reviewer_id: str) -> str:
    """Pseudonymous, stable key for a reviewer (never the raw identifier)."""
    return hashlib.sha256(reviewer_id.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class ReviewRecord:
    """One human adjudication of a scored session."""

    session_id: str
    verdict: Verdict
    reviewer_key: str
    reviewed_at: float


class ReviewStore:
    """Appends review records as Parquet files readable by ``parquet_scan``.

    Args:
        delta_lake_path: Base directory for all lake tables (``DELTA_LAKE_PATH``).
        _conn: Optional DuckDB connection (tests).
    """

    def __init__(self, delta_lake_path: str, _conn: Any = None) -> None:
        self._table_path = Path(delta_lake_path) / TABLE_REVIEWS
        self._conn = _conn
        self._log = logger.bind(component="ReviewStore")

    @property
    def table_glob(self) -> str:
        return f"{self._table_path.as_posix()}/**/*.parquet"

    def append(
        self,
        session_id: str,
        verdict: str,
        reviewer_id: str,
        reviewed_at: float | None = None,
    ) -> ReviewRecord:
        """Write one review. Append-only: earlier reviews are kept for the audit trail.

        Raises:
            ValueError: ``verdict`` is not ``confirmed`` or ``cleared``.
            OSError / duckdb.Error: the file could not be written.
        """
        if verdict not in VERDICTS:
            raise ValueError(f"verdict must be one of {VERDICTS}, got {verdict!r}")
        record = ReviewRecord(
            session_id=session_id,
            verdict=verdict,  # type: ignore[arg-type]
            reviewer_key=reviewer_key(reviewer_id),
            reviewed_at=reviewed_at if reviewed_at is not None else time.time(),
        )

        day = datetime.fromtimestamp(record.reviewed_at, tz=UTC).strftime("%Y-%m-%d")
        out_dir = self._table_path / f"date={day}"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"{uuid.uuid4().hex}.parquet"

        import duckdb

        # COPY cannot bind its target path; the name is ours (uuid) and quotes are escaped.
        target = out_file.as_posix().replace("'", "''")
        conn = self._conn or duckdb.connect()
        try:
            conn.execute(
                "COPY (SELECT ?::VARCHAR AS session_id, ?::VARCHAR AS verdict, "
                "?::VARCHAR AS reviewer_key, ?::DOUBLE AS reviewed_at) "
                f"TO '{target}' (FORMAT PARQUET)",  # noqa: S608 - values are bound
                [record.session_id, record.verdict, record.reviewer_key, record.reviewed_at],
            )
        finally:
            if self._conn is None:
                conn.close()

        self._log.info(
            "session_review_recorded",
            session_id=record.session_id,  # UUID — no PII
            verdict=record.verdict,
        )
        return record
