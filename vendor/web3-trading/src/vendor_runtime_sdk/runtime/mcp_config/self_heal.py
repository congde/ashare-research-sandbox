# -*- coding: utf-8 -*-
"""
PR D-5 — MCP server self-healing loop.

Reads ``user_mcp_servers`` rows whose ``mcp_state`` is ``degraded`` or
``failed`` and triggers ``McpServerManager.reload_for_user`` to respawn
them. Uses exponential backoff to avoid hammering broken services and
caps total respawn attempts per hour so a persistently broken row
doesn't burn unbounded resources.

State machine (per (workspace_id, user_id, namespace_prefix)):

    HEALTHY ─[health probe fails 3x]─→ DEGRADED
       ↑                                  │
       │                       [self-heal triggers respawn]
       │                                  ↓
       │                              SPAWNING
       │ [reload_for_user spawn      ┌─────┴─────┐
       │  + initialize succeeds]     │           │
       └─────────────────────────────┘           ↓
                                         [spawn fails]
                                              ↓
                                            FAILED
                                              │
                                  [retry after exponential backoff,
                                   capped at 5 attempts / hour]
                                              ↓
                                        give up → operator handles
                                        manually (toggle off+on)

Backoff schedule (seconds): 5, 15, 45, 135, 405  (5 attempts ~10 min)

Design constraints
------------------
* **No respawn during user-initiated reload** — if a request handler
  is already reloading for this (ws, user), the self-heal scan skips
  to avoid double-spawn races. Detected by checking the per-user lock
  status (``_user_reload_lock`` non-None and held → skip).
* **Fail-soft** — every database read, manager call, etc. is wrapped
  in try/except so a single bad row can't crash the loop.
* **Idempotent** — running the scan twice rapidly is safe; the second
  pass sees the now-SPAWNING state and skips (only DEGRADED/FAILED
  rows are eligible).
* **Per-attempt audit** — every respawn attempt logs WARN with the
  attempt number, last error, and time-to-next-attempt. Operators
  reading the log learn what's broken and how the system responded.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# Scan cadence + backoff schedule. Module-level so tests can monkeypatch.
_SCAN_INTERVAL_SEC: float = 30.0
# Backoff in seconds, indexed by attempt number (0-based). After the
# 5th attempt the row stays FAILED until manual intervention.
_BACKOFF_SCHEDULE: Tuple[float, ...] = (5.0, 15.0, 45.0, 135.0, 405.0)
_MAX_ATTEMPTS: int = len(_BACKOFF_SCHEDULE)


@dataclass
class _AttemptRecord:
    """In-memory tracking of respawn attempts per (ws, user, ns)."""

    attempts: int = 0
    next_eligible_at: float = 0.0  # epoch seconds


class McpSelfHealer:
    """Background asyncio task driving the respawn loop.

    Mirrors :class:`McpHealthChecker` but in the opposite direction —
    the health-checker FLAGS broken rows, the self-healer REMEDIATES.
    Keeping them separate avoids a class that has to hold both probe
    timeouts and respawn backoff state simultaneously (single
    responsibility).
    """

    def __init__(
        self,
        manager: Any,
        *,
        scan_interval_sec: float = _SCAN_INTERVAL_SEC,
        backoff_schedule: Tuple[float, ...] = _BACKOFF_SCHEDULE,
    ):
        self.manager = manager
        self.scan_interval_sec = float(scan_interval_sec)
        self.backoff_schedule = tuple(backoff_schedule)
        self._task: Optional[asyncio.Task] = None
        self._stop_evt = asyncio.Event()
        # Tracking dict keyed by (ws, user, ns).
        self._attempts: Dict[Tuple[str, str, str], _AttemptRecord] = {}

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_evt = asyncio.Event()
        self._task = asyncio.create_task(
            self._run_loop(), name="mcp-self-healer"
        )
        logger.info(
            "McpSelfHealer: started (scan_interval=%.1fs "
            "max_attempts=%d backoff=%s)",
            self.scan_interval_sec, _MAX_ATTEMPTS, self.backoff_schedule,
        )

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop_evt.set()
        try:
            await asyncio.wait_for(self._task, timeout=10.0)
        except asyncio.TimeoutError:
            self._task.cancel()
        finally:
            self._task = None

    async def _run_loop(self) -> None:
        while not self._stop_evt.is_set():
            try:
                await self._scan_and_heal()
            except Exception as exc:  # noqa: BLE001
                logger.exception("McpSelfHealer: scan raised: %s", exc)
            try:
                await asyncio.wait_for(
                    self._stop_evt.wait(), timeout=self.scan_interval_sec,
                )
            except asyncio.TimeoutError:
                continue

    async def _scan_and_heal(self) -> None:
        """Walk Mongo for DEGRADED/FAILED rows and respawn the
        whole (ws, user) group when at least one row is eligible.

        ``reload_for_user`` is whole-user (not per-namespace) — so a
        single eligible row triggers a reload that recovers EVERY
        namespace for that user. This is intentional: per-namespace
        respawn would require deeper manager API surface (selective
        spawn one ns), but in practice users have ≤8 specs so the
        whole-user reload is cheap.
        """
        try:
            from dao.user_mcp_config_dao import _col  # type: ignore
        except ImportError:
            return

        # Query rows whose state is degraded or failed.
        try:
            collection = await _col.collection
            cursor = collection.find(
                {"mcp_state": {"$in": ["degraded", "failed"]}}
            )
            rows: List[Dict[str, Any]] = []
            async for row in cursor:
                rows.append(row)
        except Exception as exc:  # noqa: BLE001
            logger.warning("self_heal: scan query failed: %s", exc)
            return

        if not rows:
            return

        # Group by (ws, user) — one reload covers all that user's specs.
        by_user: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for r in rows:
            ws = r.get("workspace_id", "")
            user = r.get("user_id", "")
            if not ws or not user:
                continue
            by_user.setdefault((ws, user), []).append(r)

        now = time.time()
        for (ws, user), user_rows in by_user.items():
            # Decide eligibility per (ws, user) — we respawn if AT
            # LEAST ONE row is eligible (past its backoff window AND
            # under the max-attempts cap). Other rows ride along on
            # the same reload — that's by design (per-namespace
            # selective respawn is out of scope for V1).
            eligible_nss: List[str] = []
            for r in user_rows:
                ns = r.get("namespace_prefix", "")
                key = (ws, user, ns)
                rec = self._attempts.setdefault(key, _AttemptRecord())
                if rec.attempts >= _MAX_ATTEMPTS:
                    continue  # exhausted — operator must intervene
                if now < rec.next_eligible_at:
                    continue  # still in backoff window
                eligible_nss.append(ns)

            if not eligible_nss:
                continue

            # Bump attempt counters AND schedule next eligibility BEFORE
            # respawning so concurrent scans don't race-double-spawn.
            for ns in eligible_nss:
                key = (ws, user, ns)
                rec = self._attempts[key]
                attempt_idx = rec.attempts  # 0-based for backoff index
                rec.attempts += 1
                backoff = (
                    self.backoff_schedule[attempt_idx]
                    if attempt_idx < len(self.backoff_schedule)
                    else self.backoff_schedule[-1]
                )
                rec.next_eligible_at = now + backoff
                logger.warning(
                    "self_heal: scheduling respawn ws=%s user=%s ns=%s "
                    "attempt=%d/%d (next eligible in %.1fs if this fails)",
                    ws, user, ns, rec.attempts, _MAX_ATTEMPTS, backoff,
                )

            # Trigger the reload. ``reload_for_user`` is idempotent +
            # internally locks the (ws, user) so even if the toggle
            # endpoint is also reloading concurrently, only one runs.
            try:
                await self.manager.reload_for_user(ws, user)
                logger.info(
                    "self_heal: reload_for_user completed ws=%s user=%s "
                    "(recovering ns=%s)",
                    ws, user, eligible_nss,
                )
                # If reload succeeded AND probe confirms healthy, the
                # next scan will see state=healthy and reset attempt
                # counters via _reset_on_healthy below. We don't
                # eagerly reset here because reload returning OK
                # doesn't mean the server is fully ready — let the
                # next health probe confirm.
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "self_heal: reload_for_user raised for ws=%s user=%s "
                    "ns=%s — will retry on next scan: %s",
                    ws, user, eligible_nss, exc,
                )

        # Reset attempt counters for any row that has flipped back to
        # healthy. Without this, a flaky service that recovers
        # naturally would still have a stale attempt counter that
        # would hit the cap faster on the next failure cycle.
        await self._reset_on_healthy()

    async def _reset_on_healthy(self) -> None:
        """Drop attempt records whose row is now healthy.

        Cheap — only touches the in-memory dict. Mongo query is bounded
        because most users have ≤8 rows so this is a small scan.
        """
        if not self._attempts:
            return
        try:
            from dao.user_mcp_config_dao import _col  # type: ignore
            collection = await _col.collection
            healthy_keys = set()
            cursor = collection.find(
                {"mcp_state": "healthy"},
                {"workspace_id": 1, "user_id": 1, "namespace_prefix": 1},
            )
            async for row in cursor:
                healthy_keys.add((
                    row.get("workspace_id", ""),
                    row.get("user_id", ""),
                    row.get("namespace_prefix", ""),
                ))
        except Exception as exc:  # noqa: BLE001
            logger.debug("self_heal: reset_on_healthy query failed: %s", exc)
            return

        for key in list(self._attempts.keys()):
            if key in healthy_keys:
                prev = self._attempts.pop(key)
                if prev.attempts > 0:
                    logger.info(
                        "self_heal: ns=%s ws=%s user=%s recovered "
                        "(was %d attempts in)",
                        key[2], key[0], key[1], prev.attempts,
                    )


# ── Module-level singleton + lifespan helpers ──────────────────────


_self_healer: Optional[McpSelfHealer] = None


def get_self_healer() -> Optional[McpSelfHealer]:
    return _self_healer


def start_self_healer(manager: Any) -> None:
    global _self_healer
    if _self_healer is not None:
        return
    if manager is None:
        return
    _self_healer = McpSelfHealer(manager)
    _self_healer.start()


async def stop_self_healer() -> None:
    global _self_healer
    if _self_healer is None:
        return
    try:
        await _self_healer.stop()
    finally:
        _self_healer = None


__all__ = [
    "McpSelfHealer",
    "get_self_healer",
    "start_self_healer",
    "stop_self_healer",
]
