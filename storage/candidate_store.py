"""Candidate profile persistence to Delta Lake (ACID).

Provides idempotent upsert operations for the candidate_profiles Delta table,
used by the pre-screening pipeline (Sprints 14–18).

Designed for batch and DAG use — SparkSession startup is ~10 s and unsuitable
for hot API paths. The FastAPI candidates router maintains its own in-memory
state; this module is the authoritative durable store consumed by Airflow DAGs
and the nightly scoring pipelines.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import structlog
from pyspark.sql import SparkSession
from pyspark.sql.types import (
    DoubleType,
    StringType,
    StructField,
    StructType,
)

logger = structlog.get_logger(__name__)

TABLE_CANDIDATES = "candidate_profiles"

CANDIDATES_SCHEMA = StructType(
    [
        StructField("candidate_uuid", StringType(), nullable=False),
        StructField("status",         StringType(), nullable=False),
        StructField("created_at",     DoubleType(), nullable=False),
        StructField("resume_path",    StringType(), nullable=True),
        StructField("repo_urls",      StringType(), nullable=True),  # JSON-encoded list
    ]
)


# ── Dataclass ──────────────────────────────────────────────────────────────────

@dataclass
class CandidateRecord:
    """Row schema for the candidate_profiles Delta table.

    Attributes:
        candidate_uuid: UUID — primary key (no PII).
        status: "pending" | "screened" | "flagged".
        created_at: Unix timestamp of profile creation.
        resume_path: MinIO object path (None until a resume is uploaded).
        repo_urls: List of linked GitHub repository URLs.
    """

    candidate_uuid: str
    status: str = "pending"
    created_at: float = field(default_factory=time.time)
    resume_path: str | None = None
    repo_urls: list[str] = field(default_factory=list)


# ── Spark session factory ──────────────────────────────────────────────────────

def _create_spark_session(master: str) -> SparkSession:
    """Build a Delta-Lake-enabled SparkSession (mirrors delta_writer.py)."""
    from delta import configure_spark_with_delta_pip  # type: ignore[import]

    builder = (
        SparkSession.builder.master(master)
        .appName("TrustSignal-CandidateStore")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config(
            "spark.sql.catalog.spark_catalog",
            "org.apache.spark.sql.delta.catalog.DeltaCatalog",
        )
        .config("spark.databricks.delta.retentionDurationCheck.enabled", "false")
        .config("spark.sql.shuffle.partitions", "4")
    )
    return configure_spark_with_delta_pip(builder).getOrCreate()


# ── CandidateStore ─────────────────────────────────────────────────────────────

class CandidateStore:
    """Idempotent upsert writer for the candidate_profiles Delta table.

    Accepts an optional pre-built SparkSession via ``_spark`` — used in unit
    tests to inject a mock without triggering real Spark startup.

    Args:
        delta_lake_path: Base path where Delta tables are stored.
        spark_master: Spark master URL, e.g. "local[*]".
        _spark: Optional pre-built SparkSession (for testing).
    """

    def __init__(
        self,
        delta_lake_path: str,
        spark_master: str = "local[*]",
        _spark: SparkSession | None = None,
    ) -> None:
        self._table_path = f"{delta_lake_path.rstrip('/')}/{TABLE_CANDIDATES}"
        self._spark = _spark or _create_spark_session(spark_master)
        self._log = logger.bind(component="CandidateStore", table_path=self._table_path)

    def upsert_candidate(self, record: CandidateRecord) -> None:
        """Idempotently upsert a candidate profile by candidate_uuid.

        Writing the same candidate_uuid twice updates the existing row rather
        than creating a duplicate.

        Args:
            record: Candidate profile to persist.
        """
        row = {
            "candidate_uuid": record.candidate_uuid,
            "status":         record.status,
            "created_at":     record.created_at,
            "resume_path":    record.resume_path,
            "repo_urls":      json.dumps(record.repo_urls),
        }
        df = self._spark.createDataFrame([row], schema=CANDIDATES_SCHEMA)
        self._upsert(df, merge_condition="t.candidate_uuid = s.candidate_uuid")
        self._log.info(
            "candidate_upserted",
            candidate_uuid=record.candidate_uuid,  # UUID — no PII
            status=record.status,
        )

    def close(self) -> None:
        """Stop the Spark session."""
        self._spark.stop()
        self._log.info("candidate_store_closed")

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _upsert(self, df, merge_condition: str) -> None:
        """Run a Delta merge; create the table from the DataFrame if absent."""
        from delta import DeltaTable  # type: ignore[import]

        if DeltaTable.isDeltaTable(self._spark, self._table_path):
            (
                DeltaTable.forPath(self._spark, self._table_path)
                .alias("t")
                .merge(df.alias("s"), merge_condition)
                .whenMatchedUpdateAll()
                .whenNotMatchedInsertAll()
                .execute()
            )
        else:
            df.write.format("delta").mode("overwrite").save(self._table_path)
            self._log.info("delta_table_created", path=self._table_path)
