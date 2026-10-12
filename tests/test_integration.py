"""Integration tests against the seeded demo database.

Start it with ``docker compose up -d`` first. Every test here is skipped automatically
if the database can't be reached (see conftest.py).
"""

from __future__ import annotations

import pytest

from salestalk_mcp import queries
from salestalk_mcp.db import Database, QueryError
from salestalk_mcp.queries import ToolInputError
from salestalk_mcp.ranges import RangeError
from salestalk_mcp.sql_guard import SqlGuardError

pytestmark = pytest.mark.integration

CITIES = {"Dubai", "Abu Dhabi", "Riyadh", "Jeddah"}


# --------------------------------------------------------------------------- seed sanity


def test_seed_volume(db: Database) -> None:
    row = db.query(
        """
        SELECT (SELECT count(*) FROM customers) AS customers,
               (SELECT count(*) FROM products) AS products,
               (SELECT count(*) FROM orders) AS orders,
               (SELECT count(*) FROM order_items) AS items,
               (SELECT count(*) FROM cities) AS cities
        """
    ).rows[0]
    assert 250 <= row["customers"] <= 500
    assert row["products"] >= 30
    assert 4500 <= row["orders"] <= 5500
    assert row["items"] > row["orders"]
    assert row["cities"] == 4


def test_seed_is_relative_to_today(db: Database) -> None:
    """'last month', 'this quarter' and 'last 30 days' must have data when the demo is recorded."""
    last_month = queries.query_sales(db, "last_month")
    assert last_month["summary"]["orders"] > 200, "Re-seed: docker compose down -v && docker compose up -d"
    assert queries.revenue_by_city(db, "this_quarter")["total_revenue"] > 0
    assert queries.top_products(db, "last_30_days")["products"]


def test_order_totals_match_lines(db: Database) -> None:
    mismatches = db.query(
        """
        SELECT count(*) AS n FROM orders o
          JOIN (SELECT order_id, sum(line_total) AS s FROM order_items GROUP BY order_id) t USING (order_id)
         WHERE o.total_amount <> t.s
        """
    ).rows[0]["n"]
    assert mismatches == 0


# --------------------------------------------------------------------------- schema tools


def test_list_tables(db: Database) -> None:
    result = queries.list_tables(db)
    names = {t["name"] for t in result["tables"]}
    assert {"cities", "customers", "products", "orders", "order_items", "dataset_info", "v_sales"} <= names
    orders = next(t for t in result["tables"] if t["name"] == "orders")
    assert orders["kind"] == "table"
    assert orders["description"]
    assert next(t for t in result["tables"] if t["name"] == "v_sales")["kind"] == "view"


def test_describe_table(db: Database) -> None:
    result = queries.describe_table(db, "orders")
    cols = {c["name"]: c for c in result["columns"]}
    assert {"order_id", "customer_id", "order_date", "status", "total_amount"} <= set(cols)
    assert cols["total_amount"]["type"].startswith("numeric")
    assert "PRIMARY KEY (order_id)" in result["primary_key"]
    assert any("REFERENCES customers" in fk for fk in result["foreign_keys"])
    assert any(r["table_name"] == "order_items" for r in result["referenced_by"])
    assert len(result["sample_rows"]) == 3


def test_describe_table_is_case_insensitive_and_accepts_schema(db: Database) -> None:
    assert queries.describe_table(db, "public.Customers")["name"] == "customers"


@pytest.mark.parametrize("bad", ["nope", "orders; DROP TABLE orders", "pg_authid", "information_schema.tables", ""])
def test_describe_table_rejects_unknown_or_unsafe(db: Database, bad: str) -> None:
    with pytest.raises(ToolInputError):
        queries.describe_table(db, bad)


# --------------------------------------------------------------------------- sales tools


def test_query_sales_last_month(db: Database) -> None:
    result = queries.query_sales(db, "last_month", 5)
    assert result["currency"] == "AED"
    top = result["top_customers"]
    assert len(top) == 5
    assert [c["rank"] for c in top] == [1, 2, 3, 4, 5]
    assert all(top[i]["revenue"] >= top[i + 1]["revenue"] for i in range(4))
    assert {c["city"] for c in top} <= CITIES
    s = result["summary"]
    assert s["revenue"] > 0 and s["orders"] > 0
    assert s["avg_order_value"] == pytest.approx(s["revenue"] / s["orders"], abs=0.01)
    assert result["previous_period"]["revenue"] > 0
    assert result["previous_period"]["revenue_change_pct"] is not None


