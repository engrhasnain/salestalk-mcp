"""SalesTalk MCP server: read-only tools over the sales database.

Run with stdio (Claude Desktop):        uv run salestalk-mcp
Run with streamable HTTP (remote/dev):  uv run salestalk-mcp --transport streamable-http --port 8765
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Callable
from functools import lru_cache
from typing import Annotated, Any, TypeVar

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field

from . import __version__, queries
from .config import Settings
from .db import Database, QueryError
from .ranges import MONTH_HELP, RANGE_HELP, RangeError
from .sql_guard import SqlGuardError

log = logging.getLogger("salestalk_mcp")

INSTRUCTIONS = """\
SalesTalk gives you READ-ONLY access to the sales database of "Dune & Dhow Trading Co.", a
fictional Gulf trading company selling dates, coffee & tea, spices, textiles, electronics and
fragrance to B2B customers in Dubai, Abu Dhabi, Riyadh and Jeddah.

Facts:
- All money is in AED. Revenue = order totals excluding cancelled and returned orders.
- Tables: cities, customers, products, orders, order_items, dataset_info; view v_sales
  (one row per order line, already joined and filtered to revenue-generating orders).
- Orders cover the last 12 full months plus the current month to date.

How to answer:
- Prefer the purpose-built tools: query_sales (a month's totals + top customers),
  revenue_by_city (city comparison, optional monthly series for charts) and top_products.
- For anything else, call list_tables / describe_table, then run_sql with ONE SELECT
  statement. Results are row-capped; aggregate in SQL instead of fetching raw rows.
- Ranges accept presets such as last_month, this_quarter, last_30_days, ytd, last_12_months,
  or explicit YYYY-MM-DD..YYYY-MM-DD.
"""

READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)

mcp = MCPServer(
    name="salestalk",
    title="SalesTalk MCP",
    description="Chat with a sample Gulf trading company's sales database (read-only PostgreSQL).",
    instructions=INSTRUCTIONS,
    version=__version__,
)


@lru_cache(maxsize=1)
def get_db() -> Database:
    """Created lazily, so the server starts (and lists tools) even if Postgres is down."""
    settings = Settings.from_env()
    db = Database(settings)
    log.info("SalesTalk using %s (max_rows=%s, timeout=%sms)", db.describe_target(),
             settings.max_rows, settings.statement_timeout_ms)
    return db


T = TypeVar("T")


def _run(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Call a query function; turn anticipated failures into ToolErrors the model can read."""
    try:
        return fn(get_db(), *args, **kwargs)
    except (SqlGuardError, RangeError, queries.ToolInputError, QueryError) as exc:
        raise ToolError(str(exc)) from exc


# --------------------------------------------------------------------------- tools


@mcp.tool(title="List tables", annotations=READ_ONLY)
def list_tables() -> dict[str, Any]:
    """List the tables and views you can query, with approximate row counts and descriptions."""
    return _run(queries.list_tables)


@mcp.tool(title="Describe table", annotations=READ_ONLY)
def describe_table(
    table_name: Annotated[str, Field(description="Table or view name, e.g. 'orders' or 'v_sales'.")],
) -> dict[str, Any]:
    """Show a table's columns (types, nullability, descriptions), keys, relationships and 3 sample rows."""
    return _run(queries.describe_table, table_name)


@mcp.tool(title="Monthly sales and top customers", annotations=READ_ONLY)
def query_sales(
    month: Annotated[str, Field(description=f"Month to report. {MONTH_HELP}")] = "last_month",
    limit: Annotated[int, Field(ge=1, le=50, description="How many top customers to return.")] = 5,
    city: Annotated[
        str | None, Field(description="Optional city filter: Dubai, Abu Dhabi, Riyadh or Jeddah.")
    ] = None,
) -> dict[str, Any]:
    """Sales for one month: revenue, orders, active customers, average order value, change vs.
    the previous month, and the top customers ranked by revenue. Use it for questions like
    "Who were our top 5 customers last month?"."""
    return _run(queries.query_sales, month, limit, city)


@mcp.tool(title="Revenue by city", annotations=READ_ONLY)
def revenue_by_city(
    range: Annotated[str, Field(description=f"Date range. {RANGE_HELP}")] = "this_quarter",  # noqa: A002
    granularity: Annotated[
        str,
        Field(description="'total' for one row per city, or 'month' to also get a monthly series (good for charts)."),
    ] = "total",
) -> dict[str, Any]:
    """Revenue, orders, customers, average order value and share per city, with % change vs. the
    previous period of equal length. Use it to compare cities, e.g. Dubai vs Riyadh this quarter."""
    return _run(queries.revenue_by_city, range, granularity)


@mcp.tool(title="Top products", annotations=READ_ONLY)
def top_products(
    range: Annotated[str, Field(description=f"Date range. {RANGE_HELP}")] = "last_30_days",  # noqa: A002
    limit: Annotated[int, Field(ge=1, le=50, description="How many products to return.")] = 10,
    category: Annotated[
        str | None,
        Field(description="Optional category: Dates, Coffee & Tea, Spices, Textiles, Electronics, Fragrance."),
    ] = None,
    city: Annotated[str | None, Field(description="Optional city filter.")] = None,
    sort_by: Annotated[str, Field(description="'revenue' (default) or 'units'.")] = "revenue",
) -> dict[str, Any]:
    """Best-selling products in a date range with units, orders, revenue, share and gross margin."""
    return _run(queries.top_products, range, limit, category, city, sort_by)


@mcp.tool(title="Run read-only SQL", annotations=READ_ONLY)
def run_sql(
    query: Annotated[
        str,
        Field(
            description="ONE PostgreSQL SELECT (or WITH ... SELECT) statement. "
            "No writes, DDL or multiple statements."
        ),
    ],
    limit: Annotated[
        int | None, Field(ge=1, description="Max rows to return (capped by the server, default 100).")
    ] = None,
) -> dict[str, Any]:
    """Run a custom read-only SELECT when the other tools don't cover the question. The query is
    checked by a SELECT-only guard, executed by a read-only database role inside a read-only
    transaction with a statement timeout, and the result is row-capped."""
    return _run(queries.run_sql, query, limit)


# --------------------------------------------------------------------------- entry point


def _transport_security(host: str) -> TransportSecuritySettings | None:
    """Keep DNS-rebinding protection on when binding to all interfaces (e.g. in Docker)."""
    if host in ("127.0.0.1", "localhost", "::1"):
        return None  # the SDK enables localhost protection automatically
    extra = [h.strip() for h in os.getenv("SALESTALK_ALLOWED_HOSTS", "").split(",") if h.strip()]
    hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*", *extra]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=[f"http://{h}" for h in hosts],
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="salestalk-mcp", description="SalesTalk MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default=os.getenv("SALESTALK_TRANSPORT", "stdio"),
        help="stdio for Claude Desktop (default) or streamable-http",
    )
    parser.add_argument("--host", default=os.getenv("SALESTALK_HTTP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("SALESTALK_HTTP_PORT", "8765")))
    parser.add_argument("--version", action="version", version=f"salestalk-mcp {__version__}")
    args = parser.parse_args(argv)

    # stdout belongs to the MCP protocol on stdio: log to stderr only.
    logging.basicConfig(
        level=os.getenv("SALESTALK_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    if args.transport == "stdio":
        mcp.run("stdio")
    else:
        log.info("Streamable HTTP on http://%s:%s/mcp", args.host, args.port)
        mcp.run(
            "streamable-http",
            host=args.host,
            port=args.port,
            transport_security=_transport_security(args.host),
        )


if __name__ == "__main__":
    main()
