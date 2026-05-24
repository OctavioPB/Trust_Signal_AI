"""Unit tests for the resumes bucket lifecycle policy.

Verifies that apply_resumes_lifecycle() correctly configures a 90-day expiry
rule on the resumes bucket. All MinIO I/O is mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from storage.lifecycle import apply_resumes_lifecycle
from storage.object_store import BUCKET_RESUMES


# ── Validation ─────────────────────────────────────────────────────────────────

def test_rejects_zero_retention_days() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        apply_resumes_lifecycle("http://localhost:9000", "key", "secret", retention_days=0)


def test_rejects_negative_retention_days() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        apply_resumes_lifecycle("http://localhost:9000", "key", "secret", retention_days=-5)


def test_rejects_float_retention_days() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        apply_resumes_lifecycle("http://localhost:9000", "key", "secret", retention_days=30.5)  # type: ignore[arg-type]


# ── MinIO interaction ──────────────────────────────────────────────────────────

@patch("storage.lifecycle.Minio")
def test_calls_set_bucket_lifecycle(mock_minio_cls: MagicMock) -> None:
    mock_client = MagicMock()
    mock_minio_cls.return_value = mock_client

    apply_resumes_lifecycle("http://localhost:9000", "key", "secret")

    mock_client.set_bucket_lifecycle.assert_called_once()


@patch("storage.lifecycle.Minio")
def test_targets_resumes_bucket(mock_minio_cls: MagicMock) -> None:
    mock_client = MagicMock()
    mock_minio_cls.return_value = mock_client

    apply_resumes_lifecycle("http://localhost:9000", "key", "secret")

    bucket_arg = mock_client.set_bucket_lifecycle.call_args.args[0]
    assert bucket_arg == BUCKET_RESUMES


@patch("storage.lifecycle.Minio")
def test_strips_http_protocol_from_endpoint(mock_minio_cls: MagicMock) -> None:
    mock_minio_cls.return_value = MagicMock()

    apply_resumes_lifecycle("http://localhost:9000", "key", "secret")

    host_arg = mock_minio_cls.call_args.args[0]
    assert not host_arg.startswith("http://")
    assert not host_arg.startswith("https://")


@patch("storage.lifecycle.Minio")
def test_strips_https_protocol_from_endpoint(mock_minio_cls: MagicMock) -> None:
    mock_minio_cls.return_value = MagicMock()

    apply_resumes_lifecycle("https://minio.prod.example.com", "key", "secret")

    host_arg = mock_minio_cls.call_args.args[0]
    assert not host_arg.startswith("https://")


@patch("storage.lifecycle.Minio")
def test_lifecycle_rule_id_is_resumes_auto_expire(mock_minio_cls: MagicMock) -> None:
    """The rule_id must be distinct from the raw-audio rule to avoid collision."""
    from minio.lifecycleconfig import LifecycleConfig

    captured: list[LifecycleConfig] = []

    def _capture_lifecycle(bucket, lifecycle_cfg):
        captured.append(lifecycle_cfg)

    mock_client = MagicMock()
    mock_client.set_bucket_lifecycle.side_effect = _capture_lifecycle
    mock_minio_cls.return_value = mock_client

    apply_resumes_lifecycle("http://localhost:9000", "key", "secret")

    assert captured, "set_bucket_lifecycle was not called"
    rules = captured[0].rules
    assert len(rules) == 1
    assert rules[0].rule_id == "resumes-auto-expire"


@patch("storage.lifecycle.Minio")
def test_default_retention_is_90_days(mock_minio_cls: MagicMock) -> None:
    from minio.lifecycleconfig import LifecycleConfig

    captured: list[LifecycleConfig] = []

    def _capture(bucket, cfg):
        captured.append(cfg)

    mock_client = MagicMock()
    mock_client.set_bucket_lifecycle.side_effect = _capture
    mock_minio_cls.return_value = mock_client

    apply_resumes_lifecycle("http://localhost:9000", "key", "secret")

    rule = captured[0].rules[0]
    assert rule.expiration.days == 90


@patch("storage.lifecycle.Minio")
def test_custom_retention_days_forwarded(mock_minio_cls: MagicMock) -> None:
    from minio.lifecycleconfig import LifecycleConfig

    captured: list[LifecycleConfig] = []

    def _capture(bucket, cfg):
        captured.append(cfg)

    mock_client = MagicMock()
    mock_client.set_bucket_lifecycle.side_effect = _capture
    mock_minio_cls.return_value = mock_client

    apply_resumes_lifecycle("http://localhost:9000", "key", "secret", retention_days=180)

    rule = captured[0].rules[0]
    assert rule.expiration.days == 180


# ── Idempotency guarantee ──────────────────────────────────────────────────────

@patch("storage.lifecycle.Minio")
def test_idempotent_two_calls_both_succeed(mock_minio_cls: MagicMock) -> None:
    """Calling twice must not raise — MinIO replaces the config each time."""
    mock_client = MagicMock()
    mock_minio_cls.return_value = mock_client

    apply_resumes_lifecycle("http://localhost:9000", "key", "secret")
    apply_resumes_lifecycle("http://localhost:9000", "key", "secret")

    assert mock_client.set_bucket_lifecycle.call_count == 2
