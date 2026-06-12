# -*- coding: utf-8 -*-
"""
GitRepoAclHook — fail-closed git ACL guard (§Gap 2 — S2).

Runs as a ``PreToolUse`` hook inside the existing ToolHookMiddleware chain
(``src/runtime/hooks/tool_hooks.py``).  For any tool call whose ``command``
argument begins with ``git``, the hook:

  1. Classifies the subcommand into one of four buckets using
     :func:`classify_git_command` — read / write / hitl / forbidden.
  2. Resolves the target repository from either an explicit
     ``_target_repo`` hint or, for ``git clone``, by URL parsing.
  3. Checks the local permission snapshot (``user_git_permissions``) via
     the injected :class:`UserGitPermissionsDao`-shaped object.
  4. For write operations, optionally re-verifies with a live GitLab API
     call supplied as ``gitlab_write_verifier``.
  5. Emits a structured audit record for every decision (allow / deny /
     hitl / forbidden / error).

All error paths fail **closed**: a DAO exception, GitLab outage, bad
classification, or unresolvable repo results in ``proceed=False`` rather
than falling through to unguarded execution.  The only case that lets a
call pass without inspection is a command that is not a ``git`` invocation
— the hook is designed to be stacked alongside other tool hooks and must
not interfere with non-git traffic.

Command classification is externalised as a plain sync function so unit
tests and callers outside the hook can reuse it (e.g. the Vault scope
resolver that needs to pre-compute repo access before minting a token).
"""

from __future__ import annotations

import logging
import re
import shlex
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, Protocol, runtime_checkable

from vendor_runtime_sdk.runtime.hooks.tool_hooks import PostHookResult, PreHookResult

# PR-E4b (SDK extraction §5 PR-E4b): GitAccessLevel + access-level
# comparison helper are now sourced via the UserGitPermissionsRepository
# Protocol module.  ``GitAccessLevel`` is re-exported from the Protocol
# module; ``allows`` is the pure-function variant ``allows_pure``
# exposed under the public name ``allows`` so call sites don't change.
from vendor_runtime_sdk.runtime.protocols.user_git_permissions_repository import (
    GitAccessLevel,
)
from vendor_runtime_sdk.runtime.protocols.user_git_permissions_repository import (
    allows_pure as allows,
)

logger = logging.getLogger(__name__)

__all__ = [
    "GitCommandClassification",
    "GitRepoAclHook",
    "classify_git_command",
]


# ── Classification primitives ───────────────────────────────────────────


_READ_SUBCOMMANDS: frozenset[str] = frozenset(
    {"clone", "status", "diff", "log", "fetch", "ls-remote", "show"}
)

_WRITE_SUBCOMMANDS: frozenset[str] = frozenset(
    {"add", "commit", "branch", "pull"}
)

_HITL_SUBCOMMANDS: frozenset[str] = frozenset(
    {"merge", "cherry-pick", "revert"}
)


@dataclass(frozen=True)
class GitCommandClassification:
    """Outcome of :func:`classify_git_command`."""

    subcommand: str
    category: str  # read | write | hitl | forbidden | unknown
    reason: str = ""


def classify_git_command(cmd: str) -> GitCommandClassification:
    """Classify a git invocation against the §Gap 2 whitelist / blacklist.

    The classifier is intentionally strict: any subcommand not enumerated
    in the plan's read / write / HITL lists returns ``category="unknown"``
    so the hook can fail closed by default.  Forbidden combinations —
    ``push --force``, ``tag -f``, ``submodule``, etc. — short-circuit
    before the whitelist is consulted.
    """
    try:
        parts = shlex.split(cmd)
    except ValueError as exc:
        # e.g. unbalanced quotes — treat as unparseable, deny downstream.
        return GitCommandClassification("", "unknown", f"parse error: {exc}")

    if len(parts) < 2 or parts[0] != "git":
        return GitCommandClassification("", "unknown", "not a git command")

    sub = parts[1]
    rest = parts[2:]

    # ── Forbidden ─────────────────────────────────────────────────────
    if sub == "push":
        if "--force" in rest or "-f" in rest or "--force-with-lease" in rest:
            return GitCommandClassification(sub, "forbidden", "force push")
        if "--delete" in rest:
            return GitCommandClassification(sub, "forbidden", "push --delete")
        return GitCommandClassification(sub, "write")

    if sub == "tag" and "-f" in rest:
        return GitCommandClassification(sub, "forbidden", "tag -f (force)")

    if sub == "submodule":
        return GitCommandClassification(
            sub, "forbidden", "submodule ops disabled in V1"
        )

    # ── HITL (before plain write classification) ──────────────────────
    if sub == "reset" and "--hard" in rest:
        return GitCommandClassification(sub, "hitl", "reset --hard requires approval")

    if sub == "rebase":
        # `git pull --rebase` is handled separately under `pull`; bare
        # rebase — including interactive — falls under HITL.
        if "-i" in rest or "--interactive" in rest:
            return GitCommandClassification(sub, "hitl", "rebase -i requires approval")
        return GitCommandClassification(sub, "hitl", "rebase requires approval")

    if sub in _HITL_SUBCOMMANDS:
        return GitCommandClassification(sub, "hitl", f"{sub} requires approval")

    # ── Checkout split: -b → write; bare → read ───────────────────────
    if sub == "checkout":
        if "-b" in rest:
            return GitCommandClassification(sub, "write")
        return GitCommandClassification(sub, "read", "checkout branch switch")

    # ── Whitelist ─────────────────────────────────────────────────────
    if sub in _READ_SUBCOMMANDS:
        return GitCommandClassification(sub, "read")
    if sub in _WRITE_SUBCOMMANDS:
        return GitCommandClassification(sub, "write")

    return GitCommandClassification(sub, "unknown", "subcommand not in whitelist")


