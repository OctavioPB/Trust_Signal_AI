"""Human-review labelling loop: review store, review API, and DAG label sourcing.

Guards the fix for the retraining feedback loop: the nightly DAG must learn only
from human verdicts, never from the system's own flags.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import duckdb
import numpy as np
import pytest
from fastapi.testclient import TestClient
from jose import jwt

import config
from airflow.dags.retraining_dag import (
    _compute_embeddings,
    _retrain_bg_classifier,
    _update_answer_bank,
    query_reviewed_segments,
)
from api.main import _SESSIONS, app
from storage.review_store import ReviewStore, reviewer_key

# ── Helpers ────────────────────────────────────────────────────────────────────


def _token(recruiter_id: str) -> str:
    return jwt.encode(
        {"sub": recruiter_id, "exp": datetime.now(UTC) + timedelta(hours=1)},
        config.FASTAPI_SECRET_KEY,
        algorithm="HS256",
    )


class _TI:
    def __init__(self, xcom: dict[str, Any]) -> None:
        self._xcom = xcom

    def xcom_pull(self, task_ids: str) -> Any:
        return self._xcom.get(task_ids)


def _seg(session_id: str, speaker: str, text: str, verdict: str, ts: float = 1.0) -> dict:
    return {
        "session_id": session_id, "chunk_seq": int(ts), "speaker": speaker, "text": text,
        "start_ts": ts, "end_ts": ts + 1, "verdict": verdict,
    }


def _write_segments(base: Path, rows: list[tuple]) -> None:
    out = base / "transcript_segments" / "part-0.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE t (session_id VARCHAR, chunk_seq INTEGER, speaker VARCHAR, "
        "text VARCHAR, start_ts DOUBLE, end_ts DOUBLE, suspicious_flag BOOLEAN)"
    )
    con.executemany("INSERT INTO t VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    con.execute(f"COPY t TO '{out.as_posix()}' (FORMAT PARQUET)")
    con.close()


@pytest.fixture(autouse=True)
def _clear_sessions():
    _SESSIONS.clear()
    yield
    _SESSIONS.clear()


# ── ReviewStore ────────────────────────────────────────────────────────────────


class TestReviewStore:
    def test_append_is_readable_with_parquet_scan(self, tmp_path: Path) -> None:
        store = ReviewStore(str(tmp_path))
        store.append("s1", "confirmed", "rec-a", reviewed_at=100.0)
        store.append("s1", "cleared", "rec-b", reviewed_at=200.0)
        rows = duckdb.sql(
            f"SELECT session_id, verdict, reviewed_at FROM parquet_scan('{store.table_glob}') "
            "ORDER BY reviewed_at"
        ).fetchall()
        assert rows == [("s1", "confirmed", 100.0), ("s1", "cleared", 200.0)]

    def test_reviewer_identity_is_pseudonymous(self, tmp_path: Path) -> None:
        record = ReviewStore(str(tmp_path)).append("s1", "cleared", "recruiter-42")
        assert record.reviewer_key == reviewer_key("recruiter-42")
        assert "recruiter-42" not in record.reviewer_key
        assert len(record.reviewer_key) == 16

    def test_rejects_unknown_verdict(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            ReviewStore(str(tmp_path)).append("s1", "maybe", "rec")


# ── Review API ─────────────────────────────────────────────────────────────────


class TestReviewApi:
    def _ended_session(self, client: TestClient, headers: dict, rid: str, high: bool) -> str:
        sid = client.post(
            "/session/start",
            json={"recruiter_id": rid, "candidate_id": str(uuid.uuid4())},
            headers=headers,
        ).json()["session_id"]
        v = 0.95 if high else 0.05
        client.post(
            f"/session/{sid}/signals",
            json={"latency_score": v, "bg_audio_score": v, "perplexity_score": v,
                  "burstiness_score": v, "similarity_score": v},
            headers=headers,
        )
        client.post(f"/session/{sid}/end", headers=headers)
        return sid

    @pytest.fixture()
    def ctx(self, tmp_path: Path):
        rid = str(uuid.uuid4())
        headers = {"Authorization": f"Bearer {_token(rid)}"}
        with patch("api.main._make_review_store", return_value=ReviewStore(str(tmp_path))):
            yield TestClient(app), headers, rid, tmp_path

    def test_live_session_cannot_be_reviewed(self, ctx) -> None:
        client, headers, rid, _ = ctx
        sid = client.post(
            "/session/start",
            json={"recruiter_id": rid, "candidate_id": str(uuid.uuid4())},
            headers=headers,
        ).json()["session_id"]
        resp = client.post(f"/session/{sid}/review", json={"verdict": "cleared"}, headers=headers)
        assert resp.status_code == 409

    def test_flagged_session_is_pending_until_reviewed(self, ctx) -> None:
        client, headers, rid, tmp_path = ctx
        sid = self._ended_session(client, headers, rid, high=True)
        self._ended_session(client, headers, rid, high=False)  # not flagged → not pending

        pending = client.get("/reviews/pending", headers=headers).json()
        assert [p["session_id"] for p in pending] == [sid]

        resp = client.post(f"/session/{sid}/review", json={"verdict": "cleared"}, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["verdict"] == "cleared"
        assert client.get("/reviews/pending", headers=headers).json() == []
        report = client.get(f"/session/{sid}/report", headers=headers).json()
        assert report["review_verdict"] == "cleared"
        assert list((tmp_path / "session_reviews").rglob("*.parquet"))

    def test_pending_is_scoped_to_caller(self, ctx) -> None:
        client, headers, rid, _ = ctx
        self._ended_session(client, headers, rid, high=True)
        other = {"Authorization": f"Bearer {_token(str(uuid.uuid4()))}"}
        assert client.get("/reviews/pending", headers=other).json() == []

    def test_invalid_verdict_is_422(self, ctx) -> None:
        client, headers, rid, _ = ctx
        sid = self._ended_session(client, headers, rid, high=True)
        resp = client.post(f"/session/{sid}/review", json={"verdict": "maybe"}, headers=headers)
        assert resp.status_code == 422

    def test_storage_failure_is_503_and_not_recorded(self, ctx) -> None:
        client, headers, rid, _ = ctx
        sid = self._ended_session(client, headers, rid, high=True)
        broken = MagicMock()
        broken.append.side_effect = OSError("disk full")
        with patch("api.main._make_review_store", return_value=broken):
            resp = client.post(
                f"/session/{sid}/review", json={"verdict": "confirmed"}, headers=headers
            )
        assert resp.status_code == 503
        assert len(client.get("/reviews/pending", headers=headers).json()) == 1

    def test_unknown_session_is_404(self, ctx) -> None:
        client, headers, _, _ = ctx
        resp = client.post("/session/nope/review", json={"verdict": "cleared"}, headers=headers)
        assert resp.status_code == 404


# ── DAG: labels come only from reviews ─────────────────────────────────────────


class TestQueryReviewedSegments:
    def test_only_reviewed_sessions_with_latest_verdict(self, tmp_path: Path) -> None:
        _write_segments(tmp_path, [
            ("a", 0, "CANDIDATE", "answer a", 10.0, 11.0, True),
            ("b", 0, "CANDIDATE", "answer b", 10.0, 11.0, True),
            ("c", 0, "CANDIDATE", "answer c", 10.0, 11.0, True),   # flagged, never reviewed
        ])
        store = ReviewStore(str(tmp_path))
        store.append("a", "confirmed", "r", reviewed_at=1000.0)
        store.append("a", "cleared", "r", reviewed_at=1500.0)     # supersedes
        store.append("b", "confirmed", "r", reviewed_at=1200.0)

        rows = query_reviewed_segments(str(tmp_path), 0.0, 2000.0)
        verdicts = {(r["session_id"], r["verdict"]) for r in rows}
        assert verdicts == {("a", "cleared"), ("b", "confirmed")}

    def test_window_applies_to_review_time(self, tmp_path: Path) -> None:
        _write_segments(tmp_path, [("a", 0, "CANDIDATE", "x", 10.0, 11.0, True)])
        ReviewStore(str(tmp_path)).append("a", "confirmed", "r", reviewed_at=5000.0)
        assert query_reviewed_segments(str(tmp_path), 0.0, 2000.0) == []
        assert len(query_reviewed_segments(str(tmp_path), 4000.0, 6000.0)) == 1

    def test_missing_tables_return_empty(self, tmp_path: Path) -> None:
        assert query_reviewed_segments(str(tmp_path), 0.0, 1.0) == []


class TestTasksUseVerdicts:
    SEGMENTS = [
        _seg("conf", "RECRUITER", "Tell me about yourself.", "confirmed", 1),
        _seg("conf", "CANDIDATE", "AI-sounding answer", "confirmed", 2),
        _seg("clr", "RECRUITER", "Tell me about yourself.", "cleared", 1),
        _seg("clr", "CANDIDATE", "honest human answer", "cleared", 2),
    ]

    def _ctx(self) -> dict:
        xcom = {"extract_suspicious": {"segments": self.SEGMENTS, "count": len(self.SEGMENTS)}}
        return {"ti": _TI(xcom), "ds_nodash": "20261126"}

    def test_answer_bank_gets_confirmed_answers_only(self) -> None:
        with patch("airflow.dags.retraining_dag.append_answer_bank", return_value=1) as app_:
            _update_answer_bank(**self._ctx())
        pairs = app_.call_args[0][1]
        assert [p["answer"] for p in pairs] == ["AI-sounding answer"]

    def test_embeddings_use_confirmed_answers_only(self) -> None:
        with (
            patch("airflow.dags.retraining_dag.embed_texts",
                  return_value=np.zeros((1, 4), dtype=np.float32)) as emb,
            patch("airflow.dags.retraining_dag.update_vector_store", return_value=1),
        ):
            _compute_embeddings(**self._ctx())
        assert emb.call_args[0][0] == ["AI-sounding answer"]

    def _run_retrain(self, segments: list[dict]) -> tuple[dict, MagicMock]:
        store = MagicMock()
        store.list_session_chunks.side_effect = lambda sid: [f"{sid}/{i}" for i in range(12)]
        store._client.get_object.return_value.read.return_value = b"\x00\x00" * 160
        xcom = {"extract_suspicious": {"segments": segments}}
        with (
            patch("airflow.dags.retraining_dag._make_object_store", return_value=store),
            patch("ml.features.audio_bg.extract_mfcc_features", return_value=np.ones(4)),
            patch("airflow.dags.retraining_dag.BackgroundAudioClassifier") as clf_cls,
        ):
            clf_cls.return_value.to_bytes.return_value = b"model"
            result = _retrain_bg_classifier(ti=_TI(xcom), ds_nodash="20261126")
        return result, clf_cls

    def test_classifier_labels_follow_verdicts(self) -> None:
        result, clf_cls = self._run_retrain(self.SEGMENTS)
        assert result["retrained"] is True
        y = clf_cls.return_value.train_from_arrays.call_args[0][1]
        assert sorted(set(y.tolist())) == [0, 1]
        assert (y == 1).sum() == 12 and (y == 0).sum() == 12

    def test_single_class_skips_retraining(self) -> None:
        only_confirmed = [s for s in self.SEGMENTS if s["verdict"] == "confirmed"]
        result, clf_cls = self._run_retrain(only_confirmed)  # 12 samples, one class
        assert result["retrained"] is False
        clf_cls.return_value.train_from_arrays.assert_not_called()
