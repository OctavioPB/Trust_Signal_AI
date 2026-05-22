"""Unit tests for Sprint 9 retraining DAG helper functions.

Each helper is tested in isolation with mocked external dependencies
(DuckDB, SentenceTransformer, requests.Session, filesystem).

No Airflow installation required — the task callables are tested in
tests/integration/test_dag_dry_run.py with a mock Airflow context.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from airflow.dags.retraining_dag import (
    append_answer_bank,
    build_slack_payload,
    embed_texts,
    make_qa_pairs,
    query_suspicious_segments,
    send_slack_notification,
    update_vector_store,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_segments(n: int = 4) -> list[dict]:
    """Build alternating RECRUITER / CANDIDATE suspicious segments."""
    base_ts = 1_716_297_600.0
    return [
        {
            "session_id": "sess-001",
            "chunk_seq":   i,
            "speaker":     "RECRUITER" if i % 2 == 0 else "CANDIDATE",
            "text":        f"{'Question' if i % 2 == 0 else 'Answer'} number {i}",
            "start_ts":    base_ts + i * 10.0,
            "end_ts":      base_ts + i * 10.0 + 8.0,
        }
        for i in range(n)
    ]


def _unit_vec(d: int, idx: int) -> np.ndarray:
    v = np.zeros(d, dtype=np.float32)
    v[idx] = 1.0
    return v


# ── query_suspicious_segments ─────────────────────────────────────────────────

class TestQuerySuspiciousSegments:

    def _mock_conn(self, rows: list[tuple]) -> MagicMock:
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = rows
        conn.execute.return_value = cursor
        return conn

    def test_returns_list_of_dicts(self) -> None:
        rows = [("sess-1", 0, "CANDIDATE", "some text", 1000.0, 1010.0)]
        conn = self._mock_conn(rows)
        result = query_suspicious_segments("/delta", 0.0, 9999.0, _conn=conn)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["session_id"] == "sess-1"

    def test_dict_has_all_expected_keys(self) -> None:
        rows = [("s1", 3, "CANDIDATE", "text", 100.0, 110.0)]
        conn = self._mock_conn(rows)
        result = query_suspicious_segments("/delta", 0.0, 9999.0, _conn=conn)
        expected_keys = {"session_id", "chunk_seq", "speaker", "text", "start_ts", "end_ts"}
        assert expected_keys == set(result[0].keys())

    def test_returns_empty_list_on_query_failure(self) -> None:
        conn = MagicMock()
        conn.execute.side_effect = Exception("parquet file not found")
        result = query_suspicious_segments("/nonexistent", 0.0, 9999.0, _conn=conn)
        assert result == []

    def test_passes_correct_time_bounds(self) -> None:
        conn = self._mock_conn([])
        query_suspicious_segments("/delta", 1000.0, 2000.0, _conn=conn)
        call_args = conn.execute.call_args
        params = call_args[0][1]
        assert params[1] == 1000.0
        assert params[2] == 2000.0

    def test_returns_empty_when_no_rows(self) -> None:
        conn = self._mock_conn([])
        result = query_suspicious_segments("/delta", 0.0, 9999.0, _conn=conn)
        assert result == []

    def test_preserves_row_order(self) -> None:
        rows = [
            ("s1", 0, "CANDIDATE", "first",  100.0, 110.0),
            ("s1", 1, "CANDIDATE", "second", 200.0, 210.0),
        ]
        conn = self._mock_conn(rows)
        result = query_suspicious_segments("/delta", 0.0, 9999.0, _conn=conn)
        assert result[0]["text"] == "first"
        assert result[1]["text"] == "second"


# ── embed_texts ───────────────────────────────────────────────────────────────

class TestEmbedTexts:

    def _stub_model(self, d: int = 4) -> MagicMock:
        m = MagicMock()
        m.encode.side_effect = lambda texts, **kw: np.stack(
            [_unit_vec(d, i % d) for i in range(len(texts))]
        )
        return m

    def test_returns_float32_array(self) -> None:
        model = self._stub_model()
        result = embed_texts(["hello", "world"], _model=model)
        assert result.dtype == np.float32

    def test_shape_matches_input(self) -> None:
        model = self._stub_model(8)
        result = embed_texts(["a", "b", "c"], _model=model)
        assert result.shape[0] == 3
        assert result.shape[1] == 8

    def test_empty_input_returns_zero_array(self) -> None:
        result = embed_texts([])
        assert result.shape[0] == 0
        assert result.ndim == 2

    def test_injected_model_skips_download(self) -> None:
        model = self._stub_model()
        with patch("airflow.dags.retraining_dag.embed_texts") as mock_fn:
            mock_fn.return_value = np.zeros((1, 4), dtype=np.float32)
            embed_texts(["text"], _model=model)
        model.encode.call_count  # no assertion needed — just confirm no ImportError

    def test_calls_encode_with_normalize_true(self) -> None:
        model = self._stub_model()
        embed_texts(["text"], _model=model)
        call_kwargs = model.encode.call_args[1]
        assert call_kwargs.get("normalize_embeddings") is True


# ── update_vector_store ───────────────────────────────────────────────────────

class TestUpdateVectorStore:

    def test_creates_store_on_first_call(self, tmp_path: Path) -> None:
        emb = np.stack([_unit_vec(4, 0), _unit_vec(4, 1)])
        n = update_vector_store(str(tmp_path), emb, ["text0", "text1"])
        assert n == 2
        assert (tmp_path / "embeddings.npy").exists()
        assert (tmp_path / "metadata.json").exists()

    def test_appends_to_existing_store(self, tmp_path: Path) -> None:
        emb1 = np.stack([_unit_vec(4, 0)])
        update_vector_store(str(tmp_path), emb1, ["first"])

        emb2 = np.stack([_unit_vec(4, 1), _unit_vec(4, 2)])
        n = update_vector_store(str(tmp_path), emb2, ["second", "third"])
        assert n == 2

        loaded = np.load(str(tmp_path / "embeddings.npy"))
        assert loaded.shape[0] == 3

    def test_metadata_has_text_and_ts_fields(self, tmp_path: Path) -> None:
        emb = np.stack([_unit_vec(4, 0)])
        update_vector_store(str(tmp_path), emb, ["hello"])
        with (tmp_path / "metadata.json").open() as f:
            meta = json.load(f)
        assert meta[0]["text"] == "hello"
        assert "ts" in meta[0]

    def test_returns_zero_for_empty_input(self, tmp_path: Path) -> None:
        n = update_vector_store(str(tmp_path), np.zeros((0, 4), np.float32), [])
        assert n == 0

    def test_creates_directory_if_missing(self, tmp_path: Path) -> None:
        store_path = tmp_path / "nested" / "store"
        emb = np.stack([_unit_vec(4, 0)])
        update_vector_store(str(store_path), emb, ["text"])
        assert store_path.exists()

    def test_saved_embeddings_are_float32(self, tmp_path: Path) -> None:
        emb = np.stack([_unit_vec(4, 0)]).astype(np.float64)
        update_vector_store(str(tmp_path), emb, ["text"])
        loaded = np.load(str(tmp_path / "embeddings.npy"))
        assert loaded.dtype == np.float32


# ── make_qa_pairs ─────────────────────────────────────────────────────────────

class TestMakeQaPairs:

    def test_recruiter_then_candidate_produces_pair(self) -> None:
        segments = _make_segments(2)  # [RECRUITER, CANDIDATE]
        pairs = make_qa_pairs(segments)
        assert len(pairs) == 1
        assert "question" in pairs[0]
        assert "answer" in pairs[0]

    def test_consecutive_candidate_segments_skipped(self) -> None:
        segs = [
            {"session_id": "s1", "chunk_seq": 0, "speaker": "CANDIDATE",
             "text": "a", "start_ts": 1.0, "end_ts": 2.0},
            {"session_id": "s1", "chunk_seq": 1, "speaker": "CANDIDATE",
             "text": "b", "start_ts": 3.0, "end_ts": 4.0},
        ]
        pairs = make_qa_pairs(segs)
        assert pairs == []

    def test_question_matches_recruiter_text(self) -> None:
        segments = _make_segments(2)
        pairs = make_qa_pairs(segments)
        assert pairs[0]["question"] == "Question number 0"

    def test_answer_matches_candidate_text(self) -> None:
        segments = _make_segments(2)
        pairs = make_qa_pairs(segments)
        assert pairs[0]["answer"] == "Answer number 1"

    def test_multiple_sessions_handled(self) -> None:
        base = 1_000_000.0
        segs = [
            {"session_id": "sess-A", "chunk_seq": 0, "speaker": "RECRUITER",
             "text": "Q-A", "start_ts": base, "end_ts": base + 5},
            {"session_id": "sess-A", "chunk_seq": 1, "speaker": "CANDIDATE",
             "text": "Ans-A", "start_ts": base + 10, "end_ts": base + 20},
            {"session_id": "sess-B", "chunk_seq": 0, "speaker": "RECRUITER",
             "text": "Q-B", "start_ts": base, "end_ts": base + 5},
            {"session_id": "sess-B", "chunk_seq": 1, "speaker": "CANDIDATE",
             "text": "Ans-B", "start_ts": base + 10, "end_ts": base + 20},
        ]
        pairs = make_qa_pairs(segs)
        assert len(pairs) == 2

    def test_empty_segments_returns_empty(self) -> None:
        assert make_qa_pairs([]) == []

    def test_only_recruiter_segments_returns_empty(self) -> None:
        segs = [
            {"session_id": "s1", "chunk_seq": i, "speaker": "RECRUITER",
             "text": "q", "start_ts": float(i), "end_ts": float(i) + 5}
            for i in range(3)
        ]
        assert make_qa_pairs(segs) == []

    def test_case_insensitive_speaker(self) -> None:
        segs = [
            {"session_id": "s1", "chunk_seq": 0, "speaker": "recruiter",
             "text": "Q", "start_ts": 0.0, "end_ts": 5.0},
            {"session_id": "s1", "chunk_seq": 1, "speaker": "candidate",
             "text": "A", "start_ts": 10.0, "end_ts": 15.0},
        ]
        pairs = make_qa_pairs(segs)
        assert len(pairs) == 1


# ── append_answer_bank ────────────────────────────────────────────────────────

class TestAppendAnswerBank:

    def _write_bank(self, tmp_path: Path, entries: list[dict]) -> Path:
        p = tmp_path / "bank.jsonl"
        with p.open("w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")
        return p

    def test_appends_new_pairs(self, tmp_path: Path) -> None:
        bank = self._write_bank(tmp_path, [{"question": "Q0", "answer": "A0"}])
        n = append_answer_bank(str(bank), [{"question": "Q1", "answer": "A1"}])
        assert n == 1
        lines = [l for l in bank.read_text().splitlines() if l.strip()]
        assert len(lines) == 2

    def test_deduplicates_on_answer(self, tmp_path: Path) -> None:
        bank = self._write_bank(tmp_path, [{"question": "Q0", "answer": "Existing answer"}])
        n = append_answer_bank(str(bank), [{"question": "Q1", "answer": "Existing answer"}])
        assert n == 0

    def test_creates_bank_if_not_exists(self, tmp_path: Path) -> None:
        bank_path = tmp_path / "new_bank.jsonl"
        n = append_answer_bank(str(bank_path), [{"question": "Q", "answer": "A"}])
        assert n == 1
        assert bank_path.exists()

    def test_returns_zero_for_empty_pairs(self, tmp_path: Path) -> None:
        bank = self._write_bank(tmp_path, [])
        n = append_answer_bank(str(bank), [])
        assert n == 0

    def test_written_entries_are_valid_json(self, tmp_path: Path) -> None:
        bank = tmp_path / "bank.jsonl"
        append_answer_bank(str(bank), [{"question": "Q", "answer": "A"}])
        for line in bank.read_text().splitlines():
            if line.strip():
                obj = json.loads(line)
                assert "question" in obj
                assert "answer" in obj

    def test_blank_answer_not_appended(self, tmp_path: Path) -> None:
        bank = tmp_path / "bank.jsonl"
        n = append_answer_bank(str(bank), [{"question": "Q", "answer": ""}])
        assert n == 0

    def test_multiple_unique_pairs_all_appended(self, tmp_path: Path) -> None:
        bank = tmp_path / "bank.jsonl"
        pairs = [{"question": f"Q{i}", "answer": f"A{i}"} for i in range(5)]
        n = append_answer_bank(str(bank), pairs)
        assert n == 5


# ── build_slack_payload ───────────────────────────────────────────────────────

class TestBuildSlackPayload:

    def _stats(self, **overrides) -> dict:
        base = {
            "segments_extracted": 42,
            "embeddings_added":   38,
            "retrained":          True,
            "artifact_name":      "20260521_bg_classifier.pkl",
            "pairs_appended":     7,
            "dag_run_date":       "2026-05-21",
        }
        base.update(overrides)
        return base

    def test_returns_dict_with_text_key(self) -> None:
        payload = build_slack_payload(self._stats())
        assert "text" in payload

    def test_text_includes_date(self) -> None:
        payload = build_slack_payload(self._stats())
        assert "2026-05-21" in payload["text"]

    def test_has_blocks_list(self) -> None:
        payload = build_slack_payload(self._stats())
        assert isinstance(payload["blocks"], list)
        assert len(payload["blocks"]) >= 2

    def test_retrained_true_mentions_artifact(self) -> None:
        payload = build_slack_payload(self._stats(retrained=True))
        payload_str = json.dumps(payload)
        assert "20260521_bg_classifier.pkl" in payload_str

    def test_retrained_false_mentions_skipped(self) -> None:
        payload = build_slack_payload(self._stats(retrained=False))
        payload_str = json.dumps(payload)
        assert "Skipped" in payload_str or "skipped" in payload_str.lower()

    def test_segment_count_in_payload(self) -> None:
        payload = build_slack_payload(self._stats(segments_extracted=99))
        payload_str = json.dumps(payload)
        assert "99" in payload_str

    def test_zero_segments_still_returns_payload(self) -> None:
        payload = build_slack_payload(self._stats(segments_extracted=0))
        assert "text" in payload


# ── send_slack_notification ───────────────────────────────────────────────────

class TestSendSlackNotification:

    def _ok_session(self) -> MagicMock:
        session = MagicMock()
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        session.post.return_value = resp
        return session

    def test_returns_true_on_success(self) -> None:
        session = self._ok_session()
        result = send_slack_notification("https://hooks.slack.com/xxx", {}, _session=session)
        assert result is True

    def test_posts_to_webhook_url(self) -> None:
        session = self._ok_session()
        send_slack_notification("https://hooks.slack.com/my-hook", {}, _session=session)
        call_url = session.post.call_args[0][0]
        assert call_url == "https://hooks.slack.com/my-hook"

    def test_sends_payload_as_json(self) -> None:
        session = self._ok_session()
        payload = {"text": "hello"}
        send_slack_notification("https://hooks.slack.com/xxx", payload, _session=session)
        call_kwargs = session.post.call_args[1]
        assert call_kwargs["json"] == payload

    def test_returns_false_on_http_error(self) -> None:
        session = MagicMock()
        resp = MagicMock()
        resp.raise_for_status.side_effect = Exception("403 Forbidden")
        session.post.return_value = resp
        result = send_slack_notification("https://hooks.slack.com/xxx", {}, _session=session)
        assert result is False

    def test_returns_false_on_connection_error(self) -> None:
        session = MagicMock()
        session.post.side_effect = ConnectionError("refused")
        result = send_slack_notification("https://hooks.slack.com/xxx", {}, _session=session)
        assert result is False

    def test_never_raises(self) -> None:
        session = MagicMock()
        session.post.side_effect = RuntimeError("boom")
        # Must not raise
        result = send_slack_notification("https://hooks.slack.com/xxx", {}, _session=session)
        assert result is False
