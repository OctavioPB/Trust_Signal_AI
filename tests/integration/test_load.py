"""Load test: 20 concurrent interview sessions; p95 latency < 12 s.

Uses FastAPI TestClient (ASGI in-process transport) via ThreadPoolExecutor to
simulate concurrent recruiter sessions without network overhead.

Run:
    pytest tests/integration/test_load.py -v
"""

from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
from fastapi.testclient import TestClient

from api.main import app, _SESSIONS

_CONCURRENT = 20
_P95_TARGET_S = 12.0
_RECRUITER_ID = "loadtest-recruiter-00000000-0000-0000-0000-000000000001"


@pytest.fixture(autouse=True)
def _clear_sessions():
    _SESSIONS.clear()
    yield
    _SESSIONS.clear()


def _token(client: TestClient) -> str:
    r = client.post("/auth/token", json={"recruiter_id": _RECRUITER_ID})
    assert r.status_code == 200
    return r.json()["access_token"]


def _one_session(client: TestClient, token: str) -> float:
    """Run start → signals → end → report; return wall-clock seconds elapsed."""
    headers = {"Authorization": f"Bearer {token}"}
    t0 = time.perf_counter()

    # 1. Start session
    r = client.post(
        "/session/start",
        json={"recruiter_id": _RECRUITER_ID, "candidate_id": str(uuid.uuid4())},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    sid = r.json()["session_id"]

    # 2. Submit signal scores (simulates ML pipeline push)
    r = client.post(
        f"/session/{sid}/signals",
        json={
            "latency_score": 0.40,
            "bg_audio_score": 0.30,
            "perplexity_score": 0.50,
            "burstiness_score": 0.35,
            "similarity_score": 0.20,
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text

    # 3. Close session
    r = client.post(f"/session/{sid}/end", headers=headers)
    assert r.status_code == 200, r.text

    # 4. Fetch full report (mirrors dashboard polling)
    r = client.get(f"/session/{sid}/report", headers=headers)
    assert r.status_code == 200, r.text

    return time.perf_counter() - t0


class TestLoad:
    def test_twenty_concurrent_sessions_complete(self):
        """All 20 concurrent sessions complete without errors."""
        client = TestClient(app)
        token = _token(client)
        errors: list[str] = []

        with ThreadPoolExecutor(max_workers=_CONCURRENT) as pool:
            futures = [pool.submit(_one_session, client, token) for _ in range(_CONCURRENT)]
            for f in as_completed(futures):
                try:
                    f.result()
                except Exception as exc:  # noqa: BLE001
                    errors.append(str(exc))

        assert not errors, f"Session errors ({len(errors)}):\n" + "\n".join(errors)

    def test_p95_latency_under_threshold(self):
        """p95 end-to-end latency (start → final report) must be < 12 s."""
        client = TestClient(app)
        token = _token(client)
        latencies: list[float] = []

        with ThreadPoolExecutor(max_workers=_CONCURRENT) as pool:
            futures = [pool.submit(_one_session, client, token) for _ in range(_CONCURRENT)]
            for f in as_completed(futures):
                latencies.append(f.result())

        latencies.sort()
        p95_idx = max(0, int(len(latencies) * 0.95) - 1)
        p95 = latencies[p95_idx]
        p99 = latencies[-1]

        assert p95 < _P95_TARGET_S, (
            f"p95={p95:.3f}s exceeds {_P95_TARGET_S}s target. "
            f"p99={p99:.3f}s. All: {[f'{x:.3f}' for x in latencies]}"
        )

    def test_health_endpoint_responsive_under_load(self):
        """Health endpoint responds during concurrent session load."""
        client = TestClient(app)
        token = _token(client)

        with ThreadPoolExecutor(max_workers=_CONCURRENT) as pool:
            session_futures = [
                pool.submit(_one_session, client, token) for _ in range(_CONCURRENT)
            ]
            r = client.get("/health")
            assert r.status_code == 200
            assert r.json()["status"] == "ok"

            for f in as_completed(session_futures):
                f.result()

    def test_score_response_schema_valid_under_load(self):
        """All concurrent sessions return well-formed ScoreResponse with trust_score in [0,100]."""
        client = TestClient(app)
        token = _token(client)
        headers = {"Authorization": f"Bearer {token}"}
        score_data: list[dict] = []

        def _session_with_score() -> dict:
            r = client.post(
                "/session/start",
                json={"recruiter_id": _RECRUITER_ID, "candidate_id": str(uuid.uuid4())},
                headers=headers,
            )
            sid = r.json()["session_id"]
            client.post(
                f"/session/{sid}/signals",
                json={
                    "latency_score": 0.1,
                    "bg_audio_score": 0.1,
                    "perplexity_score": 0.1,
                    "burstiness_score": 0.1,
                    "similarity_score": 0.1,
                },
                headers=headers,
            )
            r = client.post(f"/session/{sid}/end", headers=headers)
            return r.json()

        with ThreadPoolExecutor(max_workers=_CONCURRENT) as pool:
            futures = [pool.submit(_session_with_score) for _ in range(_CONCURRENT)]
            for f in as_completed(futures):
                score_data.append(f.result())

        assert len(score_data) == _CONCURRENT
        for data in score_data:
            assert "trust_score" in data
            assert 0.0 <= data["trust_score"] <= 100.0
            assert "flagged" in data

    def test_gdpr_delete_under_concurrent_load(self):
        """DELETE /session/{id} returns 202 and subsequent GET returns 404 under load."""
        client = TestClient(app)
        token = _token(client)
        headers = {"Authorization": f"Bearer {token}"}

        # Create 5 sessions, delete them concurrently, verify they're gone
        session_ids: list[str] = []
        for _ in range(5):
            r = client.post(
                "/session/start",
                json={"recruiter_id": _RECRUITER_ID, "candidate_id": str(uuid.uuid4())},
                headers=headers,
            )
            session_ids.append(r.json()["session_id"])

        def _delete(sid: str) -> int:
            r = client.delete(f"/session/{sid}", headers=headers)
            return r.status_code

        with ThreadPoolExecutor(max_workers=5) as pool:
            statuses = list(pool.map(_delete, session_ids))

        assert all(s == 202 for s in statuses), f"Not all deletes returned 202: {statuses}"

        for sid in session_ids:
            r = client.get(f"/session/{sid}/score", headers=headers)
            assert r.status_code == 404, f"Session {sid} still accessible after DELETE"
