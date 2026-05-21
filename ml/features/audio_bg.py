"""Background audio classifier: keyboard detection during silence windows.

Extracts MFCC features from silence segments (no speech detected) and
classifies them as keyboard_present vs ambient_silence using a Random Forest.
Artifact saved as YYYYMMDD_bg_classifier.pkl in MinIO model-artifacts.

Implemented in Sprint 5.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

# Minimum precision required (regression test guard)
MIN_CLASSIFIER_PRECISION = 0.85

# Number of MFCC coefficients to extract
N_MFCC = 13


@dataclass
class BackgroundAudioFeatures:
    """Result of background audio classification for a single silence window.

    Attributes:
        session_id: UUID of the interview session.
        window_start_s: Start of the silence window (seconds from call start).
        window_end_s: End of the silence window.
        keyboard_detected: True if mechanical keyboard typing is detected.
        confidence: Classifier probability for the keyboard_present class.
        suspicion_score: Score in [0, 1]; keyboard detected → higher score.
    """

    session_id: str
    window_start_s: float
    window_end_s: float
    keyboard_detected: bool
    confidence: float
    suspicion_score: float


class BackgroundAudioClassifier:
    """Random Forest classifier for keyboard detection in silence windows.

    Args:
        model_path: Path to a persisted .pkl classifier artifact. If None,
            the model must be trained before calling classify().
    """

    def __init__(self, model_path: Path | None = None) -> None:
        raise NotImplementedError  # Sprint 5

    def train(self, audio_dir: Path, labels_csv: Path) -> None:
        """Train the classifier on a labelled dataset of silence windows.

        Args:
            audio_dir: Directory containing .wav silence window files.
            labels_csv: CSV with columns: filename, label (0=ambient, 1=keyboard).
        """
        raise NotImplementedError  # Sprint 5

    def classify(
        self,
        audio_bytes: bytes,
        session_id: str,
        window_start_s: float,
        window_end_s: float,
        sample_rate: int = 16000,
    ) -> BackgroundAudioFeatures:
        """Classify a silence window audio segment.

        Args:
            audio_bytes: Raw 16-bit PCM audio data.
            session_id: UUID of the interview session.
            window_start_s: Start of the silence window (seconds).
            window_end_s: End of the silence window (seconds).
            sample_rate: Audio sample rate in Hz.

        Returns:
            BackgroundAudioFeatures with suspicion_score in [0, 1].
        """
        raise NotImplementedError  # Sprint 5

    def save(self, artifact_path: Path) -> None:
        """Serialise the trained classifier to disk (pickle).

        Args:
            artifact_path: Destination path; name must follow YYYYMMDD_bg_classifier.pkl.
        """
        raise NotImplementedError  # Sprint 5