# ── Repo extraction ─────────────────────────────────────────────────────


# Matches the last ``owner/repo(.git)?`` segment of a git URL, e.g.
#   https://gitlab.com/acme/svc.git          → acme/svc
#   git@gitlab.com:acme/svc.git              → acme/svc
#   ssh://git@gitlab.com/acme/svc.git/       → acme/svc
_CLONE_URL_RE = re.compile(r"[:/]([^/:\s]+/[^/\s]+?)(?:\.git)?/?$")


def _extract_target_repo(parts: list[str], args: dict) -> Optional[str]:
    """Best-effort repository identifier extraction.

    Resolution order:

      1. Explicit ``_target_repo`` hint on the tool args — required for
         commands that operate in an already-cloned workdir (``git push``,
         ``git commit``, etc.) because those commands never include the
         repo URL themselves.
      2. ``git clone <url>`` URL parse.

    Returns ``None`` when neither source yields a repo — the caller must
    treat that as a fail-closed denial.
    """
    hint = args.get("_target_repo")
    if isinstance(hint, str) and hint.strip():
        return hint.strip()
    if len(parts) >= 3 and parts[1] == "clone":
        m = _CLONE_URL_RE.search(parts[2])
        if m:
            return m.group(1)
    return None


# ── Hook ────────────────────────────────────────────────────────────────


@runtime_checkable
class _PermissionsDaoProtocol(Protocol):
    """Narrow Protocol matching :class:`UserGitPermissionsDao.get_access`."""

    async def get_access(
        self, *, user_id: str, workspace_id: str, repo: str
    ) -> Optional[GitAccessLevel]: ...


_COMMAND_ARG_KEYS: tuple[str, ...] = ("command", "cmd", "shell")


