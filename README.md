<p align="center">
  <img src="docs/banner.svg" alt="SalesTalk MCP: chat with your database, right inside Claude" width="100%">
</p>

<p align="center">
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-5360F0?style=flat-square&labelColor=0C0E1A">
  <img alt="MCP SDK" src="https://img.shields.io/badge/MCP-official%20Python%20SDK-5360F0?style=flat-square&labelColor=0C0E1A">
  <img alt="PostgreSQL 16" src="https://img.shields.io/badge/PostgreSQL-16-5360F0?style=flat-square&labelColor=0C0E1A">
  <img alt="Docker" src="https://img.shields.io/badge/docker-compose-5360F0?style=flat-square&labelColor=0C0E1A">
  <img alt="Read-only" src="https://img.shields.io/badge/access-read--only-047857?style=flat-square&labelColor=0C0E1A">
  <img alt="MIT license" src="https://img.shields.io/badge/license-MIT-5F6288?style=flat-square&labelColor=0C0E1A">
</p>

# SalesTalk MCP

**Ask your sales database questions in plain English, right inside Claude.**
"Who were our top 5 customers last month?" goes in; real numbers from PostgreSQL come out, through a custom
[Model Context Protocol](https://modelcontextprotocol.io) server that is **read-only by design**.

<p align="center">
  <img src="docs/demo.gif" alt="SalesTalk MCP answering four questions with live tool calls" width="85%">
  <br><sub>Real tool calls against the seeded demo database, rendered by <code>scripts/make_demo_gif.py</code>.
  For the Claude Desktop recording, follow <a href="docs/DEMO_SCRIPT.md">docs/DEMO_SCRIPT.md</a>.</sub>
</p>

---

## What it does

- **A custom MCP server** written in Python with the official [`mcp` SDK](https://github.com/modelcontextprotocol/python-sdk). It gives Claude six tools: `list_tables`, `describe_table`, `query_sales`, `revenue_by_city`, `top_products` and a guarded `run_sql`.
- **A sample database that is ready to demo.** `docker compose up` starts PostgreSQL 16 seeded with **Dune & Dhow Trading Co.**, a *fictional* Gulf trading company: 320 B2B customers in Dubai, Abu Dhabi, Riyadh and Jeddah, 36 products (dates, coffee & tea, spices, textiles, electronics, fragrance), **5,000 orders** and about 12,000 order lines.
- **Dates are always fresh.** Orders cover the 12 full months before the current month plus the current month to date, *counted from the day you seed*. "Last month", "this quarter" and "last 30 days" always return data when you record a demo.
- **Friendly inputs.** Ranges like `last_month`, `this_quarter`, `last_30_days`, `ytd`, `last_12_months` or `2026-01-01..2026-03-31`. Results come back as clean JSON that Claude turns into tables and charts.
- **Safe by default.** A SELECT-only Postgres role, read-only transactions, a statement timeout, a SQL guard and a hard row cap. See [Safety notes](#safety-notes-read-only-by-design).
- **A console that shows every call.** `uv run salestalk-console` opens the [SalesTalk Console](#salestalk-console): it talks to the server over real MCP and shows the exact tool, arguments, JSON-RPC frames and result Claude would get.

## Architecture

```mermaid
flowchart LR
    U(["You"]) -->|"plain English"| C["Claude Desktop"]

    subgraph S["SalesTalk MCP server (Python, MCP SDK)"]
        direction TB
        T["6 tools<br/>query_sales, revenue_by_city,<br/>top_products, run_sql, ..."] --> R["Range parser<br/>last_month, ytd, a..b"]
        T --> G["SQL guard<br/>single SELECT only"]
        R --> D["DB layer<br/>READ ONLY txn, timeout,<br/>row cap, rollback"]
        G --> D
    end

    C <-->|"MCP over stdio<br/>(or streamable HTTP)"| S
    D -->|"role: salestalk_ro<br/>(SELECT only)"| P[("PostgreSQL 16<br/>Docker, port 5433")]
    A["Admin user"] -.->|"schema + seed only"| P
```

How one question flows:

```mermaid
sequenceDiagram
    actor You
    participant Claude as Claude Desktop
    participant MCP as SalesTalk MCP
    participant PG as PostgreSQL (read-only role)
    You->>Claude: Who were our top 5 customers last month?
    Claude->>MCP: call query_sales(month="last_month", limit=5)
    MCP->>MCP: "last_month" resolves to 2026-09-01..2026-09-30
    MCP->>PG: BEGIN READ ONLY, then 2 parameterized SELECTs
    PG-->>MCP: rows
    MCP->>PG: ROLLBACK
    MCP-->>Claude: JSON (summary, change vs previous month, top customers)
    Claude-->>You: A ranked table plus a short insight
```

## Quick start

**You need:** [Docker](https://docs.docker.com/get-docker/) and [uv](https://docs.astral.sh/uv/getting-started/installation/) (it installs Python 3.12 for you).

```bash
git clone https://github.com/engrhasnain/salestalk-mcp.git
cd salestalk-mcp

# 1. (optional) copy the env file; the defaults work out of the box
cp .env.example .env

# 2. Start PostgreSQL. The first start creates the schema, seeds the data and creates the read-only role.
docker compose up -d
docker compose ps          # wait for "healthy" (about 15 to 30 s on first start)

# 3. Install and run a smoke test: it starts the MCP server over stdio and calls every tool
uv sync
uv run python scripts/smoke_test.py
```

You should see something like:

```text
Server exposes 6 tools: list_tables, describe_table, query_sales, revenue_by_city, top_products, run_sql

[OK] query_sales(month='last_month', limit=5)
    2026-09: AED 1,688,801.30 from 409 orders (19.7% vs previous month)
    #1 Al Fajr Import & Export (Dubai) AED 58,645.45
    ...
[OK (rejected as expected)] run_sql(query='DELETE FROM orders')
    Error executing tool run_sql: Only SELECT queries are allowed (query starts with 'DELETE').
```

Then [connect it to Claude Desktop](#connect-to-claude-desktop).

> **Refresh the dates before you record a demo.** The seed is relative to the day it runs. To re-seed:
> `docker compose down -v && docker compose up -d` (fresh volume), or keep the volume and run
> `docker compose exec db psql -U salestalk_admin -d salestalk -f /docker-entrypoint-initdb.d/02_seed.sql`.

### No Docker? Use a local PostgreSQL

Any PostgreSQL 14+ works. These steps start a **separate, throwaway** server in the project folder on port 5435,
so an existing PostgreSQL install is left alone. They work in Git Bash on Windows, and in any macOS/Linux shell:

```bash
export PATH="/c/Program Files/PostgreSQL/17/bin:$PATH"   # Windows (Git Bash). Skip if psql is already on PATH.

initdb -D .pgdata -U salestalk_admin --auth=trust -E UTF8 --locale=C     # local demo only: trust auth on 127.0.0.1
pg_ctl -D .pgdata -o "-p 5435 -c listen_addresses=127.0.0.1 -c timezone=Asia/Dubai" -l .pgdata.log start

export PGHOST=127.0.0.1 PGPORT=5435 PGUSER=salestalk_admin
createdb salestalk
psql -v ON_ERROR_STOP=1 -d salestalk -f db/init/01_schema.sql
psql -v ON_ERROR_STOP=1 -d salestalk -f db/init/02_seed.sql
POSTGRES_USER=salestalk_admin POSTGRES_DB=salestalk sh db/init/03_readonly_role.sh
```

Then set `SALESTALK_DATABASE_URL=postgresql://salestalk_ro:salestalk_ro_password@127.0.0.1:5435/salestalk` in `.env`
and run the smoke test. Stop the server with `pg_ctl -D .pgdata stop`. `.pgdata/` is git-ignored. In Git Bash,
`pg_ctl ... start` can leave the prompt waiting even though the server is up: check `.pgdata.log` for
"ready to accept connections" and press Enter or open a new terminal.

## Connect to Claude Desktop

Open **Claude Desktop → Settings → Developer → Edit Config**. That opens:

| OS | Config file |
|---|---|
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |

**Windows**

```json
{
  "mcpServers": {
    "salestalk": {
      "command": "uv",
      "args": ["run", "--directory", "C:\\Users\\you\\code\\salestalk-mcp", "salestalk-mcp"],
      "env": {
        "SALESTALK_DATABASE_URL": "postgresql://salestalk_ro:salestalk_ro_password@127.0.0.1:5433/salestalk"
      }
    }
  }
}
```

**macOS**

```json
{
  "mcpServers": {
    "salestalk": {
      "command": "uv",
      "args": ["run", "--directory", "/Users/you/code/salestalk-mcp", "salestalk-mcp"],
      "env": {
        "SALESTALK_DATABASE_URL": "postgresql://salestalk_ro:salestalk_ro_password@127.0.0.1:5433/salestalk"
      }
    }
  }
}
```

Quit Claude Desktop completely (tray icon or menu bar, not just the window) and reopen it. The tools menu now shows **salestalk** with 6 tools.

<details>
<summary><b>Claude can't find <code>uv</code>?</b></summary>

Claude Desktop doesn't always inherit your shell's `PATH`. Use the full path to uv as `"command"`:
run `where uv` (Windows) or `which uv` (macOS). Typical values are `C:\\Users\\you\\.local\\bin\\uv.exe` and
`/Users/you/.local/bin/uv`. Server logs are in `%APPDATA%\Claude\logs\mcp-server-salestalk.log` (Windows)
or `~/Library/Logs/Claude/mcp-server-salestalk.log` (macOS).
</details>

<details>
<summary><b>Other ways to run it</b></summary>

```bash
# Streamable HTTP on http://127.0.0.1:8765/mcp (for MCP clients that connect over HTTP)
uv run salestalk-mcp --transport streamable-http --port 8765

# Database + HTTP server in Docker (published on 127.0.0.1:8765 only)
docker compose --profile http up -d --build

# Explore the tools in the MCP Inspector
npx @modelcontextprotocol/inspector uv run salestalk-mcp
```
</details>

## SalesTalk Console

<p align="center">
  <img src="docs/screenshots/console-hero.png" alt="SalesTalk Console: a data constellation of the four cities and 320 customers, lit by live tool calls" width="100%">
</p>

The server has no screen of its own: it plugs into Claude. The console is a small web app that ships with the
project and talks to the server over **real MCP**. It spawns `python -m salestalk_mcp` over stdio exactly like
Claude Desktop does, keeps one session open, and shows what Claude sees: the tool, the arguments, the JSON-RPC
frames and the result.

```bash
uv run salestalk-console        # http://127.0.0.1:8770   (--host / --port to change)
```

There is **no language model** in the console. The question cards map to the tool call Claude would make
("In Claude, the model picks the tool. Here you can see exactly what it calls.").

- **Ask SalesTalk:** six question cards (top customers, revenue by city, a monthly series, best sellers, lapsed
  Jeddah customers via `run_sql`, and a refused `DROP TABLE`) plus a form for **any tool**, generated from its input
  schema. Results render as an animated table, bar chart or line chart, and the JSON-RPC panel streams the request and
  response frames as they crossed the pipe.
- **Data constellation:** built from tool results only. The four cities are hubs sized by revenue and every customer
  orbits its city. Each call sends a pulse through the server's checks (range parser or SQL guard) into the hubs and
  customers the result mentions. A refused call stops at the guard in red.
- **How one question flows:** Claude, MCP (stdio), the tools, range parser / SQL guard, the DB layer and PostgreSQL,
  replayed for every call made on the page, with the real resolved dates, frame sizes and row counts.
- **Try to break it:** `DELETE`, `DROP TABLE`, stacked statements, `pg_sleep(10)`, `SELECT ... INTO`, a `pg_authid`
  read and a full-table dump, each sent as a real `run_sql` call. The safety stack shows which layer stopped it,
  with the server's own error text.
- **Tools reference:** the six tools as returned by `tools/list` (titles, descriptions, input schemas and
  annotations), with live call counts and latencies from this page.

<table>
  <tr>
    <td width="50%"><img src="docs/screenshots/console-playground.png" alt="A query_sales call: tool chip, latency, constellation pulse and the result table"></td>
    <td width="50%"><img src="docs/screenshots/console-break.png" alt="A valid SELECT on pg_authid passes the SQL guard and is refused by the read-only role"></td>
  </tr>
  <tr>
    <td width="50%"><img src="docs/screenshots/console-flow.png" alt="The flow diagram replaying a call: request out, response back"></td>
    <td width="50%"><img src="docs/screenshots/console-tools.png" alt="Tool cards rendered from tools/list"></td>
  </tr>
</table>

More screenshots: [JSON-RPC frames](docs/screenshots/console-jsonrpc.png) and [mobile](docs/screenshots/console-mobile.png).

<details>
<summary><b>How the console works</b></summary>

- **Backend:** a Starlette app in `src/salestalk_mcp/console/` (Starlette and uvicorn already come with the `mcp`
  SDK, so there are no new dependencies). One `mcp.Client` session over stdio lives for the app's lifetime and
  reconnects if the server process dies.
- **API:** `GET /api/tools` (the `tools/list` answer), `POST /api/call` with `{"name", "arguments"}` (structured
  result, `is_error`, error text, latency and the JSON-RPC frames), `GET /api/overview` (the hero data, built from
  `list_tables`, `revenue_by_city`, `query_sales`, `top_products` and `run_sql` calls) and `GET /api/health`.
- **Frames are real:** the SDK's stdio transport streams are wrapped, so every message written to the server's stdin
  or read from its stdout is recorded while a call is in flight (serialized the same way the transport writes it).
  Calls go one at a time, so each captured window belongs to one call.
- **It never touches the database.** Everything goes through the MCP tools, with the same guard and read-only role.
- **Local by default:** binds `127.0.0.1` with Host-header checking. The page is plain HTML, CSS and JavaScript (no
  build step, no CDN), with Space Grotesk, Instrument Sans and Geist Mono bundled under the SIL Open Font License
  (licences in `static/fonts/`). Everything respects `prefers-reduced-motion`.
</details>

## Example questions

The first two are the ones from the [demo script](docs/DEMO_SCRIPT.md).

| Ask Claude | Tool(s) Claude uses |
|---|---|
| **Who were our top 5 customers last month?** | `query_sales` |
| **Compare revenue in Dubai vs Riyadh this quarter and make a chart.** | `revenue_by_city` (optionally `granularity="month"`) |
| Show revenue by city for the last 12 months as a monthly line chart. | `revenue_by_city` |
| What were our best-selling products in the last 30 days? Which one has the best margin? | `top_products` |
| Top coffee & tea products by units this year. | `top_products` |
| How did September compare with August? | `query_sales` |
| Which Jeddah customers haven't ordered in the last 60 days? | `describe_table`, `run_sql` |
| What share of orders came in through WhatsApp each month? | `run_sql` |
| How many new customers did we sign this year, and how much have they spent? | `run_sql` |
| What's our cancellation rate by sales channel? | `run_sql` |
| *Delete the orders table.* | Refused: the SQL guard and the database both block writes |

## Tools

| Tool | Parameters | Returns |
|---|---|---|
| `list_tables` | none | Tables and views with approximate row counts, column counts and descriptions |
| `describe_table` | `table_name` | Columns (type, nullable, default, description), primary key, foreign keys, checks, referencing tables, 3 sample rows |
| `query_sales` | `month` = `"last_month"` (`YYYY-MM`, `last_month`, `this_month`), `limit` = 5 (1 to 50), `city` (optional) | Month summary (revenue, orders, active customers, average order value), change vs. previous month, top customers ranked by revenue with share |
| `revenue_by_city` | `range` = `"this_quarter"`, `granularity` = `"total"` or `"month"` | Per city: revenue, orders, customers, average order value, share, change vs. the previous period of equal length. With `month`: a chart-ready monthly series |
| `top_products` | `range` = `"last_30_days"`, `limit` = 10, `category`, `city` (optional), `sort_by` = `"revenue"` or `"units"` | Ranked products with units, orders, revenue, share and gross margin % |
| `run_sql` | `query` (one SELECT), `limit` (default 100, max 500) | `columns`, `rows`, `row_count`, `truncated`, `elapsed_ms` and the executed SQL |

All tools are annotated `readOnlyHint: true` and `destructiveHint: false`.

**Accepted `range` values**

| Kind | Values |
|---|---|
| Presets | `today`, `yesterday`, `this_week`, `last_week`, `this_month` (`mtd`), `last_month`, `this_quarter` (`qtd`), `last_quarter`, `ytd` (`this_year`), `last_year`, `last_7_days`, `last_30_days`, `last_90_days`, `last_N_days`, `last_N_months`, `last_12_months` (`ttm`), `all_time` |
| Explicit | `2026-01-01..2026-03-31` (also `to` or `/` as separator), `2026-09` (month), `2026-Q3` (quarter), `2026` (year), `2026-09-15` (single day) |

Spaces, dashes and case don't matter (`"Last Month"` works). Unknown values return a helpful error listing the options.

<details>
<summary><b>Example output: <code>query_sales(month="last_month", limit=3)</code></b></summary>

```json
{
  "month": "2026-09",
  "period": { "label": "2026-09", "start": "2026-09-01", "end": "2026-09-30", "days": 30 },
  "currency": "AED",
  "city": null,
  "summary": { "revenue": 1688801.3, "orders": 409, "active_customers": 224, "avg_order_value": 4129.1 },
  "previous_period": {
    "label": "2026-08", "start": "2026-08-01", "end": "2026-08-31", "days": 31,
    "revenue": 1410967.85, "orders": 346, "revenue_change_pct": 19.7
  },
  "top_customers": [
    { "rank": 1, "customer": "Al Fajr Import & Export", "city": "Dubai", "segment": "Wholesale",
      "orders": 5, "revenue": 58645.45, "share_of_revenue_pct": 3.5, "last_order_date": "2026-09-23" },
    { "rank": 2, "customer": "Al Noor Hypermarket", "city": "Riyadh", "segment": "Hypermarket",
      "orders": 9, "revenue": 42488.0, "share_of_revenue_pct": 2.5, "last_order_date": "2026-09-30" },
    { "rank": 3, "customer": "Al Safa Foodstuff Trading LLC", "city": "Dubai", "segment": "Wholesale",
      "orders": 4, "revenue": 38084.0, "share_of_revenue_pct": 2.3, "last_order_date": "2026-09-20" }
  ],
  "revenue_definition": "Sum of order totals in AED, excluding cancelled and returned orders."
}
```

Exact numbers depend on the day you seed.
</details>

## Safety notes (read-only by design)

The model never gets write access. Several independent layers each block writes on their own:

| # | Layer | What it does |
|---|---|---|
| 1 | **Dedicated read-only role** | The server connects as `salestalk_ro`: `SELECT` on tables and views only. No `CREATE` on the schema or database, no temp tables, not a superuser, connection limit 20. The admin user is only used by the seed scripts in `db/init/`, and the server never sees its password. |
| 2 | **Role defaults** | `default_transaction_read_only = on`, `statement_timeout = 5s`, `idle_in_transaction_session_timeout = 15s` are set on the role itself. |
| 3 | **Read-only sessions** | Every connection sets read-only mode and the statement timeout in its startup options. Every transaction starts with `BEGIN READ ONLY` and is **always rolled back**, never committed. |
| 4 | **One statement per call** | Queries are sent as server-side prepared statements, and PostgreSQL refuses to prepare more than one statement. |
| 5 | **SQL guard** (`run_sql`) | A PostgreSQL-aware lexer strips comments and checks tokens, not raw text. The query must be a single statement starting with `SELECT` or `WITH`. It rejects write/DDL/transaction keywords (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `COPY`, `SET` ...), `SELECT ... INTO`, `FOR UPDATE/SHARE`, data-modifying CTEs and risky functions (`pg_sleep`, `pg_read_file`, `dblink`, `set_config`, `nextval`, `lo_import`, `query_to_xml` ...), including quoted, schema-qualified and `U&"..."` escaped spellings. Max 20,000 characters. |
| 6 | **Row cap** | Results are wrapped as `SELECT * FROM (<query>) LIMIT n+1` and fetched with `fetchmany`, so the cap holds even if the query has its own huge `LIMIT`. Default 100 rows, max 500 (`SALESTALK_MAX_ROWS`). |
| 7 | **Parameterized tools** | The purpose-built tools only bind values as parameters. Identifiers such as table names are validated against the catalog and quoted with `psycopg.sql.Identifier`. |
| 8 | **Clean errors** | Guard, range and database errors go back to Claude as readable messages it can act on. Connection strings and passwords are never included. |

The test suite proves layers 1 to 4 **without** the guard: it sends `INSERT`, `UPDATE`, `DELETE`, `CREATE`, `DROP` and `TRUNCATE` straight to the database layer and expects every one to fail. It also checks that a slow query is cancelled by the timeout.

**Taking this to a real database:** point `SALESTALK_DATABASE_URL` at a read replica with a dedicated role. Expose only the schemas or views you want Claude to see (hide PII columns behind views). Keep `statement_timeout` low, and audit with `pgaudit` if needed. The HTTP transport has **no authentication** and binds to `127.0.0.1` by default with DNS-rebinding protection. Put it behind an authenticating proxy (or the SDK's OAuth support) before exposing it on a network.

## The demo dataset

**Dune & Dhow Trading Co.** is fictional: a Dubai-based B2B trading company. Every company, person, email (`*.example`) and number is made up.

- **Currency:** a single currency, **AED**, for every amount. The company invoices both UAE and KSA customers in AED, so city comparisons are direct.
- **Revenue:** order totals **excluding cancelled and returned** orders. `orders.total_amount` equals the sum of its `order_items.line_total`.
- **Shape:** Ramadan and winter peaks, a summer dip, fewer orders on Fridays, about 25% growth across the year, a long tail of customers (the top 10% bring about 30% of revenue), and different product tastes in the UAE and KSA.
- **Deterministic:** every "random" value comes from `md5(label || n)` instead of `random()`. Seeding on the same day always gives identical data, whatever order Postgres evaluates rows in. Only the dates move with `CURRENT_DATE` (server timezone `Asia/Dubai`).

```mermaid
erDiagram
    cities ||--o{ customers : "based in"
    customers ||--o{ orders : places
    orders ||--|{ order_items : contains
    products ||--o{ order_items : "sold as"
    cities {
        smallint city_id PK
        text name
        text country
    }
    customers {
        int customer_id PK
        text company_name
        text segment
        smallint city_id FK
        date created_at
    }
    products {
        int product_id PK
        text sku
        text name
        text category
        numeric unit_price
        numeric unit_cost
    }
    orders {
        int order_id PK
        text order_number
        int customer_id FK
        date order_date
        text status
        text channel
        numeric total_amount
    }
    order_items {
        int order_item_id PK
        int order_id FK
        int product_id FK
        int quantity
        numeric discount_pct
        numeric line_total
    }
```

There is also a `v_sales` view (one row per order line, already joined and limited to revenue-generating orders) and a `dataset_info` table (company, currency, seed date, date coverage).

## Configuration

All settings are environment variables. They can go in `.env` (see [`.env.example`](.env.example)) or in the `env` block of the Claude Desktop config, which takes precedence.

| Variable | Default | Purpose |
|---|---|---|
| `SALESTALK_DATABASE_URL` | `postgresql://salestalk_ro:salestalk_ro_password@127.0.0.1:5433/salestalk` | Connection for the **read-only** role |
| `SALESTALK_MAX_ROWS` | `500` | Hard cap on rows returned by `run_sql` |
| `SALESTALK_DEFAULT_ROWS` | `100` | `run_sql` row limit when none is given |
| `SALESTALK_STATEMENT_TIMEOUT_MS` | `5000` | Per-query timeout |
| `SALESTALK_TRANSPORT` | `stdio` | `stdio` or `streamable-http` |
| `SALESTALK_HTTP_HOST` / `SALESTALK_HTTP_PORT` | `127.0.0.1` / `8765` | HTTP transport bind address |
| `SALESTALK_DB_PORT` | `5433` | Host port docker compose publishes Postgres on |
| `POSTGRES_ADMIN_PASSWORD`, `SALESTALK_RO_PASSWORD` | demo values | Used by docker compose when the volume is first created |

## Project structure

```text
salestalk-mcp/
├── src/salestalk_mcp/
│   ├── server.py       # MCP server: tool definitions, stdio / streamable HTTP entry point
│   ├── queries.py      # tool logic as plain functions (easy to test)
│   ├── sql_guard.py    # SELECT-only guard (PostgreSQL-aware lexer)
│   ├── ranges.py       # friendly date ranges: last_month, ytd, a..b
│   ├── db.py           # read-only sessions, timeouts, row cap, error mapping
│   ├── config.py       # settings from env / .env
│   └── console/        # SalesTalk Console (web UI over a real MCP session)
│       ├── bridge.py   # one MCP client session over stdio, JSON-RPC frame tap, reconnect
│       ├── app.py      # Starlette app: /api/tools, /api/call, /api/overview, static files
│       ├── overview.py # hero data built only from tool calls
│       └── static/     # index.html, console.css, js/ (no build step), fonts/ (OFL)
├── db/init/
│   ├── 01_schema.sql   # tables, view, comments (descriptions Claude can read)
│   ├── 02_seed.sql     # deterministic seed relative to CURRENT_DATE
│   └── 03_readonly_role.sh  # SELECT-only role for the server
├── tests/              # guard + range unit tests, MCP stdio tests, console API tests, DB integration tests
├── scripts/
│   ├── smoke_test.py   # starts the server over stdio and calls every tool
│   └── make_demo_gif.py  # renders docs/demo.gif from real tool calls
├── docs/               # banner, demo GIF, console screenshots, demo video script
├── docker-compose.yml  # Postgres (port 5433) + optional HTTP server profile
├── Dockerfile          # container image for the MCP server
└── pyproject.toml      # uv project
```

## Development

```bash
uv sync                      # installs runtime + dev dependencies
uv run pytest                # unit tests always run; DB integration tests run when the database is up
uv run pytest -m "not integration"   # unit + MCP protocol tests only
uv run python scripts/smoke_test.py  # end-to-end over stdio
uv run salestalk-console             # the console on http://127.0.0.1:8770
uv run --with pillow python scripts/make_demo_gif.py   # re-render docs/demo.gif from live tool calls
```

The integration tests skip cleanly (with a clear reason) if PostgreSQL isn't reachable. The console tests start the
real server over stdio; the ones that need data are marked `integration` too.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `port is already allocated` / connection goes to the wrong Postgres | Something else uses port 5433 (for example a locally installed PostgreSQL service). Set `SALESTALK_DB_PORT=5435` in `.env`, run `docker compose up -d` again, and use port 5435 in `SALESTALK_DATABASE_URL`. |
| Every answer takes about 5 s (Windows) | Use `127.0.0.1`, not `localhost`, in `SALESTALK_DATABASE_URL`. On Windows `localhost` tries IPv6 first and waits for it to time out, while Postgres here listens on IPv4 `127.0.0.1` only. |
| "last month" returns nothing | The data was seeded long ago. Re-seed (see [Quick start](#quick-start)). |
| `Cannot connect to PostgreSQL ...` | Run `docker compose ps` and wait for `healthy` (or check `.pgdata.log` without Docker), then check the host port in `SALESTALK_DATABASE_URL`. |
| Tools don't appear in Claude Desktop | Fully quit and reopen Claude. Check the JSON is valid, use the full path to `uv`, and read `mcp-server-salestalk.log`. |
| Changed passwords in `.env` but nothing changed | Postgres reads them only when the volume is created: `docker compose down -v && docker compose up -d`. |

## Want this for your own data?

SalesTalk is a portfolio demo of the Fiverr service **"I will build a custom MCP server"**. The same pattern connects Claude to your PostgreSQL or MySQL database, CRM, ERP or internal API, with read-only access by default, clear tools and a Docker setup. Message me with the system you want Claude to access.

## License

[MIT](LICENSE) © 2026 Muhammad Hasnain Pirzada
