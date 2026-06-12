"""S2.3 · Stdio JSON-RPC client for MCP servers.

Plan ~/.claude/plans/tui-smooth-stroustrup.md §4.2.3 — minimal
async stdio JSON-RPC 2.0 client targeting MCP servers like
``@playwright/mcp`` (the Playwright Tools for MCP package).

Why hand-rolled instead of pulling the official ``mcp`` Python
SDK: avoids a new pip dep on a fast-moving package, keeps the
attack surface small, and our usage is narrow (initialize +
list_tools + call_tool — no resources / prompts / sampling).

Wire format (per the MCP spec, JSON-RPC 2.0 with newline-
delimited messages over stdin/stdout):

    client → server: {"jsonrpc":"2.0","id":1,"method":"...","params":...}
    server → client: {"jsonrpc":"2.0","id":1,"result":...}
                   | {"jsonrpc":"2.0","id":1,"error":{"code":N,"message":...}}

Lifecycle:
    client = McpStdioClient(command="playwright-mcp")
    await client.start()
    await client.initialize()
    tools = await client.list_tools()
    result = await client.call_tool("browser_navigate", {"url": "..."})
    await client.close()
"""
from __future__ import annotations

import asyncio
import json
import logging
import shlex
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Errors ──────────────────────────────────────────────────────────────────


class McpStdioError(RuntimeError):
    """Base for all stdio-client failures."""