class GitRepoAclHook:
    """Fail-closed git ACL pre-hook.

    Parameters
    ----------
    user_id, workspace_id:
        Identifies the staff member whose snapshot we query.
    permissions_dao:
        Object implementing the narrow :class:`_PermissionsDaoProtocol`.
    gitlab_write_verifier:
        Optional ``async (user_id, repo) -> bool`` used for write-side
        double-check against GitLab.  Plan §Gap 2 mandates this for write
        calls; when ``None`` the hook skips the check (useful in tests
        and degraded modes where GitLab is known unreachable and the
        local snapshot is authoritative).
    audit_logger:
        Sync ``dict -> None`` sink for decision records.  Exceptions are
        swallowed — audit delivery must never block the hook.
    """

    def __init__(
        self,
        *,
        user_id: str,
        workspace_id: str,
        permissions_dao: _PermissionsDaoProtocol,
        gitlab_write_verifier: Optional[
            Callable[[str, str], Awaitable[bool]]
        ] = None,
        audit_logger: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self._user_id = user_id
        self._workspace_id = workspace_id
        self._permissions_dao = permissions_dao
        self._gitlab_write_verifier = gitlab_write_verifier
        self._audit_logger = audit_logger

    # ── Hook protocol methods ─────────────────────────────────────────

    async def pre(self, tool_name: str, args: dict) -> PreHookResult:
        cmd = self._extract_command(args)
        if not cmd or not self._is_git(cmd):
            return PreHookResult()

        try:
            parts = shlex.split(cmd)
        except Exception as exc:  # noqa: BLE001 — unparseable → deny
            self._audit("denied_parse_error", cmd, str(exc))
            return PreHookResult(
                proceed=False,
                injected_message="Git command parse failed; denied.",
            )

        classification = classify_git_command(cmd)
        category = classification.category

        if category == "forbidden":
            self._audit("denied_forbidden", cmd, classification.reason)
            return PreHookResult(
                proceed=False,
                injected_message=(
                    f"Git command forbidden: {classification.reason}"
                ),
            )

        if category == "hitl":
            self._audit("hitl_required", cmd, classification.reason)
            return PreHookResult(
                proceed=False,
                injected_message=(
                    "Git command requires human approval — "
                    f"{classification.reason}"
                ),
            )

        if category == "unknown":
            self._audit(
                "denied_unknown",
                cmd,
                classification.reason or classification.subcommand,
            )
            return PreHookResult(
                proceed=False,
                injected_message=(
                    f"Git subcommand '{classification.subcommand or cmd}' "
                    "is not in the whitelist; denied."
                ),
            )

        # read / write — need a concrete target repo to check ACL
        repo = _extract_target_repo(parts, args)
        if not repo:
            self._audit("denied_no_repo", cmd, "unresolvable target repo")
            return PreHookResult(
                proceed=False,
                injected_message=(
                    "Git command target repo not resolvable; "
                    "provide `_target_repo` or use a clone URL."
                ),
            )

        needed = (
            GitAccessLevel.WRITE
            if category == "write"
            else GitAccessLevel.READ
        )

        try:
            granted = await self._permissions_dao.get_access(
                user_id=self._user_id,
                workspace_id=self._workspace_id,
                repo=repo,
            )
        except Exception as exc:  # noqa: BLE001 — fail closed
            self._audit("denied_acl_error", cmd, str(exc))
            return PreHookResult(
                proceed=False,
                injected_message=(
                    "Git ACL check unavailable; denied (fail-closed)."
                ),
            )

        if granted is None or not allows(granted, needed):
            self._audit(
                "denied_insufficient",
                cmd,
                f"needed={needed.value} granted={granted}",
            )
            return PreHookResult(
                proceed=False,
                injected_message=(
                    f"Git access denied for repo '{repo}' "
                    f"(needs {needed.value})."
                ),
            )

        # Write → double-check via GitLab when verifier wired
        if (
            needed == GitAccessLevel.WRITE
            and self._gitlab_write_verifier is not None
        ):
            try:
                ok = await self._gitlab_write_verifier(self._user_id, repo)
            except Exception as exc:  # noqa: BLE001 — fail closed
                self._audit("denied_gitlab_unreachable", cmd, str(exc))
                return PreHookResult(
                    proceed=False,
                    injected_message=(
                        f"GitLab write verification failed for '{repo}'; "
                        "denied (fail-closed)."
                    ),
                )
            if not ok:
                self._audit("denied_gitlab_revoked", cmd, "gitlab denied")
                return PreHookResult(
                    proceed=False,
                    injected_message=(
                        f"GitLab denied write access to '{repo}'."
                    ),
                )

        self._audit(
            "allowed",
            cmd,
            f"category={category} repo={repo}",
        )
        return PreHookResult()

    async def post(
        self, tool_name: str, args: dict, result: Any
    ) -> PostHookResult:
        # Pure pre-execution gate.  Leave outputs untouched.
        return PostHookResult()

    async def on_failure(
        self, tool_name: str, args: dict, error: Exception
    ) -> PostHookResult:
        return PostHookResult()

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _extract_command(args: dict) -> Optional[str]:
        for key in _COMMAND_ARG_KEYS:
            value = args.get(key)
            if isinstance(value, str):
                return value
        return None

    @staticmethod
    def _is_git(cmd: str) -> bool:
        stripped = cmd.strip()
        return stripped.startswith("git ") or stripped == "git"

    def _audit(self, decision: str, cmd: str, detail: str = "") -> None:
        if self._audit_logger is None:
            return
        # Agent-vs-employee stamping (see AuditLogHook._build_entry for
        # the same convention). avatar_id present ⇒ agent on-behalf-of;
        # absent ⇒ employee operating directly. Always write both
        # fields on ACL records — simpler than audit_logs' optional
        # field because ACL decisions are low-volume and forensic
        # queries benefit from a dense schema.
        avatar_id = ""
        try:
            # PR-E2b (SDK extraction §5 PR-E2b): owner_id / avatar_id /
            # set_ownership are now sourced from runtime.context.  The legacy
            # web.middleware.* call continues via the runtime.context
            # fallback path so runtime behaviour is unchanged in Phase 0.
            # Phase 2 removes the fallback when web/ leaves the engine
            # import surface.
            from vendor_runtime_sdk.runtime.context import get_avatar_id
            avatar_id = get_avatar_id() or ""
        except Exception:  # noqa: BLE001 — audit must not break on lookup
            pass
        record = {
            "decision": decision,
            "cmd": cmd[:200],
            "user_id": self._user_id,
            "workspace_id": self._workspace_id,
            "avatar_id": avatar_id,
            "actor_type": "agent" if avatar_id else "user",
            "detail": detail,
            "ts": time.time(),
        }
        try:
            self._audit_logger(record)
        except Exception:  # noqa: BLE001 — audit must not break the hook
            logger.warning(
                "GitRepoAclHook: audit logger raised", exc_info=True
            )
