# -*- coding: utf-8 -*-
"""
EphemeralGitTokenIssuer — per-task repo-scoped deploy tokens (§Gap 2 — S2).

Replaces user-scoped PATs with short-lived, repo-scoped deploy tokens
minted at task start and revoked at task end.  Each agent's validated
``allowed_git_repos`` is used as the scope; the provider (GitLab today,
Bitbucket possible) is abstracted behind the narrow ``_GitLabClient``
Protocol so tests inject an in-memory fake and production wires the real
HTTP client.

Design invariants
-----------------

* **Atomic issue** — if any ``mint_deploy_token`` call raises, every
  previously-minted token in the same batch is revoked.  An agent never
  runs with a half-provisioned scope ("fail-closed").
* **Rollback tolerance** — a revoke failure during rollback does not
  mask the original mint error; the orphan is surfaced via a structured
  audit event for operator follow-up.
* **Idempotent revoke** — the first ``revoke(issue, reason=...)`` wins;
  subsequent calls are no-ops at the provider level, and ``revoke_reason``
  preserves the original.
* **TTL cap** — plan locks a 60-minute ceiling (``MAX_TTL_SEC``); zero,
  negative, or above-cap requests are rejected at issue time.

All decisions — issue, issue-failed, revoke, revoke-failed, orphan —
emit a structured audit record for the compliance trail called out in
plan §Gap 2.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, List, Optional, Protocol, Sequence, runtime_checkable

from vendor_runtime_sdk.agent.git_acl import AgentGitAclEntry

# PR-E4b (SDK extraction §5 PR-E4b): GitAccessLevel is re-exported from
# the UserGitPermissionsRepository Protocol module.  Engine code
# consumes it via the Protocol surface instead of touching dao.mysql.*.
from vendor_runtime_sdk.runtime.protocols.user_git_permissions_repository import GitAccessLevel

logger = logging.getLogger(__name__)

__all__ = [
    "MAX_TTL_SEC",
    "EphemeralGitIssue",
    "EphemeralGitTokenIssuer",
    "MintedDeployToken",
]


# ── Constants ──────────────────────────────────────────────────────────────


MAX_TTL_SEC: int = 3600
"""Plan §Gap 2 hard cap for per-task deploy-token lifetime (60 min)."""


# ── DTOs ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MintedDeployToken:
    """A single provider-side deploy-token handle.

    ``token_value`` is the opaque secret used by git clients (injected
    into the environment via Vault); ``token_id`` is the provider's
    handle required for the eventual revoke call.
    """

    repo: str
    access: GitAccessLevel
    token_id: str
    token_value: str
    expires_at: float


@dataclass
class EphemeralGitIssue:
    """Aggregate record of a single ``issue`` call.

    Mutable because revoke semantics stamp ``revoked_at`` / ``revoke_reason``
    on the same instance — the caller holds this object across the task
    lifecycle and hands it back to :meth:`EphemeralGitTokenIssuer.revoke`.
    """

    issue_id: str
    agent_id: str
    user_id: str
    workspace_id: str
    tokens: List[MintedDeployToken]
    issued_at: float
    expires_at: float
    revoked_at: Optional[float] = None
    revoke_reason: str = ""


# ── Provider Protocol ──────────────────────────────────────────────────────


@runtime_checkable
class _GitLabClient(Protocol):
    """Narrow Protocol for the deploy-token provider surface."""

    async def mint_deploy_token(
        self, repo: str, access: GitAccessLevel, ttl_sec: int
    ) -> MintedDeployToken: ...

    async def revoke_deploy_token(self, repo: str, token_id: str) -> bool: ...


_AuditLogger = Callable[[dict], None]


# ── Issuer ─────────────────────────────────────────────────────────────────


class EphemeralGitTokenIssuer:
    """Mint + revoke repo-scoped deploy tokens with atomic, audited
    semantics.

    Parameters
    ----------
    gitlab_client:
        Duck-typed provider implementing :class:`_GitLabClient`.
    audit_logger:
        Sync ``dict -> None`` sink for audit records.  Exceptions from
        the sink are swallowed — audit delivery must never poison the
        issue / revoke path.
    default_ttl_sec:
        Used when :meth:`issue` is called without an explicit ``ttl_sec``.
        Must be in ``(0, MAX_TTL_SEC]``.
    """

    def __init__(
        self,
        *,
        gitlab_client: _GitLabClient,
        audit_logger: Optional[_AuditLogger] = None,
        default_ttl_sec: int = MAX_TTL_SEC,
    ) -> None:
        if not (0 < default_ttl_sec <= MAX_TTL_SEC):
            raise ValueError(
                f"default_ttl_sec must be in (0, {MAX_TTL_SEC}], got {default_ttl_sec}"
            )
        self._client = gitlab_client
        self._audit_logger = audit_logger
        self._default_ttl_sec = default_ttl_sec

    # ── Public API ────────────────────────────────────────────────────

    async def issue(
        self,
        *,
        agent_id: str,
        user_id: str,
        workspace_id: str,
        entries: Sequence[AgentGitAclEntry],
        ttl_sec: Optional[int] = None,
    ) -> EphemeralGitIssue:
        """Mint one deploy token per entry, atomically.

        Raises
        ------
        ValueError
            When ``ttl_sec`` is non-positive or above ``MAX_TTL_SEC``,
            or when ``entries`` is empty (zero-scope tokens are a logic
            bug, not a valid config).
        Exception
            Propagates the original provider exception after rolling
            back any successfully-minted tokens.
        """
        effective_ttl = ttl_sec if ttl_sec is not None else self._default_ttl_sec
        if not isinstance(effective_ttl, int) or effective_ttl <= 0:
            raise ValueError(
                f"ttl_sec must be a positive integer, got {effective_ttl!r}"
            )
        if effective_ttl > MAX_TTL_SEC:
            raise ValueError(
                f"ttl_sec {effective_ttl} exceeds MAX_TTL_SEC={MAX_TTL_SEC}"
            )
        if not entries:
            raise ValueError(
                "entries must be a non-empty sequence; refusing to issue a "
                "zero-scope token"
            )

        issue_id = f"ephem-{uuid.uuid4().hex}"
        issued_at = time.time()
        minted: List[MintedDeployToken] = []

        try:
            for entry in entries:
                token = await self._client.mint_deploy_token(
                    entry.repo, entry.access, effective_ttl
                )
                minted.append(token)
        except Exception as exc:
            # Atomic rollback — revoke every successfully-minted token.
            await self._rollback(minted, issue_id=issue_id, cause=str(exc))
            self._audit(
                {
                    "event": "issue_failed",
                    "issue_id": issue_id,
                    "agent_id": agent_id,
                    "user_id": user_id,
                    "workspace_id": workspace_id,
                    "error": str(exc),
                    "minted_before_failure": [t.token_id for t in minted],
                    "ts": time.time(),
                }
            )
            raise

        expires_at = issued_at + effective_ttl
        issue = EphemeralGitIssue(
            issue_id=issue_id,
            agent_id=agent_id,
            user_id=user_id,
            workspace_id=workspace_id,
            tokens=minted,
            issued_at=issued_at,
            expires_at=expires_at,
        )
        self._audit(
            {
                "event": "issue",
                "issue_id": issue_id,
                "agent_id": agent_id,
                "user_id": user_id,
                "workspace_id": workspace_id,
                "repos": [t.repo for t in minted],
                "token_ids": [t.token_id for t in minted],
                "ttl_sec": effective_ttl,
                "expires_at": expires_at,
                "ts": issued_at,
            }
        )
        return issue

    async def revoke(
        self, issue: EphemeralGitIssue, reason: str = ""
    ) -> None:
        """Best-effort revoke fan-out; idempotent on the same issue."""
        if issue.revoked_at is not None:
            # Idempotent — first revoke wins; do not re-invoke provider.
            return

        failures: List[dict] = []
        for token in issue.tokens:
            try:
                await self._client.revoke_deploy_token(token.repo, token.token_id)
            except Exception as exc:  # noqa: BLE001 — best-effort fan-out
                failures.append(
                    {
                        "token_id": token.token_id,
                        "repo": token.repo,
                        "error": str(exc),
                    }
                )
                self._audit(
                    {
                        "event": "revoke_failed",
                        "issue_id": issue.issue_id,
                        "agent_id": issue.agent_id,
                        "token_id": token.token_id,
                        "repo": token.repo,
                        "error": str(exc),
                        "ts": time.time(),
                    }
                )

        issue.revoked_at = time.time()
        issue.revoke_reason = reason
        self._audit(
            {
                "event": "revoke",
                "issue_id": issue.issue_id,
                "agent_id": issue.agent_id,
                "user_id": issue.user_id,
                "workspace_id": issue.workspace_id,
                "reason": reason,
                "token_ids": [t.token_id for t in issue.tokens],
                "failed_revokes": failures,
                "ts": issue.revoked_at,
            }
        )

    # ── Helpers ───────────────────────────────────────────────────────

    async def _rollback(
        self,
        minted: Sequence[MintedDeployToken],
        *,
        issue_id: str,
        cause: str,
    ) -> None:
        """Revoke all tokens minted before the failure; tolerate partial
        rollback failure by emitting ``orphan_token`` audit records so
        operators can clean up manually.
        """
        for token in minted:
            try:
                await self._client.revoke_deploy_token(token.repo, token.token_id)
            except Exception as exc:  # noqa: BLE001 — orphan, not a fatal
                self._audit(
                    {
                        "event": "orphan_token",
                        "issue_id": issue_id,
                        "token_id": token.token_id,
                        "repo": token.repo,
                        "cause": cause,
                        "rollback_error": str(exc),
                        "ts": time.time(),
                    }
                )

    def _audit(self, record: dict) -> None:
        if self._audit_logger is None:
            return
        try:
            self._audit_logger(record)
        except Exception:  # noqa: BLE001 — audit must not break issue/revoke
            logger.warning(
                "EphemeralGitTokenIssuer: audit logger raised", exc_info=True
            )
