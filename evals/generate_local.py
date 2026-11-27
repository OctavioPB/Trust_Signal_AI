"""Generate the local-LLM slice of the evaluation set (run once, output is committed).

Two AI-labelled groups that the public datasets do not cover:

  local_llm    — interview answers written by the local models (Gemma, Qwen) through
                 ``ml.llm.router``, i.e. the families a candidate could run privately.
  paraphrased  — the same answers rewritten by Qwen to sound casual and spoken, the
                 cheapest evasion a candidate would try (Krishna et al., 2023).

The questions are deliberately NOT the answer-bank questions, so the
semantic-similarity signal is not scored on its own training material.

Usage (needs Ollama with both models pulled; ~30 min on a laptop CPU/GPU):
    python -m evals.generate_local            # resumes: skips ids already written
"""

from __future__ import annotations

import json
from pathlib import Path

import structlog

from ml.llm.router import RoutingExhaustedError, build_router

logger = structlog.get_logger(__name__)

OUT = Path(__file__).parent / "data" / "local_llm.jsonl"

QUESTIONS = [
    "Walk me through a project you are proud of.",
    "Describe a time you had to learn a new technology quickly.",
    "How do you prioritise when everything feels urgent?",
    "Tell me about a bug that took you a long time to find.",
    "How do you handle code review feedback you disagree with?",
    "Describe a time you missed a deadline. What happened?",
    "How would you explain a technical trade-off to a non-technical stakeholder?",
    "What does good documentation look like to you?",
    "Tell me about a time you improved a process on your team.",
    "How do you decide when a piece of code is ready to ship?",
    "Describe a disagreement with a manager and how it was resolved.",
    "How do you approach debugging a production incident?",
    "What is a technical decision you would make differently today?",
    "How do you keep your skills current?",
    "Tell me about a time you mentored someone.",
    "How do you design an API that other teams will depend on?",
    "Describe a time you had to work with incomplete requirements.",
    "How do you balance speed and quality?",
    "What motivates you in your day-to-day work?",
    "Tell me about a failure and what you learned from it.",
    "How do you test code that depends on external services?",
    "Describe how you would scale a service that is getting slow.",
    "How do you onboard yourself onto an unfamiliar codebase?",
    "Tell me about a time you had to say no to a request.",
    "How do you handle working across time zones?",
    "Describe a time you took ownership of something outside your role.",
    "What makes a team effective in your experience?",
    "How do you estimate how long a task will take?",
    "Tell me about the most complex system you have worked on.",
    "How do you deal with technical debt?",
    "Describe a time you received difficult feedback.",
    "How would you investigate a sudden drop in a key metric?",
    "What questions do you ask before starting a new feature?",
    "Tell me about a time you automated something tedious.",
    "How do you make sure your work is secure?",
    "Describe a project where you worked closely with data.",
    "How do you communicate progress on a long project?",
    "Tell me about a time you changed your mind about something technical.",
    "What would your previous teammates say about working with you?",
    "Why are you interested in this role?",
]

ANSWER_SYSTEM = (
    "You are a job candidate in a live interview. Answer the question in the first "
    "person, in one paragraph of 4 to 6 sentences, as you would say it out loud. "
    "No lists, no headings, no markdown, and never mention being an AI."
)

PARAPHRASE_SYSTEM = (
    "Rewrite the answer so it sounds like a real person speaking off the cuff: vary "
    "sentence length, add a hesitation or a self-correction, use casual wording. Keep "
    "the meaning and first person. Output only the rewritten answer, one paragraph."
)


def _done_ids() -> set[str]:
    if not OUT.exists():
        return set()
    with OUT.open(encoding="utf-8") as f:
        return {json.loads(line)["id"] for line in f if line.strip()}


def _write(row: dict) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    done = _done_ids()
    with build_router("gemma") as gemma, build_router("qwen") as qwen:
        for i, question in enumerate(QUESTIONS):
            # Alternate families so the slice covers both local models.
            router = gemma if i % 2 == 0 else qwen
            aid, pid = f"local-{i:02d}", f"para-{i:02d}"
            if aid in done and pid in done:
                continue
            try:
                answer = router.complete(
                    "answer-generation", system=ANSWER_SYSTEM, user=question, seed=1000 + i
                )
                if aid not in done:
                    _write({"id": aid, "question": question, "text": answer.text, "label": 1,
                            "group": "local_llm", "source": f"ollama:{answer.model}"})
                para = qwen.complete(
                    "answer-generation", system=PARAPHRASE_SYSTEM, user=answer.text,
                    seed=2000 + i,
                )
                _write({"id": pid, "question": question, "text": para.text, "label": 1,
                        "group": "paraphrased", "source": f"ollama:{para.model}"})
            except RoutingExhaustedError as exc:
                logger.error("local_generation_failed", index=i, error=str(exc))
                raise SystemExit(1) from exc
            logger.info("local_generation_progress", done=i + 1, total=len(QUESTIONS))


if __name__ == "__main__":
    main()
