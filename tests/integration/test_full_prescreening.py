"""Integration tests: PDF resume + mock repo → PreScreeningResult round-trip.

All external services (GitHub API, Kafka, MinIO, Spark, sentence-transformers)
are mocked. Tests verify end-to-end data flow and PII discipline without
requiring live infrastructure.

Run with:
    pytest tests/integration/test_full_prescreening.py -m integration --run-integration -v
"""

from __future__ import annotations

import base64
import json
import uuid
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import torch

pytestmark = pytest.mark.integration

# ── Fixed UUIDs for this test module (no human-readable PII) ──────────────────

_CANDIDATE_UUID = "a1b2c3d4-0000-0000-0000-000000000001"
_REPO_URL = "https://github.com/testuser/test-repo"
_REPO_UUID = str(uuid.uuid5(uuid.NAMESPACE_URL, _REPO_URL))

_RESUME_TEXT = """
Skills: Python, FastAPI, Docker, PostgreSQL, Redis

Experience:
- Built a microservices platform handling 10k req/s.
- Implemented CI/CD pipelines with GitHub Actions.

Education:
- B.Sc. Computer Science, State University, 2020.
"""

_PYTHON_CODE = b"def process():\n    return True\n"
_README_TEXT = "Python microservices platform. FastAPI, Docker, Redis."


# ── Stub helpers ───────────────────────────────────────────────────────────────

def _make_gpt_scorer_stubs(loss: float = 1.0, n_tokens: int = 20):
    """Return (tokenizer, model) stubs for GPT-style PerplexityScorer injection."""
    tok = MagicMock()
    tok.return_value = {"input_ids": torch.ones((1, n_tokens), dtype=torch.long)}
    tok.encode.return_value = list(range(n_tokens))
    out = MagicMock()
    out.loss = torch.tensor(loss)
    mod = MagicMock()
    mod.return_value = out
    return tok, mod


def _make_codebert_scorer_stubs(loss: float = 1.0, n_tokens: int = 20):
    """Return (tokenizer, model) stubs for CodeBERT CodePerplexityScorer injection."""
    tok = MagicMock()
    tok.return_value = {"input_ids": torch.ones((1, n_tokens), dtype=torch.long)}
    out = MagicMock()
    out.loss = torch.tensor(loss)
    mod = MagicMock()
    mod.return_value = out
    return tok, mod


def _make_embedding_model(emb_a: np.ndarray, emb_b: np.ndarray):
    """Return a sentence-transformer stub that returns emb_a then emb_b in turn."""
    model = MagicMock()
    call_counter = {"n": 0}
    embeddings = [emb_a, emb_b]

    def _encode(text, *args, **kwargs):
        idx = call_counter["n"] % 2
        call_counter["n"] += 1
        return embeddings[idx]

    model.encode.side_effect = _encode
    return model


def _similar_embeddings(dim: int = 8) -> tuple[np.ndarray, np.ndarray]:
    """Two nearly identical unit vectors (cosine ≈ 1)."""
    base = np.ones(dim) / np.sqrt(dim)
    return base, base.copy()


def _orthogonal_embeddings(dim: int = 8) -> tuple[np.ndarray, np.ndarray]:
    """Two orthogonal unit vectors (cosine = 0)."""
    a = np.zeros(dim)
    a[0] = 1.0
    b = np.zeros(dim)
    b[1] = 1.0
    return a, b


# ── Test 1: resume text → ResumeScoreEngine round-trip ────────────────────────

def test_resume_text_produces_valid_resume_score():
    """Parsed resume text → all four signal scorers → ResumeScoreResult."""
    from ml.features.perplexity import PerplexityScorer
    from ml.features.resume_burstiness import score_resume_burstiness
    from ml.features.resume_perplexity import score_resume_perplexity
    from ml.features.section_uniformity import score_section_uniformity
    from ml.features.vocab_richness import score_vocab_richness
    from ml.resume_score import ResumeScoreEngine

    gpt_tok, gpt_mod = _make_gpt_scorer_stubs(loss=2.0)
    emb_model = _make_embedding_model(*_similar_embeddings())

    perp_scorer = PerplexityScorer(_tokenizer=gpt_tok, _model=gpt_mod)

    sections = {"Skills": "Python FastAPI Docker", "Experience": "Built microservices platform"}

    perp  = score_resume_perplexity(_CANDIDATE_UUID, sections, _scorer=perp_scorer)
    burst = score_resume_burstiness(_CANDIDATE_UUID, sections)
    vocab = score_vocab_richness(_CANDIDATE_UUID, _RESUME_TEXT)
    unif  = score_section_uniformity(_CANDIDATE_UUID, sections, _model=emb_model)

    engine = ResumeScoreEngine()
    result = engine.compute(
        candidate_uuid=_CANDIDATE_UUID,
        perplexity_score=perp.suspicion_score,
        burstiness_score=burst.suspicion_score,
        vocab_richness_score=vocab.suspicion_score,
        section_uniformity_score=unif.suspicion_score,
    )

    assert result.candidate_uuid == _CANDIDATE_UUID
    assert 0.0 <= result.resume_ai_score <= 100.0
    assert isinstance(result.flagged, bool)
    if result.flagged:
        assert len(result.flag_reason) > 0


