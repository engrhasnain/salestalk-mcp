"""SalesTalk Console: the web API talks to the real server over MCP (stdio) and returns frames.

The non-integration tests need no database: tools/list and SQL-guard refusals never touch it.
"""

from __future__ import annotations

import sys

import pytest
from mcp import StdioServerParameters
from starlette.testclient import TestClient

from salestalk_mcp.console import allowed_hosts_for, create_app, main
from salestalk_mcp.console.bridge import McpBridge
from salestalk_mcp.console.overview import OVERVIEW_CALLS, build_data

EXPECTED_TOOLS = {"list_tables", "describe_table", "query_sales", "revenue_by_city", "top_products", "run_sql"}


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(create_app()) as c:
        yield c


def call(client: TestClient, name: str, **arguments: object) -> dict:
    return client.post("/api/call", json={"name": name, "arguments": arguments}).json()


# --------------------------------------------------------------------------- no database needed


def test_index_is_served_with_honest_label(client: TestClient) -> None:
    res = client.get("/")
    assert res.status_code == 200
    assert "SalesTalk Console" in res.text
    assert "the same MCP tools Claude uses" in res.text
    assert "Muhammad Hasnain Pirzada" in res.text
    for asset in ("/console.css", "/js/main.js", "/fonts/space-grotesk-latin-wght.woff2", "/favicon.svg"):
        assert client.get(asset).status_code == 200, asset


def test_tools_come_from_tools_list(client: TestClient) -> None:
    res = client.get("/api/tools")
    assert res.status_code == 200
    body = res.json()
    tools = {t["name"]: t for t in body["tools"]}
    assert set(tools) == EXPECTED_TOOLS
    for tool in tools.values():
        assert tool["title"] and tool["description"]
        assert tool["inputSchema"]["type"] == "object"
        assert tool["annotations"]["readOnlyHint"] is True
        assert tool["annotations"]["destructiveHint"] is False
    assert tools["run_sql"]["inputSchema"]["required"] == ["query"]
    session = body["session"]
    assert session["connected"] is True
    assert session["transport"] == "stdio"
    assert session["server"]["name"] == "salestalk"
    assert session["protocol_version"]
    # the handshake frames of the session are kept too
    assert any(f["message"].get("method") == "tools/list" for f in body["session_frames"])


def test_refused_call_returns_the_real_jsonrpc_frames(client: TestClient) -> None:
    res = client.post("/api/call", json={"name": "run_sql", "arguments": {"query": "DELETE FROM orders"}})
    assert res.status_code == 200
    out = res.json()
    assert out["ok"] is False and out["is_error"] is True
    assert "Only SELECT queries are allowed" in out["error"]
    assert out["result"] is None
    assert out["latency_ms"] > 0
    frames = out["frames"]
    assert [f["direction"] for f in frames] == ["out", "in"]
    request, response = frames[0]["message"], frames[1]["message"]
    assert request["jsonrpc"] == "2.0" and request["method"] == "tools/call"
    assert request["params"]["name"] == "run_sql"
    assert request["params"]["arguments"] == {"query": "DELETE FROM orders"}
    assert response["id"] == request["id"]
    assert response["result"]["isError"] is True
    assert all(f["bytes"] > 0 for f in frames)
    assert frames[1]["t_ms"] >= frames[0]["t_ms"]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("DROP TABLE orders", "Only SELECT"),
        ("SELECT 1; DROP TABLE orders", "single statement"),
        ("SELECT pg_sleep(10)", "pg_sleep"),
        ("SELECT * INTO orders_copy FROM orders", "INTO"),
    ],
)
def test_break_it_attacks_are_refused_by_the_guard(client: TestClient, query: str, expected: str) -> None:
    out = client.post("/api/call", json={"name": "run_sql", "arguments": {"query": query}}).json()
    assert out["ok"] is False
    assert expected in out["error"]


def test_invalid_arguments_come_back_as_a_tool_error(client: TestClient) -> None:
    out = client.post("/api/call", json={"name": "query_sales", "arguments": {"limit": 0}}).json()
    assert out["ok"] is False
    assert "limit" in out["error"]


def test_call_request_validation(client: TestClient) -> None:
    assert client.post("/api/call", content="name=run_sql", headers={"Content-Type": "text/plain"}).status_code == 415
    bad_json = client.post("/api/call", content="{not json", headers={"Content-Type": "application/json"})
    assert bad_json.status_code == 400
    assert client.post("/api/call", json=["run_sql"]).status_code == 400
    assert client.post("/api/call", json={"arguments": {}}).status_code == 400
    assert client.post("/api/call", json={"name": "run_sql", "arguments": "DELETE"}).status_code == 400
    missing = client.post("/api/call", json={"name": "drop_everything"})
    assert missing.status_code == 404
    assert "Unknown tool" in missing.json()["error"]
    assert client.get("/api/call").status_code in (404, 405)  # the static mount answers non-POST


