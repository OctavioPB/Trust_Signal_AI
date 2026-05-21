"""Shared pytest fixtures and configuration.

Marks:
    integration — requires the full docker-compose stack (Kafka + MinIO).
                  Skip with: pytest -m "not integration"
"""

from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: mark test as requiring the docker-compose stack (Kafka + MinIO)",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Auto-skip integration tests unless --run-integration is passed."""
    if config.getoption("--run-integration", default=False):
        return

    skip_integration = pytest.mark.skip(
        reason="Integration tests require docker-compose stack. "
        "Run with: pytest --run-integration -m integration"
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests that require a running docker-compose stack",
    )
