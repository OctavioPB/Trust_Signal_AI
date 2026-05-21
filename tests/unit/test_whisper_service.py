"""Unit tests for transcription/whisper_service.py.

Tests pure functions (pcm_to_float32, pcm_to_wav) and the static
detect_speaker_turns() method without loading any Whisper model.
"""

from __future__ import annotations

import io
import math
import wave

import numpy as np
import pytest

from transcription.whisper_service import (
    TranscriptionSegment,
    WhisperService,
    pcm_to_float32,
    pcm_to_wav,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _seg(
    start: float,
    end: float,
    text: str = "hello",
    session_id: str = "test-session",
    chunk_seq: int = 0,
) -> TranscriptionSegment:
    return TranscriptionSegment(
        session_id=session_id,
        chunk_seq=chunk_seq,
        start_ts=start,
        end_ts=end,
        text=text,
        confidence=0.9,
    )


# ── pcm_to_float32 ────────────────────────────────────────────────────────────

def test_pcm_to_float32_silence_is_zero() -> None:
    pcm = np.zeros(1000, dtype=np.int16).tobytes()
    result = pcm_to_float32(pcm)
    assert np.all(result == 0.0)


def test_pcm_to_float32_max_positive() -> None:
    """INT16_MAX (32767) should map to ≈ 1.0."""
    pcm = np.array([32767], dtype=np.int16).tobytes()
    result = pcm_to_float32(pcm)
    assert abs(result[0] - (32767 / 32768.0)) < 1e-6


def test_pcm_to_float32_max_negative() -> None:
    """INT16_MIN (-32768) should map to exactly -1.0."""
    pcm = np.array([-32768], dtype=np.int16).tobytes()
    result = pcm_to_float32(pcm)
    assert result[0] == pytest.approx(-1.0, abs=1e-6)


def test_pcm_to_float32_output_dtype() -> None:
    pcm = np.zeros(100, dtype=np.int16).tobytes()
    result = pcm_to_float32(pcm)
    assert result.dtype == np.float32


def test_pcm_to_float32_preserves_length() -> None:
    n_samples = 8000
    pcm = np.zeros(n_samples, dtype=np.int16).tobytes()
    result = pcm_to_float32(pcm)
    assert len(result) == n_samples


# ── pcm_to_wav ────────────────────────────────────────────────────────────────

def test_pcm_to_wav_produces_valid_wav_header() -> None:
    pcm = b"\x00\x00" * 8000   # 0.5 s of silence
    wav = pcm_to_wav(pcm)

    with wave.open(io.BytesIO(wav)) as wf:
        assert wf.getnchannels() == 1
        assert wf.getframerate() == 16_000
        assert wf.getsampwidth() == 2


def test_pcm_to_wav_preserves_audio_data() -> None:
    """PCM data extracted from the WAV must match the input."""
    pcm = b"\xAB\xCD" * 4000
    wav = pcm_to_wav(pcm)
    with wave.open(io.BytesIO(wav)) as wf:
        assert wf.readframes(wf.getnframes()) == pcm


def test_pcm_to_wav_output_is_bytes() -> None:
    assert isinstance(pcm_to_wav(b"\x00\x00" * 100), bytes)


# ── detect_speaker_turns ──────────────────────────────────────────────────────

class TestDetectSpeakerTurns:

    def test_empty_list_returns_empty(self) -> None:
        assert WhisperService.detect_speaker_turns([]) == []

    def test_single_segment_gets_initial_recruiter(self) -> None:
        result = WhisperService.detect_speaker_turns(
            [_seg(0.0, 2.0)], initial_speaker="RECRUITER"
        )
        assert result[0].speaker == "RECRUITER"

    def test_single_segment_gets_initial_candidate(self) -> None:
        result = WhisperService.detect_speaker_turns(
            [_seg(0.0, 2.0)], initial_speaker="CANDIDATE"
        )
        assert result[0].speaker == "CANDIDATE"

    def test_gap_above_threshold_toggles_recruiter_to_candidate(self) -> None:
        # gap = 3.0 − 2.0 = 1.0 s > 800 ms  →  toggle
        segs = [_seg(0.0, 2.0), _seg(3.0, 5.0)]
        WhisperService.detect_speaker_turns(
            segs, silence_threshold_ms=800.0, initial_speaker="RECRUITER"
        )
        assert segs[0].speaker == "RECRUITER"
        assert segs[1].speaker == "CANDIDATE"

    def test_gap_above_threshold_toggles_candidate_to_recruiter(self) -> None:
        segs = [_seg(0.0, 2.0), _seg(3.0, 5.0)]
        WhisperService.detect_speaker_turns(
            segs, silence_threshold_ms=800.0, initial_speaker="CANDIDATE"
        )
        assert segs[0].speaker == "CANDIDATE"
        assert segs[1].speaker == "RECRUITER"

    def test_gap_below_threshold_keeps_same_speaker(self) -> None:
        # gap = 2.5 − 2.0 = 0.5 s < 800 ms  →  no toggle
        segs = [_seg(0.0, 2.0), _seg(2.5, 4.0)]
        WhisperService.detect_speaker_turns(segs, silence_threshold_ms=800.0)
        assert segs[0].speaker == segs[1].speaker

    def test_gap_exactly_at_threshold_does_not_toggle(self) -> None:
        # gap = 2.8 − 2.0 = 0.800 s == threshold; condition is strict >
        segs = [_seg(0.0, 2.0), _seg(2.8, 4.0)]
        WhisperService.detect_speaker_turns(segs, silence_threshold_ms=800.0)
        assert segs[0].speaker == segs[1].speaker

    def test_gap_just_above_threshold_toggles(self) -> None:
        # gap = 2.801 − 2.0 = 0.801 s > 800 ms
        segs = [_seg(0.0, 2.0), _seg(2.801, 4.0)]
        WhisperService.detect_speaker_turns(segs, silence_threshold_ms=800.0)
        assert segs[0].speaker != segs[1].speaker

    def test_multiple_alternating_turns(self) -> None:
        """
        seg0: 0.0 → 2.0  RECRUITER  (first)
        seg1: 3.0 → 5.0  CANDIDATE  (gap 1.0 s > 800 ms → toggle)
        seg2: 5.3 → 7.0  CANDIDATE  (gap 0.3 s < 800 ms → no toggle)
        seg3: 8.0 → 10.0 RECRUITER  (gap 1.0 s > 800 ms → toggle back)
        """
        segs = [_seg(0.0, 2.0), _seg(3.0, 5.0), _seg(5.3, 7.0), _seg(8.0, 10.0)]
        WhisperService.detect_speaker_turns(
            segs, silence_threshold_ms=800.0, initial_speaker="RECRUITER"
        )
        assert segs[0].speaker == "RECRUITER"
        assert segs[1].speaker == "CANDIDATE"
        assert segs[2].speaker == "CANDIDATE"
        assert segs[3].speaker == "RECRUITER"

    def test_five_question_interview_pattern(self) -> None:
        """Verify recruiter asks 5 questions, candidate answers each."""
        # R: 0-3, C: 5-15, R: 17-20, C: 22-35, R: 37-40,
        # C: 42-55, R: 57-60, C: 62-75, R: 77-80, C: 82-90
        times = [
            (0, 3), (5, 15), (17, 20), (22, 35), (37, 40),
            (42, 55), (57, 60), (62, 75), (77, 80), (82, 90),
        ]
        expected = [
            "RECRUITER", "CANDIDATE", "RECRUITER", "CANDIDATE", "RECRUITER",
            "CANDIDATE", "RECRUITER", "CANDIDATE", "RECRUITER", "CANDIDATE",
        ]
        segs = [_seg(float(s), float(e)) for s, e in times]
        WhisperService.detect_speaker_turns(segs, silence_threshold_ms=800.0)
        actual = [s.speaker for s in segs]
        assert actual == expected

    def test_modifies_segments_in_place_returns_same_list(self) -> None:
        segs = [_seg(0.0, 2.0)]
        result = WhisperService.detect_speaker_turns(segs)
        assert result is segs

    def test_custom_silence_threshold(self) -> None:
        # With threshold = 2000 ms, a 1 s gap should NOT toggle
        segs = [_seg(0.0, 2.0), _seg(3.0, 5.0)]
        WhisperService.detect_speaker_turns(segs, silence_threshold_ms=2000.0)
        assert segs[0].speaker == segs[1].speaker

    def test_initial_speaker_persists_across_no_gap(self) -> None:
        """All segments touching each other keep the initial speaker."""
        segs = [_seg(0.0, 1.0), _seg(1.0, 2.0), _seg(2.0, 3.0)]
        WhisperService.detect_speaker_turns(segs, initial_speaker="CANDIDATE")
        assert all(s.speaker == "CANDIDATE" for s in segs)


# ── _build_segments confidence mapping ───────────────────────────────────────

def test_confidence_from_avg_logprob_zero() -> None:
    """avg_logprob=0 → exp(0)=1.0 (perfect confidence)."""
    svc = WhisperService.__new__(WhisperService)
    svc._model_size = "base"
    result = svc._build_segments(
        {"segments": [{"start": 0.0, "end": 1.0, "text": "hi", "avg_logprob": 0.0}]},
        session_id="s",
        chunk_seq=0,
        start_ts_offset=0.0,
    )
    assert result[0].confidence == pytest.approx(1.0)


def test_confidence_from_avg_logprob_negative() -> None:
    """avg_logprob=-1 → exp(-1) ≈ 0.368."""
    svc = WhisperService.__new__(WhisperService)
    svc._model_size = "base"
    result = svc._build_segments(
        {"segments": [{"start": 0.0, "end": 1.0, "text": "hi", "avg_logprob": -1.0}]},
        session_id="s",
        chunk_seq=0,
        start_ts_offset=0.0,
    )
    assert result[0].confidence == pytest.approx(math.exp(-1.0), rel=1e-5)


def test_build_segments_applies_start_ts_offset() -> None:
    svc = WhisperService.__new__(WhisperService)
    svc._model_size = "base"
    result = svc._build_segments(
        {"segments": [{"start": 1.0, "end": 3.0, "text": "hello", "avg_logprob": -0.2}]},
        session_id="s",
        chunk_seq=0,
        start_ts_offset=5.0,
    )
    assert result[0].start_ts == pytest.approx(6.0)
    assert result[0].end_ts == pytest.approx(8.0)


def test_build_segments_skips_empty_text() -> None:
    svc = WhisperService.__new__(WhisperService)
    svc._model_size = "base"
    result = svc._build_segments(
        {
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "", "avg_logprob": -0.2},
                {"start": 1.0, "end": 2.0, "text": "   ", "avg_logprob": -0.2},
                {"start": 2.0, "end": 3.0, "text": "hi", "avg_logprob": -0.2},
            ]
        },
        session_id="s",
        chunk_seq=0,
        start_ts_offset=0.0,
    )
    assert len(result) == 1
    assert result[0].text == "hi"
