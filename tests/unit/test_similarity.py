"""Regression and unit tests for ml/embeddings/similarity.py.

SemanticSimilarityScorer loads a real sentence-transformers model which is too
slow for unit tests. We inject a stub model that returns fixed embeddings so
cosine similarity is deterministic and the answer bank doesn't need loading.

A temporary JSONL file simulates the answer bank.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from ml.embeddings.similarity import (
    ANSWER_BANK_PATH,
    SimilarityFeatures,
    SemanticSimilarityScorer,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_bank(entries: list[dict]) -> Path:
    """Write a temporary JSONL answer bank and return its path."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
    )
    for entry in entries:
        tmp.write(json.dumps(entry) + "\n")
    tmp.close()
    return Path(tmp.name)


def _make_scorer(bank_entries: list[dict], embeddings: np.ndarray) -> SemanticSimilarityScorer:
    """Return a scorer with an injected stub model and a temp answer bank.

    Args:
        bank_entries: Q&A pairs to write as the answer bank.
        embeddings: Pre-computed numpy matrix of shape (n_entries, d). The
            stub model returns rows from this matrix in order: first
            ``n_entries`` calls return bank embeddings (one per answer); the
            next call returns the candidate embedding (last row).
    """
    bank_path = _write_bank(bank_entries)

    # encode() call-sequence: first call = bank answers (batch), second = candidate (batch)
    call_count = [0]

    def fake_encode(texts, convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False):
        idx = call_count[0]
        call_count[0] += 1
        if idx == 0:
            # Bank answers — return all bank rows
            return embeddings[: len(bank_entries)]
        else:
            # Candidate — return last row
            return embeddings[len(bank_entries) :]

    model_stub = MagicMock(name="SentenceTransformer")
    model_stub.encode.side_effect = fake_encode

    return SemanticSimilarityScorer(
        answer_bank_path=bank_path,
        _model=model_stub,
    )


def _unit_vec(d: int, idx: int) -> np.ndarray:
    """Return a unit vector with 1.0 at position idx."""
    v = np.zeros(d, dtype=np.float32)
    v[idx] = 1.0
    return v


# ── _load_answer_bank ─────────────────────────────────────────────────────────

class TestLoadAnswerBank:

    def test_raises_if_file_missing(self) -> None:
        model_stub = MagicMock()
        model_stub.encode.return_value = np.zeros((1, 4), dtype=np.float32)
        with pytest.raises(FileNotFoundError, match="not found"):
            SemanticSimilarityScorer(
                answer_bank_path=Path("/nonexistent/path/bank.jsonl"),
                _model=model_stub,
            )

    def test_raises_on_empty_bank(self) -> None:
        empty_bank = _write_bank([])
        model_stub = MagicMock()
        model_stub.encode.return_value = np.zeros((0, 4), dtype=np.float32)
        with pytest.raises(ValueError, match="no valid entries"):
            SemanticSimilarityScorer(answer_bank_path=empty_bank, _model=model_stub)

    def test_raises_on_missing_question_key(self) -> None:
        bad_bank = _write_bank([{"answer": "some answer"}])
        model_stub = MagicMock()
        model_stub.encode.return_value = np.zeros((1, 4), dtype=np.float32)
        with pytest.raises(ValueError, match="missing"):
            SemanticSimilarityScorer(answer_bank_path=bad_bank, _model=model_stub)

    def test_raises_on_missing_answer_key(self) -> None:
        bad_bank = _write_bank([{"question": "some question"}])
        model_stub = MagicMock()
        model_stub.encode.return_value = np.zeros((1, 4), dtype=np.float32)
        with pytest.raises(ValueError, match="missing"):
            SemanticSimilarityScorer(answer_bank_path=bad_bank, _model=model_stub)

    def test_raises_on_invalid_json_line(self) -> None:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        tmp.write("{not valid json}\n")
        tmp.close()
        model_stub = MagicMock()
        model_stub.encode.return_value = np.zeros((1, 4), dtype=np.float32)
        with pytest.raises(ValueError, match="invalid JSON"):
            SemanticSimilarityScorer(answer_bank_path=Path(tmp.name), _model=model_stub)

    def test_blank_lines_skipped(self) -> None:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8")
        tmp.write('\n')
        tmp.write(json.dumps({"question": "Q1", "answer": "A1"}) + "\n")
        tmp.write('\n')
        tmp.close()
        d = 4
        emb = np.stack([_unit_vec(d, 0), _unit_vec(d, 1)])  # bank + candidate
        model_stub = MagicMock()
        model_stub.encode.side_effect = [
            emb[:1],   # bank embedding
            emb[1:],   # candidate
        ]
        scorer = SemanticSimilarityScorer(answer_bank_path=Path(tmp.name), _model=model_stub)
        assert len(scorer._bank) == 1


# ── SemanticSimilarityScorer.score ────────────────────────────────────────────