# ── Test 2: mock repo → RepoScoreEngine round-trip ────────────────────────────

def test_mock_repo_produces_valid_repo_score():
    """Mocked repo files → code perplexity + style + commit → RepoScoreResult."""
    from ml.features.code_perplexity import CodePerplexityScorer
    from ml.features.code_style import CodeStyleScorer
    from ml.features.commit_pattern import CommitPatternScorer
    from ml.repo_score import RepoScoreEngine

    codebert_tok, codebert_mod = _make_codebert_scorer_stubs(loss=1.5)
    files = [("main.py", _PYTHON_CODE.decode())]

    ppl_scorer    = CodePerplexityScorer(_tokenizer=codebert_tok, _model=codebert_mod)
    style_scorer  = CodeStyleScorer()
    commit_scorer = CommitPatternScorer()

    ppl_feat    = ppl_scorer.score_repo(_REPO_UUID, files)
    style_feat  = style_scorer.score_repo(_REPO_UUID, files)
    commit_feat = commit_scorer.score_repo(_REPO_UUID, commits=[], files=files)

    engine = RepoScoreEngine()
    result = engine.compute(
        repo_uuid=_REPO_UUID,
        code_perplexity_score=ppl_feat.suspicion_score,
        commit_pattern_score=commit_feat.suspicion_score,
        code_style_score=style_feat.suspicion_score,
    )

    assert result.repo_uuid == _REPO_UUID
    assert 0.0 <= result.repo_ai_score <= 100.0
    if result.flagged:
        assert len(result.flag_reason) > 0


# ── Test 3: full prescreening aggregation round-trip ──────────────────────────

def test_prescreening_aggregates_resume_and_repo_scores():
    """Resume score + repo score → PreScreeningEngine → PreScreeningResult."""
    from ml.prescreening_score import PreScreeningEngine

    engine = PreScreeningEngine(prescreening_threshold=0.65)
    result = engine.compute(
        candidate_uuid=_CANDIDATE_UUID,
        resume_ai_score=75.0,
        repo_ai_score=70.0,
    )

    assert result.candidate_uuid == _CANDIDATE_UUID
    assert 0.0 <= result.prescreening_score <= 100.0
    assert result.repo_available is True
    assert result.interview_available is False


def test_prescreening_with_all_three_signals():
    """All three signals → weights 35/35/30; result in valid range."""
    from ml.prescreening_score import PreScreeningEngine

    engine = PreScreeningEngine()
    result = engine.compute(
        candidate_uuid=_CANDIDATE_UUID,
        resume_ai_score=80.0,
        repo_ai_score=75.0,
        interview_trust_score=25.0,
    )

    assert result.interview_available is True
    assert result.repo_available is True
    assert 0.0 <= result.prescreening_score <= 100.0
    assert len(result.signals) == 3


def test_prescreening_severity_high_low_trust():
    """Low interview trust + high prescreening → severity 'high'."""
    from ml.prescreening_score import PreScreeningEngine

    engine = PreScreeningEngine(prescreening_threshold=0.10, interview_high_threshold=40.0)
    result = engine.compute(
        candidate_uuid=_CANDIDATE_UUID,
        resume_ai_score=80.0,
        interview_trust_score=20.0,
    )
    assert result.severity == "high"
    assert result.flagged is True


# ── Test 4: cross-correlation round-trip ──────────────────────────────────────

def test_cross_correlation_coherent_candidate():
    """Resume skills ≈ repo README → high coherence → low suspicion."""
    from ml.cross_correlation import CrossCorrelationScorer

    emb_model = _make_embedding_model(*_similar_embeddings())
    scorer    = CrossCorrelationScorer(_model=emb_model)
    result    = scorer.score(
        candidate_uuid=_CANDIDATE_UUID,
        resume_skills_text="Python FastAPI Docker",
        repo_readme_text=_README_TEXT,
        resume_full_text=_RESUME_TEXT,
        interview_transcript=None,
    )

    assert result.skill_coherence_score > 0.5
    assert result.coherence_suspicion_score < 0.6


