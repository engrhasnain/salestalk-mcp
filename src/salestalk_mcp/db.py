"""PostgreSQL access: every query runs in a read-only, time-limited transaction.

Defense in depth, from the outside in:

* the server connects as a role that only has ``SELECT`` (created in db/init);
* the role defaults to ``default_transaction_read_only = on``;
* every connection is opened with ``default_transaction_read_only=on`` and a
  ``statement_timeout`` in its startup options;
* every transaction is started ``READ ONLY`` and is always rolled back, never committed;
* queries are sent as server-side prepared statements (extended protocol),
  which PostgreSQL refuses to run if they contain more than one statement;
* results are fetched with ``fetchmany(max_rows + 1)`` so the cap holds even if
  a LIMIT were missing.
"""

from __future__ import annotations

import datetime as dt
import time
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import psycopg
from psycopg import errors as pg_errors
from psycopg import sql as sql_mod
from psycopg.conninfo import conninfo_to_dict

from .config import Settings

Query = str | sql_mod.Composable
Params = Sequence[Any] | Mapping[str, Any] | None


class QueryError(Exception):
    """A database problem with a message that is safe to show to the model (no secrets)."""


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[dict[str, Any]]
    truncated: bool
    elapsed_ms: float

    @property
    def row_count(self) -> int:
        return len(self.rows)


def to_jsonable(value: Any) -> Any:
    """Convert PostgreSQL values into JSON-friendly Python values."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, Decimal):
        if not value.is_finite() or abs(value) >= Decimal("1e15"):
            return str(value)
        return int(value) if value == value.to_integral_value() and value.as_tuple().exponent >= 0 else float(value)
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, dt.timedelta):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<{len(bytes(value))} bytes>"
    if isinstance(value, Mapping):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(v) for v in value]
    return str(value)


def _unique_names(names: Sequence[str]) -> list[str]:
    """``SELECT a.id, b.id`` returns two ``id`` columns; keep both as ``id`` and ``id_2``."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for name in names:
        if name in seen:
            seen[name] += 1
            out.append(f"{name}_{seen[name]}")
        else:
            seen[name] = 1
            out.append(name)
    return out


class Database:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    # ------------------------------------------------------------------ info

    def describe_target(self) -> str:
        """``user@host:port/dbname`` without the password (for logs and error messages)."""
        try:
            info = conninfo_to_dict(self.settings.database_url)
        except psycopg.ProgrammingError:
            return "<invalid SALESTALK_DATABASE_URL>"
        return (
            f"{info.get('user', '?')}@{info.get('host', 'localhost')}:"
            f"{info.get('port', '5432')}/{info.get('dbname', '?')}"
        )

    # ------------------------------------------------------------------ sessions

    @contextmanager
    def session(self, statement_timeout_ms: int | None = None) -> Iterator[psycopg.Connection]:
        timeout = int(statement_timeout_ms or self.settings.statement_timeout_ms)
        options = " ".join(
            [
                "-c default_transaction_read_only=on",
                f"-c statement_timeout={timeout}",
                f"-c idle_in_transaction_session_timeout={max(timeout * 3, 10_000)}",
                "-c standard_conforming_strings=on",
                f"-c search_path={self.settings.schema}",
            ]
        )
        try:
            conn = psycopg.connect(
                self.settings.database_url,
                connect_timeout=self.settings.connect_timeout_s,
                options=options,
                application_name="salestalk-mcp",
                autocommit=False,
            )
        except psycopg.Error as exc:
            first_line = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
            raise QueryError(
                f"Cannot connect to PostgreSQL at {self.describe_target()}. "
                f"Is the database running (`docker compose up -d`)? Details: {first_line}"
            ) from exc
        conn.read_only = True  # every transaction starts with BEGIN READ ONLY
        try:
            yield conn
        finally:
            try:
                conn.rollback()  # never commit anything
            finally:
                conn.close()

    @contextmanager
    def connect(self, statement_timeout_ms: int | None = None) -> Iterator[Runner]:
        """Open one read-only session and run several queries in it."""
        timeout = int(statement_timeout_ms or self.settings.statement_timeout_ms)
        with self.session(timeout) as conn:
            yield Runner(conn, timeout)

    def query(
        self,
        sql: Query,
        params: Params = None,
        *,
        max_rows: int | None = None,
        statement_timeout_ms: int | None = None,
    ) -> QueryResult:
        """Run a single statement in its own read-only session."""
        with self.connect(statement_timeout_ms) as run:
            return run.query(sql, params, max_rows=max_rows)

    def ping(self) -> bool:
        try:
            self.query("SELECT 1 AS ok")
            return True
        except QueryError:
            return False


class Runner:
    """Executes statements on an open read-only connection and maps errors to QueryError."""

    def __init__(self, conn: psycopg.Connection, timeout_ms: int) -> None:
        self.conn = conn
        self.timeout_ms = timeout_ms

    def query(self, sql: Query, params: Params = None, *, max_rows: int | None = None) -> QueryResult:
        """Run one statement and return JSON-friendly rows.

        ``params`` use psycopg placeholders (``%s`` / ``%(name)s``) and are bound
        server-side. When ``params`` is None the SQL is sent verbatim.
        """
        started = time.perf_counter()
        try:
            with self.conn.cursor() as cur:
                # prepare=True forces the extended protocol: stacked statements are refused
                cur.execute(sql, params, prepare=True)
                if cur.description is None:
                    return QueryResult([], [], False, _ms(started))
                columns = _unique_names([d.name for d in cur.description])
                if max_rows is not None:
                    raw = cur.fetchmany(max_rows + 1)
                    truncated = len(raw) > max_rows
                    raw = raw[:max_rows]
                else:
                    raw, truncated = cur.fetchall(), False
        except pg_errors.QueryCanceled as exc:
            raise QueryError(
                f"Query cancelled: it exceeded the {self.timeout_ms} ms statement timeout. "
                "Add filters or aggregate more."
            ) from exc
        except pg_errors.ReadOnlySqlTransaction as exc:
            raise QueryError("Rejected by the database: this connection is read-only.") from exc
        except pg_errors.InsufficientPrivilege as exc:
            raise QueryError(f"Permission denied for the read-only role: {_primary(exc)}") from exc
        except psycopg.Error as exc:
            raise QueryError(f"Database error: {_primary(exc)}") from exc

        rows = [{c: to_jsonable(v) for c, v in zip(columns, r, strict=True)} for r in raw]
        return QueryResult(columns, rows, truncated, _ms(started))


def _primary(exc: psycopg.Error) -> str:
    diag = getattr(exc, "diag", None)
    message = (diag.message_primary if diag else None) or str(exc).strip().splitlines()[0]
    hint = diag.message_hint if diag else None
    return f"{message} (hint: {hint})" if hint else message


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)
