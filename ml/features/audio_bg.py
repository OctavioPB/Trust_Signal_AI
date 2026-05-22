"""Background audio classifier: keyboard detection during silence windows.

Extracts MFCC features from silence segments (no speech detected) and
classifies them as ``keyboard_present`` (label 1) vs ``ambient_silence``
(label 0) using a scikit-learn RandomForestClassifier.

Feature vector: mean + std of each MFCC coefficient across time frames →
shape (N_MFCC * 2,) = (26,) by default.

Artifact naming convention: ``YYYYMMDD_bg_classifier.pkl`` in MinIO
``model-artifacts`` bucket. Use ``BackgroundAudioClassifier.save()`` then
``ObjectStore.upload_model_artifact()`` to persist after training.
"""

from __future__ import annotations

import io
import pickle
from dataclasses import dataclass
from pathlib import Path

import librosa
import numpy as np
import structlog
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler

logger = structlog.get_logger(__name__)

# Minimum required precision on any regression test (guards against model rot)
MIN_CLASSIFIER_PRECISION = 0.85

# Number of MFCC coefficients to extract; feature vector = N_MFCC * 2 values
N_MFCC = 13


@dataclass
class BackgroundAudioFeatures:
    """Result of background audio classification for a single silence window.

    Attributes:
        session_id: UUID of the interview session.
        window_start_s: Start of the silence window (seconds from call start).
        window_end_s: End of the silence window.
        keyboard_detected: True when the keyboard-present class probability ≥ 0.5.
        confidence: Classifier probability for the ``keyboard_present`` class.
        suspicion_score: Score in [0, 1]; equal to ``confidence``.
    """

    session_id: str
    window_start_s: float
    window_end_s: float
    keyboard_detected: bool
    confidence: float
    suspicion_score: float


# ── Pure feature-extraction helper (testable without a model) ─────────────────

def extract_mfcc_features(audio_float32: np.ndarray, sample_rate: int = 16_000) -> np.ndarray:
    """Extract a fixed-length MFCC feature vector from a float32 audio array.

    The vector is the concatenation of the mean and standard deviation of each
    MFCC coefficient across all time frames, giving shape (N_MFCC * 2,).

    Args:
        audio_float32: Normalised float32 waveform in [-1, 1].
        sample_rate: Audio sample rate in Hz.

    Returns:
        1-D numpy array of shape (N_MFCC * 2,) = (26,).
    """
    mfccs = librosa.feature.mfcc(y=audio_float32, sr=sample_rate, n_mfcc=N_MFCC)
    return np.concatenate([mfccs.mean(axis=1), mfccs.std(axis=1)]).astype(np.float32)


def _pcm_to_float32(pcm_bytes: bytes) -> np.ndarray:
    """Convert raw 16-bit PCM bytes to a normalised float32 array."""
    return np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0


# ── Classifier ────────────────────────────────────────────────────────────────

