"""Shared fixtures. Integration tests skip cleanly when the demo database is unreachable."""

from __future__ import annotations

import pytest

from salestalk_mcp.config import Settings
from salestalk_mcp.db import Database, QueryError


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings.from_env()


@pytest.fixture(scope="session")
def db(settings: Settings) -> Database:
    database = Database(settings)
    try:
        database.query("SELECT 1 FROM dataset_info LIMIT 1")
    except QueryError as exc:
        pytest.skip(f"Seeded database not reachable at {database.describe_target()}: {exc}")
    return database
