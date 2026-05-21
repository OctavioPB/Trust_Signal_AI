"""OpenAI Whisper STT wrapper with speaker-turn detection.

Supports local inference (default) with automatic fallback to the cloud
Whisper API when OPENAI_API_KEY is set and the local latency budget is
exceeded (2 × chunk_duration_s).

Speaker-turn detection heuristic:
    A silence gap > 800 ms between consecutive Whisper segments marks a
    speaker boundary. Speakers are labelled RECRUITER / CANDIDATE alternating
    from an (override-able) initial speaker.

Audio format expected:
    16-bit signed PCM, mono, 16 kHz (same as ingestion pipeline output).
"""

from __future__ import annotations

import io
import math
import time
import wave
from dataclasses import dataclass, field

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# ── Audio constants ───────────────────────────────────────────────────────────
SAMPLE_RATE: int = 16_000
SAMPLE_WIDTH_BYTES: int = 2   # 16-bit PCM

# ── Detection defaults ────────────────────────────────────────────────────────
SILENCE_THRESHOLD_MS: float = 800.0      # gap (ms) that marks a speaker turn
LATENCY_BUDGET_MULTIPLIER: float = 2.0  # max STT time as multiple of audio duration


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class TranscriptionSegment:
    """A single speaker-turn segment emitted by the STT pipeline.

    Attributes:
        session_id: UUID of the interview session (no PII).
        chunk_seq: Index of the first source audio chunk in this window.
        start_ts: Absolute segment start (seconds from call start).
        end_ts: Absolute segment end (seconds from call start).
        text: Transcribed candidate/recruiter speech.
        confidence: Model confidence in [0, 1] derived from avg_logprob.
        speaker: "RECRUITER" or "CANDIDATE".
        metadata: Optional extra fields (model, source, etc.).
    """

    session_id: str
    chunk_seq: int
    start_ts: float
    end_ts: float
    text: str
    confidence: float
    speaker: str = "CANDIDATE"
    metadata: dict = field(default_factory=dict)


# ── Pure PCM helpers (module-level, testable without model) ───────────────────

def pcm_to_float32(pcm_bytes: bytes) -> np.ndarray:
    """Convert raw 16-bit PCM bytes to a float32 array in [-1, 1].

    Whisper's local transcribe() expects a float32 numpy array normalised to
    [-1, 1]. This is the standard conversion from 16-bit PCM.

    Args:
        pcm_bytes: Raw 16-bit signed PCM audio bytes.

    Returns:
        numpy float32 array with values in [-1.0, 1.0].
    """
    return np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0


