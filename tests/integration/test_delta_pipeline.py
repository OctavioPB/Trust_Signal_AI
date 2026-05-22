"""Integration test: Delta Lake writer idempotency + DuckDB schema query.

Requires:
    pip install pyspark delta-spark duckdb

Run with:
    pytest --run-integration -m integration tests/integration/test_delta_pipeline.py

Definition of Done (PLAN.md §4.7):
    - Writing the same SegmentRecord twice results in exactly one row.
    - InterviewRecord upsert correctly updates status and trust_score.
    - DuckDB can read the Delta Parquet files and see all expected columns.
    - flag_segment() flips suspicious_flag without creating a duplicate row.
"""

from __future__ import annotations

import os
import tempfile
import uuid

import duckdb
import pytest

from storage.delta_writer import (
    SEGMENTS_SCHEMA,
    DeltaWriter,
    InterviewRecord,
    SegmentRecord,
    _create_spark_session,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def spark_session():
    """Single Spark session shared across all tests in this module."""
    spark = _create_spark_session("local[2]")
    yield spark
    spark.stop()


@pytest.fixture()
def temp_delta_path():
    """Isolated temporary directory for each test's Delta tables."""
    with tempfile.TemporaryDirectory(prefix="ts_delta_test_") as tmpdir:
        yield tmpdir


@pytest.fixture()
def writer(spark_session, temp_delta_path):
    """DeltaWriter using the shared Spark session and a fresh temp path."""
    return DeltaWriter(delta_lake_path=temp_delta_path, _spark=spark_session)


def _make_session_id() -> str:
    return str(uuid.uuid4())


# ── Helpers ───────────────────────────────────────────────────────────────────

def _duckdb_count(table_path: str) -> int:
    """Return number of rows in a Delta table via DuckDB parquet_scan."""
    normalized = table_path.replace("\\", "/")
    con = duckdb.connect()
    try:
        return con.execute(
            f"SELECT COUNT(*) FROM parquet_scan('{normalized}/**/*.parquet')"
        ).fetchone()[0]
    finally:
        con.close()


def _duckdb_columns(table_path: str) -> set[str]:
    """Return column names of a Delta table via DuckDB parquet_scan."""
    normalized = table_path.replace("\\", "/")
    con = duckdb.connect()
    try:
        df = con.execute(
            f"SELECT * FROM parquet_scan('{normalized}/**/*.parquet') LIMIT 1"
        ).fetchdf()
        return set(df.columns)
    finally:
        con.close()


def _duckdb_fetch_all(table_path: str) -> list[dict]:
    """Return all rows from a Delta table via DuckDB as a list of dicts."""
    normalized = table_path.replace("\\", "/")
    con = duckdb.connect()
    try:
        df = con.execute(
            f"SELECT * FROM parquet_scan('{normalized}/**/*.parquet')"
        ).fetchdf()
        return df.to_dict(orient="records")
    finally:
        con.close()


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestSegmentIdempotency:

    def test_single_segment_produces_one_row(self, writer, temp_delta_path) -> None:
        seg = SegmentRecord(
            session_id=_make_session_id(),
            chunk_seq=0,
            speaker="RECRUITER",
            text="Tell me about yourself.",
            start_ts=0.0,
            end_ts=3.5,
            confidence=0.88,
        )
        writer.upsert_segment(seg)

        table_path = f"{temp_delta_path}/transcript_segments"
        assert _duckdb_count(table_path) == 1

    def test_duplicate_upsert_produces_one_row(self, writer, temp_delta_path) -> None:
        """Writing the same (session_id, chunk_seq) twice must yield exactly one row."""
        session_id = _make_session_id()
        seg = SegmentRecord(
            session_id=session_id,
            chunk_seq=0,
            speaker="RECRUITER",
            text="Tell me about yourself.",
            start_ts=0.0,
            end_ts=3.5,
            confidence=0.88,
        )
        writer.upsert_segment(seg)
        writer.upsert_segment(seg)   # identical — must not duplicate

        table_path = f"{temp_delta_path}/transcript_segments"
        assert _duckdb_count(table_path) == 1

    def test_upsert_updates_confidence_in_place(self, writer, temp_delta_path) -> None:
        """A second upsert with updated fields must update the existing row."""
        session_id = _make_session_id()
        seg = SegmentRecord(
            session_id=session_id,
            chunk_seq=0,
            speaker="RECRUITER",
            text="Tell me about yourself.",
            start_ts=0.0,
            end_ts=3.5,
            confidence=0.50,
        )
        writer.upsert_segment(seg)

        seg_updated = SegmentRecord(
            session_id=session_id,
            chunk_seq=0,
            speaker="RECRUITER",
            text="Tell me about yourself.",
            start_ts=0.0,
            end_ts=3.5,
            confidence=0.92,   # updated value
        )
        writer.upsert_segment(seg_updated)

        table_path = f"{temp_delta_path}/transcript_segments"
        rows = _duckdb_fetch_all(table_path)
        assert len(rows) == 1
        assert abs(rows[0]["confidence"] - 0.92) < 1e-6

    def test_different_chunk_seq_produces_two_rows(self, writer, temp_delta_path) -> None:
        session_id = _make_session_id()
        for seq in (0, 1):
            writer.upsert_segment(
                SegmentRecord(
                    session_id=session_id,
                    chunk_seq=seq,
                    speaker="RECRUITER",
                    text=f"segment {seq}",
                    start_ts=float(seq * 5),
                    end_ts=float(seq * 5 + 3),
                    confidence=0.9,
                )
            )

        table_path = f"{temp_delta_path}/transcript_segments"
        assert _duckdb_count(table_path) == 2


@pytest.mark.integration
class TestInterviewIdempotency:

    def test_single_interview_produces_one_row(self, writer, temp_delta_path) -> None:
        rec = InterviewRecord(
            session_id=_make_session_id(),
            recruiter_id=str(uuid.uuid4()),
            candidate_id=str(uuid.uuid4()),
            start_ts=1_700_000_000.0,
            status="live",
        )
        writer.upsert_interview(rec)

        table_path = f"{temp_delta_path}/interviews"
        assert _duckdb_count(table_path) == 1

    def test_duplicate_interview_upsert_produces_one_row(self, writer, temp_delta_path) -> None:
        session_id = _make_session_id()
        rec = InterviewRecord(
            session_id=session_id,
            recruiter_id=str(uuid.uuid4()),
            candidate_id=str(uuid.uuid4()),
            start_ts=1_700_000_000.0,
            status="live",
        )
        writer.upsert_interview(rec)
        writer.upsert_interview(rec)

        table_path = f"{temp_delta_path}/interviews"
        assert _duckdb_count(table_path) == 1

    def test_upsert_updates_status_and_trust_score(self, writer, temp_delta_path) -> None:
        session_id = _make_session_id()
        recruiter_id = str(uuid.uuid4())
        candidate_id = str(uuid.uuid4())

        writer.upsert_interview(InterviewRecord(
            session_id=session_id,
            recruiter_id=recruiter_id,
            candidate_id=candidate_id,
            start_ts=1_700_000_000.0,
            status="live",
        ))
        writer.upsert_interview(InterviewRecord(
            session_id=session_id,
            recruiter_id=recruiter_id,
            candidate_id=candidate_id,
            start_ts=1_700_000_000.0,
            end_ts=1_700_003_600.0,
            status="completed",
            trust_score=78.0,
        ))

        table_path = f"{temp_delta_path}/interviews"
        rows = _duckdb_fetch_all(table_path)
        assert len(rows) == 1
        assert rows[0]["status"] == "completed"
        assert abs(rows[0]["trust_score"] - 78.0) < 1e-6


@pytest.mark.integration
class TestDuckDBSchemaQuery:

    def test_segment_table_has_required_columns(self, writer, temp_delta_path) -> None:
        """DuckDB must see all expected columns in transcript_segments."""
        writer.upsert_segment(SegmentRecord(
            session_id=_make_session_id(),
            chunk_seq=0,
            speaker="CANDIDATE",
            text="I have five years of Python experience.",
            start_ts=5.0,
            end_ts=8.2,
            confidence=0.93,
        ))

        required = {
            "session_id", "chunk_seq", "speaker", "text",
            "start_ts", "end_ts", "confidence", "suspicious_flag",
        }
        table_path = f"{temp_delta_path}/transcript_segments"
        actual_cols = _duckdb_columns(table_path)
        assert required.issubset(actual_cols), (
            f"Missing columns: {required - actual_cols}"
        )

    def test_interview_table_has_required_columns(self, writer, temp_delta_path) -> None:
        writer.upsert_interview(InterviewRecord(
            session_id=_make_session_id(),
            recruiter_id=str(uuid.uuid4()),
            candidate_id=str(uuid.uuid4()),
            start_ts=1_700_000_000.0,
            status="live",
        ))

        required = {
            "session_id", "recruiter_id", "candidate_id",
            "start_ts", "end_ts", "status", "trust_score",
        }
        table_path = f"{temp_delta_path}/interviews"
        actual_cols = _duckdb_columns(table_path)
        assert required.issubset(actual_cols), (
            f"Missing columns: {required - actual_cols}"
        )


@pytest.mark.integration
class TestFlagSegmentIntegration:

    def test_flag_segment_sets_suspicious_flag(self, writer, temp_delta_path) -> None:
        session_id = _make_session_id()
        writer.upsert_segment(SegmentRecord(
            session_id=session_id,
            chunk_seq=0,
            speaker="CANDIDATE",
            text="Absolutely, I leverage synergies to drive value.",
            start_ts=10.0,
            end_ts=14.0,
            confidence=0.95,
            suspicious_flag=False,
        ))

        writer.flag_segment(session_id, chunk_seq=0, suspicious_flag=True)

        table_path = f"{temp_delta_path}/transcript_segments"
        rows = _duckdb_fetch_all(table_path)
        assert len(rows) == 1
        assert rows[0]["suspicious_flag"] is True

    def test_flag_segment_does_not_create_duplicate(self, writer, temp_delta_path) -> None:
        session_id = _make_session_id()
        writer.upsert_segment(SegmentRecord(
            session_id=session_id,
            chunk_seq=0,
            speaker="CANDIDATE",
            text="I synergize leveraged paradigms proactively.",
            start_ts=10.0,
            end_ts=14.0,
            confidence=0.95,
        ))
        writer.flag_segment(session_id, chunk_seq=0, suspicious_flag=True)

        table_path = f"{temp_delta_path}/transcript_segments"
        assert _duckdb_count(table_path) == 1
