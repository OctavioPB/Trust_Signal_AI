"""DeltaLake store for crawled repository file metadata — Sprint 16.

Provides idempotent upsert operations for the ``repo_artifacts`` Delta table,
used by the code AI-detection pipeline (Sprints 16–17).

Each row represents one source file from one crawl run. The merge key is
``(repo_uuid, file_path)`` so that re-crawling a repository updates the
existing rows rather than creating duplicates.

Schema: repo_uuid, file_path, language, content_hash, commit_count, crawled_at.
Source code content is stored in MinIO (``repos/`` bucket), not in Delta Lake.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)

TABLE_ARTIFACTS = "repo_artifacts"

# ── Dataclass ──────────────────────────────────────────────────────────────────


@dataclass
class RepoArtifactRecord:
    """Row schema for the repo_artifacts Delta table.

    Attributes:
        repo_uuid: uuid5(NAMESPACE_URL, repo_url) — primary key component, no PII.
        file_path: Relative path within the repository — primary key component.
        language: Detected programming language (derived from file extension).
        content_hash: SHA-256 hex digest of the stored file content.
        commit_count: Number of commits in the repository at crawl time.
        crawled_at: Unix timestamp of the crawl.
    """

    repo_uuid: str
    file_path: str
    language: str
    content_hash: str
    commit_count: int
    crawled_at: float = 0.0

    def __post_init__(self) -> None:
        if not self.crawled_at:
            self.crawled_at = time.time()


# ── Spark session factory ──────────────────────────────────────────────────────


def _create_spark_session(master: str):
    from delta import configure_spark_with_delta_pip  # type: ignore[import]
    from pyspark.sql import SparkSession

    builder = (
        SparkSession.builder.master(master)
        .appName("TrustSignal-RepoArtifactStore")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config(
            "spark.sql.catalog.spark_catalog",
            "org.apache.spark.sql.delta.catalog.DeltaCatalog",
        )
        .config("spark.databricks.delta.retentionDurationCheck.enabled", "false")
        .config("spark.sql.shuffle.partitions", "4")
    )
    return configure_spark_with_delta_pip(builder).getOrCreate()


# ── RepoArtifactStore ──────────────────────────────────────────────────────────


class RepoArtifactStore:
    """Idempotent upsert writer for the repo_artifacts Delta table.

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
        _spark=None,
    ) -> None:
        self._table_path = f"{delta_lake_path.rstrip('/')}/{TABLE_ARTIFACTS}"
        self._spark = _spark or _create_spark_session(spark_master)
        self._log = logger.bind(
            component="RepoArtifactStore", table_path=self._table_path
        )

    def upsert_artifact(self, record: RepoArtifactRecord) -> None:
        """Idempotently upsert a repo file artifact by (repo_uuid, file_path).

        Writing the same (repo_uuid, file_path) pair twice updates the existing
        row rather than creating a duplicate.

        Args:
            record: Artifact metadata to persist.
        """
        from pyspark.sql.types import (
            DoubleType,
            IntegerType,
            StringType,
            StructField,
            StructType,
        )

        schema = StructType(
            [
                StructField("repo_uuid",     StringType(),  False),
                StructField("file_path",     StringType(),  False),
                StructField("language",      StringType(),  True),
                StructField("content_hash",  StringType(),  True),
                StructField("commit_count",  IntegerType(), True),
                StructField("crawled_at",    DoubleType(),  False),
            ]
        )

        row = {
            "repo_uuid":    record.repo_uuid,
            "file_path":    record.file_path,
            "language":     record.language,
            "content_hash": record.content_hash,
            "commit_count": int(record.commit_count),
            "crawled_at":   float(record.crawled_at),
        }
        df = self._spark.createDataFrame([row], schema=schema)
        self._upsert(
            df,
            merge_condition=(
                "t.repo_uuid = s.repo_uuid AND t.file_path = s.file_path"
            ),
        )
        self._log.info(
            "repo_artifact_upserted",
            repo_uuid=record.repo_uuid,  # UUID — no PII
            language=record.language,
        )

    def close(self) -> None:
        """Stop the Spark session."""
        self._spark.stop()
        self._log.info("repo_artifact_store_closed")

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
