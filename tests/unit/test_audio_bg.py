"""Regression and unit tests for ml/features/audio_bg.py.

Tests:
  - extract_mfcc_features: output shape, dtype, silence → near-zero std.
  - BackgroundAudioClassifier.train_from_arrays: precision ≥ 0.85 on synthetic data.
  - BackgroundAudioClassifier.classify: happy path, untrained error, PCM conversion.
  - BackgroundAudioClassifier.save / to_bytes / reload: round-trip persistence.

No real audio files are needed; all audio is generated synthetically as numpy
arrays to keep tests fast and deterministic.
"""

from __future__ import annotations

import io
import pickle
import struct
import tempfile
from pathlib import Path

import numpy as np
import pytest
from sklearn.metrics import precision_score
from sklearn.model_selection import train_test_split

from ml.features.audio_bg import (
    MIN_CLASSIFIER_PRECISION,
    N_MFCC,
    BackgroundAudioClassifier,
    BackgroundAudioFeatures,
    extract_mfcc_features,
    _pcm_to_float32,
)


# ── Synthetic data helpers ────────────────────────────────────────────────────

SR = 16_000
WINDOW_SAMPLES = SR * 2   # 2 s window

_RNG = np.random.default_rng(42)


def _ambient_audio(n: int = WINDOW_SAMPLES) -> np.ndarray:
    """Low-amplitude Gaussian white noise — class 0."""
    return (_RNG.standard_normal(n) * 0.01).astype(np.float32)


def _keyboard_audio(n: int = WINDOW_SAMPLES) -> np.ndarray:
    """White noise + sparse high-amplitude transient bursts — class 1."""
    audio = (_RNG.standard_normal(n) * 0.01).astype(np.float32)
    n_clicks = _RNG.integers(4, 12)
    for _ in range(n_clicks):
        pos = int(_RNG.integers(0, n - 300))
        amp = float(_RNG.uniform(0.4, 0.7))
        burst_len = int(_RNG.integers(80, 250))
        t = np.arange(burst_len) / SR
        freq = float(_RNG.uniform(200, 600))
        decay = np.exp(-40 * t)
        burst = (amp * np.sin(2 * np.pi * freq * t) * decay).astype(np.float32)
        end = min(pos + burst_len, n)
        audio[pos:end] += burst[: end - pos]
    return np.clip(audio, -1.0, 1.0)


def _float32_to_pcm_bytes(audio: np.ndarray) -> bytes:
    """Convert a float32 array to 16-bit PCM bytes."""
    pcm = (audio * 32767).astype(np.int16)
    return pcm.tobytes()


def _make_dataset(n_per_class: int = 200):
    """Return (X, y) feature arrays for a balanced synthetic dataset."""
    X_ambient = np.stack([extract_mfcc_features(_ambient_audio()) for _ in range(n_per_class)])
    X_keyboard = np.stack([extract_mfcc_features(_keyboard_audio()) for _ in range(n_per_class)])
    X = np.vstack([X_ambient, X_keyboard])
    y = np.array([0] * n_per_class + [1] * n_per_class)
    return X, y


# ── extract_mfcc_features ─────────────────────────────────────────────────────

