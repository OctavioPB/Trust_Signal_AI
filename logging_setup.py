"""Shared structlog configuration — JSON output for all production paths.

Call configure_structlog() once at the top of each service entry-point
(producer, consumer, API) before the first log line.

Context helpers:
  bind_log_context(module=..., candidate_uuid=..., signal_name=...)
  clear_log_context()

Allowed module values: "resume" | "repo" | "interview"
No PII — only UUIDs in candidate_uuid; never names or emails.
"""

from __future__ import annotations

import logging
from typing import Literal

import structlog

_Module = Literal["resume", "repo", "interview"]


def configure_structlog(log_level: str = "INFO") -> None:
    """Configure structlog for JSON output with standard metadata."""
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, log_level.upper(), logging.INFO),
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def bind_log_context(
    *,
    module: _Module | None = None,
    candidate_uuid: str | None = None,
    signal_name: str | None = None,
) -> None:
    """Bind per-request context variables into structlog's context-var store.

    All values are optional; omitted keys are left unchanged.
    Only UUIDs accepted for candidate_uuid — never names, emails, or PII.
    """
    ctx: dict[str, str] = {}
    if module is not None:
        ctx["module"] = module
    if candidate_uuid is not None:
        ctx["candidate_uuid"] = candidate_uuid
    if signal_name is not None:
        ctx["signal_name"] = signal_name
    if ctx:
        structlog.contextvars.bind_contextvars(**ctx)


def clear_log_context() -> None:
    """Clear all structlog context variables for the current context."""
    structlog.contextvars.clear_contextvars()
