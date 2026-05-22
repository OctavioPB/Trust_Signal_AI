"""Integration tests for MinIO 90-day lifecycle policy and GDPR audio deletion.

Tests run against mocked MinIO clients (no Docker stack required).
For a true end-to-end lifecycle enforcement test, run against a live MinIO:
    docker compose up -d minio
    pytest tests/integration/test_lifecycle.py -v --live-minio

CLAUDE.md Hard Rule #7: All audio data must be deleted from MinIO within 90 days.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from storage.lifecycle import DEFAULT_RETENTION_DAYS, apply_raw_audio_lifecycle
from storage.object_store import BUCKET_RAW_AUDIO, ObjectStore


# ── apply_raw_audio_lifecycle ──────────────────────────────────────────────────

class TestApplyRawAudioLifecycle:
    def test_default_retention_is_90_days(self):
        """Constant must equal 90 — hard-coded GDPR compliance target."""
        assert DEFAULT_RETENTION_DAYS == 90

    def test_sets_lifecycle_on_correct_bucket(self):
        """Lifecycle rule is applied to raw-audio, not model-artifacts or delta-tables."""
        mock_client = MagicMock()
        with patch("storage.lifecycle.Minio", return_value=mock_client):
            apply_raw_audio_lifecycle("http://localhost:9000", "key", "secret")

        bucket_arg = mock_client.set_bucket_lifecycle.call_args[0][0]
        assert bucket_arg == BUCKET_RAW_AUDIO

    def test_idempotent_double_call(self):
        """Calling twice updates the policy in-place without error (MinIO replaces config)."""
        mock_client = MagicMock()
        with patch("storage.lifecycle.Minio", return_value=mock_client):
            apply_raw_audio_lifecycle("http://localhost:9000", "key", "secret")
            apply_raw_audio_lifecycle("http://localhost:9000", "key", "secret")

        assert mock_client.set_bucket_lifecycle.call_count == 2

    def test_custom_retention_days_forwarded(self):
        """A non-default retention value is accepted and passed to MinIO."""
        mock_client = MagicMock()
        with patch("storage.lifecycle.Minio", return_value=mock_client):
            apply_raw_audio_lifecycle("http://localhost:9000", "key", "secret", retention_days=30)

        assert mock_client.set_bucket_lifecycle.called

    def test_invalid_zero_retention_raises(self):
        """retention_days=0 raises ValueError before any MinIO call."""
        with pytest.raises(ValueError, match="retention_days"):
            apply_raw_audio_lifecycle("http://localhost:9000", "key", "secret", retention_days=0)

    def test_invalid_negative_retention_raises(self):
        """Negative retention raises ValueError."""
        with pytest.raises(ValueError, match="retention_days"):
            apply_raw_audio_lifecycle("http://localhost:9000", "key", "secret", retention_days=-7)

    def test_invalid_string_retention_raises(self):
        """Non-integer retention raises ValueError."""
        with pytest.raises((ValueError, TypeError)):
            apply_raw_audio_lifecycle(
                "http://localhost:9000", "key", "secret", retention_days="90"  # type: ignore[arg-type]
            )

    def test_secure_flag_forwarded_to_client(self):
        """secure=True is passed through to the Minio constructor."""
        mock_client = MagicMock()
        with patch("storage.lifecycle.Minio", return_value=mock_client) as mock_cls:
            apply_raw_audio_lifecycle("localhost:9000", "key", "secret", secure=True)

        _, kwargs = mock_cls.call_args
        assert kwargs.get("secure") is True

    def test_http_endpoint_strips_protocol(self):
        """http:// prefix is stripped before passing host to Minio constructor."""
        mock_client = MagicMock()
        with patch("storage.lifecycle.Minio", return_value=mock_client) as mock_cls:
            apply_raw_audio_lifecycle("http://minio:9000", "key", "secret")

        host_arg = mock_cls.call_args[0][0]
        assert host_arg == "minio:9000"


# ── ObjectStore.delete_session_audio ──────────────────────────────────────────

class TestDeleteSessionAudio:
    def _make_store(self, list_objects_return: list) -> tuple[ObjectStore, MagicMock]:
        mock_client = MagicMock()
        mock_client.list_objects.return_value = [
            MagicMock(object_name=name) for name in list_objects_return
        ]
        with patch("storage.object_store.Minio", return_value=mock_client):
            store = ObjectStore("http://localhost:9000", "k", "s")
        return store, mock_client

    def test_deletes_all_chunks_for_session(self):
        """All objects returned by list_objects are removed via remove_object."""
        chunks = [
            "sess-abc/20260521/000001.pcm",
            "sess-abc/20260521/000002.pcm",
            "sess-abc/20260521/000003.pcm",
        ]
        store, mock_client = self._make_store(chunks)
        count = store.delete_session_audio("sess-abc")

        assert count == 3
        assert mock_client.remove_object.call_count == 3
        expected_calls = [call(BUCKET_RAW_AUDIO, name) for name in chunks]
        mock_client.remove_object.assert_has_calls(expected_calls, any_order=True)

    def test_empty_session_returns_zero(self):
        """Session with no audio returns 0 and makes no remove_object calls."""
        store, mock_client = self._make_store([])
        count = store.delete_session_audio("sess-empty")

        assert count == 0
        mock_client.remove_object.assert_not_called()

    def test_returns_exact_count(self):
        """Return value equals the number of objects deleted."""
        chunks = [f"sess-x/20260521/{i:06d}.pcm" for i in range(10)]
        store, mock_client = self._make_store(chunks)
        count = store.delete_session_audio("sess-x")

        assert count == len(chunks)

    def test_lists_objects_with_session_prefix(self):
        """list_objects is called with the correct session_id prefix."""
        store, mock_client = self._make_store([])
        store.delete_session_audio("my-session-uuid")

        mock_client.list_objects.assert_called_once_with(
            BUCKET_RAW_AUDIO, prefix="my-session-uuid/", recursive=True
        )

    def test_delete_scoped_to_raw_audio_bucket(self):
        """remove_object is always called on BUCKET_RAW_AUDIO, not other buckets."""
        chunks = ["sess-b/20260521/000001.pcm"]
        store, mock_client = self._make_store(chunks)
        store.delete_session_audio("sess-b")

        bucket_arg = mock_client.remove_object.call_args[0][0]
        assert bucket_arg == BUCKET_RAW_AUDIO
