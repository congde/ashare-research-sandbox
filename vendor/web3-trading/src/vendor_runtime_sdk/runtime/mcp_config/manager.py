# -*- coding: utf-8 -*-
"""Sprint 7 PR-2 · McpServerManager — lifecycle for external MCP servers.

Owns the spawn / connect / crash-detect / restart logic for every
server declared in ``~/.aibuddy/mcp_servers.toml``.  Daemon (CLI) and
web app both instantiate this once at boot via ``start_all()`` and
shut it down via ``stop_all()``.

Design notes
------------
* stdio servers wrap :class:`runtime.mcp_stdio_client.McpStdioClient`
  (already validated by S2.3 Browser MCP).  ``stdio_client_factory`` is
  injectable for tests so we don't spawn real subprocesses.
* HTTP servers do NOT spawn anything — they're connection-only; the
  manager just records readiness so the namespace shows up in
  ``list_servers()``.
* Crash recovery uses a manual ``sweep_crashes()`` driver (no
  background loop here — daemon decides cadence) so unit tests stay
  deterministic.
* ``max_restarts_per_hour`` (D6 default 5) uses a fixed-window
  counter that resets on the wall-clock hour boundary; once exhausted
  the spec is marked ``failed_quota`` and ignored until manual restart.
"""
from __future__ import annotations

import asyncio
import logging
import shlex
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from vendor_runtime_sdk.runtime.mcp_config.schema import McpServerSpec

logger = logging.getLogger(__name__)


_HOUR_SECONDS = 3600


def _default_stdio_client_factory(command, **kwargs):
    """Production factory — lazy import so tests can stay light."""
    from vendor_runtime_sdk.runtime.mcp_stdio_client import McpStdioClient

    return McpStdioClient(command=command, **kwargs)


@dataclass
class McpServerStatus:
    """Operator-facing status for one server (consumed by ``aibuddy mcp list``)."""

    name: str
    namespace_prefix: str
    transport: str
    enabled: bool
    status: str  # ready | disabled | failed | crashed | failed_quota
    last_error: str = ""
    restart_count: int = 0
    started_at: Optional[float] = None


