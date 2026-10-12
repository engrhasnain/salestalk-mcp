"""The SalesTalk Console web app (Starlette): a JSON API over one MCP session, plus static files."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import anyio
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .bridge import BridgeUnavailable, McpBridge
from .overview import build_overview

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_BODY_BYTES = 64_000


def _error(status: int, message: str, **extra: Any) -> JSONResponse:
    return JSONResponse({"error": message, **extra}, status_code=status)


def _bridge(request: Request) -> McpBridge:
    return request.app.state.bridge


async def health(request: Request) -> Response:
    return JSONResponse(_bridge(request).describe())


async def tools(request: Request) -> Response:
    """tools/list as the server answered it (titles, descriptions, input schemas, annotations)."""
    bridge = _bridge(request)
    try:
        await bridge.wait_ready()
    except BridgeUnavailable as exc:
        return _error(503, str(exc), session=bridge.describe())
    return JSONResponse({"session": bridge.describe(), "tools": bridge.tools, "session_frames": bridge.session_frames})


async def call(request: Request) -> Response:
    """Call one tool over MCP: {"name": ..., "arguments": {...}} -> result, error, latency and frames."""
    bridge = _bridge(request)
    if "application/json" not in request.headers.get("content-type", ""):
        return _error(415, "Send the call as JSON (Content-Type: application/json).")
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        return _error(413, f"Request body too large (max {MAX_BODY_BYTES} bytes).")
    try:
        payload = await request.json()
    except ValueError:
        return _error(400, "Request body is not valid JSON.")
    if not isinstance(payload, dict):
        return _error(400, 'Expected an object like {"name": "query_sales", "arguments": {}}.')
    name = payload.get("name")
    arguments = payload.get("arguments") or {}
    if not isinstance(name, str) or not name:
        return _error(400, "Missing tool name.")
    if not isinstance(arguments, dict):
        return _error(400, "arguments must be an object.")
    try:
        await bridge.wait_ready()
        if name not in bridge.tool_names():
            return _error(404, f"Unknown tool '{name}'. Available: {', '.join(bridge.tool_names())}.")
        outcome = await bridge.call(name, arguments)
    except BridgeUnavailable as exc:
        return _error(503, str(exc), session=bridge.describe())
    return JSONResponse(outcome.to_dict())


async def overview(request: Request) -> Response:
    """Hero data, built from real tool calls made right now (the hero feed shows these calls)."""
    bridge = _bridge(request)
    try:
        await bridge.wait_ready()
        return JSONResponse(await build_overview(bridge))
    except BridgeUnavailable as exc:
        return _error(503, str(exc), session=bridge.describe())


def create_app(
    bridge: McpBridge | None = None,
    *,
    allowed_hosts: Sequence[str] | None = None,
    static_dir: Path = STATIC_DIR,
) -> Starlette:
    """Build the console app. ``allowed_hosts`` enables Host-header checking (DNS-rebinding protection)."""
    mcp_bridge = bridge or McpBridge()

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        app.state.bridge = mcp_bridge
        async with anyio.create_task_group() as tg:
            await tg.start(mcp_bridge.run)
            try:
                yield
            finally:
                mcp_bridge.close()
                with anyio.move_on_after(8):
                    await mcp_bridge.stopped.wait()
                tg.cancel_scope.cancel()

    middleware = [Middleware(TrustedHostMiddleware, allowed_hosts=list(allowed_hosts))] if allowed_hosts else []
    routes = [
        Route("/api/health", health, methods=["GET"]),
        Route("/api/tools", tools, methods=["GET"]),
        Route("/api/call", call, methods=["POST"]),
        Route("/api/overview", overview, methods=["GET"]),
        Mount("/", app=StaticFiles(directory=static_dir, html=True), name="static"),
    ]
    return Starlette(routes=routes, middleware=middleware, lifespan=lifespan)
