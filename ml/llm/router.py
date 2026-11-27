"""Task-based model routing for local LLMs served by Ollama.

Two model families, the same ones pinned in the Legal AI Assistant project:

- **Gemma** (``gemma4:26b-a4b-it-qat``) — the large model, used for long-form generation.
- **Qwen**  (``qwen3:4b-instruct-2507-q4_K_M``) — the small model, used for utility work and as
  the fallback when Gemma is unavailable.

Callers never name a model. They name a *task* (see ``TASKS``); the active *profile* maps each
task to a primary model plus an ordered fallback chain:

=================  =============================  ==========================
profile            ``answer-generation``          ``utility``
=================  =============================  ==========================
``gemma`` (default) gemma → qwen                   qwen
``qwen``           qwen (no fallback)             qwen (no fallback)
=================  =============================  ==========================

Only runtime failures (connection refused, timeout, HTTP 5xx, empty answer) raise
``ProviderError`` and trigger the next model in the chain. A 4xx is a bug in our request (e.g.
model not pulled) and raises ``ValueError`` immediately.

Everything runs on the local machine; no prompt or answer leaves it. Prompts sent here must never
contain candidate PII (CLAUDE.md Hard Rule #6) — the only caller today sends generic interview
questions from the answer bank.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Literal, get_args

import httpx
import structlog

import config

logger = structlog.get_logger(__name__)

TaskName = Literal["answer-generation", "utility"]
TASKS: tuple[TaskName, ...] = get_args(TaskName)

ProfileName = Literal["gemma", "qwen"]
PROFILES: tuple[ProfileName, ...] = get_args(ProfileName)

ModelKey = Literal["gemma", "qwen"]


class ProviderError(RuntimeError):
    """The local runtime failed (unreachable, timeout, 5xx, empty output). Triggers fallback."""


class RoutingExhaustedError(RuntimeError):
    """Every model in the task's chain failed."""


@dataclass(frozen=True)
class TaskRoute:
    """Primary model and ordered fallbacks for one task, plus its answer-length cap."""

    chain: tuple[ModelKey, ...]
    max_tokens: int


@dataclass(frozen=True)
class LLMResult:
    """One completed generation."""

    text: str
    task: TaskName
    model: str
    latency_ms: int
    fell_back: bool


def _routes(profile: ProfileName) -> dict[TaskName, TaskRoute]:
    if profile == "gemma":
        return {
            "answer-generation": TaskRoute(chain=("gemma", "qwen"), max_tokens=400),
            "utility":           TaskRoute(chain=("qwen",), max_tokens=200),
        }
    # qwen: every task on the small model; a fallback would only retry the same model.
    return {
        "answer-generation": TaskRoute(chain=("qwen",), max_tokens=400),
        "utility":           TaskRoute(chain=("qwen",), max_tokens=200),
    }


class ModelRouter:
    """Routes a task to the profile's model chain over Ollama's ``/api/chat``.

    Args:
        profile: ``"gemma"`` (default) or ``"qwen"``.
        models: Ollama model tag per model key.
        base_url: Ollama server URL.
        timeout_s: Per-request timeout.
        _transport: Optional ``httpx`` transport (tests only).
    """

    def __init__(
        self,
        profile: str = "gemma",
        *,
        models: dict[ModelKey, str] | None = None,
        base_url: str = "http://localhost:11434",
        timeout_s: float = 300.0,
        _transport: httpx.BaseTransport | None = None,
    ) -> None:
        if profile not in PROFILES:
            raise ValueError(f"unknown LLM profile {profile!r}; expected one of {PROFILES}")
        self.profile: ProfileName = profile  # type: ignore[assignment]
        self._models: dict[ModelKey, str] = models or {
            "gemma": "gemma4:26b-a4b-it-qat",
            "qwen": "qwen3:4b-instruct-2507-q4_K_M",
        }
        self._routes = _routes(self.profile)
        self._http = httpx.Client(base_url=base_url, timeout=timeout_s, transport=_transport)
        self._log = logger.bind(component="ModelRouter", profile=self.profile)

    # ── Public API ────────────────────────────────────────────────────────────

    def models_for(self, task: TaskName) -> list[str]:
        """Ollama tags tried for ``task``, in order."""
        return [self._models[k] for k in self._route(task).chain]

    def complete(
        self,
        task: TaskName,
        *,
        system: str,
        user: str,
        temperature: float = 0.7,
        seed: int | None = None,
    ) -> LLMResult:
        """Generate a completion for ``task``, falling back along the chain on runtime failures.

        Raises:
            ValueError: Unknown task, or Ollama rejected the request (4xx).
            RoutingExhaustedError: Every model in the chain failed.
        """
        route = self._route(task)
        errors: list[str] = []
        for i, key in enumerate(route.chain):
            model = self._models[key]
            t0 = time.monotonic()
            try:
                text = self._chat(model, system, user, route.max_tokens, temperature, seed)
            except ProviderError as exc:
                errors.append(f"{model}: {exc}")
                self._log.warning("llm_model_failed", task=task, model=model, error=str(exc))
                continue
            latency_ms = int((time.monotonic() - t0) * 1000)
            self._log.info(
                "llm_completed", task=task, model=model, latency_ms=latency_ms, fell_back=i > 0
            )
            return LLMResult(
                text=text, task=task, model=model, latency_ms=latency_ms, fell_back=i > 0
            )
        raise RoutingExhaustedError(f"all models failed for task {task!r}: {'; '.join(errors)}")

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> ModelRouter:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _route(self, task: str) -> TaskRoute:
        if task not in self._routes:
            raise ValueError(f"unknown LLM task {task!r}; expected one of {TASKS}")
        return self._routes[task]  # type: ignore[index]

    def _chat(
        self,
        model: str,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
        seed: int | None,
    ) -> str:
        options: dict[str, Any] = {"temperature": temperature, "num_predict": max_tokens}
        if seed is not None:
            options["seed"] = seed
        payload = {
            "model": model,
            "stream": False,
            "think": False,  # reasoning tokens would consume the answer budget
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "options": options,
        }
        try:
            res = self._http.post("/api/chat", json=payload)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderError(f"ollama unreachable or too slow: {type(exc).__name__}") from exc
        if res.status_code >= 500:
            raise ProviderError(f"ollama {res.status_code}: {res.text[:200]}")
        if res.status_code >= 400:
            raise ValueError(f"ollama rejected the request ({res.status_code}): {res.text[:300]}")
        text = ((res.json().get("message") or {}).get("content") or "").strip()
        if not text:
            raise ProviderError("empty completion")
        return text


def build_router(profile: str | None = None, **kwargs: Any) -> ModelRouter:
    """Router configured from ``config`` (``LLM_PROFILE``, ``OLLAMA_BASE_URL``, model tags)."""
    return ModelRouter(
        profile or config.LLM_PROFILE,
        models={"gemma": config.LLM_MODEL_GEMMA, "qwen": config.LLM_MODEL_QWEN},
        base_url=config.OLLAMA_BASE_URL,
        timeout_s=config.LLM_TIMEOUT_S,
        **kwargs,
    )
