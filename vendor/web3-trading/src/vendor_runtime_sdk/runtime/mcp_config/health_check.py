# -*- coding: utf-8 -*-
"""
PR D-4 — MCP server health-check loop.

Background asyncio task that periodically probes every running per-user
MCP server (stdio + http) with a cheap ``tools/list`` JSON-RPC call.
Results are reconciled into Mongo's ``user_mcp_servers.mcp_state`` so:

* The ``GET /personas/{id}/kit-status`` endpoint surfaces the live
  state to the frontend traffic-light UI.
* PR D-5's self-healing loop has a durable source of truth for
  "this row is unhealthy → respawn it".
* Operators can ``mongo find({mcp_state: {$ne: "healthy"}})`` to triage
  problem rows across users without holding any in-memory snapshot.

Design constraints
------------------
* **Fail-soft** — a single probe failure must not raise. The loop is
  best-effort observability; bugs in the probe path must never
  destabilise the request handler.
* **Bounded per-probe latency** — 5 s timeout per JSON-RPC round trip
  so a hung MCP server can't stall the loop indefinitely.
* **Consecutive-failure threshold** — 3 missed probes before flipping
  ``healthy → degraded``. Single transient failures (e.g. process
  briefly paused under load) don't generate false alarms.
* **Process-liveness short-circuit** — if the subprocess has exited,
  mark ``failed`` immediately (don't wait for 3 consecutive RPC
  timeouts when we already know the answer).
* **Per-(ws, user, ns) bookkeeping** — the consecutive-failure counter
  is held in-memory keyed by the same tuple the manager uses
  (``_user_clients[(ws, user)][ns]``). Process restart resets all
  counters which is intentional — fresh runs deserve a clean slate.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


# Probe cadence and thresholds — exposed as module constants so tests
# can monkeypatch them without subclassing the checker.
_PROBE_INTERVAL_SEC: float = 30.0
_PROBE_TIMEOUT_SEC: float = 5.0
_CONSECUTIVE_FAIL_THRESHOLD: int = 3


class McpHealthChecker:
    """Owns the asyncio task that probes every running MCP server.

    Construction is cheap. Call :meth:`start` in app lifespan after the
    MCP manager is bootstrapped; call :meth:`stop` at shutdown. The
    checker reads the manager's ``_user_clients`` dict on every tick —
    it never holds a stale snapshot, so per-user reloads (PR D-3) take
    effect on the next probe automatically.

    Attributes:
        manager: McpServerManager instance to probe through.
        interval_sec: seconds between probe sweeps (default 30).
        timeout_sec: per-probe JSON-RPC timeout (default 5).
        fail_threshold: consecutive failures to flip healthy→degraded.
    """

    def __init__(
        self,
        manager: Any,
        *,
        interval_sec: float = _PROBE_INTERVAL_SEC,
        timeout_sec: float = _PROBE_TIMEOUT_SEC,
        fail_threshold: int = _CONSECUTIVE_FAIL_THRESHOLD,
    ):
        self.manager = manager
        self.interval_sec = float(interval_sec)
        self.timeout_sec = float(timeout_sec)
        self.fail_threshold = int(fail_threshold)
        self._task: Optional[asyncio.Task] = None
        # _fail_counts[(ws, user, ns)] -> consecutive failure count.
        # Reset on every successful probe.
        self._fail_counts: Dict[Tuple[str, str, str], int] = {}
        self._stop_evt = asyncio.Event()

    def start(self) -> None:
        """Schedule the background task. Idempotent — re-calling is a
        no-op if the task is already running.
        """
        if self._task is not None and not self._task.done():
            return
        self._stop_evt = asyncio.Event()
        self._task = asyncio.create_task(
            self._run_loop(), name="mcp-health-checker"
        )
        logger.info(
            "McpHealthChecker: started (interval=%.1fs timeout=%.1fs "
            "fail_threshold=%d)",
            self.interval_sec, self.timeout_sec, self.fail_threshold,
        )

    async def stop(self) -> None:
        """Signal the loop to exit and await termination.

        Honours a short grace period so any in-flight probe finishes.
        """
        if self._task is None:
            return
        self._stop_evt.set()
        try:
            await asyncio.wait_for(self._task, timeout=self.timeout_sec + 2.0)
        except asyncio.TimeoutError:
            logger.warning(
                "McpHealthChecker: stop timeout; cancelling task"
            )
            self._task.cancel()
        finally:
            self._task = None

    async def _run_loop(self) -> None:
        """Main loop — sleep, probe all, sleep, ...

        Exits when ``_stop_evt`` is set. ANY exception inside the loop
        is caught and logged; the loop continues. This is observability
        infrastructure — it must NEVER bring down the app.
        """
        while not self._stop_evt.is_set():
            try:
                await self._probe_all()
            except Exception as exc:  # noqa: BLE001 — must not crash
                logger.exception(
                    "McpHealthChecker: _probe_all raised: %s", exc,
                )
            # Sleep with cancellation support — wait_for of stop_evt
            # so stop() returns within ~1 tick instead of waiting the
            # full interval.
            try:
                await asyncio.wait_for(
                    self._stop_evt.wait(), timeout=self.interval_sec,
                )
            except asyncio.TimeoutError:
                continue

    async def _probe_all(self) -> None:
        """Walk every running per-user client and probe it."""
        try:
            from dao.user_mcp_config_dao import update_user_mcp_state
        except ImportError:
            update_user_mcp_state = None  # type: ignore[assignment]

        # Snapshot the manager's per-user clients dict — a stale view
        # is fine (one tick lag is acceptable; the next sweep catches
        # whatever changed). Avoiding the lock prevents head-of-line
        # blocking against ongoing reload_for_user calls.
        user_clients = getattr(self.manager, "_user_clients", {}) or {}
        # Copy keys to a list so concurrent mutation doesn't blow up
        # the for-loop with RuntimeError.
        for (workspace_id, user_id) in list(user_clients.keys()):
            clients = user_clients.get((workspace_id, user_id)) or {}
            for ns in list(clients.keys()):
                client = clients.get(ns)
                if client is None:
                    continue
                ok, error_msg = await self._probe_one(client)
                key = (workspace_id, user_id, ns)
                if ok:
                    self._fail_counts.pop(key, None)
                    if update_user_mcp_state is not None:
                        try:
                            await update_user_mcp_state(
                                workspace_id=workspace_id,
                                user_id=user_id,
                                namespace_prefix=ns,
                                state="healthy",
                            )
                        except Exception as exc:  # noqa: BLE001
                            logger.debug(
                                "health_check: persist healthy state "
                                "failed for ws=%s user=%s ns=%s: %s",
                                workspace_id, user_id, ns, exc,
                            )
                    continue

                # Failure path.
                count = self._fail_counts.get(key, 0) + 1
                self._fail_counts[key] = count
                if count < self.fail_threshold:
                    logger.debug(
                        "health_check: probe failed ws=%s user=%s ns=%s "
                        "count=%d/%d err=%s",
                        workspace_id, user_id, ns,
                        count, self.fail_threshold, error_msg,
                    )
                    continue
                # Threshold breached — flip to degraded (PR 5 picks
                # this up and triggers respawn). Reset count so we
                # don't spam DAO writes every probe.
                self._fail_counts[key] = 0
                logger.warning(
                    "health_check: ns=%s ws=%s user=%s — %d consecutive "
                    "probe failures, marking DEGRADED: %s",
                    ns, workspace_id, user_id, self.fail_threshold,
                    error_msg,
                )
                if update_user_mcp_state is not None:
                    try:
                        await update_user_mcp_state(
                            workspace_id=workspace_id,
                            user_id=user_id,
                            namespace_prefix=ns,
                            state="degraded",
                            last_error=error_msg or "probe failure",
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "health_check: persist degraded state "
                            "failed for ws=%s user=%s ns=%s: %s",
                            workspace_id, user_id, ns, exc,
                        )

    async def _probe_one(self, client: Any) -> Tuple[bool, str]:
        """Send ``tools/list`` to one client. Returns (ok, error_msg).

        Considered FAILED on any of:
            * the subprocess has exited (stdio only)
            * the RPC raises an exception
            * the RPC times out after ``self.timeout_sec``

        The client must expose ``list_tools()`` (true for both
        ``McpStdioClient`` and HTTP wrapper handles). HTTP "specs"
        recorded by the manager as the bare ``spec`` object don't have
        ``list_tools`` — they're treated as healthy by default (no
        cheap probe exists; HTTP servers self-report errors during
        actual tool calls).
        """
        # HTTP handles are the spec itself — manager.py L509 stashes
        # ``spec`` into ``running[ns]`` for the http transport. They
        # don't have ``list_tools``; skip them.
        if not hasattr(client, "list_tools"):
            return True, ""

        # Stdio liveness short-circuit — if the subprocess has exited,
        # don't bother trying to write to a closed pipe.
        proc = getattr(client, "_proc", None) or getattr(client, "process", None)
        if proc is not None:
            returncode = getattr(proc, "returncode", None)
            if returncode is not None:
                return False, f"subprocess exited (returncode={returncode})"

        try:
            await asyncio.wait_for(
                client.list_tools(), timeout=self.timeout_sec,
            )
            return True, ""
        except asyncio.TimeoutError:
            return False, f"list_tools timed out after {self.timeout_sec:.1f}s"
        except Exception as exc:  # noqa: BLE001 — categorize at consumer
            # Truncate to 256 chars so a pathological provider stderr
            # dump doesn't bloat Mongo across thousands of rows.
            return False, f"{type(exc).__name__}: {str(exc)[:256]}"


# ── Module-level singleton + lifespan helpers ──────────────────────


_health_checker: Optional[McpHealthChecker] = None


def get_health_checker() -> Optional[McpHealthChecker]:
    """App-state accessor used by tests / status endpoints."""
    return _health_checker


def start_health_checker(manager: Any) -> None:
    """Boot-time helper: construct + start the checker for a manager.

    Idempotent — if a checker is already running, this is a no-op.
    Returns None on the toggle-OFF / manager=None / Celery-worker
    contexts where the checker shouldn't run.
    """
    global _health_checker
    if _health_checker is not None:
        return
    if manager is None:
        return
    _health_checker = McpHealthChecker(manager)
    _health_checker.start()


async def stop_health_checker() -> None:
    """Shutdown helper — best-effort stop + clear singleton."""
    global _health_checker
    if _health_checker is None:
        return
    try:
        await _health_checker.stop()
    finally:
        _health_checker = None


__all__ = [
    "McpHealthChecker",
    "get_health_checker",
    "start_health_checker",
    "stop_health_checker",
]
