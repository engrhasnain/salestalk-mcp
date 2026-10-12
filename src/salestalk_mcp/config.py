"""Settings, read from environment variables (and an optional .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

DEFAULT_DATABASE_URL = "postgresql://salestalk_ro:salestalk_ro_password@127.0.0.1:5433/salestalk"


def _load_env_files() -> None:
    """Load .env from the working directory, then from the project root.

    Real environment variables (e.g. the ``env`` block in claude_desktop_config.json)
    always win: ``override=False``.
    """
    cwd_env = find_dotenv(usecwd=True)
    if cwd_env:
        load_dotenv(cwd_env, override=False)
    project_env = Path(__file__).resolve().parents[2] / ".env"
    if project_env.is_file():
        load_dotenv(project_env, override=False)


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc
    return max(minimum, min(maximum, value))


@dataclass(frozen=True)
class Settings:
    database_url: str = DEFAULT_DATABASE_URL
    max_rows: int = 500
    default_rows: int = 100
    statement_timeout_ms: int = 5_000
    connect_timeout_s: int = 5
    schema: str = "public"

    @classmethod
    def from_env(cls) -> Settings:
        _load_env_files()
        max_rows = _int_env("SALESTALK_MAX_ROWS", 500, 1, 10_000)
        return cls(
            database_url=os.getenv("SALESTALK_DATABASE_URL", "").strip() or DEFAULT_DATABASE_URL,
            max_rows=max_rows,
            default_rows=min(_int_env("SALESTALK_DEFAULT_ROWS", 100, 1, 10_000), max_rows),
            statement_timeout_ms=_int_env("SALESTALK_STATEMENT_TIMEOUT_MS", 5_000, 100, 120_000),
            connect_timeout_s=_int_env("SALESTALK_CONNECT_TIMEOUT_S", 5, 1, 60),
            schema=os.getenv("SALESTALK_SCHEMA", "public").strip() or "public",
        )
