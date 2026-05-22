"""Integration tests for api/main.py — all FastAPI endpoints.

Uses FastAPI's synchronous TestClient (no real server needed).
Tests run against the in-memory session store, so each test module
starts with a clean slate via the ``clean_sessions`` autouse fixture.

Run with:
    pytest --run-integration -m integration tests/integration/test_api.py

Definition of Done (PLAN.md §7.5):
    - All endpoints return HTTP 200/201/202 on the happy path.
    - Correct response schemas are verified on every endpoint.
    - Auth guard returns 401 without a valid token.
    - 404 is returned for unknown session_ids.
    - 409 is returned when operating on a completed/flagged session.
    - False positive rate < 2 % on a 50-session "clean" synthetic dataset.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from api.main import _SESSIONS, app

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_sessions():
    """Clear the in-memory session store before each test."""
    _SESSIONS.clear()
    yield
    _SESSIONS.clear()


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="module")
def recruiter_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture(scope="module")
def token(client: TestClient, recruiter_id: str) -> str:
    resp = client.post("/auth/token", json={"recruiter_id": recruiter_id})
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest.fixture(scope="module")
def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _start_session(
    client: TestClient,
    headers: dict,
    recruiter_id: str,
    candidate_id: str | None = None,
) -> str:
    """Helper: start a session and return the session_id."""
    candidate_id = candidate_id or str(uuid.uuid4())
    resp = client.post(
        "/session/start",
        json={"recruiter_id": recruiter_id, "candidate_id": candidate_id},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["session_id"]


def _submit_signals(
    client: TestClient,
    session_id: str,
    headers: dict,
    latency: float = 0.1,
    bg: float = 0.05,
    ppl: float = 0.1,
    burst: float = 0.1,
    sim: float = 0.05,
) -> dict:
    resp = client.post(
        f"/session/{session_id}/signals",
        json={
            "latency_score": latency,
            "bg_audio_score": bg,
            "perplexity_score": ppl,
            "burstiness_score": burst,
            "similarity_score": sim,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── Health ─────────────────────────────────────────────────────────────────────

@pytest.mark.integration
def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body


# ── Auth ───────────────────────────────────────────────────────────────────────

@pytest.mark.integration
def test_auth_token_returns_bearer(client: TestClient) -> None:
    resp = client.post("/auth/token", json={"recruiter_id": str(uuid.uuid4())})
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"
    assert body["expires_in_hours"] == 24


@pytest.mark.integration
def test_unauthenticated_start_returns_401(client: TestClient) -> None:
    resp = client.post(
        "/session/start",
        json={"recruiter_id": str(uuid.uuid4()), "candidate_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 401


@pytest.mark.integration
def test_invalid_token_returns_401(client: TestClient) -> None:
    resp = client.get(
        "/session/nonexistent/score",
        headers={"Authorization": "Bearer not.a.real.token"},
    )
    assert resp.status_code == 401


# ── POST /session/start ────────────────────────────────────────────────────────

@pytest.mark.integration
def test_session_start_returns_201(
    client: TestClient, auth_headers: dict, recruiter_id: str
) -> None:
    resp = client.post(
        "/session/start",
        json={"recruiter_id": recruiter_id, "candidate_id": str(uuid.uuid4())},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "session_id" in body
    assert body["status"] == "live"
    assert body["start_ts"] > 0


@pytest.mark.integration
def test_session_start_schema(
    client: TestClient, auth_headers: dict, recruiter_id: str
) -> None:
    resp = client.post(
        "/session/start",
        json={"recruiter_id": recruiter_id, "candidate_id": str(uuid.uuid4())},
        headers=auth_headers,
    )
    body = resp.json()
    for field in ("session_id", "status", "start_ts"):
        assert field in body, f"Missing field: {field}"


@pytest.mark.integration
def test_session_start_recruiter_mismatch_returns_403(
    client: TestClient, auth_headers: dict
) -> None:
    """Token recruiter_id must match request body recruiter_id."""
    resp = client.post(
        "/session/start",
        json={"recruiter_id": str(uuid.uuid4()), "candidate_id": str(uuid.uuid4())},
        headers=auth_headers,
    )
    assert resp.status_code == 403


# ── POST /session/{id}/signals ────────────────────────────────────────────────

@pytest.mark.integration
def test_signals_returns_score_response(
    client: TestClient, auth_headers: dict, recruiter_id: str
) -> None:
    session_id = _start_session(client, auth_headers, recruiter_id)
    body = _submit_signals(client, session_id, auth_headers)

    for field in ("session_id", "status", "trust_score", "suspicion_index",
                  "flagged", "flag_reason", "signals"):
        assert field in body, f"Missing field: {field}"
    assert body["session_id"] == session_id
    assert 0.0 <= body["trust_score"] <= 100.0
    assert 0.0 <= body["suspicion_index"] <= 1.0
    assert len(body["signals"]) == 5


@pytest.mark.integration
def test_signals_on_completed_session_returns_409(
    client: TestClient, auth_headers: dict, recruiter_id: str
) -> None:
    session_id = _start_session(client, auth_headers, recruiter_id)
    client.post(f"/session/{session_id}/end", headers=auth_headers)

    resp = client.post(
        f"/session/{session_id}/signals",
        json={"latency_score": 0.5, "bg_audio_score": 0.5,
              "perplexity_score": 0.5, "burstiness_score": 0.5,
              "similarity_score": 0.5},
        headers=auth_headers,
    )
    assert resp.status_code == 409


@pytest.mark.integration
def test_signals_unknown_session_returns_404(
    client: TestClient, auth_headers: dict
) -> None:
    resp = client.post(
        "/session/does-not-exist/signals",
        json={"latency_score": 0.1, "bg_audio_score": 0.1,
              "perplexity_score": 0.1, "burstiness_score": 0.1,
              "similarity_score": 0.1},
        headers=auth_headers,
    )
    assert resp.status_code == 404


# ── GET /session/{id}/score ───────────────────────────────────────────────────

@pytest.mark.integration
def test_score_without_signals_trust_score_100(
    client: TestClient, auth_headers: dict, recruiter_id: str
) -> None:
    """Fresh session with no signals → all zeros → trust_score = 100."""
    session_id = _start_session(client, auth_headers, recruiter_id)
    resp = client.get(f"/session/{session_id}/score", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["trust_score"] == 100.0


@pytest.mark.integration
def test_score_reflects_submitted_signals(
    client: TestClient, auth_headers: dict, recruiter_id: str
) -> None:
    session_id = _start_session(client, auth_headers, recruiter_id)
    _submit_signals(client, session_id, auth_headers,
                    latency=0.9, bg=0.9, ppl=0.9, burst=0.9, sim=0.9)
    resp = client.get(f"/session/{session_id}/score", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["trust_score"] < 20.0
    assert body["flagged"] is True


@pytest.mark.integration
def test_score_unknown_session_returns_404(
    client: TestClient, auth_headers: dict
) -> None:
    resp = client.get("/session/ghost-id/score", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.integration
def test_score_schema_has_all_required_fields(
    client: TestClient, auth_headers: dict, recruiter_id: str
) -> None:
    session_id = _start_session(client, auth_headers, recruiter_id)
    resp = client.get(f"/session/{session_id}/score", headers=auth_headers)
    body = resp.json()
    for field in ("session_id", "status", "trust_score", "suspicion_index",
                  "flagged", "flag_reason", "signals"):
        assert field in body


@pytest.mark.integration
def test_signal_breakdown_has_required_fields(
    client: TestClient, auth_headers: dict, recruiter_id: str
) -> None:
    session_id = _start_session(client, auth_headers, recruiter_id)
    _submit_signals(client, session_id, auth_headers)
    resp = client.get(f"/session/{session_id}/score", headers=auth_headers)
    for signal in resp.json()["signals"]:
        for field in ("signal_name", "raw_score", "weight",
                      "weighted_contribution", "explanation"):
            assert field in signal


# ── GET /session/{id}/report ──────────────────────────────────────────────────

@pytest.mark.integration
def test_report_returns_200(
    client: TestClient, auth_headers: dict, recruiter_id: str
) -> None:
    session_id = _start_session(client, auth_headers, recruiter_id)
    resp = client.get(f"/session/{session_id}/report", headers=auth_headers)
    assert resp.status_code == 200


@pytest.mark.integration
def test_report_schema(
    client: TestClient, auth_headers: dict, recruiter_id: str
) -> None:
    session_id = _start_session(client, auth_headers, recruiter_id)
    _submit_signals(client, session_id, auth_headers)
    resp = client.get(f"/session/{session_id}/report", headers=auth_headers)
    body = resp.json()
    for field in ("session_id", "recruiter_id", "status", "start_ts", "end_ts",
                  "trust_score", "suspicion_index", "flagged", "flag_reason",
                  "signals", "turns"):
        assert field in body, f"Report missing field: {field}"


@pytest.mark.integration
def test_report_end_ts_null_for_live_session(
    client: TestClient, auth_headers: dict, recruiter_id: str
) -> None:
    session_id = _start_session(client, auth_headers, recruiter_id)
    body = client.get(f"/session/{session_id}/report", headers=auth_headers).json()
    assert body["end_ts"] is None


@pytest.mark.integration
def test_report_unknown_session_returns_404(
    client: TestClient, auth_headers: dict
) -> None:
    resp = client.get("/session/no-such-id/report", headers=auth_headers)
    assert resp.status_code == 404


# ── POST /session/{id}/end ────────────────────────────────────────────────────

@pytest.mark.integration
def test_session_end_returns_200(
    client: TestClient, auth_headers: dict, recruiter_id: str
) -> None:
    session_id = _start_session(client, auth_headers, recruiter_id)
    resp = client.post(f"/session/{session_id}/end", headers=auth_headers)
    assert resp.status_code == 200


@pytest.mark.integration
def test_session_end_schema(
    client: TestClient, auth_headers: dict, recruiter_id: str
) -> None:
    session_id = _start_session(client, auth_headers, recruiter_id)
    body = client.post(f"/session/{session_id}/end", headers=auth_headers).json()
    for field in ("session_id", "status", "trust_score", "flagged", "flag_reason"):
        assert field in body


@pytest.mark.integration
def test_session_end_status_is_completed_for_clean_session(
    client: TestClient, auth_headers: dict, recruiter_id: str
) -> None:
    session_id = _start_session(client, auth_headers, recruiter_id)
    body = client.post(f"/session/{session_id}/end", headers=auth_headers).json()
    assert body["status"] == "completed"
    assert body["flagged"] is False


@pytest.mark.integration
def test_session_end_status_is_flagged_for_suspicious_session(
    client: TestClient, auth_headers: dict, recruiter_id: str
) -> None:
    session_id = _start_session(client, auth_headers, recruiter_id)
    _submit_signals(client, session_id, auth_headers,
                    latency=1.0, bg=1.0, ppl=1.0, burst=1.0, sim=1.0)
    body = client.post(f"/session/{session_id}/end", headers=auth_headers).json()
    assert body["status"] == "flagged"
    assert body["flagged"] is True
    assert body["flag_reason"], "flag_reason must not be empty when flagged=True"


@pytest.mark.integration
def test_session_end_twice_returns_409(
    client: TestClient, auth_headers: dict, recruiter_id: str
) -> None:
    session_id = _start_session(client, auth_headers, recruiter_id)
    client.post(f"/session/{session_id}/end", headers=auth_headers)
    resp = client.post(f"/session/{session_id}/end", headers=auth_headers)
    assert resp.status_code == 409


@pytest.mark.integration
def test_score_after_end_returns_locked_result(
    client: TestClient, auth_headers: dict, recruiter_id: str
) -> None:
    session_id = _start_session(client, auth_headers, recruiter_id)
    _submit_signals(client, session_id, auth_headers, latency=0.3)
    end_body = client.post(f"/session/{session_id}/end", headers=auth_headers).json()
    score_body = client.get(f"/session/{session_id}/score", headers=auth_headers).json()
    # The locked trust_score must be returned after end
    assert score_body["trust_score"] == end_body["trust_score"]


@pytest.mark.integration
def test_report_end_ts_set_after_end(
    client: TestClient, auth_headers: dict, recruiter_id: str
) -> None:
    session_id = _start_session(client, auth_headers, recruiter_id)
    client.post(f"/session/{session_id}/end", headers=auth_headers)
    body = client.get(f"/session/{session_id}/report", headers=auth_headers).json()
    assert body["end_ts"] is not None
    assert body["end_ts"] > 0


@pytest.mark.integration
def test_session_end_unknown_returns_404(
    client: TestClient, auth_headers: dict
) -> None:
    resp = client.post("/session/phantom/end", headers=auth_headers)
    assert resp.status_code == 404


# ── DELETE /session/{id} ──────────────────────────────────────────────────────

@pytest.mark.integration
def test_delete_session_returns_202(
    client: TestClient, auth_headers: dict, recruiter_id: str
) -> None:
    session_id = _start_session(client, auth_headers, recruiter_id)
    resp = client.delete(f"/session/{session_id}", headers=auth_headers)
    assert resp.status_code == 202
    assert resp.json()["deleted"] is True


@pytest.mark.integration
def test_delete_then_score_returns_404(
    client: TestClient, auth_headers: dict, recruiter_id: str
) -> None:
    session_id = _start_session(client, auth_headers, recruiter_id)
    client.delete(f"/session/{session_id}", headers=auth_headers)
    resp = client.get(f"/session/{session_id}/score", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.integration
def test_delete_unknown_session_returns_404(
    client: TestClient, auth_headers: dict
) -> None:
    resp = client.delete("/session/no-such-session", headers=auth_headers)
    assert resp.status_code == 404


# ── 7.6  False positive rate < 2 % on 50 clean synthetic sessions ─────────────

@pytest.mark.integration
def test_false_positive_rate_below_2_percent(
    client: TestClient, auth_headers: dict, recruiter_id: str
) -> None:
    """PLAN.md §7.6: < 2 % of genuinely clean sessions must be flagged.

    Signal scores for a "clean" candidate are drawn from a realistic human
    distribution: latency CV ≈ 0.70 → score ≈ 0, background noise absent,
    perplexity high, burstiness high, semantic similarity low.
    """
    import random
    rng = random.Random(2025)

    N = 50
    flagged_count = 0

    for _ in range(N):
        session_id = _start_session(client, auth_headers, recruiter_id)

        # Human-like signal scores: all comfortably below the suspicion threshold
        _submit_signals(
            client, session_id, auth_headers,
            latency=rng.uniform(0.0, 0.10),   # natural latency variance
            bg=rng.uniform(0.0, 0.08),         # no keyboard
            ppl=rng.uniform(0.0, 0.12),        # high perplexity (unpredictable)
            burst=rng.uniform(0.0, 0.12),      # bursty natural speech
            sim=rng.uniform(0.0, 0.08),        # low AI similarity
        )
        end_body = client.post(f"/session/{session_id}/end", headers=auth_headers).json()
        if end_body["flagged"]:
            flagged_count += 1

    false_positive_rate = flagged_count / N
    assert false_positive_rate < 0.02, (
        f"False positive rate {false_positive_rate:.1%} ({flagged_count}/{N}) "
        f"exceeds the 2 % target (PLAN.md §7.6). "
        "Review suspicion_threshold or signal score ranges."
    )
