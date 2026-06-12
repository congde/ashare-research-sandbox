# -*- coding: utf-8 -*-
"""
PermissionChecker — PR-E6b of the Agent Engine SDK extraction plan.

See ``docs/Agent-Engine-SDK-剥离方案.md`` §5 Phase 0 PR-E6 / PR-E6b.

Goal
----
Replace the engine layer's direct dependency on
``lark.im_permissions`` with a Protocol-based seam. The engine's
PermissionResolver currently calls
``lark.im_permissions.lark_im_auto_execute_enabled`` to decide whether
to bypass the Prompt-lattice HITL cards for Feishu / IM dispatch.

That import path is unreachable when the engine is packaged as the
SDK :mod:`kucoin-agent-runtime-sdk` (``lark/`` is the channel-adapter
layer, kept outside the engine). PR-E6b introduces the abstraction —
the Protocol's single method is a coarse-grained sentinel
("is the current dispatch channel allowed to auto-execute tools without
HITL?"), NOT a thin Lark API passthrough.

Scope (V1)
----------
Single tier-1 call site:

* ``src/runtime/policy/permission.py`` — :func:`_lark_im_auto_execute_enabled`
  helper consumed at three points in :class:`PermissionResolver.resolve`.

Fall-back path (PR-E6b only; deleted in Phase 2)
------------------------------------------------
When no checker is installed via :func:`set_permission_checker`,
:func:`get_permission_checker` lazily synthesises one that wraps
:mod:`lark.im_permissions`. Fail-soft — when ``lark.im_permissions`` is
unreachable a fresh :class:`NoOpPermissionChecker` is returned silently
(matches engine-only deployments where every turn is subject to the
standard Prompt-lattice HITL flow).

Safe default
------------
:class:`NoOpPermissionChecker.im_auto_execute_enabled` returns ``False``
— equivalent to "no IM channel installed, run the standard HITL flow".
This is the conservative fail-closed choice: an unexpected ``True``
would bypass HITL approval for an entire turn.

Same pattern as PR-E1 :class:`EngineConfig`, PR-E3
:class:`ContextStore`, PR-E4 :class:`CostRecordRepository`, PR-E5
:class:`BackendClientProvider`, and PR-E6 :class:`NotificationDispatcher`
/ :class:`ConversationHistoryFormatter` — engine carries its own
contract; business layer keeps its own concrete types; the SDK seam
lives at the import boundary.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


class PermissionCheckerNotInstalledError(RuntimeError):
    """Reserved for future strict-mode usage. In normal operation
    :func:`get_permission_checker` is fail-soft and returns
    :class:`NoOpPermissionChecker` instead of raising.
    """


@runtime_checkable
class PermissionChecker(Protocol):
    """Pluggable channel-permission sentinel for engine policy decisions.

    Single coarse-grained method — the engine asks "is the current
    dispatch channel allowed to auto-execute tools without HITL?"
    Implementations consult their own ContextVar / env-flag policy.

    The NoOp impl always returns ``False`` (safe default).
    """

    def im_auto_execute_enabled(
        self,
        eval_ctx: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Return True iff the current dispatch channel may bypass
        Prompt-lattice HITL cards.

        Args:
            eval_ctx: Optional evaluation context dict passed by
                :class:`runtime.policy.permission.PermissionResolver`.
                Implementations may inspect ``eval_ctx['source']`` to
                pin the decision to a specific channel (e.g. ``"lark_bot"``).

        Returns:
            ``True`` iff auto-execute is permitted on the current
            channel. NoOp default is ``False`` (= run standard HITL).
        """
        ...


# ── Module-level singleton ──────────────────────────────────────────────


_permission_checker: Optional[PermissionChecker] = None


def set_permission_checker(checker: PermissionChecker) -> None:
    """Install the PermissionChecker used by the engine policy layer.

    Idempotent — subsequent calls overwrite. Logs at INFO with the
    implementation class name only — NEVER logs the checker instance
    contents.

    Raises:
        TypeError: when ``checker`` does not satisfy the
            :class:`PermissionChecker` Protocol at the structural
            level.
    """
    if not isinstance(checker, PermissionChecker):
        raise TypeError(
            f"set_permission_checker: checker must satisfy "
            f"PermissionChecker Protocol (im_auto_execute_enabled), "
            f"got {type(checker).__name__}"
        )
    global _permission_checker
    _permission_checker = checker
    logger.info(
        "PermissionChecker installed: %s",
        type(checker).__name__,
    )


def get_permission_checker() -> PermissionChecker:
    """Return the installed checker, falling back to a lazy adapter
    that wraps :mod:`lark.im_permissions` when no explicit checker is
    installed AND ``lark.im_permissions`` is importable, otherwise to
    :class:`NoOpPermissionChecker`.

    Fail-soft — NEVER raises.
    """
    if _permission_checker is not None:
        return _permission_checker

    # PR-E6b fall-back. Probe ``lark.im_permissions`` reachability.
    try:
        import importlib
        importlib.import_module("lark.im_permissions")
    except ImportError:
        return _NoOpCheckerSingleton.get()

    return _LegacyLarkPermissionChecker.get_singleton()


