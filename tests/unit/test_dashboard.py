"""Unit tests for Sprint 8 dashboard modules.

Covers:
  - dashboard.api_client: HTTP client helpers (requests mocked)
  - dashboard.app: pure helper functions (_trust_color, _trust_label, demo data)
  - dashboard.pdf_export: PDF generation from a synthetic report dict

No Streamlit server required — all Streamlit-using functions are excluded;
only the pure / side-effect-free functions are tested here.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from dashboard.api_client import APIError, get_report, get_score, get_token, health_check
from dashboard.app import (
    _demo_report_data,
    _demo_score_data,
    _signal_tier_bg,
    _signal_tier_color,
    _trust_color,
    _trust_label,
    _FLAG_THRESHOLD_SCORE,
    _GREEN,
    _ORANGE,
    _RED,
)
from dashboard.pdf_export import generate_report_pdf


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _ok_response(payload: dict) -> MagicMock:
    """Build a mock requests.Response that returns payload as JSON."""
    m = MagicMock()
    m.ok = True
    m.json.return_value = payload
    return m


def _err_response(status_code: int, detail: str) -> MagicMock:
    """Build a mock requests.Response with a non-2xx status."""
    m = MagicMock()
    m.ok = False
    m.status_code = status_code
    m.json.return_value = {"detail": detail}
    m.text = detail
    return m


def _make_report(*, flagged: bool = False, with_end_ts: bool = True) -> dict:
    """Minimal ReportResponse dict suitable for PDF generation tests."""
    return {
        "session_id":      "test-00000000-0001",
        "recruiter_id":    "recruiter-00000000-0001",
        "status":          "flagged" if flagged else "completed",
        "start_ts":        1_716_297_600.0,
        "end_ts":          1_716_299_400.0 if with_end_ts else None,
        "trust_score":     28.5 if flagged else 82.0,
        "suspicion_index": 0.715 if flagged else 0.18,
        "flagged":         flagged,
        "flag_reason":     (
            "Session flagged (suspicion index: 0.72).\n"
            "  1. Latency (score=0.90): Constant latency detected."
        ) if flagged else "",
        "signals": [
            {
                "signal_name":           "Response Latency",
                "raw_score":             0.90 if flagged else 0.10,
                "weight":                0.25,
                "weighted_contribution": 0.225 if flagged else 0.025,
                "explanation":           "Constant latency." if flagged else "Natural variation.",
            },
            {
                "signal_name":           "Background Audio",
                "raw_score":             0.50,
                "weight":                0.20,
                "weighted_contribution": 0.10,
                "explanation":           "Moderate keyboard activity detected.",
            },
        ],
        "turns": [],
    }


# ── api_client: health_check ──────────────────────────────────────────────────

class TestHealthCheck:

    def test_returns_true_when_api_ok(self) -> None:
        with patch("dashboard.api_client.requests.get", return_value=_ok_response({"status": "ok"})):
            assert health_check("http://localhost:8000") is True

    def test_returns_false_when_api_down(self) -> None:
        with patch("dashboard.api_client.requests.get", side_effect=ConnectionError("refused")):
            assert health_check("http://localhost:8000") is False

    def test_returns_false_on_non_200(self) -> None:
        m = MagicMock()
        m.ok = False
        with patch("dashboard.api_client.requests.get", return_value=m):
            assert health_check("http://localhost:8000") is False

    def test_returns_false_on_timeout(self) -> None:
        with patch("dashboard.api_client.requests.get", side_effect=TimeoutError()):
            assert health_check("http://localhost:8000") is False


# ── api_client: get_token ─────────────────────────────────────────────────────

class TestGetToken:

    def test_returns_access_token_string(self) -> None:
        resp = _ok_response({"access_token": "tok-abc", "token_type": "bearer"})
        with patch("dashboard.api_client.requests.post", return_value=resp):
            result = get_token("http://localhost:8000", "recruiter-uuid")
        assert result == "tok-abc"

    def test_posts_to_auth_token_endpoint(self) -> None:
        resp = _ok_response({"access_token": "tok", "token_type": "bearer"})
        with patch("dashboard.api_client.requests.post", return_value=resp) as mock_post:
            get_token("http://api", "r-id")
        url = mock_post.call_args[0][0]
        assert url.endswith("/auth/token")

    def test_sends_recruiter_id_in_body(self) -> None:
        resp = _ok_response({"access_token": "tok", "token_type": "bearer"})
        with patch("dashboard.api_client.requests.post", return_value=resp) as mock_post:
            get_token("http://api", "my-recruiter-id")
        body = mock_post.call_args[1]["json"]
        assert body["recruiter_id"] == "my-recruiter-id"

    def test_raises_api_error_on_400(self) -> None:
        resp = _err_response(400, "bad request")
        with patch("dashboard.api_client.requests.post", return_value=resp):
            with pytest.raises(APIError) as exc:
                get_token("http://api", "bad-id")
        assert exc.value.status_code == 400

    def test_raises_api_error_on_500(self) -> None:
        resp = _err_response(500, "internal server error")
        with patch("dashboard.api_client.requests.post", return_value=resp):
            with pytest.raises(APIError) as exc:
                get_token("http://api", "r-id")
        assert exc.value.status_code == 500

    def test_api_error_contains_detail(self) -> None:
        resp = _err_response(403, "recruiter not found")
        with patch("dashboard.api_client.requests.post", return_value=resp):
            with pytest.raises(APIError) as exc:
                get_token("http://api", "r-id")
        assert "recruiter not found" in exc.value.detail


# ── api_client: get_score ─────────────────────────────────────────────────────

class TestGetScore:

    def _score_payload(self) -> dict:
        return {
            "session_id":      "s1",
            "status":          "live",
            "trust_score":     80.0,
            "suspicion_index": 0.20,
            "flagged":         False,
            "flag_reason":     "",
            "signals":         [],
        }

    def test_returns_score_dict(self) -> None:
        with patch("dashboard.api_client.requests.get", return_value=_ok_response(self._score_payload())):
            result = get_score("http://api", "tok", "s1")
        assert result["trust_score"] == 80.0

    def test_sends_bearer_auth_header(self) -> None:
        with patch("dashboard.api_client.requests.get", return_value=_ok_response(self._score_payload())) as mock_get:
            get_score("http://api", "my-jwt-token", "s1")
        headers = mock_get.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer my-jwt-token"

    def test_requests_correct_url(self) -> None:
        with patch("dashboard.api_client.requests.get", return_value=_ok_response(self._score_payload())) as mock_get:
            get_score("http://api", "tok", "session-uuid-001")
        url = mock_get.call_args[0][0]
        assert "session-uuid-001" in url
        assert url.endswith("/score")

    def test_raises_api_error_on_404(self) -> None:
        with patch("dashboard.api_client.requests.get", return_value=_err_response(404, "Session not found.")):
            with pytest.raises(APIError) as exc:
                get_score("http://api", "tok", "nonexistent")
        assert exc.value.status_code == 404

    def test_raises_api_error_on_401(self) -> None:
        with patch("dashboard.api_client.requests.get", return_value=_err_response(401, "Unauthorized")):
            with pytest.raises(APIError):
                get_score("http://api", "bad-token", "s1")


# ── api_client: get_report ────────────────────────────────────────────────────

class TestGetReport:

    def test_returns_report_dict(self) -> None:
        payload = {"session_id": "s1", "turns": [], "trust_score": 70.0}
        with patch("dashboard.api_client.requests.get", return_value=_ok_response(payload)):
            result = get_report("http://api", "tok", "s1")
        assert result["session_id"] == "s1"
        assert isinstance(result["turns"], list)

    def test_requests_correct_report_url(self) -> None:
        payload = {"session_id": "s2", "turns": []}
        with patch("dashboard.api_client.requests.get", return_value=_ok_response(payload)) as mock_get:
            get_report("http://api", "tok", "session-42")
        url = mock_get.call_args[0][0]
        assert url.endswith("/report")

    def test_raises_api_error_on_404(self) -> None:
        with patch("dashboard.api_client.requests.get", return_value=_err_response(404, "Not found.")):
            with pytest.raises(APIError):
                get_report("http://api", "tok", "missing-session")


# ── APIError ──────────────────────────────────────────────────────────────────

class TestAPIError:

    def test_stores_status_code(self) -> None:
        err = APIError(404, "not found")
        assert err.status_code == 404

    def test_stores_detail(self) -> None:
        err = APIError(422, "validation error")
        assert err.detail == "validation error"

    def test_str_contains_status_and_detail(self) -> None:
        err = APIError(500, "server exploded")
        assert "500" in str(err)
        assert "server exploded" in str(err)


# ── app: _trust_color ─────────────────────────────────────────────────────────

class TestTrustColor:

    def test_score_100_is_green(self) -> None:
        assert _trust_color(100.0) == _GREEN

    def test_score_70_is_green(self) -> None:
        assert _trust_color(70.0) == _GREEN

    def test_score_69_is_orange(self) -> None:
        assert _trust_color(69.9) == _ORANGE

    def test_score_40_is_orange(self) -> None:
        assert _trust_color(40.0) == _ORANGE

    def test_score_39_is_red(self) -> None:
        assert _trust_color(39.9) == _RED

    def test_score_0_is_red(self) -> None:
        assert _trust_color(0.0) == _RED

    def test_midpoint_55_is_orange(self) -> None:
        assert _trust_color(55.0) == _ORANGE

    def test_high_trust_85_is_green(self) -> None:
        assert _trust_color(85.0) == _GREEN


# ── app: _trust_label ─────────────────────────────────────────────────────────

class TestTrustLabel:

    def test_90_is_trustworthy(self) -> None:
        assert _trust_label(90.0) == "TRUSTWORTHY"

    def test_70_is_trustworthy(self) -> None:
        assert _trust_label(70.0) == "TRUSTWORTHY"

    def test_69_is_moderate_risk(self) -> None:
        assert _trust_label(69.0) == "MODERATE RISK"

    def test_40_is_moderate_risk(self) -> None:
        assert _trust_label(40.0) == "MODERATE RISK"

    def test_39_is_high_risk(self) -> None:
        assert _trust_label(39.0) == "HIGH RISK"

    def test_0_is_high_risk(self) -> None:
        assert _trust_label(0.0) == "HIGH RISK"


# ── app: _signal_tier_color / _signal_tier_bg ────────────────────────────────

class TestSignalTierHelpers:

    def test_high_raw_score_returns_red(self) -> None:
        assert _signal_tier_color(0.65) == _RED

    def test_medium_raw_score_returns_orange(self) -> None:
        assert _signal_tier_color(0.35) == _ORANGE

    def test_low_raw_score_returns_green(self) -> None:
        assert _signal_tier_color(0.10) == _GREEN

    def test_high_raw_score_bg_is_red_bg(self) -> None:
        bg = _signal_tier_bg(0.80)
        assert bg.startswith("#FD") or "EA" in bg  # #FDEAEA

    def test_low_raw_score_bg_is_green_bg(self) -> None:
        bg = _signal_tier_bg(0.10)
        assert "F7" in bg or bg.startswith("#E0")  # #E0F7EF


# ── app: _demo_score_data ─────────────────────────────────────────────────────

class TestDemoScoreData:

    def test_has_all_required_keys(self) -> None:
        data = _demo_score_data()
        required = {
            "session_id", "status", "trust_score", "suspicion_index",
            "flagged", "flag_reason", "signals",
        }
        assert required <= data.keys()

    def test_trust_score_in_range(self) -> None:
        data = _demo_score_data()
        assert 0.0 <= data["trust_score"] <= 100.0

    def test_has_five_signals(self) -> None:
        assert len(_demo_score_data()["signals"]) == 5

    def test_all_signals_have_required_fields(self) -> None:
        required = {"signal_name", "raw_score", "weight", "weighted_contribution", "explanation"}
        for sig in _demo_score_data()["signals"]:
            assert required <= sig.keys()

    def test_flagged_session_has_non_empty_reason(self) -> None:
        data = _demo_score_data()
        if data["flagged"]:
            assert data["flag_reason"] != ""

    def test_suspicion_index_in_range(self) -> None:
        data = _demo_score_data()
        assert 0.0 <= data["suspicion_index"] <= 1.0

    def test_signal_weights_sum_to_one(self) -> None:
        signals = _demo_score_data()["signals"]
        total = sum(s["weight"] for s in signals)
        assert abs(total - 1.0) < 1e-4


# ── app: _demo_report_data ────────────────────────────────────────────────────

class TestDemoReportData:

    def test_includes_all_score_fields(self) -> None:
        data = _demo_report_data()
        for key in ("trust_score", "suspicion_index", "flagged", "signals"):
            assert key in data

    def test_has_recruiter_id(self) -> None:
        assert "recruiter_id" in _demo_report_data()

    def test_has_turns_list(self) -> None:
        data = _demo_report_data()
        assert isinstance(data["turns"], list)

    def test_turns_are_non_empty(self) -> None:
        data = _demo_report_data()
        assert len(data["turns"]) > 0

    def test_turns_have_speaker_and_text(self) -> None:
        for turn in _demo_report_data()["turns"]:
            assert "speaker" in turn
            assert "text" in turn

    def test_flag_threshold_score_is_35(self) -> None:
        assert _FLAG_THRESHOLD_SCORE == pytest.approx(35.0, abs=1e-3)


# ── pdf_export: generate_report_pdf ──────────────────────────────────────────

class TestGenerateReportPdf:

    def test_returns_bytes(self) -> None:
        result = generate_report_pdf(_make_report())
        assert isinstance(result, bytes)

    def test_output_starts_with_pdf_header(self) -> None:
        result = generate_report_pdf(_make_report())
        assert result[:4] == b"%PDF"

    def test_non_empty_pdf_for_completed_session(self) -> None:
        result = generate_report_pdf(_make_report(flagged=False))
        assert len(result) > 2000

    def test_non_empty_pdf_for_flagged_session(self) -> None:
        result = generate_report_pdf(_make_report(flagged=True))
        assert len(result) > 2000

    def test_flagged_pdf_is_valid_bytes(self) -> None:
        result = generate_report_pdf(_make_report(flagged=True))
        assert b"PDF" in result

    def test_handles_missing_end_ts(self) -> None:
        report = _make_report(with_end_ts=False)
        result = generate_report_pdf(report)
        assert isinstance(result, bytes)
        assert len(result) > 1000

    def test_generates_for_all_five_signals(self) -> None:
        report = _make_report()
        report["signals"] = _demo_score_data()["signals"]
        result = generate_report_pdf(report)
        assert isinstance(result, bytes)

    def test_does_not_raise_on_empty_flag_reason(self) -> None:
        report = _make_report(flagged=False)
        report["flag_reason"] = ""
        result = generate_report_pdf(report)
        assert isinstance(result, bytes)

    def test_does_not_raise_on_zero_trust_score(self) -> None:
        report = _make_report(flagged=True)
        report["trust_score"] = 0.0
        result = generate_report_pdf(report)
        assert isinstance(result, bytes)

    def test_does_not_raise_on_perfect_trust_score(self) -> None:
        report = _make_report(flagged=False)
        report["trust_score"] = 100.0
        result = generate_report_pdf(report)
        assert isinstance(result, bytes)