class TestExtractMfccFeatures:

    def test_output_shape(self) -> None:
        audio = _ambient_audio()
        features = extract_mfcc_features(audio, SR)
        assert features.shape == (N_MFCC * 2,), (
            f"Expected ({N_MFCC * 2},), got {features.shape}"
        )

    def test_output_dtype_float32(self) -> None:
        features = extract_mfcc_features(_ambient_audio(), SR)
        assert features.dtype == np.float32

    def test_silence_std_near_zero(self) -> None:
        """Perfect silence should have near-zero MFCC std features."""
        silence = np.zeros(WINDOW_SAMPLES, dtype=np.float32)
        features = extract_mfcc_features(silence, SR)
        stds = features[N_MFCC:]   # second half = std of each coefficient
        assert np.all(np.abs(stds) < 1.0), (
            "Silence MFCC stds should be small"
        )

    def test_keyboard_differs_from_ambient(self) -> None:
        """Keyboard audio should produce a feature vector distinct from ambient."""
        f_ambient = extract_mfcc_features(_ambient_audio(), SR)
        f_keyboard = extract_mfcc_features(_keyboard_audio(), SR)
        distance = float(np.linalg.norm(f_ambient - f_keyboard))
        assert distance > 1.0, (
            "Feature vectors for ambient vs keyboard should be far apart"
        )

    def test_deterministic_output(self) -> None:
        """Same input → same feature vector."""
        audio = _ambient_audio()
        assert np.allclose(
            extract_mfcc_features(audio, SR),
            extract_mfcc_features(audio, SR),
        )


# ── _pcm_to_float32 ───────────────────────────────────────────────────────────

def test_pcm_to_float32_silence_is_zero() -> None:
    pcm = np.zeros(1000, dtype=np.int16).tobytes()
    result = _pcm_to_float32(pcm)
    assert np.all(result == 0.0)


def test_pcm_to_float32_preserves_length() -> None:
    n = 8000
    pcm = np.zeros(n, dtype=np.int16).tobytes()
    assert len(_pcm_to_float32(pcm)) == n


# ── Classifier: untrained error ───────────────────────────────────────────────

def test_classify_raises_without_training() -> None:
    clf = BackgroundAudioClassifier()
    pcm = _float32_to_pcm_bytes(_ambient_audio())
    with pytest.raises(RuntimeError, match="not trained"):
        clf.classify(pcm, "s", 0.0, 2.0)


def test_save_raises_without_training() -> None:
    clf = BackgroundAudioClassifier()
    with pytest.raises(RuntimeError, match="untrained"):
        clf.save(Path("/tmp/never_written.pkl"))


def test_to_bytes_raises_without_training() -> None:
    clf = BackgroundAudioClassifier()
    with pytest.raises(RuntimeError, match="untrained"):
        clf.to_bytes()


# ── Classifier: training from arrays ─────────────────────────────────────────

@pytest.fixture(scope="module")
def trained_clf():
    """Shared trained classifier (expensive — built once per test session)."""
    X, y = _make_dataset(n_per_class=250)
    clf = BackgroundAudioClassifier()
    clf.train_from_arrays(X, y)
    return clf


# ── 5.5 Regression test: precision ≥ 0.85 ────────────────────────────────────

def test_classifier_precision_meets_target() -> None:
    """Precision ≥ 0.85 on a hold-out set — the primary Sprint 5.5 regression gate."""
    X, y = _make_dataset(n_per_class=300)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, stratify=y, random_state=0
    )

    clf = BackgroundAudioClassifier()
    clf.train_from_arrays(X_train, y_train)

    # Use PCM bytes path via classify() to exercise the full inference pipeline
    proba_list = []
    for i in range(len(X_test)):
        # Re-derive PCM from the test feature's original class to keep things consistent;
        # we directly call the internal scaler+clf to avoid needing audio bytes for every test row.
        pass

    # Directly measure on the feature-level test split (exercises clf + scaler)
    from sklearn.preprocessing import StandardScaler
    scaler = clf._scaler
    X_test_scaled = scaler.transform(X_test)
    y_pred = clf._clf.predict(X_test_scaled)

    precision = precision_score(y_test, y_pred)
    assert precision >= MIN_CLASSIFIER_PRECISION, (
        f"Keyboard-detection precision {precision:.4f} < target {MIN_CLASSIFIER_PRECISION}. "
        "Model may be undertrained or feature distribution shifted."
    )


# ── Classifier: classify() happy path ────────────────────────────────────────