def reset_permission_checker_for_test() -> None:
    """Test-only helper to clear the installed checker between cases.

    NOT for production use. Mirrors
    :func:`runtime.protocols.conversation_history_formatter.reset_conversation_history_formatter_for_test`.
    """
    global _permission_checker
    _permission_checker = None
    _LegacyLarkPermissionChecker.reset_singleton_for_test()
    _NoOpCheckerSingleton.reset_for_test()


# ── NoOp impl (engine default — safe fail-closed) ──────────────────────


class NoOpPermissionChecker:
    """Engine-only default — every turn runs the standard HITL flow.

    :meth:`im_auto_execute_enabled` always returns ``False``. This is
    the conservative fail-closed choice: an unexpected ``True`` would
    bypass HITL approval for an entire turn.
    """

    def im_auto_execute_enabled(
        self,
        eval_ctx: Optional[Dict[str, Any]] = None,
    ) -> bool:
        return False


class _NoOpCheckerSingleton:
    """Holds the singleton NoOp checker for the fail-soft fallback."""

    _INSTANCE: Optional[NoOpPermissionChecker] = None

    @classmethod
    def get(cls) -> NoOpPermissionChecker:
        if cls._INSTANCE is None:
            cls._INSTANCE = NoOpPermissionChecker()
        return cls._INSTANCE

    @classmethod
    def reset_for_test(cls) -> None:
        cls._INSTANCE = None


# ── Legacy lark.im_permissions adapter (fallback) ──────────────────────


class _LegacyLarkPermissionChecker:
    """Adapter that exposes :mod:`lark.im_permissions` via the
    :class:`PermissionChecker` Protocol.

    Used only via the fall-back path in :func:`get_permission_checker`
    when no SDK-side checker is installed. ai-buddy can choose to
    install this adapter explicitly at boot (cleaner audit trail) or
    rely on the fall-back (zero boot wiring).

    Mirrors the channel-pinning logic the legacy
    :func:`runtime.policy.permission._lark_im_auto_execute_enabled`
    helper used: when ``eval_ctx['source'] == 'lark_bot'`` the channel
    is force-pinned, otherwise we defer to the env-flag policy in
    :func:`lark.im_permissions.lark_im_auto_execute_enabled`.

    Failures are caught + returned as ``True`` for the pinned channel
    (preserves prior fail-soft behaviour where IM dispatch defaulted
    to auto-execute when the env helper raised) and ``False``
    otherwise.
    """

    _SINGLETON: Optional["_LegacyLarkPermissionChecker"] = None

    @classmethod
    def get_singleton(cls) -> "_LegacyLarkPermissionChecker":
        if cls._SINGLETON is None:
            cls._SINGLETON = cls()
        return cls._SINGLETON

    @classmethod
    def reset_singleton_for_test(cls) -> None:
        cls._SINGLETON = None

    def im_auto_execute_enabled(
        self,
        eval_ctx: Optional[Dict[str, Any]] = None,
    ) -> bool:
        # Mirror the prior 2-branch helper:
        #
        # 1. When eval_ctx says the dispatch source is the Lark bot we
        #    consult the env opt-back-in flag locally — the channel is
        #    pinned regardless of whether the ContextVar in
        #    ``lark.im_permissions.is_lark_im_dispatch`` agrees (the
        #    PolicyEngine eval_ctx is the authoritative signal).
        # 2. Otherwise we delegate to
        #    ``lark.im_permissions.lark_im_auto_execute_enabled`` which
        #    itself checks ``is_lark_im_dispatch`` + env.
        if (eval_ctx or {}).get("source") == "lark_bot":
            try:
                # Probe module reachability — call into env helper
                # only if the module imports cleanly.
                import importlib
                importlib.import_module("lark.im_permissions")
                import os

                env = os.environ.get(
                    "LARK_IM_REQUIRE_TOOL_APPROVAL", ""
                ).strip().lower()
                if env in ("1", "true", "yes", "on"):
                    return False
                return True
            except Exception as exc:
                logger.debug(
                    "_LegacyLarkPermissionChecker.im_auto_execute_enabled "
                    "(lark_bot pin) failed: %s",
                    type(exc).__name__,
                )
                # Preserve the prior fail-soft default for the pinned
                # channel — IM dispatch defaulted to auto-execute when
                # the env helper raised.
                return True
        try:
            from lark.im_permissions import lark_im_auto_execute_enabled
            return bool(lark_im_auto_execute_enabled())
        except Exception as exc:
            logger.debug(
                "_LegacyLarkPermissionChecker.im_auto_execute_enabled "
                "fall-through failed: %s",
                type(exc).__name__,
            )
            return False


__all__ = [
    "PermissionChecker",
    "PermissionCheckerNotInstalledError",
    "NoOpPermissionChecker",
    "set_permission_checker",
    "get_permission_checker",
    "reset_permission_checker_for_test",
]
# ``_LegacyLarkPermissionChecker`` is intentionally NOT exported —
# matches the PR-E3/E4/E5/E6 convention of keeping the legacy adapter
# private (tests import it by name).
