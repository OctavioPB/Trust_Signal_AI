"""Anytime-valid sequential monitor (ml/sequential.py), its API, and turn splitting."""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from fastapi.testclient import TestClient
from jose import jwt

import config
from evals.sequential import split_turns
from ml.sequential import SequentialMonitor, SequentialState

# ── Synthetic sessions with within-session dependence ─────────────────────────


def _sessions(n: int, seed: int, ai_share: float = 0.5) -> tuple[list[list[float]], np.ndarray]:
    """Each session has its own random offset (same author → correlated turns)."""
    rng = np.random.default_rng(seed)
    y = (rng.random(n) < ai_share).astype(int)
    out = []
    for lab in y:
        offset = rng.normal(0, 0.12)                     # session-level random effect
        turns = int(rng.integers(2, 10))
        mu = 0.3 + 0.35 * lab + offset
        out.append([float(np.clip(rng.normal(mu, 0.12), 0, 1)) for _ in range(turns)])
    return out, y


@pytest.fixture(scope="module")
def monitor() -> SequentialMonitor:
    s, y = _sessions(1200, 0)
    return SequentialMonitor.fit(s[:600], y[:600], s[600:], y[600:], alpha=0.05)


class TestGuarantee:
    def test_human_sessions_rarely_ever_flagged(self, monitor: SequentialMonitor) -> None:
        """Checked after every turn, P(human ever flagged) stays near alpha despite dependence."""
        s, y = _sessions(4000, 1)
        humans = [x for x, lab in zip(s, y, strict=True) if lab == 0]
        ever = [monitor.path(x).max() > monitor.threshold for x in humans]
        assert np.mean(ever) <= monitor.alpha + 0.02

    def test_detects_ai_sessions(self, monitor: SequentialMonitor) -> None:
        s, y = _sessions(2000, 2)
        ai = [x for x, lab in zip(s, y, strict=True) if lab == 1]
        hit = [monitor.path(x).max() > monitor.threshold for x in ai]
        assert np.mean(hit) > 0.5

    def test_too_few_calibration_sessions_never_flags(self) -> None:
        s, y = _sessions(60, 3)
        mon = SequentialMonitor.fit(s[:50], y[:50], s[50:], y[50:], alpha=0.02)
        assert math.isinf(mon.threshold)


class TestUpdate:
    def _mon(self, threshold: float = 2.0, max_turns: int = 4) -> SequentialMonitor:
        return SequentialMonitor(weight=4.0, intercept=-2.0, prior_logit=0.0, clip=3.0,
                                 threshold=threshold, alpha=0.02, max_turns=max_turns,
                                 n_calibration_sessions=100)

    def test_flags_at_first_crossing_and_stays_flagged(self) -> None:
        mon, st = self._mon(), SequentialState()
        for score in (0.9, 0.9, 0.0, 0.0):
            mon.update(st, score)
        assert st.flagged_at_turn == 2
        assert st.flagged
        assert "2 candidate turn" in mon.flag_reason(st)

    def test_evidence_frozen_after_max_turns(self) -> None:
        mon, st = self._mon(threshold=100.0, max_turns=2), SequentialState()
        for score in (0.9, 0.9, 0.9, 0.9):
            mon.update(st, score)
        assert st.turns == 4 and len(st.history) == 2

    def test_single_turn_evidence_is_clipped(self) -> None:
        assert self._mon().turn_llr(1.0) == pytest.approx(2.0)
        mon = SequentialMonitor(50.0, -10.0, 0.0, 3.0, 1.0, 0.02, 12, 100)
        assert mon.turn_llr(1.0) == 3.0 and mon.turn_llr(0.0) == -3.0


def test_json_round_trip(tmp_path: Path, monitor: SequentialMonitor) -> None:
    path = tmp_path / "20261126_sequential.json"
    monitor.save(path)
    loaded = SequentialMonitor.load(path)
    assert loaded.threshold == monitor.threshold
    assert loaded.turn_llr(0.7) == pytest.approx(monitor.turn_llr(0.7))


def test_split_turns_merges_short_tail() -> None:
    text = "One two three four five six. Seven eight nine ten eleven twelve. Short end."
    turns = split_turns(text)
    assert len(turns) == 1 and turns[0].endswith("Short end.")
    long = " ".join(f"Sentence number {i} has quite a few words in it." for i in range(6))
    assert len(split_turns(long)) == 3


# ── API ────────────────────────────────────────────────────────────────────────


def _headers(rid: str) -> dict:
    tok = jwt.encode({"sub": rid, "exp": datetime.now(UTC) + timedelta(hours=1)},
                     config.FASTAPI_SECRET_KEY, algorithm="HS256")
    return {"Authorization": f"Bearer {tok}"}


class TestApi:
    @pytest.fixture()
    def client(self):
        from api.main import _SESSIONS, app

        _SESSIONS.clear()
        yield TestClient(app)
        _SESSIONS.clear()

    def _start(self, client: TestClient, rid: str, h: dict) -> str:
        return client.post("/session/start", headers=h,
                           json={"recruiter_id": rid, "candidate_id": str(uuid.uuid4())}
                           ).json()["session_id"]

    def test_turn_endpoint_503_when_not_configured(self, client: TestClient) -> None:
        rid = str(uuid.uuid4())
        h = _headers(rid)
        sid = self._start(client, rid, h)
        with patch("api.main._MONITOR", None):
            assert client.post(f"/session/{sid}/turn", json={"text_score": 0.5},
                               headers=h).status_code == 503

    def test_early_flag_surfaces_and_survives_end(self, client: TestClient) -> None:
        rid = str(uuid.uuid4())
        h = _headers(rid)
        sid = self._start(client, rid, h)
        mon = SequentialMonitor(4.0, -2.0, 0.0, 3.0, 2.0, 0.02, 12, 100)
        with patch("api.main._MONITOR", mon):
            r1 = client.post(f"/session/{sid}/turn", json={"text_score": 0.9}, headers=h).json()
            assert not r1["early_flag"]
            r2 = client.post(f"/session/{sid}/turn", json={"text_score": 0.9}, headers=h).json()
            assert r2["early_flag"] and r2["flagged_at_turn"] == 2

            score = client.get(f"/session/{sid}/score", headers=h).json()
            assert score["flagged"] and "sequential threshold" in score["flag_reason"]
            assert score["sequential"]["early_flag"]

            end = client.post(f"/session/{sid}/end", headers=h).json()
            assert end["status"] == "flagged" and end["flag_reason"]

    def test_partial_signal_update_keeps_earlier_values(self, client: TestClient) -> None:
        from api.main import _SESSIONS

        rid = str(uuid.uuid4())
        h = _headers(rid)
        sid = self._start(client, rid, h)
        client.post(f"/session/{sid}/signals", json={"latency_score": 0.4}, headers=h)
        client.post(f"/session/{sid}/signals", json={"perplexity_score": 0.7}, headers=h)
        client.post(f"/session/{sid}/signals", json={"burstiness_score": None}, headers=h)
        assert _SESSIONS[sid].signal_scores == {
            "latency": 0.4, "perplexity": 0.7, "burstiness": None,
        }
