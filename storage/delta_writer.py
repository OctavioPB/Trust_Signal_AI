"""Transcript and metadata persistence to Delta Lake (ACID).

Provides idempotent upsert operations for the interviews and
transcript_segments Delta tables, and a flag_segment() method used
by the ML pipeline to mark suspicious segments.

Sprint 4: Full implementation with PySpark + delta-spark merge logic.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    BooleanType,
    DoubleType,
    IntegerType,
    StringType,
    StructField,
    StructType,
)

logger = structlog.get_logger(__name__)

# Delta Lake table names (used as subfolder names under delta_lake_path)
TABLE_INTERVIEWS = "interviews"
TABLE_SEGMENTS = "transcript_segments"

# ── PySpark schemas ────────────────────────────────────────────────────────────

INTERVIEWS_SCHEMA = StructType(
    [
        StructField("session_id", StringType(), nullable=False),
        StructField("recruiter_id", StringType(), nullable=False),
        StructField("candidate_id", StringType(), nullable=False),
        StructField("start_ts", DoubleType(), nullable=False),
        StructField("end_ts", DoubleType(), nullable=True),
        StructField("status", StringType(), nullable=False),
        StructField("trust_score", DoubleType(), nullable=True),
    ]
)

SEGMENTS_SCHEMA = StructType(
    [
        StructField("session_id", StringType(), nullable=False),
        StructField("chunk_seq", IntegerType(), nullable=False),
        StructField("speaker", StringType(), nullable=False),
        StructField("text", StringType(), nullable=False),
        StructField("start_ts", DoubleType(), nullable=False),
        StructField("end_ts", DoubleType(), nullable=False),
        StructField("confidence", DoubleType(), nullable=False),
        StructField("suspicious_flag", BooleanType(), nullable=False),
    ]
)


# ── Dataclasses ────────────────────────────────────────────────────────────────

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


# ── Spark session factory (extracted for easy test mocking) ────────────────────

def _create_spark_session(master: str) -> SparkSession:
    """Build and return a Delta-Lake-enabled SparkSession.

    Args:
        master: Spark master URL, e.g. "local[*]" or "spark://host:7077".

    Returns:
        A configured SparkSession with Delta Lake extensions.
    """
    from delta import configure_spark_with_delta_pip  # type: ignore[import]

    builder = (
        SparkSession.builder.master(master)
        .appName("TrustSignal-DeltaWriter")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config(
            "spark.sql.catalog.spark_catalog",
            "org.apache.spark.sql.delta.catalog.DeltaCatalog",
        )
        .config("spark.databricks.delta.retentionDurationCheck.enabled", "false")
        .config("spark.sql.shuffle.partitions", "4")
    )
    return configure_spark_with_delta_pip(builder).getOrCreate()


# ── DeltaWriter ────────────────────────────────────────────────────────────────

class DeltaWriter:
    """Idempotent upsert writer for Delta Lake tables.

    Accepts an optional pre-built SparkSession via the ``_spark`` parameter —
    used in unit tests to inject a mock without triggering real Spark startup.

    Args:
        delta_lake_path: Base path where Delta tables are stored.
        spark_master: Spark master URL (e.g. "local[*]" or a remote URL).
        _spark: Optional pre-built SparkSession (for testing).
    """

    def __init__(
        self,
        delta_lake_path: str,
        spark_master: str = "local[*]",
        _spark: SparkSession | None = None,
    ) -> None:
        self._delta_lake_path = delta_lake_path.rstrip("/")
        self._interviews_path = f"{self._delta_lake_path}/{TABLE_INTERVIEWS}"
        self._segments_path = f"{self._delta_lake_path}/{TABLE_SEGMENTS}"
        self._spark = _spark or _create_spark_session(spark_master)
        self._log = logger.bind(
            component="DeltaWriter",
            delta_lake_path=delta_lake_path,
        )

    # ── Public API ─────────────────────────────────────────────────────────────

    def upsert_interview(self, record: InterviewRecord) -> None:
        """Idempotently upsert an interview record by session_id.

        Writing the same session_id twice updates the existing row rather than
        creating a duplicate.

        Args:
            record: Interview metadata to persist.
        """
        row = {
            "session_id": record.session_id,
            "recruiter_id": record.recruiter_id,
            "candidate_id": record.candidate_id,
            "start_ts": record.start_ts,
            "end_ts": record.end_ts,
            "status": record.status,
            "trust_score": record.trust_score,
        }
        df = self._spark.createDataFrame([row], schema=INTERVIEWS_SCHEMA)

        self._upsert(
            df=df,
            table_path=self._interviews_path,
            merge_condition="t.session_id = s.session_id",
        )
        self._log.info(
            "interview_upserted",
            session_id=record.session_id,   # UUID — no PII
            status=record.status,
        )

    def upsert_segment(self, record: SegmentRecord) -> None:
        """Idempotently upsert a transcript segment by (session_id, chunk_seq).

        Writing the same segment twice must produce exactly one row.

        Args:
            record: Transcript segment to persist.
        """
        row = {
            "session_id": record.session_id,
            "chunk_seq": record.chunk_seq,
            "speaker": record.speaker,
            "text": record.text,
            "start_ts": record.start_ts,
            "end_ts": record.end_ts,
            "confidence": record.confidence,
            "suspicious_flag": record.suspicious_flag,
        }
        df = self._spark.createDataFrame([row], schema=SEGMENTS_SCHEMA)

        self._upsert(
            df=df,
            table_path=self._segments_path,
            merge_condition="t.session_id = s.session_id AND t.chunk_seq = s.chunk_seq",
        )
        self._log.debug(
            "segment_upserted",
            session_id=record.session_id,   # UUID — no PII
            chunk_seq=record.chunk_seq,
        )

    def flag_segment(
        self,
        session_id: str,
        chunk_seq: int,
        suspicious_flag: bool = True,
    ) -> None:
        """Set the suspicious_flag on an existing segment row.

        Called by the ML pipeline after signal scoring. A human-readable
        explanation is surfaced via the API; the flag here drives the Airflow
        retraining DAG query.

        Args:
            session_id: UUID of the interview session.
            chunk_seq: Sequence number of the chunk to flag.
            suspicious_flag: True to mark suspicious; False to clear.
        """
        from delta import DeltaTable  # type: ignore[import]

        table_path = self._segments_path
        try:
            dt = DeltaTable.forPath(self._spark, table_path)
        except Exception as exc:
            self._log.error(
                "flag_segment_table_not_found",
                session_id=session_id,
                chunk_seq=chunk_seq,
                error=str(exc),
            )
            raise

        dt.update(
            condition=(
                F.col("session_id") == session_id
            ) & (F.col("chunk_seq") == chunk_seq),
            set={"suspicious_flag": F.lit(suspicious_flag)},
        )
        self._log.info(
            "segment_flagged",
            session_id=session_id,   # UUID — no PII
            chunk_seq=chunk_seq,
            suspicious_flag=suspicious_flag,
        )

    def close(self) -> None:
        """Stop the Spark session."""
        self._spark.stop()
        self._log.info("delta_writer_closed")

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _upsert(self, df, table_path: str, merge_condition: str) -> None:
        """Run a Delta merge (upsert) for the given DataFrame.

        Creates the table from the DataFrame if it does not yet exist.

        Args:
            df: Source DataFrame with new/updated rows.
            table_path: Absolute path to the Delta table directory.
            merge_condition: SQL expression matching target alias ``t`` and
                source alias ``s`` (e.g. "t.session_id = s.session_id").
        """
        from delta import DeltaTable  # type: ignore[import]

        if DeltaTable.isDeltaTable(self._spark, table_path):
            (
                DeltaTable.forPath(self._spark, table_path)
                .alias("t")
                .merge(df.alias("s"), merge_condition)
                .whenMatchedUpdateAll()
                .whenNotMatchedInsertAll()
                .execute()
            )
        else:
            # First write — create the table
            df.write.format("delta").mode("overwrite").save(table_path)
            self._log.info("delta_table_created", path=table_path)
