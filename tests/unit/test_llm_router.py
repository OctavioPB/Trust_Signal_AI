"""Unit tests for ml.llm.router and ml.llm.answer_generator (no live Ollama)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from ml.llm.answer_generator import generate_answers, load_questions
from ml.llm.router import ModelRouter, RoutingExhaustedError

GEMMA = "gemma4:26b-a4b-it-qat"
QWEN = "qwen3:4b-instruct-2507-q4_K_M"


def _router(
    profile: str, handler: Callable[[httpx.Request], httpx.Response]
) -> tuple[ModelRouter, list[dict]]:
    calls: list[dict] = []

    def wrapped(req: httpx.Request) -> httpx.Response:
        calls.append(json.loads(req.content))
        return handler(req)

    return ModelRouter(profile, _transport=httpx.MockTransport(wrapped)), calls


def _ok(text: str = "An answer.") -> httpx.Response:
    return httpx.Response(200, json={"message": {"role": "assistant", "content": text}})


def _by_model(responses: dict[str, httpx.Response | Exception]):
    def handler(req: httpx.Request) -> httpx.Response:
        r = responses[json.loads(req.content)["model"]]
        if isinstance(r, Exception):
            raise r
        return r

    return handler


# ── Routing table ─────────────────────────────────────────────────────────────

def test_gemma_profile_routes_generation_to_gemma_then_qwen() -> None:
    router, _ = _router("gemma", lambda r: _ok())
    assert router.models_for("answer-generation") == [GEMMA, QWEN]
    assert router.models_for("utility") == [QWEN]


def test_qwen_profile_uses_qwen_only() -> None:
    router, _ = _router("qwen", lambda r: _ok())
    assert router.models_for("answer-generation") == [QWEN]
    assert router.models_for("utility") == [QWEN]


def test_unknown_profile_and_task_rejected() -> None:
    with pytest.raises(ValueError):
        ModelRouter("llama")
    router, _ = _router("gemma", lambda r: _ok())
    with pytest.raises(ValueError):
        router.complete("summarize", system="s", user="u")  # type: ignore[arg-type]


# ── Completion + fallback ─────────────────────────────────────────────────────

def test_primary_success_sends_expected_payload() -> None:
    router, calls = _router("gemma", lambda r: _ok("  Hello.  "))
    res = router.complete("answer-generation", system="sys", user="q?", seed=42)
    assert res.text == "Hello."
    assert res.model == GEMMA and not res.fell_back
    body = calls[0]
    assert body["model"] == GEMMA and body["stream"] is False and body["think"] is False
    assert body["messages"][0] == {"role": "system", "content": "sys"}
    assert body["options"]["seed"] == 42 and body["options"]["num_predict"] == 400


@pytest.mark.parametrize(
    "failure",
    [
        httpx.Response(503, text="loading"),
        httpx.ConnectError("refused"),
        httpx.ReadTimeout("slow"),
        _ok("   "),
    ],
)
def test_runtime_failure_falls_back_to_qwen(failure) -> None:
    router, calls = _router("gemma", _by_model({GEMMA: failure, QWEN: _ok("from qwen")}))
    res = router.complete("answer-generation", system="s", user="u")
    assert res.model == QWEN and res.fell_back and res.text == "from qwen"
    assert [c["model"] for c in calls] == [GEMMA, QWEN]


def test_client_error_does_not_fall_back() -> None:
    router, calls = _router("gemma", _by_model({GEMMA: httpx.Response(404, text="not found")}))
    with pytest.raises(ValueError):
        router.complete("answer-generation", system="s", user="u")
    assert len(calls) == 1


def test_chain_exhausted_raises() -> None:
    router, _ = _router("qwen", lambda r: httpx.Response(500, text="boom"))
    with pytest.raises(RoutingExhaustedError):
        router.complete("utility", system="s", user="u")


# ── Answer generator ──────────────────────────────────────────────────────────

def test_load_questions_dedupes(tmp_path: Path) -> None:
    bank = tmp_path / "bank.jsonl"
    bank.write_text(
        '{"question": "A?", "answer": "1"}\n{"question": "A?", "answer": "2"}\n'
        "not json\n\n"
        '{"question": "B?", "answer": "3"}\n',
        encoding="utf-8",
    )
    assert load_questions(bank) == ["A?", "B?"]
    assert load_questions(tmp_path / "missing.jsonl") == []


def test_generate_answers_tags_source_model_and_caps() -> None:
    router, calls = _router("gemma", lambda r: _ok("I am great."))
    out = generate_answers(router, ["A?", "B?", "C?"], max_questions=2, seed=1)
    assert out == [
        {"question": "A?", "answer": "I am great.", "source_model": GEMMA},
        {"question": "B?", "answer": "I am great.", "source_model": GEMMA},
    ]
    assert len(calls) == 2


def test_generate_answers_aborts_when_runtime_down() -> None:
    router, calls = _router("gemma", lambda r: (_ for _ in ()).throw(httpx.ConnectError("x")))
    assert generate_answers(router, ["A?", "B?", "C?"], max_questions=3) == []
    assert len(calls) == 2  # gemma + qwen for the first question only