def pcm_to_wav(
    pcm_bytes: bytes,
    sample_rate: int = SAMPLE_RATE,
    n_channels: int = 1,
    sample_width: int = SAMPLE_WIDTH_BYTES,
) -> bytes:
    """Wrap raw PCM bytes in a WAV container.

    Required for the cloud Whisper API which does not accept raw PCM.

    Args:
        pcm_bytes: Raw 16-bit PCM audio bytes.
        sample_rate: Audio sample rate in Hz.
        n_channels: Number of audio channels (1 = mono).
        sample_width: Bytes per sample (2 = 16-bit).

    Returns:
        WAV-formatted audio bytes (header + PCM data).
    """
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(n_channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


# ── WhisperService ────────────────────────────────────────────────────────────

class WhisperService:
    """Transcribes reassembled audio windows using local or cloud Whisper.

    The model is loaded lazily on the first call to transcribe() to avoid
    startup cost in services that may not need STT immediately.

    Args:
        model_size: Whisper model variant (tiny/base/small/medium/large).
            Controlled by the WHISPER_MODEL_SIZE environment variable.
        openai_api_key: If set and local latency budget exceeded, the service
            falls back to the OpenAI cloud Whisper API.
        latency_budget_multiplier: STT must complete within this multiple of
            the audio chunk duration (default 2×, so a 5 s window gets 10 s).
    """

    def __init__(
        self,
        model_size: str = "base",
        openai_api_key: str | None = None,
        latency_budget_multiplier: float = LATENCY_BUDGET_MULTIPLIER,
    ) -> None:
        self._model_size = model_size
        self._api_key = openai_api_key
        self._budget_mult = latency_budget_multiplier
        self._model = None   # lazy-loaded on first transcribe()
        self._log = logger.bind(component="WhisperService", model_size=model_size)

    # ── Public API ────────────────────────────────────────────────────────────

    def transcribe(
        self,
        audio_bytes: bytes,
        session_id: str,
        chunk_seq: int,
        chunk_duration_s: float = 5.0,
        start_ts_offset: float = 0.0,
    ) -> list[TranscriptionSegment]:
        """Transcribe a PCM audio window and return speaker-tagged segments.

        Enforces the latency budget (3.5). Falls back to the cloud API if the
        budget is exceeded and OPENAI_API_KEY is available (3.6).

        Args:
            audio_bytes: Raw 16-bit PCM at 16 kHz; typically 5 s (80 000 bytes).
            session_id: UUID of the interview session (no PII).
            chunk_seq: Sequence number of the first chunk in this window.
            chunk_duration_s: Duration of the audio window in seconds.
            start_ts_offset: Absolute call time at the window start (seconds).

        Returns:
            List of TranscriptionSegments ordered by start_ts. Empty if no
            speech was detected.
        """
        self._ensure_model_loaded()

        budget_s = self._budget_mult * chunk_duration_s
        audio_array = pcm_to_float32(audio_bytes)

        t0 = time.perf_counter()
        result = self._model.transcribe(audio_array, language="en", fp16=False)  # type: ignore[union-attr]
        elapsed = time.perf_counter() - t0

        if elapsed > budget_s:
            self._log.warning(
                "latency_budget_exceeded",
                session_id=session_id,
                elapsed_s=round(elapsed, 3),
                budget_s=budget_s,
            )
            if self._api_key:
                self._log.info("falling_back_to_cloud_whisper", session_id=session_id)
                result = self._cloud_transcribe(audio_bytes)
        else:
            self._log.debug(
                "stt_complete",
                session_id=session_id,
                elapsed_s=round(elapsed, 3),
                budget_s=budget_s,
            )

        return self._build_segments(result, session_id, chunk_seq, start_ts_offset)

    @staticmethod
    def detect_speaker_turns(
        segments: list[TranscriptionSegment],
        silence_threshold_ms: float = SILENCE_THRESHOLD_MS,
        initial_speaker: str = "RECRUITER",
    ) -> list[TranscriptionSegment]:
        """Tag each segment with RECRUITER or CANDIDATE based on silence gaps.

        Heuristic (3.4): a gap greater than silence_threshold_ms between the
        end of one segment and the start of the next marks a speaker boundary.
        Speakers alternate starting from initial_speaker.

        Modifies segments in-place and returns the same list.

        Args:
            segments: Ordered TranscriptionSegments with absolute timestamps.
            silence_threshold_ms: Minimum gap (ms) that triggers a speaker toggle.
            initial_speaker: Speaker label for the first segment.

        Returns:
            The same segments list with speaker fields populated.
        """
        if not segments:
            return segments

        threshold_s = silence_threshold_ms / 1000.0
        current_speaker = initial_speaker
        prev_end_ts = segments[0].start_ts   # baseline: no gap before the first word

        for i, seg in enumerate(segments):
            gap_s = seg.start_ts - prev_end_ts
            if i > 0 and gap_s > threshold_s:
                current_speaker = (
                    "CANDIDATE" if current_speaker == "RECRUITER" else "RECRUITER"
                )
            seg.speaker = current_speaker
            prev_end_ts = seg.end_ts

        return segments

    # ── Private helpers ───────────────────────────────────────────────────────

    def _ensure_model_loaded(self) -> None:
        if self._model is not None:
            return
        import whisper  # openai-whisper package

        self._log.info("loading_whisper_model")
        self._model = whisper.load_model(self._model_size)
        self._log.info("whisper_model_loaded")

    def _cloud_transcribe(self, audio_bytes: bytes) -> dict:
        """Fallback: transcribe via OpenAI cloud Whisper API.

        Args:
            audio_bytes: Raw 16-bit PCM bytes (converted to WAV for the API).

        Returns:
            Normalised result dict with "segments" key, matching local format.
        """
        import openai

        wav_bytes = pcm_to_wav(audio_bytes)
        client = openai.OpenAI(api_key=self._api_key)
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=("audio.wav", wav_bytes, "audio/wav"),
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )
        # Normalise OpenAI response object to a plain dict matching local Whisper format
        segs: list[dict] = []
        for seg in getattr(response, "segments", None) or []:
            segs.append(
                {
                    "start": getattr(seg, "start", 0.0),
                    "end": getattr(seg, "end", 0.0),
                    "text": getattr(seg, "text", ""),
                    "avg_logprob": getattr(seg, "avg_logprob", -0.2),
                }
            )
        return {"segments": segs, "text": getattr(response, "text", "")}

    def _build_segments(
        self,
        result: dict,
        session_id: str,
        chunk_seq: int,
        start_ts_offset: float,
    ) -> list[TranscriptionSegment]:
        """Convert a Whisper result dict into TranscriptionSegment objects.

        Segments with empty text (after stripping) are discarded. Confidence
        is derived from avg_logprob using exp() → maps to (0, 1].

        Args:
            result: Whisper result dict with "segments" list.
            session_id: UUID of the interview session.
            chunk_seq: First source chunk index for this window.
            start_ts_offset: Seconds to add to all Whisper-relative timestamps.

        Returns:
            List of TranscriptionSegments with absolute timestamps.
        """
        segments: list[TranscriptionSegment] = []
        for raw in (result.get("segments") or []):
            text = raw.get("text", "").strip()
            if not text:
                continue

            avg_logprob: float = raw.get("avg_logprob", -0.5)
            confidence = max(0.0, min(1.0, math.exp(avg_logprob)))

            segments.append(
                TranscriptionSegment(
                    session_id=session_id,
                    chunk_seq=chunk_seq,
                    start_ts=round(raw["start"] + start_ts_offset, 3),
                    end_ts=round(raw["end"] + start_ts_offset, 3),
                    text=text,
                    confidence=confidence,
                    metadata={"model": self._model_size},
                )
            )
        return segments
