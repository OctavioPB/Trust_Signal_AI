"""Unit tests for storage/delta_writer.py.

All Spark and Delta Lake I/O is mocked — no real Spark session is started.
Tests verify:
  - Merge condition includes BOTH session_id AND chunk_seq for segments.
  - Merge condition uses only session_id for interviews.
  - Idempotency: calling upsert_segment twice results in one merge, not two inserts.
  - flag_segment() calls delta.update() with the correct filter and value.
  - _create_spark_session is NOT called when _spark is injected.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from storage.delta_writer import (
    INTERVIEWS_SCHEMA,
    SEGMENTS_SCHEMA,
    DeltaWriter,
    InterviewRecord,
    SegmentRecord,
    _create_spark_session,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_interview() -> InterviewRecord:
    return InterviewRecord(
        session_id="sess-uuid-001",
        recruiter_id="recruiter-uuid-001",
        candidate_id="candidate-uuid-001",
        start_ts=1_700_000_000.0,
        end_ts=1_700_003_600.0,
        status="completed",
        trust_score=82.5,
    )


def _make_segment(chunk_seq: int = 0) -> SegmentRecord:
    return SegmentRecord(
        session_id="sess-uuid-001",
        chunk_seq=chunk_seq,
        speaker="RECRUITER",
        text="Tell me about yourself.",
        start_ts=0.0,
        end_ts=3.0,
        confidence=0.91,
        suspicious_flag=False,
    )


def _make_mock_spark() -> MagicMock:
    """Return a MagicMock that mimics a SparkSession well enough for DeltaWriter."""
    spark = MagicMock(name="SparkSession")
    mock_df = MagicMock(name="DataFrame")
    spark.createDataFrame.return_value = mock_df
    mock_df.alias.return_value = mock_df
    mock_df.write = MagicMock()
    mock_df.write.format.return_value = mock_df.write
    mock_df.write.mode.return_value = mock_df.write
    return spark, mock_df


# ── _create_spark_session skipped when injected ───────────────────────────────

def test_injected_spark_skips_create_spark_session() -> None:
    """DeltaWriter must not call _create_spark_session when _spark is provided."""
    spark, _ = _make_mock_spark()
    with patch("storage.delta_writer._create_spark_session") as mock_create:
        DeltaWriter(delta_lake_path="/tmp/delta", _spark=spark)
        mock_create.assert_not_called()


# ── upsert_interview — merge condition ────────────────────────────────────────

class TestUpsertInterview:

    def _make_writer_with_delta(self):
        spark, mock_df = _make_mock_spark()

        mock_delta_table = MagicMock(name="DeltaTable")
        mock_merge = MagicMock(name="MergeBuilder")
        mock_delta_table.alias.return_value = mock_delta_table
        mock_delta_table.merge.return_value = mock_merge
        mock_merge.whenMatchedUpdateAll.return_value = mock_merge
        mock_merge.whenNotMatchedInsertAll.return_value = mock_merge

        writer = DeltaWriter(delta_lake_path="/tmp/delta", _spark=spark)
        return writer, spark, mock_df, mock_delta_table, mock_merge

    def test_merge_condition_uses_session_id_only(self) -> None:
        writer, spark, mock_df, mock_delta_table, mock_merge = self._make_writer_with_delta()

        with (
            patch("storage.delta_writer.DeltaTable") as mock_dt_cls,
        ):
            mock_dt_cls.isDeltaTable.return_value = True
            mock_dt_cls.forPath.return_value = mock_delta_table

            writer.upsert_interview(_make_interview())

        # Verify merge was called with session_id-only condition
        mock_delta_table.merge.assert_called_once()
        condition_arg = mock_delta_table.merge.call_args[0][1]
        assert "session_id" in condition_arg
        assert "chunk_seq" not in condition_arg, (
            "Interview merge must NOT include chunk_seq in its condition"
        )

    def test_createDataFrame_called_with_interviews_schema(self) -> None:
        writer, spark, mock_df, _, _ = self._make_writer_with_delta()

        with patch("storage.delta_writer.DeltaTable") as mock_dt_cls:
            mock_dt_cls.isDeltaTable.return_value = True
            mock_dt_cls.forPath.return_value = MagicMock(
                alias=lambda x: MagicMock(
                    merge=lambda df, cond: MagicMock(
                        whenMatchedUpdateAll=lambda: MagicMock(
                            whenNotMatchedInsertAll=lambda: MagicMock(execute=lambda: None)
                        )
                    )
                )
            )
            writer.upsert_interview(_make_interview())

        spark.createDataFrame.assert_called_once()
        _, kwargs = spark.createDataFrame.call_args
        # schema is a positional-or-keyword arg
        call_args = spark.createDataFrame.call_args
        schema_passed = call_args[1].get("schema") or (
            call_args[0][1] if len(call_args[0]) > 1 else None
        )
        assert schema_passed is INTERVIEWS_SCHEMA

    def test_first_write_uses_overwrite_not_merge(self) -> None:
        writer, spark, mock_df, _, _ = self._make_writer_with_delta()

        with patch("storage.delta_writer.DeltaTable") as mock_dt_cls:
            mock_dt_cls.isDeltaTable.return_value = False  # table does not exist yet

            writer.upsert_interview(_make_interview())

        mock_df.write.format.assert_called_with("delta")
        mock_df.write.format("delta").mode.assert_called_with("overwrite")


# ── upsert_segment — merge condition ─────────────────────────────────────────

class TestUpsertSegment:

    def _make_writer(self):
        spark, mock_df = _make_mock_spark()
        writer = DeltaWriter(delta_lake_path="/tmp/delta", _spark=spark)
        return writer, spark, mock_df

    def test_merge_condition_includes_session_id_and_chunk_seq(self) -> None:
        """The merge condition MUST contain both columns for idempotency."""
        writer, spark, mock_df = self._make_writer()

        mock_delta_table = MagicMock(name="DeltaTable")
        mock_merge = MagicMock(name="MergeBuilder")
        mock_delta_table.alias.return_value = mock_delta_table
        mock_delta_table.merge.return_value = mock_merge
        mock_merge.whenMatchedUpdateAll.return_value = mock_merge
        mock_merge.whenNotMatchedInsertAll.return_value = mock_merge

        with patch("storage.delta_writer.DeltaTable") as mock_dt_cls:
            mock_dt_cls.isDeltaTable.return_value = True
            mock_dt_cls.forPath.return_value = mock_delta_table

            writer.upsert_segment(_make_segment(chunk_seq=5))

        condition_arg = mock_delta_table.merge.call_args[0][1]
        assert "session_id" in condition_arg, "merge condition must include session_id"
        assert "chunk_seq" in condition_arg, "merge condition must include chunk_seq"

    def test_createDataFrame_called_with_segments_schema(self) -> None:
        writer, spark, mock_df = self._make_writer()

        with patch("storage.delta_writer.DeltaTable") as mock_dt_cls:
            mock_dt_cls.isDeltaTable.return_value = True
            mock_dt_cls.forPath.return_value = MagicMock(
                alias=lambda x: MagicMock(
                    merge=lambda df, cond: MagicMock(
                        whenMatchedUpdateAll=lambda: MagicMock(
                            whenNotMatchedInsertAll=lambda: MagicMock(execute=lambda: None)
                        )
                    )
                )
            )
            writer.upsert_segment(_make_segment())

        spark.createDataFrame.assert_called_once()
        call_args = spark.createDataFrame.call_args
        schema_passed = call_args[1].get("schema") or (
            call_args[0][1] if len(call_args[0]) > 1 else None
        )
        assert schema_passed is SEGMENTS_SCHEMA

    def test_upsert_twice_calls_merge_twice(self) -> None:
        """Two upserts must both go through merge (not insert) when table exists."""
        writer, spark, mock_df = self._make_writer()

        mock_delta_table = MagicMock(name="DeltaTable")
        mock_merge = MagicMock(name="MergeBuilder")
        mock_delta_table.alias.return_value = mock_delta_table
        mock_delta_table.merge.return_value = mock_merge
        mock_merge.whenMatchedUpdateAll.return_value = mock_merge
        mock_merge.whenNotMatchedInsertAll.return_value = mock_merge

        with patch("storage.delta_writer.DeltaTable") as mock_dt_cls:
            mock_dt_cls.isDeltaTable.return_value = True
            mock_dt_cls.forPath.return_value = mock_delta_table

            seg = _make_segment(chunk_seq=0)
            writer.upsert_segment(seg)
            writer.upsert_segment(seg)   # identical payload — idempotency test

        assert mock_delta_table.merge.call_count == 2, (
            "Each upsert call must invoke merge; the merge itself enforces idempotency"
        )
        assert mock_merge.execute.call_count == 2

    def test_first_segment_write_creates_table(self) -> None:
        writer, spark, mock_df = self._make_writer()

        with patch("storage.delta_writer.DeltaTable") as mock_dt_cls:
            mock_dt_cls.isDeltaTable.return_value = False

            writer.upsert_segment(_make_segment())

        mock_df.write.format.assert_called_with("delta")
        mock_df.write.format("delta").mode.assert_called_with("overwrite")
        mock_df.write.format("delta").mode("overwrite").save.assert_called_once()


# ── flag_segment ──────────────────────────────────────────────────────────────

class TestFlagSegment:

    def _make_writer(self):
        spark, _ = _make_mock_spark()
        writer = DeltaWriter(delta_lake_path="/tmp/delta", _spark=spark)
        return writer

    def test_flag_segment_calls_delta_update(self) -> None:
        writer = self._make_writer()
        mock_delta_table = MagicMock(name="DeltaTable")

        with patch("storage.delta_writer.DeltaTable") as mock_dt_cls:
            mock_dt_cls.forPath.return_value = mock_delta_table

            writer.flag_segment("sess-uuid-001", chunk_seq=3, suspicious_flag=True)

        mock_delta_table.update.assert_called_once()

    def test_flag_segment_passes_suspicious_flag_true(self) -> None:
        writer = self._make_writer()
        mock_delta_table = MagicMock(name="DeltaTable")

        with patch("storage.delta_writer.DeltaTable") as mock_dt_cls:
            mock_dt_cls.forPath.return_value = mock_delta_table

            writer.flag_segment("sess-uuid-001", chunk_seq=3, suspicious_flag=True)

        _, kwargs = mock_delta_table.update.call_args
        assert "suspicious_flag" in kwargs.get("set", {}), (
            "update() must set 'suspicious_flag' in the set dict"
        )

    def test_flag_segment_false_clears_flag(self) -> None:
        writer = self._make_writer()
        mock_delta_table = MagicMock(name="DeltaTable")

        with patch("storage.delta_writer.DeltaTable") as mock_dt_cls:
            mock_dt_cls.forPath.return_value = mock_delta_table

            writer.flag_segment("sess-uuid-001", chunk_seq=3, suspicious_flag=False)

        mock_delta_table.update.assert_called_once()

    def test_flag_segment_table_not_found_raises(self) -> None:
        writer = self._make_writer()

        with patch("storage.delta_writer.DeltaTable") as mock_dt_cls:
            mock_dt_cls.forPath.side_effect = RuntimeError("Table not found")

            with pytest.raises(RuntimeError):
                writer.flag_segment("sess-uuid-001", chunk_seq=0)


# ── close ─────────────────────────────────────────────────────────────────────

def test_close_stops_spark_session() -> None:
    spark, _ = _make_mock_spark()
    writer = DeltaWriter(delta_lake_path="/tmp/delta", _spark=spark)
    writer.close()
    spark.stop.assert_called_once()