def test_cross_correlation_incoherent_candidate():
    """Resume skills vs. orthogonal repo README → high suspicion."""
    from ml.cross_correlation import CrossCorrelationScorer

    emb_model = _make_embedding_model(*_orthogonal_embeddings())
    scorer    = CrossCorrelationScorer(_model=emb_model)
    result    = scorer.score(
        candidate_uuid=_CANDIDATE_UUID,
        resume_skills_text="Management PowerPoint Excel",
        repo_readme_text="Deep C++ kernel graphics pipeline",
        resume_full_text=None,
        interview_transcript=None,
    )

    assert result.coherence_suspicion_score >= 0.5


# ── Test 5: Kafka profile event carries no PII ───────────────────────────────

def test_profile_producer_payload_has_no_pii():
    """Published Kafka payload must not contain names, emails, or source code."""
    from ingestion.profile_producer import ProfileProducer

    captured: list[dict] = []
    mock_producer = MagicMock()

    def capture(**kwargs):
        captured.append(json.loads(kwargs["value"].decode()))

    mock_producer.produce.side_effect = lambda *a, **kw: capture(**kw)

    with patch("ingestion.profile_producer.Producer", return_value=mock_producer):
        producer = ProfileProducer("localhost:9092", "candidate-profile-stream")
        import time
        producer.publish_prescreening_result(
            candidate_uuid=_CANDIDATE_UUID,
            prescreening_score=78.5,
            resume_ai_score=80.0,
            repo_ai_score=75.0,
            interview_trust_score=None,
            flagged=True,
            severity="medium",
            flag_reason="High resume AI score detected.",
            scored_at=time.time(),
        )

    assert captured, "No events published"
    payload = captured[0]

    # Must contain the UUID identifier
    assert "candidate_uuid" in payload
    assert payload["candidate_uuid"] == _CANDIDATE_UUID

    # Must not contain raw content or names
    assert "resume_text" not in payload
    assert "code" not in payload
    assert "name" not in payload
    assert "email" not in payload

    # Scores must be numeric
    assert isinstance(payload["prescreening_score"], (int, float))
    assert isinstance(payload["flagged"], bool)
    assert payload["severity"] in ("low", "medium", "high")


# ── Test 6: DeltaLake prescreening store appends correctly ────────────────────

def test_prescreening_store_append_calls_spark():
    """PreScreeningStore.append_record invokes Spark write with correct data."""
    from storage.prescreening_store import PreScreeningRecord, PreScreeningStore
    import time

    mock_spark = MagicMock()
    mock_df    = MagicMock()
    mock_spark.createDataFrame.return_value = mock_df
    mock_df.write.format.return_value.mode.return_value.save = MagicMock()

    store = PreScreeningStore("/delta", _spark=mock_spark)
    record = PreScreeningRecord(
        candidate_uuid=_CANDIDATE_UUID,
        prescreening_score=78.5,
        resume_ai_score=80.0,
        repo_ai_score=75.0,
        interview_trust_score=None,
        suspicion_index=0.785,
        flagged=True,
        severity="medium",
        flag_reason="High resume AI score detected.",
        signals_json=json.dumps([]),
        scored_at=time.time(),
    )

    store.append_record(record)

    mock_spark.createDataFrame.assert_called_once()
    mock_df.write.format.assert_called_once_with("delta")


def test_prescreening_store_path_uses_table_name():
    """The Delta Lake path includes the correct table name."""
    from storage.prescreening_store import PreScreeningRecord, PreScreeningStore, TABLE_PRESCREENING
    import time

    mock_spark = MagicMock()
    mock_df    = MagicMock()
    mock_spark.createDataFrame.return_value = mock_df
    mock_df.write.format.return_value.mode.return_value.save = MagicMock()

    store = PreScreeningStore("/my/delta", _spark=mock_spark)
    record = PreScreeningRecord(
        candidate_uuid=_CANDIDATE_UUID,
        prescreening_score=0.0,
        resume_ai_score=0.0,
        repo_ai_score=None,
        interview_trust_score=None,
        suspicion_index=0.0,
        flagged=False,
        severity="low",
        flag_reason="",
        signals_json="[]",
        scored_at=time.time(),
    )
    store.append_record(record)

    save_call = mock_df.write.format.return_value.mode.return_value.save
    save_call.assert_called_once()
    saved_path = save_call.call_args[0][0]
    assert TABLE_PRESCREENING in saved_path
    assert "/my/delta" in saved_path
