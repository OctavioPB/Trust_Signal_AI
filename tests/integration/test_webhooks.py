"""Integration tests for api/webhooks.py.

Verifies:
  1. Payload structure — no PII, required fields present, flags populated correctly.
  2. Delivery behaviour — success path, retry on transient failure, correct attempt count.
  3. Back-off — sleep called between retries with the correct delays.
  4. DLQ — dead-letter record written on permanent failure; path, schema, and content.
  5. dispatch_to_configured_ats — skips unconfigured ATSes; delivers to configured ones.

All HTTP calls and Spark operations are mocked; no real network or Spark required.

Run with:
    pytest tests/integration/test_webhooks.py -m integration --run-integration -v
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from api.webhooks import (
    TABLE_WEBHOOK_DLQ,
    WebhookDelivery,
    WebhookFlag,
    WebhookPayload,
    _BACKOFF_SECONDS,
    _MAX_RETRIES,
    build_payload_from_result,
    dispatch_to_configured_ats,
)
import config

pytestmark = pytest.mark.integration

# ── Fixed test constants ───────────────────────────────────────────────────────

_CANDIDATE_UUID = "a1b2c3d4-0000-0000-0000-000000000099"
_WEBHOOK_URL    = "https://ats.example.com/webhook/prescreening"


# ── Response stubs ─────────────────────────────────────────────────────────────

def _success_resp(status_code: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.raise_for_status.return_value = None
    return resp


def _error_resp(status_code: int = 503) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        f"{status_code} Server Error",
        request=MagicMock(),
        response=resp,
    )
    return resp


# ── Delivery factory ───────────────────────────────────────────────────────────

def _make_delivery(
    mock_client: MagicMock,
    mock_spark: MagicMock | None = None,
    sleep_log: list[float] | None = None,
) -> WebhookDelivery:
    recorded = sleep_log if sleep_log is not None else []

    def _sleep(s: float) -> None:
        recorded.append(s)

    return WebhookDelivery(
        ats_name="greenhouse",
        webhook_url=_WEBHOOK_URL,
        delta_lake_path="/delta",
        _http_client=mock_client,
        _spark=mock_spark,
        _sleep_fn=_sleep,
    )


def _make_payload(flagged: bool = True) -> WebhookPayload:
    return WebhookPayload(
        candidate_uuid=_CANDIDATE_UUID,
        prescreening_score=78.5 if flagged else 12.0,
        flags=[
            WebhookFlag(
                signal="Resume AI Score",
                explanation="High perplexity and low burstiness detected.",
                score=0.824,
            )
        ] if flagged else [],
        delivered_at=1_700_000_000.0,
    )


def _mock_spark() -> MagicMock:
    spark  = MagicMock()
    df     = MagicMock()
    spark.createDataFrame.return_value = df
    df.write.format.return_value.mode.return_value.save = MagicMock()
    return spark


# ── Payload structure ──────────────────────────────────────────────────────────

def test_payload_contains_no_pii():
    d = _make_payload().to_dict()
    assert "name"      not in d
    assert "email"     not in d
    assert "recruiter" not in d


def test_payload_candidate_uuid_present():
    d = _make_payload().to_dict()
    assert d["candidate_uuid"] == _CANDIDATE_UUID


def test_payload_required_fields():
    d = _make_payload().to_dict()
    for field in ("candidate_uuid", "prescreening_score", "flags", "delivered_at"):
        assert field in d


def test_flags_have_required_keys():
    d = _make_payload(flagged=True).to_dict()
    assert len(d["flags"]) == 1
    flag = d["flags"][0]
    assert "signal"      in flag
    assert "explanation" in flag
    assert "score"       in flag


def test_unflagged_payload_has_empty_flags():
    d = _make_payload(flagged=False).to_dict()
    assert d["flags"] == []


def test_payload_is_json_serializable():
    assert json.dumps(_make_payload().to_dict())   # must not raise


# ── Successful delivery ────────────────────────────────────────────────────────

def test_successful_delivery_returns_true():
    mock_client = MagicMock()
    mock_client.post.return_value = _success_resp()
    delivery = _make_delivery(mock_client)
    assert delivery.deliver(_make_payload()) is True


def test_delivery_calls_correct_url():
    mock_client = MagicMock()
    mock_client.post.return_value = _success_resp()
    _make_delivery(mock_client).deliver(_make_payload())
    assert mock_client.post.call_args[0][0] == _WEBHOOK_URL


def test_delivery_sends_json_content_type():
    mock_client = MagicMock()
    mock_client.post.return_value = _success_resp()
    _make_delivery(mock_client).deliver(_make_payload())
    headers = mock_client.post.call_args[1].get("headers", {})
    assert headers.get("Content-Type") == "application/json"


def test_single_attempt_on_success():
    mock_client = MagicMock()
    mock_client.post.return_value = _success_resp()
    _make_delivery(mock_client).deliver(_make_payload())
    assert mock_client.post.call_count == 1


# ── Retry behaviour ────────────────────────────────────────────────────────────

def test_retry_succeeds_on_second_attempt():
    mock_client = MagicMock()
    mock_client.post.side_effect = [_error_resp(503), _success_resp(200)]
    delivery = _make_delivery(mock_client)
    assert delivery.deliver(_make_payload()) is True
    assert mock_client.post.call_count == 2


def test_retry_succeeds_on_third_attempt():
    mock_client = MagicMock()
    mock_client.post.side_effect = [
        _error_resp(503), _error_resp(503), _success_resp(200)
    ]
    delivery = _make_delivery(mock_client)
    assert delivery.deliver(_make_payload()) is True
    assert mock_client.post.call_count == 3


def test_total_attempts_equals_max_retries_plus_one():
    """1 initial attempt + _MAX_RETRIES retries = _MAX_RETRIES + 1 total calls."""
    mock_client = MagicMock()
    mock_client.post.side_effect = [_error_resp()] * (_MAX_RETRIES + 1)
    delivery = _make_delivery(mock_client, _mock_spark())
    delivery.deliver(_make_payload())
    assert mock_client.post.call_count == _MAX_RETRIES + 1


def test_returns_false_when_all_attempts_fail():
    mock_client = MagicMock()
    mock_client.post.side_effect = [_error_resp()] * (_MAX_RETRIES + 1)
    delivery = _make_delivery(mock_client, _mock_spark())
    assert delivery.deliver(_make_payload()) is False


# ── Back-off ───────────────────────────────────────────────────────────────────

def test_sleep_called_once_after_first_failure():
    sleep_log: list[float] = []
    mock_client = MagicMock()
    mock_client.post.side_effect = [_error_resp(), _success_resp()]
    _make_delivery(mock_client, sleep_log=sleep_log).deliver(_make_payload())
    assert len(sleep_log) == 1
    assert sleep_log[0] == _BACKOFF_SECONDS[0]


def test_sleep_uses_first_backoff_before_second_attempt():
    sleep_log: list[float] = []
    mock_client = MagicMock()
    mock_client.post.side_effect = [_error_resp(), _success_resp()]
    _make_delivery(mock_client, sleep_log=sleep_log).deliver(_make_payload())
    assert sleep_log[0] == 10


def test_sleep_uses_all_backoffs_on_full_failure():
    sleep_log: list[float] = []
    mock_client = MagicMock()
    mock_client.post.side_effect = [_error_resp()] * (_MAX_RETRIES + 1)
    _make_delivery(mock_client, _mock_spark(), sleep_log).deliver(_make_payload())
    assert sleep_log == list(_BACKOFF_SECONDS)


def test_no_sleep_on_first_attempt_success():
    sleep_log: list[float] = []
    mock_client = MagicMock()
    mock_client.post.return_value = _success_resp()
    _make_delivery(mock_client, sleep_log=sleep_log).deliver(_make_payload())
    assert sleep_log == []


# ── DLQ ───────────────────────────────────────────────────────────────────────

def test_dlq_written_on_permanent_failure():
    mock_client = MagicMock()
    mock_client.post.side_effect = [_error_resp()] * (_MAX_RETRIES + 1)
    spark = _mock_spark()
    _make_delivery(mock_client, spark).deliver(_make_payload())
    spark.createDataFrame.assert_called_once()
    spark.createDataFrame.return_value.write.format.assert_called_once_with("delta")


def test_dlq_uses_append_mode():
    mock_client = MagicMock()
    mock_client.post.side_effect = [_error_resp()] * (_MAX_RETRIES + 1)
    spark = _mock_spark()
    _make_delivery(mock_client, spark).deliver(_make_payload())
    spark.createDataFrame.return_value.write.format.return_value.mode.assert_called_once_with("append")


def test_dlq_path_contains_table_name():
    mock_client = MagicMock()
    mock_client.post.side_effect = [_error_resp()] * (_MAX_RETRIES + 1)
    spark = _mock_spark()
    save_mock = spark.createDataFrame.return_value.write.format.return_value.mode.return_value.save
    _make_delivery(mock_client, spark).deliver(_make_payload())
    saved_path = save_mock.call_args[0][0]
    assert TABLE_WEBHOOK_DLQ in saved_path
    assert "/delta" in saved_path


def test_dlq_row_contains_candidate_uuid():
    mock_client = MagicMock()
    mock_client.post.side_effect = [_error_resp()] * (_MAX_RETRIES + 1)
    spark = _mock_spark()
    _make_delivery(mock_client, spark).deliver(_make_payload())
    rows = spark.createDataFrame.call_args[0][0]
    assert rows[0][0] == _CANDIDATE_UUID   # first column: candidate_uuid


def test_dlq_not_written_on_success():
    mock_client = MagicMock()
    mock_client.post.return_value = _success_resp()
    spark = _mock_spark()
    _make_delivery(mock_client, spark).deliver(_make_payload())
    spark.createDataFrame.assert_not_called()


def test_dlq_not_written_when_retry_eventually_succeeds():
    mock_client = MagicMock()
    mock_client.post.side_effect = [_error_resp(), _success_resp()]
    spark = _mock_spark()
    _make_delivery(mock_client, spark).deliver(_make_payload())
    spark.createDataFrame.assert_not_called()


# ── build_payload_from_result ─────────────────────────────────────────────────

def test_build_payload_no_pii():
    payload = build_payload_from_result(
        candidate_uuid=_CANDIDATE_UUID,
        prescreening_score=78.5,
        signals=[
            {"signal_name": "Resume AI Score", "raw_suspicion": 0.82, "explanation": "High."},
        ],
    )
    d = payload.to_dict()
    assert d["candidate_uuid"] == _CANDIDATE_UUID
    assert "name"  not in d
    assert "email" not in d


def test_build_payload_only_high_suspicion_signals_become_flags():
    """Only signals with raw_suspicion >= 0.5 are included as flags."""
    payload = build_payload_from_result(
        candidate_uuid=_CANDIDATE_UUID,
        prescreening_score=78.5,
        signals=[
            {"signal_name": "Resume AI Score", "raw_suspicion": 0.82, "explanation": "High."},
            {"signal_name": "Repo AI Score",   "raw_suspicion": 0.30, "explanation": "Low."},
        ],
    )
    assert len(payload.flags) == 1
    assert payload.flags[0].signal == "Resume AI Score"


def test_build_payload_no_flags_when_all_low_suspicion():
    payload = build_payload_from_result(
        candidate_uuid=_CANDIDATE_UUID,
        prescreening_score=20.0,
        signals=[
            {"signal_name": "Resume AI Score", "raw_suspicion": 0.20, "explanation": "Low."},
            {"signal_name": "Repo AI Score",   "raw_suspicion": 0.15, "explanation": "Low."},
        ],
    )
    assert payload.flags == []


# ── dispatch_to_configured_ats ─────────────────────────────────────────────────

def test_dispatch_skips_unconfigured_ats():
    payload = _make_payload()
    with (
        patch.object(config, "ATS_WEBHOOK_GREENHOUSE", None),
        patch.object(config, "ATS_WEBHOOK_LEVER",      None),
    ):
        results = dispatch_to_configured_ats(payload, delta_lake_path="/delta")
    assert results == {}


def test_dispatch_delivers_to_greenhouse_when_configured():
    mock_client = MagicMock()
    mock_client.post.return_value = _success_resp()
    payload = _make_payload()
    with (
        patch.object(config, "ATS_WEBHOOK_GREENHOUSE", "https://greenhouse.test/hook"),
        patch.object(config, "ATS_WEBHOOK_LEVER",      None),
    ):
        results = dispatch_to_configured_ats(
            payload,
            delta_lake_path="/delta",
            _http_client=mock_client,
            _sleep_fn=lambda _: None,
        )
    assert results == {"greenhouse": True}


def test_dispatch_delivers_to_both_when_both_configured():
    mock_client = MagicMock()
    mock_client.post.return_value = _success_resp()
    payload = _make_payload()
    with (
        patch.object(config, "ATS_WEBHOOK_GREENHOUSE", "https://greenhouse.test/hook"),
        patch.object(config, "ATS_WEBHOOK_LEVER",      "https://lever.test/hook"),
    ):
        results = dispatch_to_configured_ats(
            payload,
            delta_lake_path="/delta",
            _http_client=mock_client,
            _sleep_fn=lambda _: None,
        )
    assert set(results.keys()) == {"greenhouse", "lever"}
    assert all(results.values())