@dataclass
class McpServerManager:
    """Owns the lifecycle of every configured MCP server.

    Construction is cheap; call :meth:`start_all` at boot and
    :meth:`stop_all` at shutdown.  Crash recovery is driven by
    :meth:`sweep_crashes` (caller picks cadence — typically every 30s
    via daemon background task).
    """

    specs: List[McpServerSpec]
    # ``stdio_client_factory`` is intentionally Optional + late-bound:
    # tests can monkeypatch the module-level
    # ``_default_stdio_client_factory`` and the manager will pick up
    # the swap at spawn time.  Pin a concrete factory here only when
    # constructing from tests that want to override the default
    # entirely (the McpServerManager unit tests do this — pin _Fake).
    stdio_client_factory: Optional[Callable[..., Any]] = None
    workspace_root: Optional[str] = None

    # ── Internal state ────────────────────────────────────────────────────

    _clients: Dict[str, Any] = field(default_factory=dict)
    _statuses: Dict[str, McpServerStatus] = field(default_factory=dict)
    _restart_window_start: Dict[str, float] = field(default_factory=dict)

    # Sprint S-EK-V1 PR 4 — per-user MCP server clients live in a
    # SECOND map keyed by ``(workspace_id, user_id)`` so they NEVER
    # cross-contaminate ``_clients`` / ``_statuses`` (those are the
    # global, toml-declared servers shared across all users). Each
    # per-user entry is ``{spec_key -> client}`` where ``spec_key`` is
    # ``"{ws}:{user}:{namespace_prefix}"`` so collisions across users
    # are impossible.
    _user_clients: Dict[tuple, Dict[str, Any]] = field(default_factory=dict)
    _user_specs: Dict[tuple, Dict[str, McpServerSpec]] = field(default_factory=dict)
    _user_reload_lock: Dict[tuple, asyncio.Lock] = field(default_factory=dict)

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def start_all(self) -> Dict[str, McpServerStatus]:
        """Spawn / connect every enabled server.  Failures isolated per
        server — one bad server never blocks the others."""
        for spec in self.specs:
            if not spec.enabled:
                self._statuses[spec.name] = McpServerStatus(
                    name=spec.name,
                    namespace_prefix=spec.namespace_prefix,
                    transport=spec.transport,
                    enabled=False,
                    status="disabled",
                )
                continue

            try:
                if spec.transport == "stdio":
                    await self._spawn_stdio(spec)
                else:
                    self._connect_http(spec)
                self._statuses[spec.name] = McpServerStatus(
                    name=spec.name,
                    namespace_prefix=spec.namespace_prefix,
                    transport=spec.transport,
                    enabled=True,
                    status="ready",
                    started_at=time.time(),
                )
            except (RuntimeError, OSError, ImportError, ValueError) as exc:
                logger.warning(
                    "mcp server %s start failed (continuing with others): %s",
                    spec.name, exc,
                )
                self._statuses[spec.name] = McpServerStatus(
                    name=spec.name,
                    namespace_prefix=spec.namespace_prefix,
                    transport=spec.transport,
                    enabled=True,
                    status="failed",
                    last_error=str(exc),
                )

        return dict(self._statuses)

    # First-spawn timeout for ``initialize`` — npx / uvx may need to
    # download tens of MB of deps on cold cache (pymupdf 22 MB / lxml
    # 8 MB / pikepdf 4 MB for pdf-mcp-server alone). The default 30s
    # on McpStdioClient is too tight for that; we bump it for the
    # initial handshake. Subsequent spawns hit the cache and are fast.
    _INITIALIZE_TIMEOUT_SEC = 180

    async def _spawn_stdio(self, spec: McpServerSpec) -> None:
        """Construct + start + initialize a stdio client for *spec*."""
        # schema.command is List[str]; McpStdioClient takes a single
        # command string and shlex.split internally — round-trip via
        # shlex.join preserves args containing spaces / quotes.
        cmd_str = shlex.join(spec.command or [])
        # Late-bind module-level default so monkeypatch in tests works:
        # without this, the dataclass field would have captured the
        # function reference at class-definition time.
        factory = self.stdio_client_factory or _default_stdio_client_factory
        client = factory(
            command=cmd_str,
            workspace_root=self.workspace_root,
        )
        await client.start()
        await client.initialize(timeout=self._INITIALIZE_TIMEOUT_SEC)
        self._clients[spec.name] = client

    def _connect_http(self, spec: McpServerSpec) -> None:
        """HTTP servers don't need a persistent client at this layer —
        per-call HTTP requests happen at tool invocation time.  We just
        record the spec for later lookup."""
        # Stash the spec itself as the "client handle" so get_client()
        # consumers (tool registration in PR-3) can reach the url + auth.
        self._clients[spec.name] = spec

    async def stop_all(self) -> None:
        """Idempotent shutdown — close every stdio client (global AND
        per-user).

        Per-user clients live in ``_user_clients[(ws,user)][ns]`` and
        were previously NOT closed by ``stop_all`` (Sprint 7 only knew
        about the global ``_clients`` dict). Sprint S-EK-V1 PR 4
        introduced the per-user state — on long-running pods where
        users had installed expert kits, dozens of orphaned stdio
        subprocesses would accumulate at shutdown unless we tear them
        down here too. Idempotent: re-running after first shutdown is
        a no-op (dicts get cleared).
        """
        for name, client in list(self._clients.items()):
            if hasattr(client, "close"):
                try:
                    await client.close()
                except (OSError, RuntimeError, asyncio.CancelledError):
                    # Narrow capture: subprocess kill races / cancelled
                    # tasks during shutdown.  Programming bugs propagate.
                    logger.warning("mcp_stdio close raised for %s", name,
                                   exc_info=True)
        self._clients.clear()

        # Sprint S-EK-V1 PR 4 — close per-user stdio subprocesses.
        for (ws, user), clients in list(self._user_clients.items()):
            for ns, client in list(clients.items()):
                if hasattr(client, "close"):
                    try:
                        await client.close()
                    except (OSError, RuntimeError, asyncio.CancelledError):
                        logger.warning(
                            "user mcp_stdio close raised for ws=%s user=%s ns=%s",
                            ws, user, ns, exc_info=True,
                        )
        self._user_clients.clear()
        self._user_specs.clear()
        self._user_reload_lock.clear()

    # ── Query ─────────────────────────────────────────────────────────────

    def list_servers(self) -> List[McpServerStatus]:
        """Return current status snapshot, refreshing crashed flag."""
        out: List[McpServerStatus] = []
        for name, status in self._statuses.items():
            client = self._clients.get(name)
            if (status.status == "ready"
                    and client is not None
                    and hasattr(client, "is_running")
                    and not client.is_running):
                # Live-check: was ready, now subprocess died → crashed
                status.status = "crashed"
            out.append(status)
        return out

    def get_client(self, name: str) -> Optional[Any]:
        return self._clients.get(name)

    def get_spec(self, name: str) -> Optional[McpServerSpec]:
        for s in self.specs:
            if s.name == name:
                return s
        return None

    async def list_tools_for(self, name: str) -> List[Dict[str, Any]]:
        """Return tool definitions for *name* (empty when unknown / not ready)."""
        client = self._clients.get(name)
        if client is None or not hasattr(client, "list_tools"):
            return []
        try:
            tools = await client.list_tools()
            return list(tools or [])
        except (OSError, RuntimeError, ValueError) as exc:
            # Narrow capture: subprocess crash / RPC error / malformed
            # response.  TypeError etc. propagates as a programming bug.
            logger.warning("list_tools failed for %s: %s", name, exc)
            return []

    # ── Crash recovery ───────────────────────────────────────────────────

    async def sweep_crashes(self) -> int:
        """Detect crashed stdio servers + restart per spec.

        Returns the number of servers restarted (zero when nothing
        needed it).  Honours ``restart_on_crash`` + per-hour quota.
        """
        # Refresh status (live-checks subprocess state)
        self.list_servers()

        restarted = 0
        now = time.time()
        for spec in self.specs:
            if spec.transport != "stdio":
                continue
            status = self._statuses.get(spec.name)
            if status is None or status.status != "crashed":
                continue
            if not spec.restart_on_crash:
                continue

            # Quota: rolling 1-hour window
            window_start = self._restart_window_start.get(spec.name, 0.0)
            if now - window_start >= _HOUR_SECONDS:
                # New window — reset counter
                self._restart_window_start[spec.name] = now
                status.restart_count = 0

            if status.restart_count >= spec.max_restarts_per_hour:
                logger.warning(
                    "mcp server %s exhausted restart quota (%d/hour); "
                    "skipping until manual restart",
                    spec.name, spec.max_restarts_per_hour,
                )
                status.status = "failed_quota"
                continue

            # Drop the dead client and respawn
            old = self._clients.pop(spec.name, None)
            if old is not None and hasattr(old, "close"):
                try:
                    await old.close()
                except (OSError, RuntimeError, asyncio.CancelledError):
                    # Same shutdown race set as stop_all.  Programming
                    # bugs (TypeError / NameError) propagate.
                    pass

            try:
                await self._spawn_stdio(spec)
                status.status = "ready"
                status.restart_count += 1
                status.last_error = ""
                restarted += 1
                logger.info(
                    "mcp server %s restarted (count=%d/%d this hour)",
                    spec.name, status.restart_count, spec.max_restarts_per_hour,
                )
            except (RuntimeError, OSError, ImportError, ValueError) as exc:
                status.last_error = str(exc)
                status.restart_count += 1
                # Keep status=crashed so next sweep can retry (until quota)
                logger.warning(
                    "mcp server %s restart failed (will retry next sweep): %s",
                    spec.name, exc,
                )

        return restarted


    # ── Per-user reload (Sprint S-EK-V1 PR 4) ────────────────────────────

    async def reload_for_user(
        self,
        workspace_id: str,
        user_id: str,
    ) -> Dict[str, McpServerStatus]:
        """Diff the user's persisted ``user_mcp_servers`` rows against the
        currently-running per-user stdio clients, then:

          * spawn newly-added stdio specs
          * stop+remove specs that disappeared from Mongo
          * leave unchanged specs alone (no spurious restart cycle)

        Idempotent: calling twice in a row with no Mongo changes is a
        true no-op. Safe to call from multiple async tasks — guarded
        by a per-(workspace, user) ``asyncio.Lock``.

        Per-user stdio clients are stored in :attr:`_user_clients` and
        are NEVER mixed with the global ``_clients`` dict (which holds
        the operator-toml-declared servers shared across all users).
        HTTP transport is treated the same way as global HTTP — recorded
        but no persistent client spawned.

        Returns a snapshot of the user's spec statuses keyed by
        ``namespace_prefix``. Fail-soft: per-spec spawn errors land in
        ``McpServerStatus.last_error`` but never raise.
        """
        # Lazy DAO import — DAO pulls Motor / Mongo which only the
        # web app / daemon path care about; unit tests should be able
        # to construct a manager without the DAO dependency. The DAO
        # import is wrapped so a missing collection / driver does not
        # crash the in-flight toggle request — the persistent Mongo
        # rows ARE the durable source of truth; tools will appear on
        # the next manager invocation after the reload re-tries.
        try:
            from dao.user_mcp_config_dao import list_user_mcp_servers
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "reload_for_user: DAO unavailable (skipping reload for "
                "ws=%s user=%s; rows ARE persisted): %s",
                workspace_id, user_id, exc,
            )
            return {}

        key = (workspace_id, user_id)
        # CRITICAL fix — use ``setdefault`` instead of get-then-set so
        # two concurrent reload_for_user calls for the same (ws, user)
        # converge on the SAME lock object. With get-then-set, both
        # tasks could pass ``get → None`` between the await yields,
        # each construct a distinct ``asyncio.Lock``, and the second
        # one writes last — the loser's lock is leaked and the two
        # tasks would enter the protected region simultaneously,
        # double-spawning the same stdio server. ``dict.setdefault``
        # is atomic at the C level (single bytecode op), so it is
        # safe without an outer lock.
        lock = self._user_reload_lock.setdefault(key, asyncio.Lock())

        async with lock:
            try:
                rows = await list_user_mcp_servers(workspace_id, user_id)
            except Exception as exc:  # noqa: BLE001
                # MEDIUM fix (PR 4 review) — return BEFORE any
                # ``setdefault`` on _user_clients/_user_specs so a
                # failed query never plants empty dicts that
                # ``list_user_servers`` would mis-report as "this
                # user has 0 servers" (vs. "load failed; previous
                # state still authoritative"). Previous state in
                # the maps is left untouched.
                logger.warning(
                    "reload_for_user: query failed for ws=%s user=%s "
                    "(leaving previous state alone): %s",
                    workspace_id, user_id, exc,
                )
                return {}

            # Build the desired-state spec map. Use ``namespace_prefix``
            # as the per-user identity key — the DAO already enforces
            # ``(workspace, user, namespace_prefix)`` uniqueness so this
            # is collision-free.
            desired_specs: Dict[str, McpServerSpec] = {}
            desired_statuses: Dict[str, McpServerStatus] = {}
            # Sprint S-EK-V1 PR 10 — track each row's ``auth_env``
            # (template like ``{SENTRY_ACCESS_TOKEN: $VAULT:sentry_token}``)
            # alongside the validated spec. Vault resolution happens at
            # spawn time (below) so a stale cached spec doesn't fire
            # with a since-rotated credential.
            desired_auth_env: Dict[str, Dict[str, str]] = {}
            for row in rows or []:
                try:
                    spec = _user_row_to_spec(row)
                except Exception as exc:  # noqa: BLE001 — bad row should not poison reload
                    ns = row.get("namespace_prefix") or "<unknown>"
                    logger.warning(
                        "reload_for_user: spec build failed for ns=%s "
                        "(skipping this row): %s", ns, exc,
                    )
                    continue
                desired_specs[spec.namespace_prefix] = spec
                desired_auth_env[spec.namespace_prefix] = dict(
                    row.get("auth_env") or {}
                )

            running = self._user_clients.setdefault(key, {})
            previous_specs = self._user_specs.setdefault(key, {})

            # ── 1. Stop clients whose spec was removed ────────────────
            removed_names = set(running.keys()) - set(desired_specs.keys())
            for name in removed_names:
                client = running.pop(name, None)
                if client is not None and hasattr(client, "close"):
                    try:
                        await client.close()
                    except (OSError, RuntimeError, asyncio.CancelledError):
                        logger.warning(
                            "reload_for_user: close failed for ws=%s user=%s ns=%s",
                            workspace_id, user_id, name, exc_info=True,
                        )
                previous_specs.pop(name, None)
                logger.info(
                    "reload_for_user: stopped removed spec ws=%s user=%s ns=%s",
                    workspace_id, user_id, name,
                )

            # ── 2. Spawn / refresh kept and added specs ────────────────
            for ns, spec in desired_specs.items():
                prev = previous_specs.get(ns)
                if prev is not None and _user_spec_equal(prev, spec) and ns in running:
                    # PR D-5 — even when the spec is unchanged AND we
                    # have an entry in ``running``, we must verify the
                    # underlying subprocess is still alive. Without
                    # this, a crashed/killed stdio process leaves a
                    # dead client object in the dict; subsequent
                    # reload calls (incl. self-heal) hit the
                    # ``unchanged → skip`` path and never respawn, so
                    # the row stays DEGRADED forever.
                    _client = running.get(ns)
                    _proc = (
                        getattr(_client, "_proc", None)
                        or getattr(_client, "process", None)
                    )
                    _alive = True
                    if _proc is not None:
                        _alive = getattr(_proc, "returncode", None) is None
                    if _alive:
                        # Unchanged AND alive — no respawn, just refresh
                        # recorded status.
                        desired_statuses[ns] = McpServerStatus(
                            name=spec.name,
                            namespace_prefix=spec.namespace_prefix,
                            transport=spec.transport,
                            enabled=spec.enabled,
                            status="ready",
                        )
                        continue
                    # Subprocess died — fall through to respawn path.
                    # Drop the stale client first so the close()
                    # below in the respawn path doesn't double-close.
                    logger.info(
                        "reload_for_user: ns=%s ws=%s user=%s — stale "
                        "client (subprocess dead, returncode=%s); "
                        "respawning",
                        ns, workspace_id, user_id,
                        getattr(_proc, "returncode", "?"),
                    )
                    running.pop(ns, None)

                if not spec.enabled:
                    desired_statuses[ns] = McpServerStatus(
                        name=spec.name,
                        namespace_prefix=spec.namespace_prefix,
                        transport=spec.transport,
                        enabled=False,
                        status="disabled",
                    )
                    # Tear down any previous client for this spec.
                    old = running.pop(ns, None)
                    if old is not None and hasattr(old, "close"):
                        try:
                            await old.close()
                        except (OSError, RuntimeError, asyncio.CancelledError):
                            pass
                    previous_specs[ns] = spec
                    continue

                # Changed or new — tear down old (if any) and spawn fresh.
                old = running.pop(ns, None)
                if old is not None and hasattr(old, "close"):
                    try:
                        await old.close()
                    except (OSError, RuntimeError, asyncio.CancelledError):
                        pass

                # PR D-1 — persist state transitions to Mongo so the
                # frontend traffic-light + PR D-5 self-healing can read
                # them without holding an in-memory copy of the manager.
                # All update_user_mcp_state calls are best-effort and
                # MUST NOT mask the underlying spawn outcome — wrap each
                # in try/except so a Mongo blip can't turn a healthy
                # spawn into a "failed" log line.
                try:
                    from dao.user_mcp_config_dao import update_user_mcp_state as _save_state
                except ImportError:
                    _save_state = None  # type: ignore[assignment]

                async def _safe_save_state(_ns: str, _state: str, _err: str = "") -> None:
                    if _save_state is None:
                        return
                    try:
                        await _save_state(
                            workspace_id=workspace_id,
                            user_id=user_id,
                            namespace_prefix=_ns,
                            state=_state,
                            last_error=_err,
                        )
                    except Exception as _persist_exc:  # noqa: BLE001
                        logger.warning(
                            "reload_for_user: persist state=%s failed for "
                            "ws=%s user=%s ns=%s: %s",
                            _state, workspace_id, user_id, _ns, _persist_exc,
                        )

                try:
                    if spec.transport == "stdio":
                        # Resolve $VAULT: references in auth_env at
                        # spawn time so a token rotation between calls
                        # is picked up automatically.
                        resolved_env = await _resolve_vault_env(
                            workspace_id, user_id,
                            desired_auth_env.get(ns) or {},
                        )
                        logger.debug(
                            "reload_for_user: spawning ns=%s env_keys=%s "
                            "cmd=%s",
                            ns,
                            sorted(resolved_env.keys()),
                            spec.command,
                        )
                        # Mark SPAWNING before the subprocess fork so a
                        # caller polling kit-status mid-handshake sees
                        # the in-flight state, not stale "healthy".
                        await _safe_save_state(ns, "spawning")
                        await self._spawn_user_stdio(running, spec, env=resolved_env)
                    else:
                        # HTTP — record the spec as the "client handle"
                        # (same convention as global ``_connect_http``).
                        running[ns] = spec
                    desired_statuses[ns] = McpServerStatus(
                        name=spec.name,
                        namespace_prefix=spec.namespace_prefix,
                        transport=spec.transport,
                        enabled=True,
                        status="ready",
                        started_at=time.time(),
                    )
                    await _safe_save_state(ns, "healthy")
                except (RuntimeError, OSError, ImportError, ValueError) as exc:
                    logger.warning(
                        "reload_for_user: spawn failed for ws=%s user=%s ns=%s: %s",
                        workspace_id, user_id, ns, exc,
                    )
                    desired_statuses[ns] = McpServerStatus(
                        name=spec.name,
                        namespace_prefix=spec.namespace_prefix,
                        transport=spec.transport,
                        enabled=True,
                        status="failed",
                        last_error=str(exc),
                    )
                    await _safe_save_state(ns, "failed", str(exc))

                previous_specs[ns] = spec

            logger.info(
                "reload_for_user: ws=%s user=%s desired=%d running=%d",
                workspace_id, user_id, len(desired_specs), len(running),
            )
            return desired_statuses

    async def _spawn_user_stdio(
        self,
        running_map: Dict[str, Any],
        spec: McpServerSpec,
        *,
        env: Optional[Dict[str, str]] = None,
    ) -> None:
        """Per-user stdio spawn — stores into ``running_map`` keyed by
        ``namespace_prefix`` rather than the global ``_clients`` dict.

        ``env`` is the resolved auth-env mapping (Vault references
        already substituted). Passed through to ``McpStdioClient`` as
        ``env_overrides`` which the client merges onto ``os.environ``
        when spawning the subprocess. Without this, MCP servers like
        ``@sentry/mcp-server`` that require ``SENTRY_ACCESS_TOKEN``
        die immediately at startup with "no access token provided".
        """
        cmd_str = shlex.join(spec.command or [])
        factory = self.stdio_client_factory or _default_stdio_client_factory
        # Pass env_overrides if the factory accepts it; older factories
        # (older tests) don't take this kwarg, so use a defensive
        # try/except. The production factory always accepts it.
        try:
            client = factory(
                command=cmd_str,
                workspace_root=self.workspace_root,
                env_overrides=env or None,
            )
        except TypeError:
            client = factory(
                command=cmd_str,
                workspace_root=self.workspace_root,
            )
        await client.start()
        # Same first-spawn timeout reasoning as ``_spawn_stdio``; expert
        # kit MCP servers commonly pull tens of MB on cold cache.
        await client.initialize(timeout=self._INITIALIZE_TIMEOUT_SEC)
        running_map[spec.namespace_prefix] = client

    def list_user_servers(
        self,
        workspace_id: str,
        user_id: str,
    ) -> List[McpServerStatus]:
        """Operator-facing snapshot of the user's MCP server statuses.

        Used by the per-request tool registry merge to decide which
        specs are healthy enough to expose to the LLM.
        """
        key = (workspace_id, user_id)
        specs = self._user_specs.get(key) or {}
        clients = self._user_clients.get(key) or {}
        out: List[McpServerStatus] = []
        for ns, spec in specs.items():
            client = clients.get(ns)
            running = (
                client is not None
                and hasattr(client, "is_running")
                and bool(client.is_running)
            )
            status_str: str
            if not spec.enabled:
                status_str = "disabled"
            elif client is None:
                status_str = "failed"
            elif hasattr(client, "is_running"):
                status_str = "ready" if running else "crashed"
            else:
                status_str = "ready"  # HTTP handle
            out.append(McpServerStatus(
                name=spec.name,
                namespace_prefix=spec.namespace_prefix,
                transport=spec.transport,
                enabled=spec.enabled,
                status=status_str,
            ))
        return out

    def get_user_client(
        self,
        workspace_id: str,
        user_id: str,
        namespace_prefix: str,
    ) -> Optional[Any]:
        """Lookup a single user stdio client / HTTP spec by prefix."""
        return (self._user_clients.get((workspace_id, user_id)) or {}).get(namespace_prefix)

    def get_user_spec(
        self,
        workspace_id: str,
        user_id: str,
        namespace_prefix: str,
    ) -> Optional[McpServerSpec]:
        return (self._user_specs.get((workspace_id, user_id)) or {}).get(namespace_prefix)

    async def list_user_tools_for(
        self,
        workspace_id: str,
        user_id: str,
        namespace_prefix: str,
    ) -> List[Dict[str, Any]]:
        client = self.get_user_client(workspace_id, user_id, namespace_prefix)
        if client is None or not hasattr(client, "list_tools"):
            return []
        try:
            tools = await client.list_tools()
            return list(tools or [])
        except (OSError, RuntimeError, ValueError) as exc:
            logger.warning(
                "list_user_tools failed ws=%s user=%s ns=%s: %s",
                workspace_id, user_id, namespace_prefix, exc,
            )
            return []


