"""One long-lived MCP client session to the SalesTalk server, with a JSON-RPC frame tap.

The console never touches the database. It spawns the real server over stdio (exactly like
Claude Desktop does: ``python -m salestalk_mcp``), keeps that session open for the lifetime of
the web app, and reconnects if the server process dies.

Frames: the stdio transport's read/write streams are wrapped so every JSON-RPC message that is
written to the server's stdin, or read from its stdout, is recorded while a call is in flight.
Outgoing messages are serialized the same way the SDK's stdio transport writes them
(``model_dump_json(by_alias=True, exclude_unset=True)``), so what the UI shows is what went over
the pipe. Calls are serialized with a lock, so each captured window belongs to one call.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

import anyio
import anyio.abc
from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import MCPError
from mcp.shared.message import SessionMessage
from mcp_types import CONNECTION_CLOSED, Implementation

from .. import __version__

log = logging.getLogger("salestalk_mcp.console")

Direction = Literal["out", "in"]

#: Errors that mean the stdio session is gone (server exited, pipe closed), not a tool failure.
CONNECTION_ERRORS: tuple[type[BaseException], ...] = (
    anyio.ClosedResourceError,
    anyio.BrokenResourceError,
    anyio.EndOfStream,
    ConnectionError,
    BrokenPipeError,
)


class BridgeUnavailable(RuntimeError):
    """The MCP session is not connected (yet). The message is safe to show in the UI."""


def default_server_params() -> StdioServerParameters:
    """Spawn the SalesTalk server like Claude Desktop does, passing our environment through."""
    return StdioServerParameters(command=sys.executable, args=["-m", "salestalk_mcp"], env=dict(os.environ))


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


# --------------------------------------------------------------------------- frame tap


@dataclass
class Capture:
    """Frames recorded during one request window."""

    started: float = field(default_factory=time.perf_counter)
    frames: list[dict[str, Any]] = field(default_factory=list)

    def add(self, direction: Direction, message: SessionMessage) -> None:
        wire = message.message.model_dump_json(by_alias=True, exclude_unset=True)
        self.frames.append(
            {
                "direction": direction,
                "t_ms": round((time.perf_counter() - self.started) * 1000, 2),
                "bytes": len(wire.encode()) + 1,  # + the newline delimiter on the pipe
                "message": json.loads(wire),
            }
        )


class FrameTap:
    """Holds the capture that is currently recording (None when idle)."""

    def __init__(self) -> None:
        self.capture: Capture | None = None
        self.total_frames = 0

    def record(self, direction: Direction, message: SessionMessage | Exception) -> None:
        if isinstance(message, Exception):
            return
        self.total_frames += 1
        if self.capture is not None:
            self.capture.add(direction, message)


class _TapRead:
    """Read side of the transport: records each message read from the server's stdout."""

    def __init__(self, inner: Any, tap: FrameTap) -> None:
        self._inner = inner
        self._tap = tap

    async def receive(self) -> SessionMessage | Exception:
        item = await self._inner.receive()
        self._tap.record("in", item)
        return item

    async def aclose(self) -> None:
        await self._inner.aclose()

    def __aiter__(self) -> _TapRead:
        return self

    async def __anext__(self) -> SessionMessage | Exception:
        try:
            return await self.receive()
        except (anyio.EndOfStream, anyio.ClosedResourceError):
            raise StopAsyncIteration from None

    async def __aenter__(self) -> _TapRead:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()


class _TapWrite:
    """Write side of the transport: records each message just before it goes to the server's stdin."""

    def __init__(self, inner: Any, tap: FrameTap) -> None:
        self._inner = inner
        self._tap = tap

    async def send(self, item: SessionMessage, /) -> None:
        self._tap.record("out", item)
        await self._inner.send(item)

    async def aclose(self) -> None:
        await self._inner.aclose()

    async def __aenter__(self) -> _TapWrite:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()


@asynccontextmanager
async def tapped_stdio(params: StdioServerParameters, tap: FrameTap) -> AsyncIterator[tuple[_TapRead, _TapWrite]]:
    """The SDK's stdio transport with both streams wrapped by the tap."""
    async with stdio_client(params) as (read_stream, write_stream):
        yield _TapRead(read_stream, tap), _TapWrite(write_stream, tap)


# --------------------------------------------------------------------------- bridge


