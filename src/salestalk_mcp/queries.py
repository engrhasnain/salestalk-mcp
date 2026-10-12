"""The tool logic, as plain functions (easy to test and to call without MCP).

Every function takes a :class:`~salestalk_mcp.db.Database` and returns a
JSON-friendly ``dict``. Business rules live here:

* Currency: every amount is AED (Dune & Dhow invoices all customers in AED).
* Revenue: sum of ``orders.total_amount`` (= sum of ``order_items.line_total``)
  for orders whose status is NOT ``cancelled`` or ``returned``.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from psycopg import sql

from .db import Database, QueryError, Runner
from .ranges import DateRange, add_months, parse_month, parse_range, previous_period
from .sql_guard import guard_sql, wrap_with_limit

CURRENCY = "AED"
REVENUE_STATUSES_EXCLUDED = ("cancelled", "returned")
REVENUE_DEFINITION = "Sum of order totals in AED, excluding cancelled and returned orders."

_TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]{0,62}$")
_REVENUE_FILTER = "o.status NOT IN ('cancelled', 'returned')"


class ToolInputError(ValueError):
    """Invalid tool input (message is shown to the model)."""


# --------------------------------------------------------------------------- helpers


def _money(value: Any) -> float:
    return round(float(value or 0), 2)


def _pct(part: float, whole: float) -> float | None:
    return round(100.0 * part / whole, 1) if whole else None


def _change_pct(current: float, previous: float) -> float | None:
    return round(100.0 * (current - previous) / previous, 1) if previous else None


def _clamp(value: int | None, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    return max(minimum, min(maximum, int(value)))


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _resolve_city(run: Runner, city: str | None) -> tuple[int | None, str | None]:
    """Map a free-text city ('abu dhabi', 'Abu_Dhabi', 'DUBAI') to (city_id, canonical name)."""
    if city is None or not city.strip():
        return None, None
    rows = run.query("SELECT city_id, name FROM cities ORDER BY city_id").rows
    wanted = _norm(city)
    for row in rows:
        if _norm(row["name"]) == wanted:
            return row["city_id"], row["name"]
    names = ", ".join(r["name"] for r in rows)
    raise ToolInputError(f"Unknown city '{city}'. Available cities: {names}.")


def _resolve_category(run: Runner, category: str | None) -> str | None:
    """Case-insensitive category match; a unique partial match ('coffee') is accepted too."""
    if category is None or not category.strip():
        return None
    cats = [r["category"] for r in run.query("SELECT DISTINCT category FROM products ORDER BY 1").rows]
    wanted = _norm(category)
    exact = [c for c in cats if _norm(c) == wanted]
    if exact:
        return exact[0]
    partial = [c for c in cats if wanted and wanted in _norm(c)]
    if len(partial) == 1:
        return partial[0]
    raise ToolInputError(f"Unknown category '{category}'. Available categories: {', '.join(cats)}.")


# --------------------------------------------------------------------------- schema tools


def list_tables(db: Database) -> dict[str, Any]:
    result = db.query(
        """
        SELECT c.relname AS name,
               CASE c.relkind WHEN 'v' THEN 'view' WHEN 'm' THEN 'materialized view' ELSE 'table' END AS kind,
               CASE WHEN c.relkind IN ('r', 'p', 'm') AND c.reltuples >= 0
                    THEN c.reltuples::bigint END AS approx_rows,
               (SELECT count(*) FROM pg_attribute a
                 WHERE a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped) AS column_count,
               obj_description(c.oid, 'pg_class') AS description
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = %s
           AND c.relkind IN ('r', 'p', 'v', 'm')
           AND has_table_privilege(c.oid, 'SELECT')
         ORDER BY CASE c.relkind WHEN 'v' THEN 1 WHEN 'm' THEN 1 ELSE 0 END, c.relname
        """,
        (db.settings.schema,),
    )
    return {
        "schema": db.settings.schema,
        "table_count": result.row_count,
        "tables": result.rows,
        "note": "approx_rows comes from planner statistics. Use describe_table for columns and sample rows.",
    }


def describe_table(db: Database, table_name: str) -> dict[str, Any]:
    name = (table_name or "").strip().strip('"')
    if "." in name:
        schema_part, _, name = name.partition(".")
        if schema_part.strip('"') != db.settings.schema:
            raise ToolInputError(f"Only the '{db.settings.schema}' schema is exposed.")
        name = name.strip('"')
    if not _TABLE_NAME_RE.match(name):
        raise ToolInputError(f"'{table_name}' is not a valid table name.")

    with db.connect() as run:
        found = run.query(
            """
            SELECT c.oid::int8 AS oid, c.relname AS name,
                   CASE c.relkind WHEN 'v' THEN 'view' WHEN 'm' THEN 'materialized view' ELSE 'table' END AS kind,
                   CASE WHEN c.relkind IN ('r', 'p', 'm') AND c.reltuples >= 0
                        THEN c.reltuples::bigint END AS approx_rows,
                   obj_description(c.oid, 'pg_class') AS description
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = %(schema)s
               AND c.relkind IN ('r', 'p', 'v', 'm')
               AND has_table_privilege(c.oid, 'SELECT')
               AND (c.relname = %(name)s OR lower(c.relname) = lower(%(name)s))
             ORDER BY (c.relname = %(name)s) DESC
             LIMIT 1
            """,
            {"schema": db.settings.schema, "name": name},
        ).rows
        if not found:
            available = run.query(
                """
                SELECT string_agg(c.relname, ', ' ORDER BY c.relname) AS names
                  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = %s AND c.relkind IN ('r', 'p', 'v', 'm')
                   AND has_table_privilege(c.oid, 'SELECT')
                """,
                (db.settings.schema,),
            ).rows[0]["names"]
            raise ToolInputError(f"Table '{table_name}' not found. Available: {available}.")
        table = found[0]
        oid = table.pop("oid")

        columns = run.query(
            """
            SELECT a.attname AS name,
                   format_type(a.atttypid, a.atttypmod) AS type,
                   NOT a.attnotnull AS nullable,
                   pg_get_expr(d.adbin, d.adrelid) AS default,
                   col_description(a.attrelid, a.attnum) AS description
              FROM pg_attribute a
              LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
             WHERE a.attrelid = %s::oid AND a.attnum > 0 AND NOT a.attisdropped
             ORDER BY a.attnum
            """,
            (oid,),
        ).rows
        constraints = run.query(
            """
            SELECT conname AS name, contype AS type, pg_get_constraintdef(oid) AS definition
              FROM pg_constraint WHERE conrelid = %s::oid ORDER BY contype, conname
            """,
            (oid,),
        ).rows
        referenced_by = run.query(
            """
            SELECT conrelid::regclass::text AS table_name, pg_get_constraintdef(oid) AS definition
              FROM pg_constraint WHERE confrelid = %s::oid AND contype = 'f' ORDER BY 1
            """,
            (oid,),
        ).rows
        sample = run.query(
            sql.SQL("SELECT * FROM {}.{} LIMIT 3").format(
                sql.Identifier(db.settings.schema), sql.Identifier(table["name"])
            )
        ).rows

    kinds = {"p": "primary_key", "f": "foreign_keys", "u": "unique", "c": "checks"}
    grouped: dict[str, list[str]] = {v: [] for v in kinds.values()}
    for con in constraints:
        key = kinds.get(con["type"])
        if key:
            grouped[key].append(con["definition"])

    return {
        **table,
        "columns": columns,
        "primary_key": grouped["primary_key"][0] if grouped["primary_key"] else None,
        "foreign_keys": grouped["foreign_keys"],
        "unique_constraints": grouped["unique"],
        "check_constraints": grouped["checks"],
        "referenced_by": referenced_by,
        "sample_rows": sample,
    }


# --------------------------------------------------------------------------- sales tools


def query_sales(
    db: Database,
    month: str | None = "last_month",
    limit: int | None = 5,
    city: str | None = None,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """Monthly sales summary + top customers by revenue."""
    period = parse_month(month, today)
    limit = _clamp(limit, 5, 1, 50)

    # Comparison period: the previous calendar month (same number of days if month-to-date).
    prev_start = add_months(period.start, -1)
    if period.end.day == _last_day(period.end):
        prev = DateRange(prev_start, period.start - timedelta(days=1), prev_start.strftime("%Y-%m"))
    else:
        prev_end = min(prev_start + timedelta(days=period.days - 1), period.start - timedelta(days=1))
        prev = DateRange(prev_start, prev_end, prev_start.strftime("%Y-%m") + " (same days)")

    with db.connect() as run:
        city_id, city_name = _resolve_city(run, city)
        params = {
            "start": period.start,
            "end_x": period.end_exclusive,
            "prev_start": prev.start,
            "prev_end_x": prev.end_exclusive,
            "city_id": city_id,
            "limit": limit,
        }
        summary = run.query(
            f"""
            SELECT coalesce(sum(o.total_amount) FILTER (WHERE o.order_date >= %(start)s), 0) AS revenue,
                   count(*) FILTER (WHERE o.order_date >= %(start)s) AS orders,
                   count(DISTINCT o.customer_id) FILTER (WHERE o.order_date >= %(start)s) AS active_customers,
                   coalesce(sum(o.total_amount) FILTER (
                       WHERE o.order_date >= %(prev_start)s AND o.order_date < %(prev_end_x)s), 0) AS prev_revenue,
                   count(*) FILTER (
                       WHERE o.order_date >= %(prev_start)s AND o.order_date < %(prev_end_x)s) AS prev_orders
              FROM orders o
              JOIN customers c ON c.customer_id = o.customer_id
             WHERE {_REVENUE_FILTER}
               AND o.order_date >= %(prev_start)s AND o.order_date < %(end_x)s
               AND (%(city_id)s::int IS NULL OR c.city_id = %(city_id)s::int)
            """,
            params,
        ).rows[0]
        top = run.query(
            f"""
            SELECT c.company_name AS customer, ci.name AS city, c.segment,
                   count(*) AS orders, sum(o.total_amount) AS revenue,
                   max(o.order_date) AS last_order_date
              FROM orders o
              JOIN customers c ON c.customer_id = o.customer_id
              JOIN cities ci ON ci.city_id = c.city_id
             WHERE {_REVENUE_FILTER}
               AND o.order_date >= %(start)s AND o.order_date < %(end_x)s
               AND (%(city_id)s::int IS NULL OR c.city_id = %(city_id)s::int)
             GROUP BY c.customer_id, c.company_name, ci.name, c.segment
             ORDER BY revenue DESC, c.customer_id
             LIMIT %(limit)s
            """,
            params,
        ).rows

    revenue = _money(summary["revenue"])
    orders = int(summary["orders"])
    prev_revenue = _money(summary["prev_revenue"])
    return {
        "month": period.label,
        "period": period.to_dict(),
        "currency": CURRENCY,
        "city": city_name,
        "summary": {
            "revenue": revenue,
            "orders": orders,
            "active_customers": int(summary["active_customers"]),
            "avg_order_value": _money(revenue / orders) if orders else 0.0,
        },
        "previous_period": {
            **prev.to_dict(),
            "revenue": prev_revenue,
            "orders": int(summary["prev_orders"]),
            "revenue_change_pct": _change_pct(revenue, prev_revenue),
        },
        "top_customers": [
            {
                "rank": i,
                "customer": r["customer"],
                "city": r["city"],
                "segment": r["segment"],
                "orders": int(r["orders"]),
                "revenue": _money(r["revenue"]),
                "share_of_revenue_pct": _pct(_money(r["revenue"]), revenue),
                "last_order_date": r["last_order_date"],
            }
            for i, r in enumerate(top, start=1)
        ],
        "revenue_definition": REVENUE_DEFINITION,
    }


def revenue_by_city(
    db: Database,
    range: str | None = "this_quarter",  # noqa: A002 - public tool parameter name
    granularity: str | None = "total",
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """Revenue, orders and customers per city, with change vs. the previous equal-length period."""
    period = parse_range(range, today, default="this_quarter")
    prev = previous_period(period)
    gran = (granularity or "total").strip().lower()
    if gran not in {"total", "month"}:
        raise ToolInputError("granularity must be 'total' or 'month'.")

    params = {
        "start": period.start,
        "end_x": period.end_exclusive,
        "prev_start": prev.start,
        "prev_end_x": prev.end_exclusive,
    }
    with db.connect() as run:
        rows = run.query(
            f"""
            SELECT ci.name AS city, ci.country,
                   coalesce(sum(o.total_amount) FILTER (WHERE o.order_date >= %(start)s), 0) AS revenue,
                   count(o.order_id) FILTER (WHERE o.order_date >= %(start)s) AS orders,
                   count(DISTINCT o.customer_id) FILTER (WHERE o.order_date >= %(start)s) AS customers,
                   coalesce(sum(o.total_amount) FILTER (WHERE o.order_date < %(prev_end_x)s), 0) AS prev_revenue
              FROM cities ci
              LEFT JOIN customers c ON c.city_id = ci.city_id
              LEFT JOIN orders o
                     ON o.customer_id = c.customer_id
                    AND {_REVENUE_FILTER}
                    AND o.order_date >= %(prev_start)s AND o.order_date < %(end_x)s
             GROUP BY ci.city_id, ci.name, ci.country
             ORDER BY revenue DESC, ci.name
            """,
            params,
        ).rows
        monthly_rows = []
        if gran == "month":
            monthly_rows = run.query(
                f"""
                SELECT to_char(date_trunc('month', o.order_date), 'YYYY-MM') AS month,
                       ci.name AS city, sum(o.total_amount) AS revenue
                  FROM orders o
                  JOIN customers c ON c.customer_id = o.customer_id
                  JOIN cities ci ON ci.city_id = c.city_id
                 WHERE {_REVENUE_FILTER}
                   AND o.order_date >= %(start)s AND o.order_date < %(end_x)s
                 GROUP BY 1, 2
                 ORDER BY 1, 2
                """,
                params,
            ).rows

    total = sum(_money(r["revenue"]) for r in rows)
    prev_total = sum(_money(r["prev_revenue"]) for r in rows)
    cities = []
    for r in rows:
        rev, n = _money(r["revenue"]), int(r["orders"])
        cities.append(
            {
                "city": r["city"],
                "country": r["country"],
                "revenue": rev,
                "orders": n,
                "customers": int(r["customers"]),
                "avg_order_value": _money(rev / n) if n else 0.0,
                "share_pct": _pct(rev, total),
                "revenue_previous_period": _money(r["prev_revenue"]),
                "change_pct": _change_pct(rev, _money(r["prev_revenue"])),
            }
        )

    result: dict[str, Any] = {
        "range": period.to_dict(),
        "previous_period": prev.to_dict(),
        "currency": CURRENCY,
        "total_revenue": round(total, 2),
        "total_change_pct": _change_pct(total, prev_total),
        "cities": cities,
        "revenue_definition": REVENUE_DEFINITION,
    }
    if gran == "month":
        city_names = [c["city"] for c in cities]
        series: dict[str, dict[str, Any]] = {}
        for r in monthly_rows:
            series.setdefault(r["month"], {"month": r["month"], **{c: 0.0 for c in city_names}})
            series[r["month"]][r["city"]] = _money(r["revenue"])
        result["monthly"] = list(series.values())
    return result


def top_products(
    db: Database,
    range: str | None = "last_30_days",  # noqa: A002 - public tool parameter name
    limit: int | None = 10,
    category: str | None = None,
    city: str | None = None,
    sort_by: str | None = "revenue",
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """Best-selling products by revenue or units, with gross margin."""
    period = parse_range(range, today, default="last_30_days")
    limit = _clamp(limit, 10, 1, 50)
    sort = (sort_by or "revenue").strip().lower()
    if sort not in {"revenue", "units"}:
        raise ToolInputError("sort_by must be 'revenue' or 'units'.")

    with db.connect() as run:
        cat = _resolve_category(run, category)
        city_id, city_name = _resolve_city(run, city)
        query = sql.SQL(
            """
            SELECT p.name AS product, p.sku, p.category,
                   sum(oi.quantity) AS units,
                   count(DISTINCT oi.order_id) AS orders,
                   sum(oi.line_total) AS revenue,
                   sum(oi.quantity * p.unit_cost) AS cost,
                   sum(sum(oi.line_total)) OVER () AS total_revenue
              FROM order_items oi
              JOIN orders o ON o.order_id = oi.order_id
              JOIN products p ON p.product_id = oi.product_id
              JOIN customers c ON c.customer_id = o.customer_id
             WHERE o.status NOT IN ('cancelled', 'returned')
               AND o.order_date >= %(start)s AND o.order_date < %(end_x)s
               AND (%(category)s::text IS NULL OR p.category = %(category)s::text)
               AND (%(city_id)s::int IS NULL OR c.city_id = %(city_id)s::int)
             GROUP BY p.product_id, p.name, p.sku, p.category
             ORDER BY {sort} DESC, p.product_id
             LIMIT %(limit)s
            """
        ).format(sort=sql.Identifier(sort))
        rows = run.query(
            query,
            {
                "start": period.start,
                "end_x": period.end_exclusive,
                "category": cat,
                "city_id": city_id,
                "limit": limit,
            },
        ).rows

    total = _money(rows[0]["total_revenue"]) if rows else 0.0
    products = []
    for i, r in enumerate(rows, start=1):
        rev, cost = _money(r["revenue"]), _money(r["cost"])
        products.append(
            {
                "rank": i,
                "product": r["product"],
                "sku": r["sku"],
                "category": r["category"],
                "units": int(r["units"]),
                "orders": int(r["orders"]),
                "revenue": rev,
                "share_pct": _pct(rev, total),
                "gross_margin_pct": _pct(rev - cost, rev),
            }
        )
    return {
        "range": period.to_dict(),
        "currency": CURRENCY,
        "sort_by": sort,
        "category": cat,
        "city": city_name,
        "total_revenue_in_scope": total,
        "products": products,
        "revenue_definition": REVENUE_DEFINITION,
    }


# --------------------------------------------------------------------------- free-form SQL


def run_sql(db: Database, query: str, limit: int | None = None) -> dict[str, Any]:
    """Run one guarded, read-only SELECT with a hard row cap."""
    settings = db.settings
    cap = _clamp(limit, settings.default_rows, 1, settings.max_rows)
    guarded = guard_sql(query)  # raises SqlGuardError
    result = db.query(wrap_with_limit(guarded.sql, cap + 1), max_rows=cap)
    out: dict[str, Any] = {
        "columns": result.columns,
        "rows": result.rows,
        "row_count": result.row_count,
        "truncated": result.truncated,
        "row_limit": cap,
        "elapsed_ms": result.elapsed_ms,
        "sql": guarded.sql,
    }
    if result.truncated:
        out["note"] = f"Only the first {cap} rows are shown. Aggregate or filter for a complete answer."
    return out


def _last_day(d: date) -> int:
    return (add_months(d.replace(day=1), 1) - timedelta(days=1)).day


__all__ = [
    "CURRENCY",
    "QueryError",
    "ToolInputError",
    "describe_table",
    "list_tables",
    "query_sales",
    "revenue_by_city",
    "run_sql",
    "top_products",
]
