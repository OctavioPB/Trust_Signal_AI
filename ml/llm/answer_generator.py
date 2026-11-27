"""Generate canonical LLM answers for the semantic-similarity answer bank.

The similarity signal compares a candidate's answer with answers an LLM would give to the same
question. A bank written by a single model family under-represents what candidates actually
paste, so this module asks the routed local models (Gemma, Qwen) to answer the bank's own
questions and returns new ``{question, answer, source_model}`` entries.

Runs only inside the nightly retraining DAG (CLAUDE.md Hard Rule #5). Inputs are generic
interview questions — never candidate text — so no PII reaches the model.
"""

from __future__ import annotations

import json
from pathlib import Path

import structlog

from ml.llm.router import ModelRouter, RoutingExhaustedError

logger = structlog.get_logger(__name__)

SYSTEM_PROMPT = (
    "You are a job candidate answering an interview question. Answer in the first person, "
    "in one polished paragraph of 3 to 5 sentences. Do not use lists, headings or markdown, "
    "and do not mention that you are an AI."
)


def load_questions(bank_path: Path) -> list[str]:
    """Unique questions from the JSONL bank, in first-seen order."""
    seen: dict[str, None] = {}
    if not bank_path.exists():
        return []
    with bank_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                q = str(json.loads(line).get("question", "")).strip()
            except json.JSONDecodeError:
                continue
            if q:
                seen.setdefault(q, None)
    return list(seen)


def generate_answers(
    router: ModelRouter,
    questions: list[str],
    *,
    max_questions: int,
    seed: int | None = None,
) -> list[dict[str, str]]:
    """Answer up to ``max_questions`` questions with the ``answer-generation`` route.

    A question whose whole model chain fails is skipped (logged), so a partial outage still
    yields the answers that succeeded. If the first question fails on every model the runtime
    is treated as down and generation stops early.
    """
    entries: list[dict[str, str]] = []
    for i, question in enumerate(questions[:max_questions]):
        try:
            result = router.complete(
                "answer-generation", system=SYSTEM_PROMPT, user=question, seed=seed
            )
        except RoutingExhaustedError as exc:
            logger.warning("answer_generation_failed", index=i, error=str(exc))
            if not entries and i == 0:
                logger.warning("answer_generation_aborted", reason="llm_runtime_unavailable")
                break
            continue
        entries.append(
            {"question": question, "answer": result.text, "source_model": result.model}
        )
    logger.info("answer_generation_done", requested=min(len(questions), max_questions),
                generated=len(entries), profile=router.profile)
    return entries