@dataclass
class CallOutcome:
    tool: str
    arguments: dict[str, Any]
    is_error: bool
    error: str | None
    result: dict[str, Any] | None
    content_text: str
    latency_ms: float
    frames: list[dict[str, Any]]
    called_at: str
    protocol_error: bool = False

    def to_dict(self, *, frames: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {
            "tool": self.tool,
            "arguments": self.arguments,
            "ok": not self.is_error,
            "is_error": self.is_error,
            "error": self.error,
            "protocol_error": self.protocol_error,
            "result": self.result,
            "content_text": self.content_text,
            "latency_ms": self.latency_ms,
            "called_at": self.called_at,
        }
        if frames:
            out["frames"] = self.frames
        return out


class McpBridge:
    """Owns the MCP client session. Run :meth:`run` in a task; call :meth:`call` from anywhere."""

    def __init__(
        self,
        params: StdioServerParameters | None = None,
        *,
        mode: str = "auto",
        read_timeout_s: float = 30.0,
        connect_wait_s: float = 25.0,
    ) -> None:
        self.params = params or default_server_params()
        self.mode = mode
        self.read_timeout_s = read_timeout_s
        self.connect_wait_s = connect_wait_s
        self.tap = FrameTap()
        self.tools: list[dict[str, Any]] = []
        self.server: dict[str, Any] = {}
        self.protocol_version: str | None = None
        self.session_frames: list[dict[str, Any]] = []
        self.connected_at: str | None = None
        self.connections = 0
        self.last_error: str | None = None
        self._client: Client | None = None
        self._ready = anyio.Event()
        self._lost = anyio.Event()
        self._closing = False
        self._lock = anyio.Lock()
        self.stopped = anyio.Event()

    # ------------------------------------------------------------------ lifecycle

    @property
    def connected(self) -> bool:
        return self._client is not None

    async def run(self, *, task_status: anyio.abc.TaskStatus[None] = anyio.TASK_STATUS_IGNORED) -> None:
        """Connect, keep the session open, reconnect with backoff if it dies. Returns on :meth:`close`."""
        started = False
        backoff = 0.5
        while not self._closing:
            try:
                capture = Capture()
                self.tap.capture = capture
                client = Client(
                    tapped_stdio(self.params, self.tap),
                    mode=self.mode,
                    cache=None,  # every call really goes over the wire
                    read_timeout_seconds=self.read_timeout_s,
                    client_info=Implementation(name="salestalk-console", version=__version__),
                )
                async with client:
                    listed = await client.list_tools()
                    self.tap.capture = None
                    self.session_frames = capture.frames
                    self.tools = [t.model_dump(mode="json", by_alias=True, exclude_none=True) for t in listed.tools]
                    info = client.server_info
                    self.server = info.model_dump(mode="json", by_alias=True, exclude_none=True) if info else {}
                    self.server["instructions"] = client.instructions
                    self.protocol_version = client.protocol_version
                    self.connected_at = _now_iso()
                    self.connections += 1
                    self.last_error = None
                    self._lost = anyio.Event()
                    self._client = client
                    self._ready.set()
                    backoff = 0.5
                    log.info("MCP session open (%s, protocol %s, %d tools)", self.mode, self.protocol_version,
                             len(self.tools))
                    if not started:
                        task_status.started()
                        started = True
                    await self._lost.wait()
            except Exception as exc:  # noqa: BLE001 - any failure means "reconnect", never crash the app
                self.last_error = f"{type(exc).__name__}: {exc}"
                log.warning("MCP session failed: %s", self.last_error)
            finally:
                self.tap.capture = None
                self._client = None
                if self._ready.is_set():
                    self._ready = anyio.Event()
            if not started:
                task_status.started()  # let the web app start; calls wait for the session or fail cleanly
                started = True
            if self._closing:
                break
            self._lost = anyio.Event()
            with anyio.move_on_after(backoff):
                await self._lost.wait()  # close() interrupts the backoff
            backoff = min(backoff * 2, 8.0)
        self.stopped.set()

    def close(self) -> None:
        self._closing = True
        self._lost.set()

    def mark_lost(self) -> None:
        """Ask :meth:`run` to drop the session and reconnect."""
        self._client = None
        self._lost.set()

    async def wait_ready(self, timeout: float | None = None) -> Client:
        with anyio.move_on_after(self.connect_wait_s if timeout is None else timeout):
            while self._client is None and not self._closing:
                await self._ready.wait()
                if self._client is None:  # the event belonged to a session that already died
                    await anyio.sleep(0.05)
        if self._client is None:
            detail = f" Last error: {self.last_error}" if self.last_error else ""
            raise BridgeUnavailable(f"The SalesTalk MCP server is not connected.{detail}")
        return self._client

    # ------------------------------------------------------------------ calls

    def tool_names(self) -> list[str]:
        return [t["name"] for t in self.tools]

    async def call(self, name: str, arguments: dict[str, Any] | None = None, *, retry: bool = True) -> CallOutcome:
        """Call one tool over MCP and return the result plus the JSON-RPC frames of that exchange."""
        arguments = dict(arguments or {})
        async with self._lock:
            client = await self.wait_ready()
            capture = Capture()
            self.tap.capture = capture
            called_at = _now_iso()
            started = time.perf_counter()
            try:
                result = await client.call_tool(name, arguments)
            except MCPError as exc:
                latency = round((time.perf_counter() - started) * 1000, 1)
                if exc.code != CONNECTION_CLOSED:
                    # A JSON-RPC error response (e.g. invalid params): a real answer from the server.
                    return CallOutcome(name, arguments, True, exc.message, None, "", latency, capture.frames,
                                       called_at, protocol_error=True)
                self.mark_lost()
                lost: BaseException = exc
            except CONNECTION_ERRORS as exc:
                self.mark_lost()
                lost = exc
            else:
                latency = round((time.perf_counter() - started) * 1000, 1)
                text = " ".join(getattr(c, "text", "") for c in result.content).strip()
                structured = result.structured_content if isinstance(result.structured_content, dict) else None
                return CallOutcome(
                    tool=name,
                    arguments=arguments,
                    is_error=bool(result.is_error),
                    error=(text or "The tool reported an error.") if result.is_error else None,
                    result=None if result.is_error else structured,
                    content_text=text,
                    latency_ms=latency,
                    frames=capture.frames,
                    called_at=called_at,
                )
            finally:
                self.tap.capture = None
        log.warning("MCP session lost during %s: %s", name, lost)
        if retry and not self._closing:
            await self.wait_ready()
            return await self.call(name, arguments, retry=False)
        raise BridgeUnavailable(f"The MCP session closed during the call ({type(lost).__name__}).")

    def describe(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            "transport": "stdio",
            "command": " ".join([os.path.basename(self.params.command), *self.params.args]),
            "mode": self.mode,
            "protocol_version": self.protocol_version,
            "server": self.server,
            "connected_at": self.connected_at,
            "connections": self.connections,
            "frames_seen": self.tap.total_frames,
            "last_error": self.last_error,
        }