def _user_row_to_spec(row: Dict[str, Any]) -> McpServerSpec:
    """Convert a ``user_mcp_servers`` Mongo row into a validated
    :class:`McpServerSpec`. Re-uses the same Pydantic schema validation
    the operator-toml path uses — same shell-wrapper guard, same
    https-only rule.

    Field mapping:
      * ``namespace_prefix`` → both ``name`` (display) and
        ``namespace_prefix`` (tool prefix). The DAO doesn't store
        a separate display name; the prefix is unique per user
        anyway.
      * ``auth_env`` is dropped here — credential injection happens
        downstream at tool-execution time via the Vault lookup helper.
        Including it in the spec would force every per-user reload
        to round-trip Vault before validating; we defer the lookup
        to the proxy tool's ``execute`` path instead.

    **SSRF tightening (PR 4 review MEDIUM)**: the Sprint 7 schema only
    consults ``host_allowlist`` IF it's non-empty — an http spec with
    an absent / empty allowlist passes validation and would let the
    proxy hit arbitrary internal hosts. The per-user path is operator-
    declared via YAML curation today, but the install fan-out persists
    the spec into Mongo where a future SQL-injection / privilege bug
    could mutate it. Defence-in-depth: reject http transport rows
    that lack a non-empty allowlist BEFORE handing to the schema.
    """
    transport = row.get("transport") or "stdio"
    namespace_prefix = row.get("namespace_prefix") or ""
    payload: Dict[str, Any] = {
        "name": namespace_prefix or "user_mcp",
        "namespace_prefix": namespace_prefix,
        "transport": transport,
        "enabled": True,
        # Sprint S-EK-V1 PR 14 — preserve the install-time kit
        # attribution so the per-request registration helper can
        # filter to only the @-mentioned kits' tool sets.
        "source_kit_id": str(row.get("source_kit_id") or "") or None,
    }
    if transport == "stdio":
        payload["command"] = list(row.get("command") or [])
    else:
        payload["url"] = row.get("url") or ""
        host_allowlist = list(row.get("host_allowlist") or [])
        if not host_allowlist:
            raise ValueError(
                f"user_mcp_servers row ns={namespace_prefix!r}: http "
                "transport requires a non-empty host_allowlist (SSRF "
                "defence; defence-in-depth against schema permissiveness)"
            )
        payload["host_allowlist"] = host_allowlist
    return McpServerSpec(**payload)