class TestScore:

    def _make_orthogonal_scorer(self):
        """3 bank answers with orthogonal embeddings in R^4.

        bank[0] → unit vec e0
        bank[1] → unit vec e1
        bank[2] → unit vec e2
        candidate → unit vec e1  (identical to bank[1])
        """
        d = 4
        bank = [
            {"question": "Q0", "answer": "A0"},
            {"question": "Q1", "answer": "A1"},
            {"question": "Q2", "answer": "A2"},
        ]
        emb = np.stack([
            _unit_vec(d, 0),   # bank[0]
            _unit_vec(d, 1),   # bank[1]
            _unit_vec(d, 2),   # bank[2]
            _unit_vec(d, 1),   # candidate ← identical to bank[1]
        ])
        return _make_scorer(bank, emb)

    def test_returns_similarity_features(self) -> None:
        scorer = self._make_orthogonal_scorer()
        result = scorer.score("s", "some text")
        assert isinstance(result, SimilarityFeatures)

    def test_session_id_preserved(self) -> None:
        scorer = self._make_orthogonal_scorer()
        result = scorer.score("uuid-abc", "some text")
        assert result.session_id == "uuid-abc"

    def test_text_preserved(self) -> None:
        scorer = self._make_orthogonal_scorer()
        text = "Tell me about yourself in detail."
        result = scorer.score("s", text)
        assert result.text == text

    def test_selects_max_similarity(self) -> None:
        """Candidate identical to bank[1] → max_cosine_similarity = 1.0."""
        scorer = self._make_orthogonal_scorer()
        result = scorer.score("s", "some text")
        assert result.max_cosine_similarity == pytest.approx(1.0, abs=1e-5)

    def test_matched_question_corresponds_to_best_match(self) -> None:
        """Candidate identical to bank[1] → matched_question = 'Q1'."""
        scorer = self._make_orthogonal_scorer()
        result = scorer.score("s", "some text")
        assert result.matched_question == "Q1"

    def test_suspicion_score_equals_max_similarity(self) -> None:
        scorer = self._make_orthogonal_scorer()
        result = scorer.score("s", "some text")
        assert result.suspicion_score == pytest.approx(result.max_cosine_similarity, abs=1e-6)

    def test_suspicion_score_in_unit_interval(self) -> None:
        scorer = self._make_orthogonal_scorer()
        result = scorer.score("s", "some text")
        assert 0.0 <= result.suspicion_score <= 1.0

    def test_orthogonal_candidate_low_similarity(self) -> None:
        """Candidate orthogonal to all bank answers → similarity ≈ 0."""
        d = 4
        bank = [
            {"question": "Q0", "answer": "A0"},
            {"question": "Q1", "answer": "A1"},
        ]
        emb = np.stack([
            _unit_vec(d, 0),   # bank[0]
            _unit_vec(d, 1),   # bank[1]
            _unit_vec(d, 3),   # candidate ← orthogonal to both
        ])
        scorer = _make_scorer(bank, emb)
        result = scorer.score("s", "unrelated text")
        assert result.max_cosine_similarity == pytest.approx(0.0, abs=1e-5)
        assert result.suspicion_score == pytest.approx(0.0, abs=1e-5)

    def test_negative_similarity_clamped_to_zero(self) -> None:
        """Cosine similarity < 0 must be clamped to 0.0 for the suspicion score."""
        d = 2
        bank = [{"question": "Q0", "answer": "A0"}]
        # bank embedding: (1, 0), candidate: (-1, 0) → cosine = -1.0
        emb = np.array([[1.0, 0.0], [-1.0, 0.0]], dtype=np.float32)
        scorer = _make_scorer(bank, emb)
        result = scorer.score("s", "negative text")
        assert result.suspicion_score == pytest.approx(0.0)
        assert result.max_cosine_similarity == pytest.approx(-1.0, abs=1e-5)

    def test_injected_model_skips_download(self) -> None:
        """Providing _model must not trigger sentence_transformers import."""
        from unittest.mock import patch
        with patch("ml.embeddings.similarity.SentenceTransformer") as mock_st:
            _ = self._make_orthogonal_scorer()
            mock_st.assert_not_called()


# ── Regression: real JSONL bank schema ───────────────────────────────────────

def test_real_answer_bank_loads_50_plus_entries() -> None:
    """data/llm_answer_bank.jsonl must exist and have ≥ 50 entries."""
    bank_path = Path("data/llm_answer_bank.jsonl")
    if not bank_path.exists():
        pytest.skip("data/llm_answer_bank.jsonl not present (run from project root)")

    entries = []
    with bank_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                obj = json.loads(line)
                assert "question" in obj, "Each entry must have a 'question' key"
                assert "answer" in obj, "Each entry must have an 'answer' key"
                entries.append(obj)

    assert len(entries) >= 50, (
        f"Answer bank has {len(entries)} entries; Sprint 6 requires ≥ 50."
    )
