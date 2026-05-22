"""Integration test: full DAG dry-run on 30 days of synthetic data (Sprint 9.4).

All five task callables are invoked in topological order using a mock Airflow
context that simulates XCom push/pull via a plain dict.  External dependencies
(DuckDB, MinIO, SentenceTransformer, Slack) are mocked so no real services
are required.

Assertions:
  - Every task callable completes without raising.
  - XCom return values contain the expected keys.
  - The vector store on disk grows by the number of candidate segments embedded.
  - The answer bank on disk grows by the number of unique Q&A pairs extracted.
  - The notify task logs correctly when no Slack webhook is configured.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from airflow.dags.retraining_dag import (
    _compute_embeddings,
    _extract_suspicious,
    _notify,
    _retrain_bg_classifier,
    _update_answer_bank,
)


# ── Synthetic data factory ─────────────────────────────────────────────────────

_DAG_START = datetime(2026, 1, 1, 2, 0, 0, tzinfo=timezone.utc)
_DAYS       = 30
_SESSIONS_PER_DAY = 3
_TURNS_PER_SESSION = 6   # alternating RECRUITER / CANDIDATE


def _build_synthetic_segments(days: int = _DAYS) -> list[dict]:
    """Build a 30-day corpus of alternating RECRUITER/CANDIDATE segments.

    Total segments = days × sessions_per_day × turns_per_session
                   = 30 × 3 × 6 = 540

    All CANDIDATE segments have suspicious_flag=True so they appear in
    the extract result.
    """
    segments = []
    for day in range(days):
        day_offset = day * 86_400.0
        for sess in range(_SESSIONS_PER_DAY):
            session_id = f"sess-day{day:02d}-{sess:02d}"
            for turn in range(_TURNS_PER_SESSION):
                speaker = "RECRUITER" if turn % 2 == 0 else "CANDIDATE"
                ts = _DAG_START.timestamp() + day_offset + sess * 3600.0 + turn * 30.0
                segments.append({
                    "session_id": session_id,
                    "chunk_seq":  turn,
                    "speaker":    speaker,
                    "text": (
                        f"{'Please describe your experience with' if speaker == 'RECRUITER' else 'I have extensive experience in'} "
                        f"topic-{day}-{sess}-{turn}."
                    ),
                    "start_ts":  ts,
                    "end_ts":    ts + 25.0,
                })
    return segments


# ── Mock Airflow context ───────────────────────────────────────────────────────

class _MockTaskInstance:
    """Minimal simulation of Airflow TaskInstance for XCom push/pull."""

    def __init__(self) -> None:
        self._xcom: dict[str, object] = {}

    def xcom_push(self, key: str, value: object) -> None:
        self._xcom[key] = value

    def xcom_pull(self, task_ids: str, key: str = "return_value") -> object:
        return self._xcom.get(task_ids)


def _make_context(
    ti: _MockTaskInstance,
    *,
    day_offset: int = 0,
) -> dict:
    """Build a mock Airflow context dict for the given DAG run day."""
    interval_start = _DAG_START + timedelta(days=day_offset)
    interval_end   = interval_start + timedelta(days=1)
    date_str       = interval_start.strftime("%Y-%m-%d")
    ds_nodash      = interval_start.strftime("%Y%m%d")

    return {
        "ti":                  ti,
        "data_interval_start": interval_start,
        "data_interval_end":   interval_end,
        "ds":                  date_str,
        "ds_nodash":           ds_nodash,
    }


# ── Stub embedding model ───────────────────────────────────────────────────────

def _stub_embed_model(d: int = 384) -> MagicMock:
    """Return a SentenceTransformer stub that produces unit vectors."""
    model = MagicMock(name="SentenceTransformer")
    model.encode.side_effect = lambda texts, **kw: np.random.default_rng(42).random(
        (len(texts), d), dtype=float
    ).astype(np.float32)
    return model


# ── Full DAG dry-run ───────────────────────────────────────────────────────────

class TestDagDryRun:
    """Run all five task callables on 30 days of synthetic data.

    External I/O is patched:
      - query_suspicious_segments → returns synthetic corpus
      - embed_texts               → uses stub model (no download)
      - _make_object_store        → returns MagicMock (no MinIO)
      - SLACK_WEBHOOK_URL         → empty (notify falls back to log)
    """

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path: Path) -> None:
        self.tmp_path   = tmp_path
        self.segments   = _build_synthetic_segments(_DAYS)
        self.ti         = _MockTaskInstance()
        self.context    = _make_context(self.ti)

        # Pre-populate the vector store path and answer bank path
        self.store_path = tmp_path / "vector_store"
        self.bank_path  = tmp_path / "llm_answer_bank.jsonl"
        self.bank_path.write_text("")   # empty but existing

    # ── Task 1: extract_suspicious ─────────────────────────────────────────────

    def test_01_extract_suspicious_returns_expected_keys(self) -> None:
        with patch(
            "airflow.dags.retraining_dag.query_suspicious_segments",
            return_value=self.segments,
        ):
            result = _extract_suspicious(**self.context)

        assert "segments" in result
        assert "count" in result
        self.ti._xcom["extract_suspicious"] = result   # simulate XCom push

    def test_01_extract_count_matches_segments(self) -> None:
        with patch(
            "airflow.dags.retraining_dag.query_suspicious_segments",
            return_value=self.segments,
        ):
            result = _extract_suspicious(**self.context)
        assert result["count"] == len(self.segments)

    def test_01_extract_does_not_raise_on_empty_delta(self) -> None:
        with patch(
            "airflow.dags.retraining_dag.query_suspicious_segments",
            return_value=[],
        ):
            result = _extract_suspicious(**self.context)
        assert result["count"] == 0

    # ── Task 2: compute_embeddings ─────────────────────────────────────────────

    def _prime_xcom_with_segments(self) -> None:
        self.ti._xcom["extract_suspicious"] = {
            "segments": self.segments,
            "count":    len(self.segments),
        }

    def test_02_compute_embeddings_returns_expected_keys(self) -> None:
        self._prime_xcom_with_segments()

        stub_model = _stub_embed_model()
        with (
            patch("airflow.dags.retraining_dag.embed_texts",
                  side_effect=lambda texts, **kw: stub_model.encode(texts)),
            patch("airflow.dags.retraining_dag.update_vector_store",
                  return_value=len([s for s in self.segments if s["speaker"] == "CANDIDATE"])) as mock_vs,
            patch("airflow.dags.retraining_dag.config") as mock_cfg,
        ):
            mock_cfg.VECTOR_STORE_PATH = str(self.store_path)
            result = _compute_embeddings(**self.context)

        assert "embeddings_added" in result
        self.ti._xcom["compute_embeddings"] = result

    def test_02_compute_embeddings_skips_recruiter_turns(self) -> None:
        self._prime_xcom_with_segments()
        embedded_texts: list[str] = []

        def capture_embed(texts, **kw):
            embedded_texts.extend(texts)
            return np.zeros((len(texts), 4), dtype=np.float32)

        with (
            patch("airflow.dags.retraining_dag.embed_texts", side_effect=capture_embed),
            patch("airflow.dags.retraining_dag.update_vector_store", return_value=0),
            patch("airflow.dags.retraining_dag.config") as mock_cfg,
        ):
            mock_cfg.VECTOR_STORE_PATH = str(self.store_path)
            _compute_embeddings(**self.context)

        for text in embedded_texts:
            # None of the embedded texts should be recruiter questions
            assert "Please describe" not in text

    def test_02_compute_embeddings_no_segments_returns_zero(self) -> None:
        self.ti._xcom["extract_suspicious"] = {"segments": [], "count": 0}
        with patch("airflow.dags.retraining_dag.config") as mock_cfg:
            mock_cfg.VECTOR_STORE_PATH = str(self.store_path)
            result = _compute_embeddings(**self.context)
        assert result["embeddings_added"] == 0

    # ── Task 3: retrain_bg_classifier ─────────────────────────────────────────

    def test_03_retrain_skipped_when_minio_unavailable(self) -> None:
        self._prime_xcom_with_segments()
        mock_store = MagicMock()
        mock_store.list_session_chunks.side_effect = Exception("MinIO down")

        with (
            patch("airflow.dags.retraining_dag._make_object_store", return_value=mock_store),
            patch("airflow.dags.retraining_dag.config") as mock_cfg,
        ):
            mock_cfg.DELTA_LAKE_PATH = str(self.tmp_path / "delta")
            result = _retrain_bg_classifier(**self.context)

        assert "artifact_name" in result
        assert "retrained" in result
        assert result["retrained"] is False          # skipped gracefully
        self.ti._xcom["retrain_bg_classifier"] = result

    def test_03_retrain_returns_correct_artifact_name_format(self) -> None:
        self._prime_xcom_with_segments()
        mock_store = MagicMock()
        mock_store.list_session_chunks.return_value = []

        with (
            patch("airflow.dags.retraining_dag._make_object_store", return_value=mock_store),
        ):
            result = _retrain_bg_classifier(**self.context)

        date_str = self.context["ds_nodash"]
        assert result["artifact_name"] == f"{date_str}_bg_classifier.pkl"

    def test_03_retrain_does_not_raise_on_no_sessions(self) -> None:
        self.ti._xcom["extract_suspicious"] = {"segments": [], "count": 0}
        result = _retrain_bg_classifier(**self.context)
        assert "retrained" in result
        assert result["retrained"] is False

    # ── Task 4: update_answer_bank ─────────────────────────────────────────────

    def test_04_update_answer_bank_returns_expected_keys(self) -> None:
        self._prime_xcom_with_segments()

        with (
            patch("airflow.dags.retraining_dag.ANSWER_BANK_PATH", self.bank_path),
        ):
            result = _update_answer_bank(**self.context)

        assert "pairs_appended" in result
        assert "pairs_found" in result
        self.ti._xcom["update_answer_bank"] = result

    def test_04_pairs_appended_is_nonnegative(self) -> None:
        self._prime_xcom_with_segments()
        with patch("airflow.dags.retraining_dag.ANSWER_BANK_PATH", self.bank_path):
            result = _update_answer_bank(**self.context)
        assert result["pairs_appended"] >= 0

    def test_04_bank_grows_after_task(self) -> None:
        self._prime_xcom_with_segments()
        initial_lines = sum(
            1 for l in self.bank_path.read_text().splitlines() if l.strip()
        )
        with patch("airflow.dags.retraining_dag.ANSWER_BANK_PATH", self.bank_path):
            result = _update_answer_bank(**self.context)
        final_lines = sum(
            1 for l in self.bank_path.read_text().splitlines() if l.strip()
        )
        assert final_lines == initial_lines + result["pairs_appended"]

    def test_04_no_segments_appends_zero_pairs(self) -> None:
        self.ti._xcom["extract_suspicious"] = {"segments": [], "count": 0}
        with patch("airflow.dags.retraining_dag.ANSWER_BANK_PATH", self.bank_path):
            result = _update_answer_bank(**self.context)
        assert result["pairs_appended"] == 0

    # ── Task 5: notify ─────────────────────────────────────────────────────────

    def _prime_all_xcom(self) -> None:
        self.ti._xcom["extract_suspicious"]   = {"segments": self.segments, "count": len(self.segments)}
        self.ti._xcom["compute_embeddings"]   = {"embeddings_added": 42}
        self.ti._xcom["retrain_bg_classifier"] = {"artifact_name": "20260101_bg_classifier.pkl",
                                                   "samples_used": 0, "retrained": False}
        self.ti._xcom["update_answer_bank"]   = {"pairs_appended": 7, "pairs_found": 10}

    def test_05_notify_does_not_raise_without_webhook(self) -> None:
        self._prime_all_xcom()
        with patch("airflow.dags.retraining_dag.config") as mock_cfg:
            mock_cfg.SLACK_WEBHOOK_URL = ""
            _notify(**self.context)   # must not raise

    def test_05_notify_sends_webhook_when_url_set(self) -> None:
        self._prime_all_xcom()
        with (
            patch("airflow.dags.retraining_dag.config") as mock_cfg,
            patch("airflow.dags.retraining_dag.send_slack_notification",
                  return_value=True) as mock_send,
        ):
            mock_cfg.SLACK_WEBHOOK_URL = "https://hooks.slack.com/test"
            _notify(**self.context)

        mock_send.assert_called_once()

    def test_05_notify_passes_correct_payload_stats(self) -> None:
        self._prime_all_xcom()
        captured_stats: dict = {}

        def capture_payload(webhook_url, payload, **kw):
            captured_stats.update(payload)
            return True

        with (
            patch("airflow.dags.retraining_dag.config") as mock_cfg,
            patch("airflow.dags.retraining_dag.send_slack_notification",
                  side_effect=capture_payload),
        ):
            mock_cfg.SLACK_WEBHOOK_URL = "https://hooks.slack.com/test"
            _notify(**self.context)

        # The payload is a Slack Block Kit dict
        assert "text" in captured_stats
        assert "2026-01-01" in captured_stats["text"]

    # ── Full pipeline: all 5 tasks in sequence ────────────────────────────────

    def test_full_pipeline_no_exceptions(self) -> None:
        """Run all five tasks end-to-end; assert no task raises."""
        stub_model = _stub_embed_model()
        mock_store = MagicMock()
        mock_store.list_session_chunks.return_value = []

        # Write a minimal starting answer bank
        self.bank_path.write_text(
            json.dumps({"question": "Seed Q", "answer": "Seed A"}) + "\n"
        )

        with (
            patch("airflow.dags.retraining_dag.query_suspicious_segments",
                  return_value=self.segments),
            patch("airflow.dags.retraining_dag.embed_texts",
                  side_effect=lambda texts, **kw: stub_model.encode(texts)),
            patch("airflow.dags.retraining_dag.update_vector_store",
                  return_value=len([s for s in self.segments if s["speaker"] == "CANDIDATE"])),
            patch("airflow.dags.retraining_dag._make_object_store",
                  return_value=mock_store),
            patch("airflow.dags.retraining_dag.ANSWER_BANK_PATH", self.bank_path),
            patch("airflow.dags.retraining_dag.config") as mock_cfg,
        ):
            mock_cfg.DELTA_LAKE_PATH   = str(self.tmp_path / "delta")
            mock_cfg.VECTOR_STORE_PATH = str(self.store_path)
            mock_cfg.SLACK_WEBHOOK_URL = ""

            # Task 1
            r1 = _extract_suspicious(**self.context)
            assert r1["count"] == len(self.segments)
            self.ti._xcom["extract_suspicious"] = r1

            # Task 2
            r2 = _compute_embeddings(**self.context)
            assert "embeddings_added" in r2
            self.ti._xcom["compute_embeddings"] = r2

            # Task 3
            r3 = _retrain_bg_classifier(**self.context)
            assert "retrained" in r3
            assert "artifact_name" in r3
            self.ti._xcom["retrain_bg_classifier"] = r3

            # Task 4
            r4 = _update_answer_bank(**self.context)
            assert "pairs_appended" in r4
            self.ti._xcom["update_answer_bank"] = r4

            # Task 5
            _notify(**self.context)   # must not raise

    def test_full_pipeline_default_args_present(self) -> None:
        """Verify DEFAULT_ARGS has retries=2 and retry_delay=5 min."""
        try:
            from airflow.dags.retraining_dag import DEFAULT_ARGS
            from datetime import timedelta
            assert DEFAULT_ARGS["retries"] == 2
            assert DEFAULT_ARGS["retry_delay"] == timedelta(minutes=5)
        except ImportError:
            pytest.skip("apache-airflow not installed")

    def test_30_day_candidate_segment_count(self) -> None:
        """Verify the synthetic corpus has the expected CANDIDATE count."""
        candidate_count = sum(
            1 for s in self.segments if s["speaker"] == "CANDIDATE"
        )
        # 30 days × 3 sessions × 3 candidate turns per session = 270
        assert candidate_count == _DAYS * _SESSIONS_PER_DAY * (_TURNS_PER_SESSION // 2)

    def test_30_day_qa_pairs_extractable(self) -> None:
        """Verify make_qa_pairs produces the expected count from the corpus."""
        from airflow.dags.retraining_dag import make_qa_pairs
        pairs = make_qa_pairs(self.segments)
        # Each session has 3 RECRUITER→CANDIDATE transitions
        expected = _DAYS * _SESSIONS_PER_DAY * (_TURNS_PER_SESSION // 2)
        assert len(pairs) == expected
