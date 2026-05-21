"""Shared structlog configuration — JSON output for all production paths.

Call configure_structlog() once at the top of each service entry-point
(producer, consumer, API) before the first log line.
"""

from __future__ import annotations

import logging

import structlog


def configure_structlog(log_level: str = "INFO") -> None:
    """Configure structlog for JSON output with standard metadata.

    Args:
        log_level: Python logging level string (DEBUG, INFO, WARNING, ERROR).
    """
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