def test_query_sales_matches_raw_sql(db: Database) -> None:
    result = queries.query_sales(db, "last_month", 3)
    start, end = result["period"]["start"], result["period"]["end"]
    raw = db.query(
        """
        SELECT coalesce(sum(total_amount), 0) AS revenue, count(*) AS orders FROM orders
         WHERE status NOT IN ('cancelled', 'returned') AND order_date BETWEEN %s AND %s
        """,
        (start, end),
    ).rows[0]
    assert result["summary"]["revenue"] == pytest.approx(raw["revenue"], abs=0.01)
    assert result["summary"]["orders"] == raw["orders"]


def test_query_sales_city_filter(db: Database) -> None:
    result = queries.query_sales(db, "last_month", 10, city="abu dhabi")
    assert result["city"] == "Abu Dhabi"
    assert {c["city"] for c in result["top_customers"]} == {"Abu Dhabi"}


def test_query_sales_explicit_month_and_this_month(db: Database) -> None:
    lm = queries.query_sales(db, "last_month")
    explicit = queries.query_sales(db, lm["month"])
    assert explicit["summary"] == lm["summary"]
    this_month = queries.query_sales(db, "this_month")
    assert this_month["period"]["start"].endswith("-01")
    assert this_month["month"] > lm["month"]


def test_query_sales_bad_input(db: Database) -> None:
    with pytest.raises(RangeError):
        queries.query_sales(db, "septembre")
    with pytest.raises(ToolInputError, match="Available cities"):
        queries.query_sales(db, "last_month", city="Paris")


def test_revenue_by_city_this_quarter(db: Database) -> None:
    result = queries.revenue_by_city(db, "this_quarter")
    cities = {c["city"]: c for c in result["cities"]}
    assert set(cities) == CITIES
    assert result["total_revenue"] == pytest.approx(sum(c["revenue"] for c in cities.values()), abs=0.05)
    assert cities["Dubai"]["revenue"] > 0 and cities["Riyadh"]["revenue"] > 0
    assert sum(c["share_pct"] for c in cities.values()) == pytest.approx(100, abs=0.5)
    revenues = [c["revenue"] for c in result["cities"]]
    assert revenues == sorted(revenues, reverse=True)


def test_revenue_by_city_monthly_series(db: Database) -> None:
    result = queries.revenue_by_city(db, "last_12_months", "month")
    monthly = result["monthly"]
    assert 12 <= len(monthly) <= 13
    assert all(set(CITIES) <= set(m) for m in monthly)
    total = sum(m[c] for m in monthly for c in CITIES)
    assert total == pytest.approx(result["total_revenue"], rel=1e-6)


def test_revenue_by_city_explicit_range(db: Database) -> None:
    lm = queries.query_sales(db, "last_month")
    rng = f"{lm['period']['start']}..{lm['period']['end']}"
    result = queries.revenue_by_city(db, rng)
    assert result["total_revenue"] == pytest.approx(lm["summary"]["revenue"], abs=0.05)


def test_revenue_by_city_bad_granularity(db: Database) -> None:
    with pytest.raises(ToolInputError):
        queries.revenue_by_city(db, "ytd", "weekly")


def test_top_products(db: Database) -> None:
    result = queries.top_products(db, "last_30_days", 5)
    products = result["products"]
    assert len(products) == 5
    assert all(products[i]["revenue"] >= products[i + 1]["revenue"] for i in range(4))
    assert all(0 < p["gross_margin_pct"] < 100 for p in products)


def test_top_products_filters_and_sort(db: Database) -> None:
    by_units = queries.top_products(db, "ytd", 5, category="coffee", sort_by="units")
    assert by_units["category"] == "Coffee & Tea"
    assert {p["category"] for p in by_units["products"]} == {"Coffee & Tea"}
    units = [p["units"] for p in by_units["products"]]
    assert units == sorted(units, reverse=True)
    riyadh = queries.top_products(db, "last_quarter", 3, city="Riyadh")
    assert riyadh["city"] == "Riyadh" and riyadh["products"]


