"""DeltaLake persistence for candidate pre-screening scores — Sprint 18.

Writes to the ``candidate_prescreening`` table using append mode.
Each row captures one scoring run identified by (candidate_uuid, scored_at),
preserving the full audit trail per CLAUDE.md §8.4.

Table schema:
    candidate_uuid        StringType   non-nullable  UUID — no PII
    prescreening_score    DoubleType   non-nullable  0–100
    resume_ai_score       DoubleType   non-nullable  0–100
    repo_ai_score         DoubleType   nullable      null when no repo linked
    interview_trust_score DoubleType   nullable      null when interview absent
    suspicion_index       DoubleType   non-nullable  0–1
    flagged               BooleanType  non-nullable
    severity              StringType   non-nullable  "low" | "medium" | "high"
    flag_reason           StringType   nullable
    signals_json          StringType   nullable      JSON list of signal details
    scored_at             DoubleType   non-nullable  Unix timestamp
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

TABLE_PRESCREENING = "candidate_prescreening"


# ── Data class ─────────────────────────────────────────────────────────────────

@dataclass
class PreScreeningRecord:
    """One row for the candidate_prescreening Delta Lake table.

    Attributes:
        candidate_uuid: UUID of the candidate (no PII).
        prescreening_score: Aggregated score in [0, 100].
        resume_ai_score: Resume signal score in [0, 100].
        repo_ai_score: Repo signal score, or None.
        interview_trust_score: Interview score, or None.
        suspicion_index: Weighted suspicion in [0, 1].
        flagged: True when above threshold.
        severity: "low", "medium", or "high".
        flag_reason: Non-empty explanation when flagged.
        signals_json: JSON-serialised list of signal detail dicts.
        scored_at: Unix timestamp of score computation.
    """

    candidate_uuid: str
    prescreening_score: float
    resume_ai_score: float
    repo_ai_score: float | None
    interview_trust_score: float | None
    suspicion_index: float
    flagged: bool
    severity: str
    flag_reason: str
    signals_json: str
    scored_at: float


# ── Store ───────────────────────────────────────────────────────────────────────

class PreScreeningStore:
    """Appends pre-screening score records to the Delta Lake table.

    Args:
        delta_lake_path: Base directory for all Delta Lake tables.
        spark_master: Spark master URL (default ``"local[*]"`` for local mode).
        _spark: Optional pre-built SparkSession for test injection.
    """

    def __init__(
        self,
        delta_lake_path: str,
        spark_master: str = "local[*]",
        _spark: Any = None,
    ) -> None:
        self._base_path  = delta_lake_path
        self._table_path = f"{delta_lake_path}/{TABLE_PRESCREENING}"
        self._spark      = _spark
        self._master     = spark_master
        self._log        = logger.bind(component="PreScreeningStore")

    def _get_spark(self) -> Any:
        if self._spark is not None:
            return self._spark
        from pyspark.sql import SparkSession
        self._spark = (
            SparkSession.builder
            .master(self._master)
            .appName("TrustSignal-PreScreening")
            .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
            .config(
                "spark.sql.catalog.spark_catalog",
                "org.apache.spark.sql.delta.catalog.DeltaCatalog",
            )
            .getOrCreate()
        )
        return self._spark

    def append_record(self, record: PreScreeningRecord) -> None:
        """Append a pre-screening score record to the Delta Lake table.

        Append-only: existing rows are never modified. The audit trail of all
        historical scores is preserved per CLAUDE.md §8.4.

        Args:
            record: A PreScreeningRecord to write.
        """
        from pyspark.sql.types import (
            BooleanType,
            DoubleType,
            StringType,
            StructField,
            StructType,
        )

        schema = StructType([
            StructField("candidate_uuid",        StringType(),  False),
            StructField("prescreening_score",    DoubleType(),  False),
            StructField("resume_ai_score",       DoubleType(),  False),
            StructField("repo_ai_score",         DoubleType(),  True),
            StructField("interview_trust_score", DoubleType(),  True),
            StructField("suspicion_index",       DoubleType(),  False),
            StructField("flagged",               BooleanType(), False),
            StructField("severity",              StringType(),  False),
            StructField("flag_reason",           StringType(),  True),
            StructField("signals_json",          StringType(),  True),
            StructField("scored_at",             DoubleType(),  False),
        ])

        row = [(
            record.candidate_uuid,
            float(record.prescreening_score),
            float(record.resume_ai_score),
            float(record.repo_ai_score) if record.repo_ai_score is not None else None,
            float(record.interview_trust_score) if record.interview_trust_score is not None else None,
            float(record.suspicion_index),
            bool(record.flagged),
            record.severity,
            record.flag_reason or None,
            record.signals_json or None,
            float(record.scored_at),
        )]

        spark = self._get_spark()
        df = spark.createDataFrame(row, schema=schema)
        df.write.format("delta").mode("append").save(self._table_path)

        self._log.info(
            "prescreening_record_appended",
            candidate_uuid=record.candidate_uuid,   # UUID — no PII
            prescreening_score=record.prescreening_score,
            flagged=record.flagged,
            severity=record.severity,
        )

    def close(self) -> None:
        """Stop the SparkSession if it was created by this store instance."""
        if self._spark is not None:
            try:
                self._spark.stop()
            except Exception:
                pass
            self._spark = None
            self._log.info("prescreening_store_closed")


# ── Convenience builder ─────────────────────────────────────────────────────────

def build_record_from_result(
    result: Any,          # PreScreeningResult — avoids circular import at type level
    resume_ai_score: float,
    repo_ai_score: float | None,
    interview_trust_score: float | None,
) -> PreScreeningRecord:
    """Construct a PreScreeningRecord from a PreScreeningResult.

    Args:
        result: PreScreeningResult from PreScreeningEngine.compute().
        resume_ai_score: Raw resume score in [0, 100] (re-passed for the row).
        repo_ai_score: Raw repo score in [0, 100] or None.
        interview_trust_score: Raw interview trust score in [0, 100] or None.

    Returns:
        PreScreeningRecord ready for PreScreeningStore.append_record().
    """
    signals_list = [
        {
            "signal_name":          s.signal_name,
            "raw_suspicion":        s.raw_suspicion,
            "weight":               s.weight,
            "weighted_contribution": s.weighted_contribution,
            "explanation":          s.explanation,
        }
        for s in result.signals
    ]
    return PreScreeningRecord(
        candidate_uuid=result.candidate_uuid,
        prescreening_score=result.prescreening_score,
        resume_ai_score=resume_ai_score,
        repo_ai_score=repo_ai_score,
        interview_trust_score=interview_trust_score,
        suspicion_index=result.suspicion_index,
        flagged=result.flagged,
        severity=result.severity,
        flag_reason=result.flag_reason,
        signals_json=json.dumps(signals_list),
        scored_at=result.scored_at,
    )
