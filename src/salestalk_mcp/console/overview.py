"""Data for the console's hero, built only from MCP tool calls (never from the database directly)."""

from __future__ import annotations

from datetime import date
from typing import Any

from .bridge import CallOutcome, McpBridge

STATS_SQL = """\
SELECT (SELECT count(*) FROM customers)   AS customers,
       (SELECT count(*) FROM products)    AS products,
       (SELECT count(*) FROM orders)      AS orders,
       (SELECT count(*) FROM order_items) AS order_lines,
       (SELECT min(order_date) FROM orders) AS first_order,
       (SELECT max(order_date) FROM orders) AS last_order"""

CUSTOMERS_SQL = """SELECT c.customer_id, c.company_name AS customer, ci.name AS city, c.segment,
       count(o.order_id) AS orders, coalesce(round(sum(o.total_amount)), 0) AS revenue
  FROM customers c
  JOIN cities ci     ON ci.city_id = c.city_id
  LEFT JOIN orders o ON o.customer_id = c.customer_id AND o.status NOT IN ('cancelled', 'returned')
 GROUP BY c.customer_id, c.company_name, ci.name, c.segment
 ORDER BY revenue DESC"""

#: The calls made when the console loads, in order. They also feed the hero's "live tool calls" card.
#: The last one is meant to be refused: it shows the SQL guard at work.
OVERVIEW_CALLS: list[tuple[str, str, dict[str, Any]]] = [
    ("sales", "query_sales", {"month": "last_month", "limit": 5}),
    ("cities", "revenue_by_city", {"range": "last_12_months", "granularity": "month"}),
    ("products", "top_products", {"range": "last_30_days", "limit": 5}),
    ("tables", "list_tables", {}),
    ("stats", "run_sql", {"query": STATS_SQL}),
    ("customers", "run_sql", {"query": CUSTOMERS_SQL, "limit": 400}),
    ("refused", "run_sql", {"query": "DELETE FROM orders"}),
]


def _months_between(first: str | None, last: str | None) -> int | None:
    try:
        a, b = date.fromisoformat(str(first)), date.fromisoformat(str(last))
    except ValueError:
        return None
    return (b.year - a.year) * 12 + (b.month - a.month) + 1


def build_data(results: dict[str, CallOutcome], tool_count: int) -> dict[str, Any]:
    """Shape the raw tool results into what the hero needs. Missing pieces stay None."""

    def ok(key: str) -> dict[str, Any] | None:
        outcome = results.get(key)
        return outcome.result if outcome is not None and not outcome.is_error else None

    data: dict[str, Any] = {"stats": None, "cities": [], "monthly": [], "customers": [], "last_month": None,
                            "top_products": [], "revenue_12m": None, "range_12m": None, "tables": []}

    stats = ok("stats")
    if stats and stats.get("rows"):
        row = stats["rows"][0]
        data["stats"] = {
            "customers": row.get("customers"),
            "products": row.get("products"),
            "orders": row.get("orders"),
            "order_lines": row.get("order_lines"),
            "first_order": row.get("first_order"),
            "last_order": row.get("last_order"),
            "months": _months_between(row.get("first_order"), row.get("last_order")),
            "tools": tool_count,
        }

    cities = ok("cities")
    if cities:
        data["cities"] = [
            {k: c.get(k) for k in ("city", "country", "revenue", "orders", "customers", "share_pct")}
            for c in cities.get("cities", [])
        ]
        data["monthly"] = cities.get("monthly", [])
        data["revenue_12m"] = cities.get("total_revenue")
        data["range_12m"] = cities.get("range")

    customers = ok("customers")
    if customers:
        data["customers"] = [
            {
                "id": r.get("customer_id"),
                "name": r.get("customer"),
                "city": r.get("city"),
                "segment": r.get("segment"),
                "orders": r.get("orders"),
                "revenue": r.get("revenue"),
            }
            for r in customers.get("rows", [])
        ]

    sales = ok("sales")
    if sales:
        data["last_month"] = {
            "month": sales.get("month"),
            "revenue": sales.get("summary", {}).get("revenue"),
            "orders": sales.get("summary", {}).get("orders"),
            "change_pct": sales.get("previous_period", {}).get("revenue_change_pct"),
            "top_customers": sales.get("top_customers", []),
        }

    products = ok("products")
    if products:
        data["top_products"] = products.get("products", [])

    tables = ok("tables")
    if tables:
        data["tables"] = [{"name": t.get("name"), "kind": t.get("kind"), "approx_rows": t.get("approx_rows")}
                          for t in tables.get("tables", [])]
    return data


async def build_overview(bridge: McpBridge) -> dict[str, Any]:
    """Run the load-time calls over MCP and return the hero data plus the calls themselves."""
    results: dict[str, CallOutcome] = {}
    calls: list[dict[str, Any]] = []
    for key, tool, args in OVERVIEW_CALLS:
        outcome = await bridge.call(tool, args)
        results[key] = outcome
        entry = outcome.to_dict(frames=False)
        entry["key"] = key
        entry["frames_count"] = len(outcome.frames)
        entry["bytes"] = sum(f["bytes"] for f in outcome.frames)
        if key == "customers" and outcome.result:
            # The rows are delivered once, in data.customers; keep the feed entry small.
            entry["result"] = {k: v for k, v in outcome.result.items() if k != "rows"}
        calls.append(entry)
    return {"session": bridge.describe(), "data": build_data(results, len(bridge.tools)), "calls": calls}
