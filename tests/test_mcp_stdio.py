"""End-to-end: start the real server over stdio (like Claude Desktop does) and talk MCP to it."""

from __future__ import annotations

import os
import sys

import pytest
from mcp import Client, StdioServerParameters

EXPECTED_TOOLS = {"list_tables", "describe_table", "query_sales", "revenue_by_city", "top_products", "run_sql"}


def server_params() -> StdioServerParameters:
    # Pass the current environment through so SALESTALK_DATABASE_URL (if set) reaches the server.
    return StdioServerParameters(command=sys.executable, args=["-m", "salestalk_mcp"], env=dict(os.environ))


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_server_starts_and_lists_tools(mode: str) -> None:
    """Works without a database: tools are listed before any connection is made."""
    async with Client(server_params(), mode=mode) as client:
        result = await client.list_tools()
    tools = {t.name: t for t in result.tools}
    assert set(tools) == EXPECTED_TOOLS
    for tool in tools.values():
        assert tool.description
        assert tool.annotations is not None and tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
    assert "range" in tools["revenue_by_city"].input_schema["properties"]
    assert set(tools["query_sales"].input_schema["properties"]) >= {"month", "limit"}


async def test_guard_rejection_is_reported_to_the_model() -> None:
    async with Client(server_params()) as client:
        result = await client.call_tool("run_sql", {"query": "DELETE FROM orders"})
    assert result.is_error
    text = " ".join(getattr(c, "text", "") for c in result.content)
    assert "Only SELECT" in text


async def test_bad_range_is_reported_to_the_model() -> None:
    async with Client(server_params()) as client:
        result = await client.call_tool("revenue_by_city", {"range": "next_decade"})
    assert result.is_error
    assert "Unknown range" in " ".join(getattr(c, "text", "") for c in result.content)


@pytest.mark.integration
async def test_tool_calls_over_stdio(db: object) -> None:
    async with Client(server_params(), mode="legacy") as client:
        sales = await client.call_tool("query_sales", {"month": "last_month", "limit": 3})
        cities = await client.call_tool("revenue_by_city", {"range": "this_quarter"})
        sql = await client.call_tool("run_sql", {"query": "SELECT count(*) AS n FROM orders"})
    assert not sales.is_error and not cities.is_error and not sql.is_error
    assert len(sales.structured_content["top_customers"]) == 3
    assert {c["city"] for c in cities.structured_content["cities"]} == {"Dubai", "Abu Dhabi", "Riyadh", "Jeddah"}
    assert sql.structured_content["rows"][0]["n"] > 0