class McpRpcError(McpStdioError):
    """Server returned a JSON-RPC error response (server-side failure
    distinct from transport failure).  ``code`` + ``data`` mirror
    the spec; ``message`` is human-readable."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(f"MCP error {code}: {message}")
        self.code = code
        self.message = message
        self.data = data


class McpTimeoutError(McpStdioError):
    """A request exceeded its declared timeout."""


class McpServerCrashed(McpStdioError):
    """Subprocess died (or stdout closed) before the request completed."""


# ── Client ──────────────────────────────────────────────────────────────────


_PROTOCOL_VERSION = "2025-06-18"
_CLIENT_NAME = "ai-buddy"
_CLIENT_VERSION = "0.1"


@dataclass
class McpStdioClient:
    """Minimal async JSON-RPC client for an MCP stdio server.

    Construction is cheap.  ``start()`` spawns the subprocess +
    starts the response reader; ``initialize()`` performs the
    MCP handshake + caches the server's capabilities; subsequent
    ``call_tool()`` calls go through the same subprocess.
    ``close()`` is idempotent.
    """

    command: str
    default_timeout: float = 30.0
    workspace_root: Optional[str] = None
    # Sprint S-EK-V1 PR 10 — env overrides merged onto the inherited
    # ``os.environ`` when spawning the subprocess. Used by
    # ``McpServerManager._spawn_user_stdio`` to inject Vault-resolved
    # secrets (e.g. ``SENTRY_ACCESS_TOKEN=<plaintext>``) so the MCP
    # server can authenticate to its vendor API. Without this, every
    # auth-requiring MCP server (Sentry / GitHub / Notion / …) would
    # die on startup with "missing credential" because the YAML's
    # ``auth_env`` template was being dropped on the floor.
    env_overrides: Optional[Dict[str, str]] = None

    # ── Internal state ────────────────────────────────────────────────
    _proc: Optional[asyncio.subprocess.Process] = field(
        default=None, init=False, repr=False,
    )
    _reader_task: Optional[asyncio.Task] = field(
        default=None, init=False, repr=False,
    )
    _stderr_task: Optional[asyncio.Task] = field(
        default=None, init=False, repr=False,
    )
    _stderr_tail: bytearray = field(
        default_factory=bytearray, init=False, repr=False,
    )
    _next_id: int = field(default=0, init=False, repr=False)
    _pending: Dict[int, "asyncio.Future[Any]"] = field(
        default_factory=dict, init=False, repr=False,
    )
    _initialized: bool = field(default=False, init=False, repr=False)
    _server_caps: Dict[str, Any] = field(
        default_factory=dict, init=False, repr=False,
    )
    _send_lock: Optional[asyncio.Lock] = field(
        default=None, init=False, repr=False,
    )
    _closed: bool = field(default=False, init=False, repr=False)

    # ── Lifecycle ─────────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return (
            self._proc is not None
            and self._proc.returncode is None
            and not self._closed
        )

    async def start(self) -> None:
        """Spawn the subprocess + start the response reader."""
        if self._proc is not None:
            return
        try:
            argv = shlex.split(self.command)
        except ValueError as exc:
            raise McpStdioError(
                f"invalid mcp command syntax: {exc}",
            ) from exc
        if not argv:
            raise McpStdioError("empty mcp command after parsing")

        # Compose subprocess env: inherit ``os.environ`` (PATH / HOME /
        # etc. needed by npx / uvx / brew binaries) and overlay any
        # operator-supplied overrides. Order matters — overrides win
        # so a Vault-injected ``SENTRY_ACCESS_TOKEN`` beats whatever
        # the daemon's env has (which is normally nothing).
        #
        # ``UV_NATIVE_TLS=true`` is injected unconditionally because
        # ``uvx`` (Astral uv) bundles Rustls + its own CA store, which
        # doesn't include corporate / macOS Keychain CAs — caught in
        # PR 10 dogfood with ``invalid peer certificate: UnknownIssuer``
        # against https://pypi.org/simple/. Setting ``UV_NATIVE_TLS=true``
        # makes uv use the system TLS stack (macOS Keychain on Mac,
        # OpenSSL on Linux) which DOES trust the standard CAs. No-op
        # for non-uv subprocesses.
        import os as _os

        from vendor_runtime_sdk.runtime.ssl_ca import tls_subprocess_env

        env = tls_subprocess_env(_os.environ)
        if self.env_overrides:
            env.update({str(k): str(v) for k, v in self.env_overrides.items()})

        try:
            self._proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.workspace_root,
                env=env,
            )
        except FileNotFoundError as exc:
            raise McpStdioError(
                f"mcp server executable not found: {argv[0]}",
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise McpStdioError(
                f"failed to spawn mcp server: {exc}",
            ) from exc

        self._send_lock = asyncio.Lock()
        self._reader_task = asyncio.create_task(
            self._read_loop(), name="mcp_stdio_reader",
        )
        # Drain stderr in background — otherwise a chatty MCP server
        # (e.g. FastMCP servers print ASCII banner + INFO logs) fills
        # the 64KB pipe buffer + blocks. Keep last 4KB so we can
        # surface stderr context on spawn failure.
        self._stderr_task = asyncio.create_task(
            self._stderr_drain_loop(), name="mcp_stdio_stderr",
        )

    async def close(self) -> None:
        """Idempotent shutdown — kills subprocess + cancels reader."""
        if self._closed:
            return
        self._closed = True
        # Cancel any pending requests so awaiters don't hang forever.
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(McpServerCrashed("client closed"))
        self._pending.clear()
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
            self._reader_task = None
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except (asyncio.CancelledError, Exception):
                pass
            self._stderr_task = None
        if self._proc is not None and self._proc.returncode is None:
            try:
                self._proc.kill()
                await self._proc.wait()
            except Exception:  # noqa: BLE001
                logger.warning(
                    "mcp_stdio: kill on close raised", exc_info=True,
                )
        self._proc = None

    # ── MCP handshake ─────────────────────────────────────────────────

    async def initialize(self, *, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Run the MCP initialize handshake.  Returns the server's
        result payload (includes ``protocolVersion`` + capabilities).
        Caches it so subsequent calls short-circuit.

        ``timeout`` overrides ``default_timeout`` for this call only.
        First-time spawn of npx/uvx packages can pull tens of MB of
        deps (pymupdf 22 MB, lxml 8 MB etc.) so the default 30s is
        too tight; expert-kit ``McpServerManager`` passes ~180s for
        first spawn. Subsequent spawns are cached and fast.
        """
        if self._initialized:
            return self._server_caps
        result = await self._call_method(
            "initialize",
            {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": _CLIENT_NAME,
                    "version": _CLIENT_VERSION,
                },
            },
            timeout=timeout,
        )
        self._server_caps = result or {}
        self._initialized = True
        # Per spec, send an "initialized" notification (no id, no
        # response expected).  Best-effort.
        try:
            await self._send_notification("notifications/initialized", {})
        except Exception:
            logger.debug("mcp_stdio: initialized notification failed")
        return self._server_caps

    # ── Tool API ──────────────────────────────────────────────────────

    async def list_tools(self) -> List[Dict[str, Any]]:
        """Return the list of tools the server exposes."""
        result = await self._call_method("tools/list", {})
        return list(result.get("tools") or [])

    async def call_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
        *,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Invoke a tool by name; return the server's result payload
        (typically ``{"content": [...], "isError": bool}``)."""
        return await self._call_method(
            "tools/call",
            {"name": name, "arguments": dict(arguments or {})},
            timeout=timeout,
        )

    # ── Internals ─────────────────────────────────────────────────────

    async def _call_method(
        self,
        method: str,
        params: Dict[str, Any],
        *,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        if not self.is_running:
            raise McpStdioError(
                "mcp client not running — call start() first",
            )
        rid = self._next_id
        self._next_id += 1
        envelope: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": rid,
            "method": method,
            "params": params,
        }
        loop = asyncio.get_running_loop()
        fut: "asyncio.Future[Any]" = loop.create_future()
        self._pending[rid] = fut

        await self._send_envelope(envelope)
        try:
            payload = await asyncio.wait_for(
                fut, timeout=timeout if timeout is not None else self.default_timeout,
            )
        except asyncio.TimeoutError as exc:
            self._pending.pop(rid, None)
            raise McpTimeoutError(
                f"mcp call {method!r} exceeded "
                f"{timeout if timeout is not None else self.default_timeout}s"
            ) from exc

        if isinstance(payload, McpRpcError):
            raise payload
        return payload or {}

    async def _send_notification(
        self, method: str, params: Dict[str, Any],
    ) -> None:
        envelope = {"jsonrpc": "2.0", "method": method, "params": params}
        await self._send_envelope(envelope)

    async def _send_envelope(self, envelope: Dict[str, Any]) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        line = (
            json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        async with self._send_lock:  # type: ignore[union-attr]
            try:
                self._proc.stdin.write(line)
                await self._proc.stdin.drain()
            except Exception as exc:  # noqa: BLE001
                raise McpServerCrashed(
                    f"mcp stdin write failed: {exc}"
                ) from exc

    async def _stderr_drain_loop(self) -> None:
        """Drain stderr in background to prevent pipe-buffer backpressure
        (chatty MCP servers like FastMCP print ASCII banners + INFO
        logs at startup; ~64KB would block the subprocess). Keep the
        last 4KB so we can surface failure context.
        """
        assert self._proc is not None and self._proc.stderr is not None
        try:
            while True:
                chunk = await self._proc.stderr.read(4096)
                if not chunk:
                    return
                # Keep a rolling tail of last 4KB
                self._stderr_tail.extend(chunk)
                if len(self._stderr_tail) > 4096:
                    del self._stderr_tail[:-4096]
        except asyncio.CancelledError:
            raise
        except Exception:
            # Don't crash the stderr drain — failure here is non-fatal
            logger.debug("mcp_stdio: stderr drain ended", exc_info=True)

    def stderr_tail_text(self) -> str:
        """Return the last 4KB of stderr as text (best-effort decode)."""
        try:
            return bytes(self._stderr_tail).decode("utf-8", errors="replace")
        except Exception:
            return ""

    async def _read_loop(self) -> None:
        """Read newline-delimited JSON responses from the subprocess
        stdout and dispatch them to the matching pending future."""
        assert self._proc is not None and self._proc.stdout is not None
        try:
            while True:
                line = await self._proc.stdout.readline()
                if not line:
                    # EOF — subprocess died.  Surface to all pending
                    # awaiters; include the last stderr bytes so the
                    # operator can see WHY the server died (missing
                    # auth env var, missing file, etc.).
                    stderr_snippet = self.stderr_tail_text().strip()
                    # Trim to a sensible single-line preview
                    if stderr_snippet:
                        snippet = stderr_snippet[-300:]
                        snippet = snippet.replace("\n", " | ")
                        crash_msg = f"mcp stdout closed; stderr_tail: {snippet}"
                    else:
                        crash_msg = "mcp stdout closed"
                    for fut in self._pending.values():
                        if not fut.done():
                            fut.set_exception(
                                McpServerCrashed(crash_msg),
                            )
                    self._pending.clear()
                    return
                try:
                    msg = json.loads(line.decode("utf-8").strip())
                except Exception:
                    logger.debug(
                        "mcp_stdio: non-JSON line dropped: %r", line[:200],
                    )
                    continue
                rid = msg.get("id")
                if rid is None:
                    # Notification from server (no id); we don't act
                    # on them today (sampling / progress / etc.).
                    continue
                fut = self._pending.pop(rid, None)
                if fut is None or fut.done():
                    continue
                if "error" in msg and msg["error"]:
                    err = msg["error"]
                    fut.set_result(McpRpcError(
                        code=int(err.get("code") or -32000),
                        message=str(err.get("message") or ""),
                        data=err.get("data"),
                    ))
                else:
                    fut.set_result(msg.get("result") or {})
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("mcp_stdio: read loop crashed")
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(
                        McpServerCrashed("read loop crashed"),
                    )
            self._pending.clear()