class BackgroundAudioClassifier:
    """Random Forest classifier for keyboard detection in silence windows.

    The class wraps feature extraction (MFCC), a StandardScaler, and a
    RandomForestClassifier into a single pickleable object.

    Args:
        model_path: Path to a persisted ``.pkl`` classifier artifact.
            If None, the model must be trained before calling classify().
    """

    def __init__(self, model_path: Path | None = None) -> None:
        self._clf: RandomForestClassifier | None = None
        self._scaler: StandardScaler | None = None
        self._log = logger.bind(component="BackgroundAudioClassifier")

        if model_path is not None:
            self._load(Path(model_path))

    # ── Training ──────────────────────────────────────────────────────────────

    def train(self, audio_dir: Path, labels_csv: Path) -> None:
        """Train the classifier on a labelled dataset of silence windows.

        Reads each audio file listed in ``labels_csv``, extracts MFCC features,
        fits a StandardScaler, and trains a RandomForestClassifier.

        Args:
            audio_dir: Directory containing ``.wav`` silence window files.
            labels_csv: CSV with header ``filename,label``; label is 0 (ambient)
                or 1 (keyboard).

        Raises:
            FileNotFoundError: If ``audio_dir`` or ``labels_csv`` do not exist.
            ValueError: If the labels CSV contains no rows.
        """
        import csv

        audio_dir = Path(audio_dir)
        labels_csv = Path(labels_csv)

        X: list[np.ndarray] = []
        y: list[int] = []

        with labels_csv.open() as f:
            reader = csv.DictReader(f)
            for row in reader:
                wav_path = audio_dir / row["filename"]
                audio, sr = librosa.load(str(wav_path), sr=16_000, mono=True)
                features = extract_mfcc_features(audio, sr)
                X.append(features)
                y.append(int(row["label"]))

        if not X:
            raise ValueError(f"No rows found in {labels_csv}")

        X_arr = np.stack(X)
        y_arr = np.array(y)

        self._scaler = StandardScaler()
        X_scaled = self._scaler.fit_transform(X_arr)

        self._clf = RandomForestClassifier(
            n_estimators=100,
            max_depth=8,
            random_state=42,
            n_jobs=-1,
        )
        self._clf.fit(X_scaled, y_arr)

        self._log.info(
            "classifier_trained",
            n_samples=len(y_arr),
            n_keyboard=int(y_arr.sum()),
            n_ambient=int((y_arr == 0).sum()),
        )

    def train_from_arrays(
        self,
        features: np.ndarray,
        labels: np.ndarray,
    ) -> None:
        """Train directly from pre-computed feature arrays.

        Used by unit / regression tests to bypass file I/O.

        Args:
            features: Float array of shape (n_samples, n_features).
            labels: Integer label array of shape (n_samples,); 0=ambient, 1=keyboard.
        """
        self._scaler = StandardScaler()
        X_scaled = self._scaler.fit_transform(features)

        self._clf = RandomForestClassifier(
            n_estimators=100,
            max_depth=8,
            random_state=42,
            n_jobs=-1,
        )
        self._clf.fit(X_scaled, labels)
        self._log.debug("classifier_trained_from_arrays", n_samples=len(labels))

    # ── Inference ─────────────────────────────────────────────────────────────

    def classify(
        self,
        audio_bytes: bytes,
        session_id: str,
        window_start_s: float,
        window_end_s: float,
        sample_rate: int = 16_000,
    ) -> BackgroundAudioFeatures:
        """Classify a silence window audio segment.

        Args:
            audio_bytes: Raw 16-bit PCM audio data.
            session_id: UUID of the interview session (no PII in logs).
            window_start_s: Start of the silence window (seconds from call start).
            window_end_s: End of the silence window.
            sample_rate: Audio sample rate in Hz.

        Returns:
            BackgroundAudioFeatures with ``suspicion_score`` in [0, 1].

        Raises:
            RuntimeError: If the classifier has not been trained or loaded.
        """
        if self._clf is None or self._scaler is None:
            raise RuntimeError("Classifier not trained. Call train() or load a model first.")

        audio = _pcm_to_float32(audio_bytes)
        features = extract_mfcc_features(audio, sample_rate)
        features_scaled = self._scaler.transform(features.reshape(1, -1))

        proba = self._clf.predict_proba(features_scaled)[0]
        # Class ordering: [0=ambient, 1=keyboard]; if only one class was seen at
        # training time, predict_proba returns a single column — handle safely.
        classes = list(self._clf.classes_)
        keyboard_prob = float(proba[classes.index(1)]) if 1 in classes else 0.0

        detected = keyboard_prob >= 0.5

        self._log.debug(
            "window_classified",
            session_id=session_id,   # UUID — no PII
            window_start_s=window_start_s,
            window_end_s=window_end_s,
            keyboard_detected=detected,
            confidence=round(keyboard_prob, 4),
        )

        return BackgroundAudioFeatures(
            session_id=session_id,
            window_start_s=window_start_s,
            window_end_s=window_end_s,
            keyboard_detected=detected,
            confidence=keyboard_prob,
            suspicion_score=keyboard_prob,
        )

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self, artifact_path: Path) -> None:
        """Serialise the trained classifier to disk.

        The pickle contains both the scaler and the classifier so the artifact
        is self-contained. File name must follow ``YYYYMMDD_bg_classifier.pkl``.

        Args:
            artifact_path: Destination file path.

        Raises:
            RuntimeError: If the classifier has not been trained.
        """
        if self._clf is None or self._scaler is None:
            raise RuntimeError("Cannot save an untrained classifier.")

        artifact_path = Path(artifact_path)
        artifact_path.parent.mkdir(parents=True, exist_ok=True)

        payload = {"clf": self._clf, "scaler": self._scaler}
        with artifact_path.open("wb") as f:
            pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)

        self._log.info("classifier_saved", path=str(artifact_path))

    def to_bytes(self) -> bytes:
        """Serialise to bytes for direct upload to MinIO.

        Returns:
            Pickled bytes of the classifier + scaler payload.

        Raises:
            RuntimeError: If the classifier has not been trained.
        """
        if self._clf is None or self._scaler is None:
            raise RuntimeError("Cannot serialise an untrained classifier.")

        buf = io.BytesIO()
        pickle.dump({"clf": self._clf, "scaler": self._scaler}, buf, protocol=pickle.HIGHEST_PROTOCOL)
        return buf.getvalue()

    # ── Private ───────────────────────────────────────────────────────────────

    def _load(self, model_path: Path) -> None:
        """Load a pickled classifier + scaler from disk.

        Args:
            model_path: Path to the ``.pkl`` artifact.
        """
        with model_path.open("rb") as f:
            payload = pickle.load(f)  # noqa: S301 — trusted internal artifact
        self._clf = payload["clf"]
        self._scaler = payload["scaler"]
        self._log.info("classifier_loaded", path=str(model_path))
