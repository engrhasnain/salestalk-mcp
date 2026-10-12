"""SalesTalk Console: a web console that talks to the SalesTalk MCP server over real MCP (stdio).

    uv run salestalk-console              # http://127.0.0.1:8770
    uv run salestalk-console --port 9000

There is no language model here. The console spawns the server exactly like Claude Desktop does,
calls the same six tools and shows the tool, the arguments, the JSON-RPC frames and the result.
It never connects to the database itself.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from .. import __version__
from .app import create_app
from .bridge import McpBridge

__all__ = ["McpBridge", "create_app", "main"]

LOOPBACK = ("127.0.0.1", "localhost", "::1")


def allowed_hosts_for(host: str) -> list[str] | None:
    """Host-header allow-list (DNS-rebinding protection). None means "accept any Host"."""
    hosts = ["127.0.0.1", "localhost", "[::1]"]
    if host in LOOPBACK:
        return hosts
    extra = [h.strip() for h in os.getenv("SALESTALK_CONSOLE_ALLOWED_HOSTS", "").split(",") if h.strip()]
    if host not in ("0.0.0.0", "::"):
        hosts.append(host)
    elif not extra:
        return None  # all interfaces and no allow-list given
    return hosts + extra


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="salestalk-console",
        description="SalesTalk Console: the same MCP tools Claude uses, in your browser.",
    )
    parser.add_argument("--host", default=os.getenv("SALESTALK_CONSOLE_HOST", "127.0.0.1"),
                        help="bind address (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=int(os.getenv("SALESTALK_CONSOLE_PORT", "8770")),
                        help="port (default 8770)")
    parser.add_argument("--version", action="version", version=f"salestalk-console {__version__}")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=os.getenv("SALESTALK_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    import uvicorn

    shown = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
    print(f"SalesTalk Console on http://{shown}:{args.port}  (MCP over stdio: python -m salestalk_mcp)",
          file=sys.stderr, flush=True)
    uvicorn.run(create_app(allowed_hosts=allowed_hosts_for(args.host)), host=args.host, port=args.port,
                log_level="warning")