def _user_spec_equal(a: McpServerSpec, b: McpServerSpec) -> bool:
    """Cheap equality check for change detection in ``reload_for_user``.

    Compares every field used downstream by either the spawn path
    (``transport`` / ``command`` / ``url`` / ``host_allowlist``) OR
    the user-facing status snapshot (``name``). Missing ``name`` from
    the check would let a rename slip through silently — the display
    label in ``list_user_servers`` would lag the Mongo row. Equality
    via attribute compare is intentional over ``model_dump`` because
    pydantic's ``__eq__`` would include defaults like ``timeout_s``
    that the per-user path doesn't write.
    """
    return (
        a.name == b.name
        and a.transport == b.transport
        and a.command == b.command
        and a.url == b.url
        and list(a.host_allowlist) == list(b.host_allowlist)
        and a.enabled == b.enabled
    )


# ── Vault $VAULT: env resolver (Sprint S-EK-V1 PR 10) ─────────────────


_VAULT_REF_PREFIX = "$VAULT:"
# The synthetic URL prefix kit_installer.store_credentials writes
# (mirrors agent.persona.kit_installer._VAULT_URL_PREFIX). Hard-coded
# here to avoid a layering inversion (manager → agent.persona).
_VAULT_URL_PREFIX_FOR_KIT_CREDS = "expert_kit_credential:"
_VAULT_ENC_PLAINTEXT_PREFIX = "enc:"


