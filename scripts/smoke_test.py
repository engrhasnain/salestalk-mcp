"""Smoke test: start SalesTalk over stdio, list its tools and call each one, like Claude Desktop would.

    uv run python scripts/smoke_test.py            # needs `docker compose up -d` for the tool calls
    uv run python scripts/smoke_test.py --legacy   # use the classic initialize handshake
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

from mcp import Client, StdioServerParameters

CALLS: list[tuple[str, dict[str, Any]]] = [
    ("list_tables", {}),
    ("describe_table", {"table_name": "orders"}),
    ("query_sales", {"month": "last_month", "limit": 5}),
    ("revenue_by_city", {"range": "this_quarter"}),
    ("revenue_by_city", {"range": "last_12_months", "granularity": "month"}),
    ("top_products", {"range": "last_30_days", "limit": 5}),
    ("run_sql", {"query": "SELECT segment, count(*) AS customers FROM customers GROUP BY 1 ORDER BY 2 DESC"}),
    ("run_sql", {"query": "DELETE FROM orders"}),  # must be rejected
    ("run_sql", {"query": "SELECT 1; DROP TABLE orders"}),  # must be rejected
]


def summarize(name: str, data: dict[str, Any]) -> str:
    if name == "list_tables":
        return ", ".join(f"{t['name']}({t['approx_rows']})" for t in data["tables"])
    if name == "describe_table":
        return f"{data['name']}: {len(data['columns'])} columns, {len(data['sample_rows'])} sample rows"
    if name == "query_sales":
        s, top = data["summary"], data["top_customers"]
        lines = [f"{data['month']}: AED {s['revenue']:,.2f} from {s['orders']} orders "
                 f"({data['previous_period']['revenue_change_pct']}% vs previous month)"]
        lines += [f"    #{c['rank']} {c['customer']} ({c['city']}) AED {c['revenue']:,.2f}" for c in top]
        return "\n".join(lines)
    if name == "revenue_by_city":
        head = f"{data['range']['label']} {data['range']['start']}..{data['range']['end']}: "
        body = ", ".join(f"{c['city']} AED {c['revenue']:,.0f}" for c in data["cities"])
        extra = f" | {len(data['monthly'])} monthly points" if "monthly" in data else ""
        return head + body + extra
    if name == "top_products":
        return "; ".join(f"#{p['rank']} {p['product']} AED {p['revenue']:,.0f}" for p in data["products"])
    if name == "run_sql":
        return f"{data['row_count']} rows: {json.dumps(data['rows'][:4])}"
    return json.dumps(data)[:200]


async def main(legacy: bool) -> int:
    params = StdioServerParameters(command=sys.executable, args=["-m", "salestalk_mcp"], env=dict(os.environ))
    failures = 0
    async with Client(params, mode="legacy" if legacy else "auto") as client:
        tools = (await client.list_tools()).tools
        print(f"Server exposes {len(tools)} tools: {', '.join(t.name for t in tools)}\n")
        for name, args in CALLS:
            result = await client.call_tool(name, args)
            expect_error = name == "run_sql" and not args["query"].upper().startswith("SELECT SEGMENT")
            label = f"{name}({', '.join(f'{k}={v!r}' for k, v in args.items())})"
            if result.is_error:
                text = " ".join(getattr(c, "text", "") for c in result.content)
                status = "OK (rejected as expected)" if expect_error else "FAIL"
                failures += 0 if expect_error else 1
                print(f"[{status}] {label}\n    {text}\n")
            else:
                status = "FAIL (should have been rejected)" if expect_error else "OK"
                failures += 1 if expect_error else 0
                print(f"[{status}] {label}\n    {summarize(name, result.structured_content or {})}\n")
    print("All checks passed." if not failures else f"{failures} check(s) failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--legacy", action="store_true", help="use the classic initialize handshake")
    sys.exit(asyncio.run(main(parser.parse_args().legacy)))
