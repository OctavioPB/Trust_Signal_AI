"""Transcript and metadata persistence to Delta Lake (ACID).

Provides idempotent upsert operations for the interviews and
transcript_segments tables. Implemented in Sprint 4.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)

# Delta Lake table names
TABLE_INTERVIEWS = "interviews"
TABLE_SEGMENTS = "transcript_segments"


@dataclass
class InterviewRecord:
    """Row schema for the interviews Delta table.

    Attributes:
        session_id: UUID — primary key (no PII).
        recruiter_id: UUID of the recruiter org.
        candidate_id: UUID of the candidate (anonymised).
        start_ts: Unix timestamp of call start.
        end_ts: Unix timestamp of call end (None if still live).
        status: "live" | "completed" | "flagged".
        trust_score: Final aggregated score 0–100 (None until call ends).
    """

    session_id: str
    recruiter_id: str
    candidate_id: str
    start_ts: float
    end_ts: float | None = None
    status: str = "live"
    trust_score: float | None = None


@dataclass
class SegmentRecord:
    """Row schema for the transcript_segments Delta table."""

    session_id: str
    chunk_seq: int
    speaker: str
    text: str
    start_ts: float
    end_ts: float
    confidence: float
    suspicious_flag: bool = False


class DeltaWriter:
    """Idempotent upsert writer for Delta Lake tables.

    Args:
        delta_lake_path: Base path where Delta tables are stored.
        spark_master: Spark master URL (e.g. "spark://spark-master:7077").
    """

    def __init__(self, delta_lake_path: str, spark_master: str = "local[*]") -> None:
        raise NotImplementedError  # Sprint 4

    def upsert_interview(self, record: InterviewRecord) -> None:
        """Idempotently upsert an interview record by session_id.

        Args:
            record: Interview metadata to persist.
        """
        raise NotImplementedError  # Sprint 4

    def upsert_segment(self, record: SegmentRecord) -> None:
        """Idempotently upsert a transcript segment by (session_id, chunk_seq).

        Writing the same segment twice must produce exactly one row.

        Args:
            record: Transcript segment to persist.
        """
        raise NotImplementedError  # Sprint 4

    def close(self) -> None:
        """Stop the Spark session."""
        raise NotImplementedError  # Sprint 4