async def _resolve_vault_env(
    workspace_id: str,
    user_id: str,
    auth_env_template: Dict[str, str],
) -> Dict[str, str]:
    """Resolve ``$VAULT:<vault_name>`` references in an MCP spec's
    ``auth_env`` mapping to the plaintext credential stored in Vault.

    Example::

        template = {"SENTRY_ACCESS_TOKEN": "$VAULT:sentry_token"}
        → {"SENTRY_ACCESS_TOKEN": "sntryu_abc123..."}

    Resolution rules:
      * Value doesn't start with ``$VAULT:`` → passed through verbatim
        (operator can hard-code e.g. ``LOG_LEVEL: DEBUG`` in YAML).
      * Vault lookup fails / credential missing → entry DROPPED from
        the resolved env (the MCP server will start without that var
        and either degrade gracefully OR die at handshake — either
        way the user gets a clear ``spawn failed`` log instead of a
        confusing "$VAULT:foo" literal env value).
      * ``enc:`` prefix on stored value → stripped to get plaintext
        (matches the kit_installer.store_credentials convention).

    Fail-soft: any DAO / decoding error logs a warning + drops the
    entry, never raises. The caller (``_spawn_user_stdio``) will
    surface a clean spawn failure if the resulting env is incomplete.
    """
    out: Dict[str, str] = {}
    needs_vault = False
    for env_name, value in (auth_env_template or {}).items():
        v = str(value or "")
        if not v.startswith(_VAULT_REF_PREFIX):
            # Literal value — passed through. Note we DO allow operators
            # to hard-code env values in the YAML (e.g. log levels) but
            # the YAML is committed to git so secrets MUST go via Vault.
            out[env_name] = v
            continue
        needs_vault = True

    if not needs_vault:
        return out

    # Lazy Vault DAO import — keep this module loadable in unit tests
    # that don't pull Motor / Mongo. Same fail-soft pattern as
    # reload_for_user's lazy DAO import above.
    try:
        # PR-E5 — engine reads Mongo via BackendClientProvider seam.
        from dao.vault_dao import VaultDAO
        from vendor_runtime_sdk.runtime.protocols.backend_provider import get_backend_provider
        client = await get_backend_provider().get_mongo_client()
        import os as _os
        db = client[_os.environ.get("MONGO_DB_NAME") or "ai-assistant"]
        dao = VaultDAO(db)
        rows = await dao.find_by_user(workspace_id, user_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "_resolve_vault_env: vault lookup failed for ws=%s user=%s "
            "(env will be missing %d entries): %s",
            workspace_id, user_id,
            sum(1 for v in auth_env_template.values()
                if str(v or "").startswith(_VAULT_REF_PREFIX)),
            exc,
        )
        return out  # already populated with literal values

    # Build name → plaintext map from Vault rows.
    have: Dict[str, str] = {}
    for r in rows or []:
        url = str(r.get("mcp_server_url") or "")
        if not url.startswith(_VAULT_URL_PREFIX_FOR_KIT_CREDS):
            continue
        vault_name = url[len(_VAULT_URL_PREFIX_FOR_KIT_CREDS):]
        encrypted = str(r.get("encrypted_value") or "")
        # Strip the placeholder ``enc:`` prefix
        # (kit_installer.store_credentials documents this is a dev-only
        # convention; real KMS decrypt is a follow-up PR. Until then
        # we treat ``enc:`` as a "this is plaintext" marker.)
        if encrypted.startswith(_VAULT_ENC_PLAINTEXT_PREFIX):
            have[vault_name] = encrypted[len(_VAULT_ENC_PLAINTEXT_PREFIX):]
        else:
            # No ``enc:`` prefix — log + use as-is so a legacy row
            # written before the convention existed still works.
            have[vault_name] = encrypted

    for env_name, value in (auth_env_template or {}).items():
        v = str(value or "")
        if not v.startswith(_VAULT_REF_PREFIX):
            continue  # literal already in ``out``
        vault_name = v[len(_VAULT_REF_PREFIX):]
        if vault_name in have:
            out[env_name] = have[vault_name]
        else:
            logger.warning(
                "_resolve_vault_env: ws=%s user=%s missing vault credential "
                "%r for env var %r — MCP server will start without it",
                workspace_id, user_id, vault_name, env_name,
            )

    return out


__all__ = ["McpServerManager", "McpServerStatus"]