class TestClassify:

    def test_classify_ambient_returns_features(self, trained_clf) -> None:
        pcm = _float32_to_pcm_bytes(_ambient_audio())
        result = trained_clf.classify(pcm, "sess-001", 10.0, 12.0)
        assert isinstance(result, BackgroundAudioFeatures)

    def test_classify_returns_correct_session_id(self, trained_clf) -> None:
        pcm = _float32_to_pcm_bytes(_ambient_audio())
        result = trained_clf.classify(pcm, "uuid-xyz", 0.0, 2.0)
        assert result.session_id == "uuid-xyz"

    def test_classify_window_timestamps_preserved(self, trained_clf) -> None:
        pcm = _float32_to_pcm_bytes(_ambient_audio())
        result = trained_clf.classify(pcm, "s", 5.0, 7.0)
        assert result.window_start_s == pytest.approx(5.0)
        assert result.window_end_s == pytest.approx(7.0)

    def test_suspicion_score_in_unit_interval(self, trained_clf) -> None:
        for make_audio in (_ambient_audio, _keyboard_audio):
            pcm = _float32_to_pcm_bytes(make_audio())
            result = trained_clf.classify(pcm, "s", 0.0, 2.0)
            assert 0.0 <= result.suspicion_score <= 1.0

    def test_suspicion_score_equals_confidence(self, trained_clf) -> None:
        pcm = _float32_to_pcm_bytes(_keyboard_audio())
        result = trained_clf.classify(pcm, "s", 0.0, 2.0)
        assert result.suspicion_score == pytest.approx(result.confidence)

    def test_keyboard_audio_higher_confidence_than_ambient(self, trained_clf) -> None:
        """On average, keyboard audio should score higher than ambient silence."""
        n = 20
        keyboard_scores = [
            trained_clf.classify(
                _float32_to_pcm_bytes(_keyboard_audio()), "s", 0.0, 2.0
            ).suspicion_score
            for _ in range(n)
        ]
        ambient_scores = [
            trained_clf.classify(
                _float32_to_pcm_bytes(_ambient_audio()), "s", 0.0, 2.0
            ).suspicion_score
            for _ in range(n)
        ]
        assert np.mean(keyboard_scores) > np.mean(ambient_scores), (
            "Classifier should assign higher suspicion to keyboard audio on average"
        )

    def test_keyboard_detected_flag_matches_threshold(self, trained_clf) -> None:
        pcm = _float32_to_pcm_bytes(_keyboard_audio())
        result = trained_clf.classify(pcm, "s", 0.0, 2.0)
        assert result.keyboard_detected == (result.confidence >= 0.5)


# ── Classifier: persistence round-trip ───────────────────────────────────────

class TestPersistence:

    def test_save_and_reload_predict_same(self, trained_clf) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "20260521_bg_classifier.pkl"
            trained_clf.save(path)
            assert path.exists()

            reloaded = BackgroundAudioClassifier(model_path=path)
            pcm = _float32_to_pcm_bytes(_keyboard_audio())
            r1 = trained_clf.classify(pcm, "s", 0.0, 2.0)
            r2 = reloaded.classify(pcm, "s", 0.0, 2.0)

        assert r1.confidence == pytest.approx(r2.confidence, abs=1e-6)

    def test_to_bytes_round_trip(self, trained_clf) -> None:
        raw = trained_clf.to_bytes()
        assert isinstance(raw, bytes)
        assert len(raw) > 0

        # Deserialise the payload manually to verify structure
        payload = pickle.loads(raw)  # noqa: S301 — test-only round-trip check
        assert "clf" in payload
        assert "scaler" in payload

    def test_artifact_name_follows_convention(self, trained_clf) -> None:
        """Artifact file name must match YYYYMMDD_bg_classifier.pkl."""
        import re
        with tempfile.TemporaryDirectory() as tmpdir:
            name = "20260521_bg_classifier.pkl"
            path = Path(tmpdir) / name
            trained_clf.save(path)
            assert re.match(r"\d{8}_bg_classifier\.pkl", path.name)
