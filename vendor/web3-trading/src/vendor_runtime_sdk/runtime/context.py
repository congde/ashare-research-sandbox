# -*- coding: utf-8 -*-
"""
WorkspaceContext — PR-E2 / PR-E2b of the Agent Engine SDK extraction plan.

See ``docs/Agent-Engine-SDK-剥离方案.md`` §5 Phase 0 PR-E2 + PR-E2b.

Goal (PR-E2)
------------
Engine modules currently call ``web.middleware.get_workspace_id()`` to
discover the active tenant.  That import path is unreachable when the
engine is packaged as the standalone ``kucoin-agent-runtime-sdk``.
PR-E2 introduces an engine-owned :class:`~contextvars.ContextVar` so:

* engine modules import :func:`get_workspace_id` from
  :mod:`runtime.context`
* business HTTP middleware sets it via
  :func:`runtime.context.set_workspace_id`
* the legacy :func:`web.middleware.get_workspace_id` continues to work
  via a lazy fallback so business code is unchanged in Phase 0

Goal (PR-E2b)
-------------
Extends PR-E2 with the **owner_id** and **avatar_id** ContextVars plus
the bundled ergonomic :func:`set_ownership` API.  These complete the
"tenant context" trio used by :class:`~runtime.hooks_core.AuditLogHook`
and :class:`~runtime.tools.git_repo_acl_hook.GitRepoAclHook`:

* :func:`get_owner_id` / :func:`set_owner_id` / :func:`reset_owner_id`
  / :func:`reset_owner_id_for_test` / :func:`is_owner_context_installed`
* :func:`get_avatar_id` / :func:`set_avatar_id` / :func:`reset_avatar_id`
  / :func:`reset_avatar_id_for_test` / :func:`is_avatar_context_installed`
* :func:`set_ownership(ws, owner, avatar=None)` →
  :class:`OwnershipTokens` (3-token bundle)
* :func:`reset_ownership(tokens)` — counterpart resetter
* :func:`ownership_scope(ws, owner, avatar=None)` — sync ctx manager

Fall-back path (PR-E2 only; deleted in Phase 2)
-----------------------------------------------
When the engine ContextVar is unset, :func:`get_workspace_id` /
:func:`get_owner_id` / :func:`get_avatar_id` fall back to the
corresponding ``web.middleware`` accessor via a lazy
``importlib.import_module`` probe (same pattern as PR-E5
:class:`_LegacyComponentBackendProvider`).  This makes PR-E2/E2b a
zero-behaviour-change refactor for ai-buddy's current boot path.  SDK
consumers (Phase 2) must call :func:`set_workspace_id` /
:func:`set_ownership` themselves at every task/request boundary.

Sentinel design
---------------
The legacy ContextVars use ``default=""`` which conflates "never set in
this task" with "explicitly set to empty string".  The engine
ContextVars use ``default=None`` instead so the two cases are
distinguishable:

* ``_VAR.get() is None`` → not installed by engine layer → consult
  legacy fallback
* ``_VAR.get() == ""`` → engine layer explicitly cleared it → return
  ``""`` verbatim (do NOT fall through to legacy)

Same pattern as PR-E1 :mod:`runtime.protocols.engine_config`, PR-E5
:mod:`runtime.protocols.backend_provider`, PR-E7 :mod:`runtime.errors`
— engine carries its own contract; business layer keeps its own; the
SDK seam lives at the import boundary.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
from dataclasses import dataclass
from typing import Iterator, Optional

logger = logging.getLogger(__name__)


class WorkspaceContextNotInstalledError(RuntimeError):
    """Raised in Phase 2 when :func:`get_workspace_id` is called with no
    value installed AND :mod:`web.middleware` is not reachable for
    fallback.

    Currently (PR-E2 / V1) :func:`get_workspace_id` does NOT raise
    when both paths miss — it returns ``""`` to preserve byte-identical
    behaviour with ai-buddy's pre-extraction codepath, where engine
    modules already tolerate an empty workspace_id.  The class is
    defined now so the public API surface is forward-compatible with
    Phase 2 (when the legacy fallback is removed and missing context
    becomes a hard error).

    SDK consumers (Phase 2 onwards) MUST call
    :func:`set_workspace_id` at every task/request boundary before any
    engine code path runs.
    """


# ─────────────────────────────────────────────────────────────────────────────
# Engine-owned ContextVars.
# ``default=None`` (not ``""``) so the reader can distinguish "unset"
# from "explicitly set to empty".
# ─────────────────────────────────────────────────────────────────────────────

_WORKSPACE_VAR: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "runtime_workspace_id",
    default=None,
)

_OWNER_VAR: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "runtime_owner_id",
    default=None,
)

_AVATAR_VAR: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "runtime_avatar_id",
    default=None,
)


# ─────────────────────────────────────────────────────────────────────────────
# Workspace context — PR-E2
# ─────────────────────────────────────────────────────────────────────────────


def set_workspace_id(workspace_id: str) -> contextvars.Token:
    """Install ``workspace_id`` into the engine ContextVar and return
    the :class:`contextvars.Token` so callers can later
    :func:`reset_workspace_id` to restore the prior value.

    Args:
        workspace_id: The workspace identifier.  Empty string is
            allowed (treated as "explicitly unset" by the engine layer;
            does NOT trigger the legacy fallback in subsequent
            :func:`get_workspace_id` calls).  ``None`` raises
            :class:`TypeError` — the engine API is strictly typed.

    Returns:
        :class:`contextvars.Token` suitable for passing to
        :func:`reset_workspace_id` in a ``finally`` block.

    Raises:
        TypeError: when ``workspace_id`` is not a :class:`str`.
    """
    if not isinstance(workspace_id, str):
        raise TypeError(
            f"set_workspace_id: workspace_id must be str, "
            f"got {type(workspace_id).__name__}"
        )
    return _WORKSPACE_VAR.set(workspace_id)


def reset_workspace_id(token: contextvars.Token) -> None:
    """Restore the engine ContextVar to the value it held before the
    matching :func:`set_workspace_id` call.

    Args:
        token: The :class:`contextvars.Token` returned by
            :func:`set_workspace_id`.

    Raises:
        ValueError: when ``token`` is from a different ContextVar
            (delegated to :meth:`contextvars.ContextVar.reset`).
    """
    _WORKSPACE_VAR.reset(token)


@contextlib.contextmanager
def workspace_scope(workspace_id: str) -> Iterator[str]:
    """Context manager that installs ``workspace_id`` on entry and
    restores the prior value on exit (even on exception).

    Preferred over raw :func:`set_workspace_id` / :func:`reset_workspace_id`
    for synchronous scopes such as Celery workers, CLI scripts, and
    tests.  Sync and async-task safe because :class:`contextvars.ContextVar`
    is loop-aware via :func:`contextvars.copy_context`.

    Example::

        with workspace_scope("kucoin") as ws:
            await do_engine_work()

    Yields:
        The installed ``workspace_id`` string (mirrors the argument
        verbatim, including the empty-string case).
    """
    token = set_workspace_id(workspace_id)
    try:
        yield workspace_id
    finally:
        reset_workspace_id(token)


def get_workspace_id() -> str:
    """Return the active ``workspace_id`` for the current async-task
    context.

    Resolution order:

    1. The engine-owned ContextVar (set via :func:`set_workspace_id` /
       :func:`workspace_scope`).  Returned verbatim, even if empty.
    2. PR-E2 fallback — :func:`web.middleware.get_workspace_id` when
       that module is importable via lazy ``importlib.import_module``
       probe.  This keeps the migration zero-behaviour-change for
       ai-buddy until business middleware is updated.
    3. Empty string ``""`` when neither resolves.

    Never raises in V1 — engine modules already tolerate empty
    workspace_id.  Phase 2 deletes case (2) and switches case (3) to
    raise :class:`WorkspaceContextNotInstalledError`.

    Returns:
        The resolved workspace_id string.  Empty string is a valid
        return value (mirrors legacy behaviour).
    """
    value = _WORKSPACE_VAR.get()
    if value is not None:
        # Engine layer has explicitly set this — return verbatim,
        # even if it's the empty string.  Do NOT fall through to the
        # legacy probe; an empty string means "engine layer cleared it".
        return value

    # PR-E2 fallback — deleted in Phase 2.  Lazy import so the engine
    # module remains importable from Celery workers / CLI / tests that
    # don't have web/ on PYTHONPATH.
    try:
        import importlib

        legacy = importlib.import_module("web.middleware")
    except ImportError:
        # Engine layer never raises in V1 — return "" so engine code
        # paths that tolerate empty workspace_id keep working.  Phase 2
        # will switch this to raise WorkspaceContextNotInstalledError.
        return ""

    fn = getattr(legacy, "get_workspace_id", None)
    if fn is None:
        # Module imported but doesn't export the expected symbol —
        # treat as "fallback not reachable", same as ImportError.
        return ""
    try:
        result = fn()
    except Exception:  # noqa: BLE001 — engine never raises in V1
        return ""
    return result or ""


def reset_workspace_id_for_test() -> None:
    """Test-only helper.  Clears the engine ContextVar back to the
    default sentinel so the next :func:`get_workspace_id` call falls
    through to the legacy probe.

    NOT for production use.  Production code must hold the
    :class:`contextvars.Token` returned by :func:`set_workspace_id`
    and call :func:`reset_workspace_id`.

    Mirrors :func:`runtime.protocols.engine_config.reset_engine_config_for_test`
    and :func:`runtime.protocols.backend_provider.reset_backend_provider_for_test`.
    """
    # ContextVar has no public clear() — set to None which our reader
    # treats as "use fallback".
    _WORKSPACE_VAR.set(None)


def is_workspace_context_installed() -> bool:
    """Return ``True`` iff the engine ContextVar has been explicitly
    set in the current async-task context.  Does NOT consult the
    legacy fallback.

    Used by callers that need to differentiate "engine layer set me"
    from "engine fell back to web.middleware" for telemetry / boot
    diagnostics.  Production business code should not branch on this
    — :func:`get_workspace_id` already serves the right value.
    """
    return _WORKSPACE_VAR.get() is not None


# ─────────────────────────────────────────────────────────────────────────────
# Owner context — PR-E2b
# ─────────────────────────────────────────────────────────────────────────────


def set_owner_id(owner_id: str) -> contextvars.Token:
    """Install ``owner_id`` (= user_id) into the engine ContextVar and
    return the :class:`contextvars.Token` so callers can later
    :func:`reset_owner_id` to restore the prior value.

    Lower-level primitive backing :func:`set_ownership`.  Direct
    callers expected to be tests and the dual-write shim inside
    :func:`web.middleware.set_ownership`.

    Args:
        owner_id: The user identifier.  Empty string is allowed (e.g.
            Celery workers without an authenticated user).  ``None``
            raises :class:`TypeError`.

    Returns:
        :class:`contextvars.Token` suitable for passing to
        :func:`reset_owner_id` in a ``finally`` block.

    Raises:
        TypeError: when ``owner_id`` is not a :class:`str`.
    """
    if not isinstance(owner_id, str):
        raise TypeError(
            f"set_owner_id: owner_id must be str, "
            f"got {type(owner_id).__name__}"
        )
    return _OWNER_VAR.set(owner_id)


def reset_owner_id(token: contextvars.Token) -> None:
    """Restore the engine owner ContextVar to its pre-:func:`set_owner_id`
    value.

    Args:
        token: The :class:`contextvars.Token` returned by
            :func:`set_owner_id`.

    Raises:
        ValueError: when ``token`` is from a different ContextVar
            (delegated to :meth:`contextvars.ContextVar.reset`).
    """
    _OWNER_VAR.reset(token)


def get_owner_id() -> str:
    """Return the active ``owner_id`` for the current async-task
    context.

    Resolution order mirrors :func:`get_workspace_id`:

    1. The engine-owned ContextVar (set via :func:`set_owner_id` /
       :func:`set_ownership`).  Returned verbatim, even if empty.
    2. PR-E2b fallback — :func:`web.middleware.get_owner_id` when that
       module is importable via lazy ``importlib.import_module`` probe.
    3. Empty string ``""`` when neither resolves.

    Never raises in V1.

    Returns:
        The resolved owner_id string.  Empty string is a valid return
        value (mirrors legacy behaviour for Celery workers / anonymous
        contexts).
    """
    value = _OWNER_VAR.get()
    if value is not None:
        return value

    try:
        import importlib

        legacy = importlib.import_module("web.middleware")
    except ImportError:
        return ""

    fn = getattr(legacy, "get_owner_id", None)
    if fn is None:
        return ""
    try:
        result = fn()
    except Exception:  # noqa: BLE001 — engine never raises in V1
        return ""
    return result or ""


def reset_owner_id_for_test() -> None:
    """Test-only helper paralleling :func:`reset_workspace_id_for_test`.

    Clears the engine owner ContextVar back to None so the next
    :func:`get_owner_id` call falls through to the legacy probe.
    """
    _OWNER_VAR.set(None)


def is_owner_context_installed() -> bool:
    """Return ``True`` iff the owner ContextVar has been explicitly set
    in the current async-task context.  Does NOT consult the legacy
    fallback.
    """
    return _OWNER_VAR.get() is not None


@contextlib.contextmanager
def owner_scope(owner_id: str) -> Iterator[str]:
    """Sync context manager — installs ``owner_id`` on entry and
    restores the prior value on exit (even on exception).
    """
    token = set_owner_id(owner_id)
    try:
        yield owner_id
    finally:
        reset_owner_id(token)


# ─────────────────────────────────────────────────────────────────────────────
# Avatar context — PR-E2b
# ─────────────────────────────────────────────────────────────────────────────


def set_avatar_id(avatar_id: str) -> contextvars.Token:
    """Install ``avatar_id`` into the engine ContextVar and return the
    :class:`contextvars.Token` so callers can later
    :func:`reset_avatar_id` to restore the prior value.

    The legacy :func:`web.middleware.avatar_isolation.set_avatar_id`
    has signature ``(value: str) -> None``; the engine variant upgrades
    to Token return for scoped semantics consistent with the workspace
    + owner pair.

    Args:
        avatar_id: The avatar identifier.  Empty string is the V1
            "employee-not-agent" case and is allowed.  ``None`` raises
            :class:`TypeError`.

    Returns:
        :class:`contextvars.Token` suitable for passing to
        :func:`reset_avatar_id` in a ``finally`` block.

    Raises:
        TypeError: when ``avatar_id`` is not a :class:`str`.
    """
    if not isinstance(avatar_id, str):
        raise TypeError(
            f"set_avatar_id: avatar_id must be str, "
            f"got {type(avatar_id).__name__}"
        )
    return _AVATAR_VAR.set(avatar_id)


def reset_avatar_id(token: contextvars.Token) -> None:
    """Restore the engine avatar ContextVar to its pre-:func:`set_avatar_id`
    value.
    """
    _AVATAR_VAR.reset(token)


def get_avatar_id() -> str:
    """Return the active ``avatar_id`` for the current async-task
    context.

    Resolution order mirrors :func:`get_workspace_id`:

    1. The engine-owned ContextVar (set via :func:`set_avatar_id` /
       :func:`set_ownership` with the avatar arg).  Returned verbatim,
       even if empty.
    2. PR-E2b fallback — :func:`web.middleware.avatar_isolation.get_avatar_id`
       when that module is importable via lazy
       ``importlib.import_module`` probe.
    3. Empty string ``""`` when neither resolves.

    Empty string return is the documented "no avatar — direct employee
    call" case.  Never raises in V1.
    """
    value = _AVATAR_VAR.get()
    if value is not None:
        return value

    try:
        import importlib

        legacy = importlib.import_module("web.middleware.avatar_isolation")
    except ImportError:
        return ""

    fn = getattr(legacy, "get_avatar_id", None)
    if fn is None:
        return ""
    try:
        result = fn()
    except Exception:  # noqa: BLE001 — engine never raises in V1
        return ""
    return result or ""


def reset_avatar_id_for_test() -> None:
    """Test-only helper — clears the avatar ContextVar back to None."""
    _AVATAR_VAR.set(None)


def is_avatar_context_installed() -> bool:
    """Return ``True`` iff the avatar ContextVar has been explicitly
    set in the current async-task context.  Does NOT consult the
    legacy fallback.

    Forward-compat hook for the Phase 2 audit-log tightening
    (distinguish "no avatar context" from "empty avatar context" for
    actor_type classification — see design_notes #15 in PR-E2b).
    """
    return _AVATAR_VAR.get() is not None


@contextlib.contextmanager
def avatar_scope(avatar_id: str) -> Iterator[str]:
    """Sync context manager — installs ``avatar_id`` on entry and
    restores the prior value on exit (even on exception).
    """
    token = set_avatar_id(avatar_id)
    try:
        yield avatar_id
    finally:
        reset_avatar_id(token)


# ─────────────────────────────────────────────────────────────────────────────
# Combined ownership API — PR-E2b
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class OwnershipTokens:
    """Return type of :func:`set_ownership` and yield type of
    :func:`ownership_scope`.

    Bundles the three :class:`contextvars.Token` instances so callers
    can later restore all three with a single :func:`reset_ownership`
    call.  Frozen so tokens cannot be partially mutated after capture.

    Attributes:
        workspace_token: Token returned by :func:`set_workspace_id`.
        owner_token: Token returned by :func:`set_owner_id`.
        avatar_token: Token returned by :func:`set_avatar_id`, or
            ``None`` when the :func:`set_ownership` caller omitted the
            ``avatar_id`` argument (avatar ContextVar untouched).
    """

    workspace_token: contextvars.Token
    owner_token: contextvars.Token
    avatar_token: Optional[contextvars.Token] = None

    def __post_init__(self) -> None:  # noqa: D401 — defensive ctor validation
        # Construction validation: all non-None tokens must be
        # contextvars.Token instances.  Defense-in-depth so a mistyped
        # None instead of a Token causes a clean TypeError at
        # construction rather than a confusing AttributeError later in
        # reset_ownership.
        if not isinstance(self.workspace_token, contextvars.Token):
            raise TypeError(
                f"OwnershipTokens.workspace_token must be contextvars.Token, "
                f"got {type(self.workspace_token).__name__}"
            )
        if not isinstance(self.owner_token, contextvars.Token):
            raise TypeError(
                f"OwnershipTokens.owner_token must be contextvars.Token, "
                f"got {type(self.owner_token).__name__}"
            )
        if self.avatar_token is not None and not isinstance(
            self.avatar_token, contextvars.Token
        ):
            raise TypeError(
                f"OwnershipTokens.avatar_token must be contextvars.Token or None, "
                f"got {type(self.avatar_token).__name__}"
            )


def set_ownership(
    workspace_id: str,
    owner_id: str,
    avatar_id: Optional[str] = None,
) -> OwnershipTokens:
    """Install ``workspace_id`` + ``owner_id`` (+ optional ``avatar_id``)
    into the engine ContextVars and return the bundled
    :class:`OwnershipTokens` for later :func:`reset_ownership`.

    The headline ergonomic API — replaces ``from web.middleware import
    set_ownership`` at the 8 engine call sites that need the
    ``(workspace, owner)`` pair set in one call (Celery workers,
    schedule dispatchers, CR agent, worker_pool init).

    Args:
        workspace_id: The workspace identifier.  Must be :class:`str`;
            empty string allowed.
        owner_id: The user identifier.  Must be :class:`str`; empty
            string allowed (Celery workers without an authenticated
            user — celery_tasks.py / worker_pool/worker.py pass ``""``).
        avatar_id: Optional avatar identifier.  ``None`` means "do not
            touch the avatar ContextVar at all" (preserves the 7-of-8
            legacy call sites that never passed avatar).  Empty string
            means "clear avatar to empty" — different semantics from
            ``None``.

    Returns:
        :class:`OwnershipTokens` bundling all three tokens.
        ``avatar_token`` is ``None`` when ``avatar_id`` is ``None``.

    Raises:
        TypeError: when any argument has the wrong type.

    Note:
        Callers that ignore the return value get legacy
        "leak-into-next-task" semantics — intentional; matches today's
        :func:`web.middleware.set_ownership` behaviour at the 8
        imperative call sites.  Prefer :func:`ownership_scope` for new
        code.
    """
    workspace_token = set_workspace_id(workspace_id)
    owner_token = set_owner_id(owner_id)
    avatar_token: Optional[contextvars.Token] = None
    if avatar_id is not None:
        avatar_token = set_avatar_id(avatar_id)
    return OwnershipTokens(
        workspace_token=workspace_token,
        owner_token=owner_token,
        avatar_token=avatar_token,
    )


def reset_ownership(tokens: OwnershipTokens) -> None:
    """Restore all three engine ContextVars to the values they held
    before the matching :func:`set_ownership` call.

    Resets in reverse order (avatar → owner → workspace) so the call
    pattern mirrors LIFO stack discipline.  ``avatar_token=None`` is
    skipped (matches :func:`set_ownership` without an avatar argument).

    Args:
        tokens: The :class:`OwnershipTokens` returned by
            :func:`set_ownership`.

    Raises:
        ValueError: when any token is from a different ContextVar
            (delegated to :meth:`contextvars.ContextVar.reset`).
    """
    if tokens.avatar_token is not None:
        reset_avatar_id(tokens.avatar_token)
    reset_owner_id(tokens.owner_token)
    reset_workspace_id(tokens.workspace_token)


@contextlib.contextmanager
def ownership_scope(
    workspace_id: str,
    owner_id: str,
    avatar_id: Optional[str] = None,
) -> Iterator[OwnershipTokens]:
    """Sync context manager — preferred new-code path for Celery
    workers, CLI scripts, and tests.

    Wraps :func:`set_ownership` + :func:`reset_ownership` in a
    ``try/finally``.  Mirrors :func:`workspace_scope` exactly but
    bundles all three context-var changes.

    Example::

        with ownership_scope("kucoin", "user-42") as tokens:
            await do_engine_work()

    The yielded :class:`OwnershipTokens` is the same tokens object that
    will be reset on exit — callers rarely need it but it is exposed for
    symmetry with :func:`set_ownership`.

    Args:
        workspace_id: The workspace identifier (str).
        owner_id: The user identifier (str).
        avatar_id: Optional avatar identifier.  ``None`` means avatar
            ContextVar is untouched throughout the scope.

    Yields:
        :class:`OwnershipTokens` bundling the three tokens.
    """
    tokens = set_ownership(workspace_id, owner_id, avatar_id)
    try:
        yield tokens
    finally:
        reset_ownership(tokens)


def reset_ownership_for_test() -> None:
    """Test-only helper paralleling :func:`reset_workspace_id_for_test`.

    Clears ``_OWNER_VAR`` and ``_AVATAR_VAR`` back to ``None`` so the
    next :func:`get_owner_id` / :func:`get_avatar_id` calls fall through
    to the legacy probe.  Does NOT touch ``_WORKSPACE_VAR`` — callers
    that want a full reset must also call
    :func:`reset_workspace_id_for_test`.
    """
    _OWNER_VAR.set(None)
    _AVATAR_VAR.set(None)


__all__ = [
    "WorkspaceContextNotInstalledError",
    "OwnershipTokens",
    # workspace
    "set_workspace_id",
    "reset_workspace_id",
    "workspace_scope",
    "get_workspace_id",
    "reset_workspace_id_for_test",
    "is_workspace_context_installed",
    # owner
    "set_owner_id",
    "reset_owner_id",
    "owner_scope",
    "get_owner_id",
    "reset_owner_id_for_test",
    "is_owner_context_installed",
    # avatar
    "set_avatar_id",
    "reset_avatar_id",
    "avatar_scope",
    "get_avatar_id",
    "reset_avatar_id_for_test",
    "is_avatar_context_installed",
    # combined
    "set_ownership",
    "reset_ownership",
    "ownership_scope",
    "reset_ownership_for_test",
]
