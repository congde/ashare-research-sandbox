# -*- coding: utf-8 -*-
"""
TaskTokenLifecycle — bind per-task deploy-token issue/revoke to
``agent_task_queue`` rows for Spec PR 23 (§Gap 2 — S2 / Workflow D).

:class:`EphemeralGitTokenIssuer` already handles the atomic mint +
rollback + idempotent-revoke primitive.  What Spec PR 23 adds is the
**task-row binding**:

  * ``issue_for_task(task_id=...)`` — idempotent per task; a second call
    within the same task returns the existing issue instead of minting
    again.
  * ``revoke_for_task(task_id=..., reason=...)`` — looks up the issue,
    delegates to :meth:`EphemeralGitTokenIssuer.revoke`, drops the row
    from the in-memory registry.
  * ``sweep_expired()`` — back-stop that revokes any issue whose
    ``expires_at`` has passed, in case the dispatcher path crashed
    before its own terminal revoke fired.  Orphan window is capped by
    the plan's 60-minute ``MAX_TTL_SEC``.

Fail-closed semantics
---------------------

  * ``issue_for_task`` surfaces the underlying provider exception
    unchanged.  The dispatcher is expected to treat this as a terminal
    task failure for WRITE-capable agents and (per plan §Gap 2) fall
    back to local-snapshot read-only mode for read-only agents.
  * ``revoke_for_task`` NEVER raises; a revoke miss is logged + audited
    but cannot stall task completion — the issuer's own rollback /
    ``revoke_failed`` audit trail is the single source of truth for
    operator follow-up.

Isolation
---------

The registry is keyed by ``task_id`` (opaque str).  Tasks never share
issues.  The lifecycle holds no references across revokes, so
idempotent re-calls for the same task after revoke mint fresh tokens
only if explicitly re-issued — matching the one-issue-per-task
contract the dispatcher relies on.

This module is toggle-gated: :func:`get_task_token_lifecycle` returns
``None`` when the ``vault_ephemeral_git_token`` module toggle is OFF or
when GitLab admin credentials are not configured.  Callers must handle
the ``None`` case and skip token issuance entirely.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import TYPE_CHECKING, Dict, Optional, Sequence, Tuple

from vendor_runtime_sdk.runtime.config.toggles import get_toggles
from vendor_runtime_sdk.runtime.vault.ephemeral_git_token import (
    EphemeralGitIssue,
    EphemeralGitTokenIssuer,
)

if TYPE_CHECKING:  # pragma: no cover
    from vendor_runtime_sdk.agent.git_acl import AgentGitAclEntry  # noqa: F401

logger = logging.getLogger(__name__)

__all__ = [
    "TaskTokenLifecycle",
    "get_task_token_lifecycle",
    "reset_task_token_lifecycle",
]


class TaskTokenLifecycle:
    """Task-scoped wrapper over :class:`EphemeralGitTokenIssuer`.

    Parameters
    ----------
    issuer:
        Underlying issuer.  The lifecycle delegates all provider-facing
        work here; it only maintains a ``task_id → issue`` registry.
    """

    def __init__(self, issuer: EphemeralGitTokenIssuer) -> None:
        self._issuer = issuer
        self._registry: Dict[str, EphemeralGitIssue] = {}
        self._lock = asyncio.Lock()

    async def issue_for_task(
        self,
        *,
        task_id: str,
        agent_id: str,
        user_id: str,
        workspace_id: str,
        entries: "Sequence[AgentGitAclEntry]",
        ttl_sec: Optional[int] = None,
    ) -> EphemeralGitIssue:
        """Mint (or return the existing) issue for this task.

        Idempotent: a second call with the same ``task_id`` returns the
        active issue without re-minting.  Callers that need a fresh
        scope after a revoke must invoke ``revoke_for_task`` first.

        Raises
        ------
        ValueError
            When ``task_id`` is empty/whitespace, or when the underlying
            issuer rejects the input (non-positive ttl, empty entries).
        Exception
            Propagates provider exceptions from the issuer unchanged
            after atomic rollback of any partially-minted tokens.
        """
        if not task_id or not task_id.strip():
            raise ValueError("task_id must be a non-empty string")

        async with self._lock:
            existing = self._registry.get(task_id)
            if existing is not None and existing.revoked_at is None:
                return existing

        issue = await self._issuer.issue(
            agent_id=agent_id,
            user_id=user_id,
            workspace_id=workspace_id,
            entries=entries,
            ttl_sec=ttl_sec,
        )

        async with self._lock:
            # Recheck in case of concurrent issue_for_task races — the
            # first winner's record stays; runner-up revokes its own.
            current = self._registry.get(task_id)
            if current is not None and current.revoked_at is None:
                await self._issuer.revoke(
                    issue,
                    reason=f"task_token_lifecycle:concurrent_issue_loser task_id={task_id}",
                )
                return current
            self._registry[task_id] = issue
        return issue

    async def revoke_for_task(self, task_id: str, reason: str = "") -> bool:
        """Revoke the issue for ``task_id``; never raises.

        Returns
        -------
        bool
            True if an active issue was found + revoked (or already
            revoked but still registered); False if no issue existed.
        """
        if not task_id:
            return False
        async with self._lock:
            issue = self._registry.pop(task_id, None)
        if issue is None:
            return False
        try:
            await self._issuer.revoke(issue, reason=reason)
        except Exception:  # noqa: BLE001 — revoke is best-effort
            logger.warning(
                "task_token_lifecycle.revoke_for_task raised task_id=%s",
                task_id,
                exc_info=True,
            )
            return True
        return True

    async def sweep_expired(self, *, now: Optional[float] = None) -> int:
        """Revoke any issue past its ``expires_at``; return count revoked.

        Cheap to call on a timer; safe under concurrent ``issue_for_task``
        / ``revoke_for_task`` since all registry mutations hold the lock.
        """
        cutoff = now if now is not None else time.time()
        async with self._lock:
            stale = [
                (tid, iss)
                for tid, iss in self._registry.items()
                if iss.expires_at <= cutoff
            ]
            for tid, _ in stale:
                self._registry.pop(tid, None)

        revoked = 0
        for task_id, issue in stale:
            try:
                await self._issuer.revoke(issue, reason=f"sweep_expired task_id={task_id}")
                revoked += 1
            except Exception:  # noqa: BLE001
                logger.warning(
                    "task_token_lifecycle.sweep_expired revoke failed task_id=%s",
                    task_id,
                    exc_info=True,
                )
        return revoked

    async def snapshot_active(self) -> Tuple[EphemeralGitIssue, ...]:
        """Immutable snapshot of currently-registered issues (metrics)."""
        async with self._lock:
            return tuple(self._registry.values())


# ── Singleton factory ──────────────────────────────────────────────────────


_LIFECYCLE_SINGLETON: Optional[TaskTokenLifecycle] = None


def get_task_token_lifecycle() -> Optional[TaskTokenLifecycle]:
    """Return the process-wide :class:`TaskTokenLifecycle` or None.

    Returns ``None`` when:

      * ``vault_ephemeral_git_token`` toggle is OFF (default); callers
        must skip token issuance and fall through to the legacy path.
      * Required GitLab configuration is missing
        (``GITLAB_BASE_URL`` / ``GITLAB_ADMIN_TOKEN``); we refuse to
        construct a half-configured issuer so an admin misstep does
        not silently degrade to no-tokens in production.

    The first successful call caches the instance.
    """
    global _LIFECYCLE_SINGLETON
    toggles = get_toggles()
    if not toggles.is_enabled("vault_ephemeral_git_token"):
        return None
    if _LIFECYCLE_SINGLETON is not None:
        return _LIFECYCLE_SINGLETON

    base_url = os.environ.get("GITLAB_BASE_URL", "").strip()
    admin_token = os.environ.get("GITLAB_ADMIN_TOKEN", "").strip()
    if not base_url or not admin_token:
        logger.warning(
            "task_token_lifecycle: GITLAB_BASE_URL/GITLAB_ADMIN_TOKEN missing; "
            "vault_ephemeral_git_token toggle ON but lifecycle disabled until config present"
        )
        return None

    # Local import so modules that never hit this code path do not drag
    # httpx into their import graph.
    from vendor_runtime_sdk.libs.gitlab_client import GitLabClient

    client = GitLabClient(base_url=base_url, admin_token=admin_token)
    issuer = EphemeralGitTokenIssuer(
        gitlab_client=client,
        audit_logger=_audit_sink,
    )
    _LIFECYCLE_SINGLETON = TaskTokenLifecycle(issuer)
    return _LIFECYCLE_SINGLETON


def reset_task_token_lifecycle() -> None:
    """Drop the cached singleton — tests and process teardown."""
    global _LIFECYCLE_SINGLETON
    _LIFECYCLE_SINGLETON = None


# ── Audit sink ─────────────────────────────────────────────────────────────


def _audit_sink(record: dict) -> None:
    """Default audit sink: structured INFO log.

    Production deployments may patch this via
    :meth:`TaskTokenLifecycle` construction to forward into the central
    ``audit_log`` table once the DAO for ephemeral-token events is in
    place — tracked separately from PR 23's HTTP lifecycle cut.
    """
    try:
        event = record.get("event", "unknown")
        logger.info(
            "ephemeral_git_token %s record=%s",
            event,
            {k: v for k, v in record.items() if k != "token_value"},
        )
    except Exception:  # noqa: BLE001 — audit must never raise upstream
        logger.debug("task_token_lifecycle: audit sink failed", exc_info=True)