def test_top_products_bad_input(db: Database) -> None:
    with pytest.raises(ToolInputError, match="Available categories"):
        queries.top_products(db, "ytd", category="Cars")
    with pytest.raises(ToolInputError):
        queries.top_products(db, "ytd", sort_by="profit; DROP TABLE x")


# --------------------------------------------------------------------------- run_sql


def test_run_sql_select(db: Database) -> None:
    result = queries.run_sql(db, "SELECT name, country FROM cities ORDER BY city_id")
    assert result["columns"] == ["name", "country"]
    assert [r["name"] for r in result["rows"]] == ["Dubai", "Abu Dhabi", "Riyadh", "Jeddah"]
    assert result["truncated"] is False


def test_run_sql_row_cap_overrides_user_limit(db: Database) -> None:
    result = queries.run_sql(db, "SELECT * FROM orders LIMIT 100000", limit=7)
    assert result["row_count"] == 7
    assert result["truncated"] is True
    assert "note" in result


def test_run_sql_server_max_rows(db: Database) -> None:
    result = queries.run_sql(db, "SELECT order_id FROM orders", limit=10_000_000)
    assert result["row_limit"] == db.settings.max_rows
    assert result["row_count"] == db.settings.max_rows


def test_run_sql_cte_and_view(db: Database) -> None:
    result = queries.run_sql(
        db,
        """
        WITH m AS (SELECT city, sum(revenue) AS revenue FROM v_sales GROUP BY city)
        SELECT city, round(revenue) AS revenue FROM m ORDER BY revenue DESC
        """,
    )
    assert {r["city"] for r in result["rows"]} == CITIES


def test_run_sql_duplicate_column_names(db: Database) -> None:
    result = queries.run_sql(
        db, "SELECT o.order_id, i.order_id FROM orders o JOIN order_items i USING (order_id) LIMIT 1"
    )
    assert result["columns"] == ["order_id", "order_id_2"]


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM orders",
        "SELECT 1; DROP TABLE orders",
        "WITH d AS (DELETE FROM orders RETURNING *) SELECT * FROM d",
        "SELECT pg_sleep(30)",
        "UPDATE products SET unit_price = 0",
    ],
)
def test_run_sql_guard_blocks_writes(db: Database, sql: str) -> None:
    with pytest.raises(SqlGuardError):
        queries.run_sql(db, sql)


def test_run_sql_reports_sql_errors(db: Database) -> None:
    with pytest.raises(QueryError, match="does not exist"):
        queries.run_sql(db, "SELECT no_such_column FROM orders")


# --------------------------------------------------------------------------- database-level defenses
# These bypass the guard on purpose: the database itself must refuse writes.


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO cities VALUES (99, 'Doha', 'Qatar', 'QA')",
        "UPDATE products SET unit_price = 1",
        "DELETE FROM order_items",
        "CREATE TABLE hacked (i int)",
        "DROP TABLE orders",
        "TRUNCATE orders",
    ],
)
def test_database_rejects_writes_even_without_guard(db: Database, sql: str) -> None:
    with pytest.raises(QueryError):
        db.query(sql)


def test_role_has_select_only(db: Database) -> None:
    row = db.query(
        """
        SELECT current_user AS who,
               has_table_privilege('orders', 'SELECT') AS can_select,
               has_table_privilege('orders', 'INSERT') AS can_insert,
               has_table_privilege('orders', 'UPDATE') AS can_update,
               has_table_privilege('orders', 'DELETE') AS can_delete,
               has_schema_privilege('public', 'CREATE') AS can_create,
               (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) AS is_superuser,
               current_setting('transaction_read_only') AS tx_read_only
        """
    ).rows[0]
    assert row["can_select"] is True
    assert not (row["can_insert"] or row["can_update"] or row["can_delete"] or row["can_create"])
    assert row["is_superuser"] is False
    assert row["tx_read_only"] == "on"


def test_statement_timeout_cancels_slow_queries(db: Database) -> None:
    with pytest.raises(QueryError, match="timeout"):
        db.query("SELECT pg_sleep(3)", statement_timeout_ms=300)


def test_multiple_statements_rejected_by_protocol(db: Database) -> None:
    with pytest.raises(QueryError):
        db.query("SELECT 1; SELECT 2")