def test_health_reports_the_session(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["connected"] is True
    assert body["command"].endswith("-m salestalk_mcp")
    assert body["frames_seen"] > 0


def test_host_header_is_checked_when_bound_to_loopback() -> None:
    hosts = allowed_hosts_for("127.0.0.1")
    assert hosts is not None and "localhost" in hosts
    assert allowed_hosts_for("0.0.0.0") is None
    assert "salestalk.internal" in (allowed_hosts_for("salestalk.internal") or [])
    with TestClient(create_app(allowed_hosts=hosts), base_url="http://evil.example") as c:
        assert c.get("/api/health").status_code == 400
    with TestClient(create_app(allowed_hosts=hosts), base_url="http://127.0.0.1:8770") as c:
        assert c.get("/api/health").status_code == 200


def test_bridge_reconnects_after_losing_the_session() -> None:
    bridge = McpBridge()
    with TestClient(create_app(bridge)) as c:
        first = c.post("/api/call", json={"name": "run_sql", "arguments": {"query": "DROP TABLE x"}}).json()
        assert first["ok"] is False
        bridge.mark_lost()  # as if the server process had died
        again = c.post("/api/call", json={"name": "run_sql", "arguments": {"query": "DROP TABLE x"}}).json()
        assert again["ok"] is False and "Only SELECT" in again["error"]
        assert bridge.connections == 2


def test_unreachable_server_fails_cleanly() -> None:
    dead = StdioServerParameters(command=sys.executable, args=["-c", "pass"])
    with TestClient(create_app(McpBridge(dead, connect_wait_s=1.5))) as c:
        res = c.get("/api/tools")
        assert res.status_code == 503
        assert "not connected" in res.json()["error"]
        assert c.post("/api/call", json={"name": "run_sql", "arguments": {"query": "SELECT 1"}}).status_code == 503


def test_console_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "salestalk-console" in capsys.readouterr().out


def test_overview_calls_only_use_mcp_tools() -> None:
    assert {tool for _, tool, _ in OVERVIEW_CALLS} <= EXPECTED_TOOLS
    assert OVERVIEW_CALLS[-1][1:] == ("run_sql", {"query": "DELETE FROM orders"})  # the refused feed entry
    empty = build_data({}, tool_count=6)
    assert empty["stats"] is None and empty["customers"] == [] and empty["cities"] == []


# --------------------------------------------------------------------------- with the seeded database


@pytest.mark.integration
def test_query_sales_over_mcp(client: TestClient, db: object) -> None:
    out = call(client, "query_sales", month="last_month", limit=3)
    assert out["ok"] is True, out["error"]
    assert len(out["result"]["top_customers"]) == 3
    response = out["frames"][-1]["message"]
    assert response["result"]["structuredContent"] == out["result"]


@pytest.mark.integration
def test_valid_select_is_stopped_by_the_read_only_role(client: TestClient, db: object) -> None:
    out = call(client, "run_sql", query="SELECT rolname, rolpassword FROM pg_authid")
    assert out["ok"] is False
    assert "Permission denied for the read-only role" in out["error"]


@pytest.mark.integration
def test_row_cap_applies_over_mcp(client: TestClient, db: object) -> None:
    out = client.post("/api/call", json={"name": "run_sql", "arguments": {"query": "SELECT * FROM order_items"}}).json()
    assert out["ok"] is True
    assert out["result"]["truncated"] is True
    assert out["result"]["row_count"] == out["result"]["row_limit"]


@pytest.mark.integration
def test_overview_is_built_from_tool_calls(client: TestClient, db: object) -> None:
    res = client.get("/api/overview")
    assert res.status_code == 200
    body = res.json()
    calls = body["calls"]
    assert [c["tool"] for c in calls] == [tool for _, tool, _ in OVERVIEW_CALLS]
    assert all(c["ok"] for c in calls[:-1])
    assert calls[-1]["ok"] is False and "Only SELECT" in calls[-1]["error"]
    data = body["data"]
    assert data["stats"]["customers"] == len(data["customers"]) > 0
    assert data["stats"]["tools"] == 6
    assert data["stats"]["months"] >= 12
    assert {c["city"] for c in data["cities"]} == {"Dubai", "Abu Dhabi", "Riyadh", "Jeddah"}
    assert len(data["last_month"]["top_customers"]) == 5
    assert "rows" not in calls[5]["result"]  # customer rows are delivered once, in data.customers
