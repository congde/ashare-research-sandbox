# -*- coding: utf-8 -*-
"""
ConversationHistoryFormatter — PR-E6 of the Agent Engine SDK extraction plan.

See ``docs/Agent-Engine-SDK-剥离方案.md`` §5 Phase 0 PR-E6 / PR-E6b.

PR-E6b extension
----------------
Adds :meth:`ConversationHistoryFormatter.trim_im_history_for_dag_with_context`
so engine call sites in ``src/agent/dag_execution/_pipeline.py`` can stop
calling ``lark.history_policy.trim_lark_im_history_for_dag`` directly. The
original :meth:`trim_im_history_for_dag` is preserved for backward
compatibility.

Goal
----
Replace the engine layer's direct dependency on
``lark.history_policy`` with a Protocol-based seam. The 5 public
functions in ``lark.history_policy`` are IM-channel-specific
heuristics (Lark / Feishu bot context) deciding whether the current
turn originated from an IM bot and how to trim+format history
accordingly.

Bundling them into a Protocol keeps the IM-channel-specific
heuristics out of engine modules and lets SDK consumers ship
channel-neutral defaults. The NoOp impl returns
``is_im_bot_turn=False`` and identity formatters so engine-only
deployments behave like "no IM channel".

Scope (V1)
----------
This PR handles 2 tier-1 call-site anchors:

* ``src/agent/dag_execution/_phase1.py`` —
  ``query_wants_workspace_analysis`` callsite (Phase 1 tool selection
  for Lark-bot workspace analysis)
* ``src/agent/plan/gateway.py`` —
  ``query_wants_workspace_analysis`` callsite (Gateway routing)

Five Protocol methods 1:1 match the five unique symbols in the audit.

Fall-back path (PR-E6 only; deleted in Phase 2)
-----------------------------------------------
When no formatter is installed via
:func:`set_conversation_history_formatter`,
:func:`get_conversation_history_formatter` lazily synthesises one
that wraps :mod:`lark.history_policy`. Fail-soft — when
``lark.history_policy`` is unreachable a fresh
:class:`NoOpConversationHistoryFormatter` is returned silently
(matches engine-only deployments).

Same pattern as PR-E1 :class:`EngineConfig`, PR-E3
:class:`ContextStore`, PR-E4 :class:`CostRecordRepository`, PR-E5
:class:`BackendClientProvider`, and the sibling
:class:`NotificationDispatcher` Protocol in this PR.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


class ConversationHistoryFormatterNotInstalledError(RuntimeError):
    """Reserved for future strict-mode usage. In normal operation
    :func:`get_conversation_history_formatter` is fail-soft and
    returns :class:`NoOpConversationHistoryFormatter` instead of
    raising.
    """


@runtime_checkable
class ConversationHistoryFormatter(Protocol):
    """Pluggable formatter for IM-channel conversation history.

    Pure functions over query string + history list. No I/O, no
    client. SDK consumers implementing a non-IM channel can supply
    :class:`NoOpConversationHistoryFormatter` (the default) — the
    engine then treats every turn as channel-neutral.

    PR-E6b extension
    ----------------
    Adds :meth:`trim_im_history_for_dag_with_context` — a richer
    variant of :meth:`trim_im_history_for_dag` that exposes the
    ``current_qa_id`` + ``current_query`` knobs the
    ``lark.history_policy.trim_lark_im_history_for_dag`` adapter
    consumes. The original :meth:`trim_im_history_for_dag` is
    preserved for backward compatibility and now delegates by passing
    ``current_qa_id=None`` / ``current_query=""``.
    """

    def is_im_bot_turn(self) -> bool:
        """Return True when the current turn originated from an IM
        bot context.

        Implementations typically read a ContextVar set by the IM
        webhook handler. The NoOp impl always returns False.
        """
        ...

    def query_wants_workspace_analysis(self, query: str) -> bool:
        """Heuristic — does the query request workspace / local
        directory analysis? Affects DAG planner tool-selection.
        """
        ...

    def im_effective_history_turns(self, query: str) -> Optional[int]:
        """Compute the max-turns history budget for the current
        query+context. ``None`` means "no IM-specific override —
        use the engine default".
        """
        ...

    def trim_im_history_for_dag(
        self,
        history: List[Dict[str, Any]],
        *,
        max_turns: int,
    ) -> List[Dict[str, Any]]:
        """Drop oldest IM-bot turns past ``max_turns`` budget, keeping
        the most recent. NoOp returns ``history`` unchanged (identity).
        """
        ...

    def trim_im_history_for_dag_with_context(
        self,
        history: List[Dict[str, Any]],
        *,
        current_qa_id: Optional[str],
        current_query: str,
        max_supplement_turns: int,
    ) -> List[Dict[str, Any]]:
        """PR-E6b: richer trim variant exposing current-turn context.

        The Lark adapter uses ``current_qa_id`` to drop the in-flight
        QA row and ``current_query`` to skip prior turns whose content
        is already covered by the new message. NoOp returns
        ``history[:max_supplement_turns]`` (best-effort identity
        truncation; ignores current-turn context entirely).
        """
        ...

    def format_im_history_for_dag_prompt(
        self,
        history: List[Dict[str, Any]],
    ) -> str:
        """Render the history list into a DAG planner prompt string.
        NoOp returns an empty string (no IM-specific framing).
        """
        ...


# ── Module-level singleton ──────────────────────────────────────────────


_conversation_history_formatter: Optional[ConversationHistoryFormatter] = None


_PR_E6_CORE_METHODS = (
    "is_im_bot_turn",
    "query_wants_workspace_analysis",
    "im_effective_history_turns",
    "trim_im_history_for_dag",
    "format_im_history_for_dag_prompt",
)


def set_conversation_history_formatter(
    formatter: ConversationHistoryFormatter,
) -> None:
    """Install the ConversationHistoryFormatter used by engine modules.

    Idempotent. Logs at INFO with the implementation class name only —
    never logs the formatter instance contents.

    Backwards compatibility (PR-E6b review fix)
    -------------------------------------------
    PR-E6b extended the Protocol with
    :meth:`trim_im_history_for_dag_with_context` (a 6th method).  To
    avoid silently breaking SDK consumers that registered a formatter
    with the original 5-method shape (PR-E6 contract), the validation
    here requires only the 5 core methods.  When the installed
    formatter lacks the 6th method, :func:`get_conversation_history_
    formatter` returns a wrapper that synthesises a default impl
    delegating to :meth:`trim_im_history_for_dag` — engine callers
    using the new method still work; the legacy formatter stays
    installed unmodified.

    Raises:
        TypeError: when ``formatter`` is missing any of the 5 core
            PR-E6 methods.
    """
    missing = [m for m in _PR_E6_CORE_METHODS if not callable(getattr(formatter, m, None))]
    if missing:
        raise TypeError(
            f"set_conversation_history_formatter: formatter must implement "
            f"all 5 core ConversationHistoryFormatter methods "
            f"({', '.join(_PR_E6_CORE_METHODS)}); missing "
            f"{', '.join(missing)} on {type(formatter).__name__}"
        )
    global _conversation_history_formatter
    _conversation_history_formatter = formatter
    logger.info(
        "ConversationHistoryFormatter installed: %s",
        type(formatter).__name__,
    )


def get_conversation_history_formatter() -> ConversationHistoryFormatter:
    """Return the installed formatter, falling back to a lazy adapter
    that wraps :mod:`lark.history_policy` when no explicit formatter
    is installed AND ``lark.history_policy`` is importable, otherwise
    to :class:`NoOpConversationHistoryFormatter`.

    Fail-soft — NEVER raises.

    Backwards compatibility (PR-E6b review fix): if the installed
    formatter implements the 5 core PR-E6 methods but is missing
    :meth:`trim_im_history_for_dag_with_context` (PR-E6b new method),
    return a forward-compat wrapper that synthesises the 6th method
    by delegating to :meth:`trim_im_history_for_dag`.  This lets a
    legacy 5-method formatter keep working unchanged while engine
    callers using the new 6th method still get a sensible result.
    """
    if _conversation_history_formatter is not None:
        return _wrap_pr_e6b_compat(_conversation_history_formatter)

    # PR-E6 fall-back. Probe ``lark.history_policy`` reachability.
    try:
        import importlib
        importlib.import_module("lark.history_policy")
    except ImportError:
        return _NoOpFormatterSingleton.get()

    return _LegacyLarkHistoryFormatter.get_singleton()


def _wrap_pr_e6b_compat(
    formatter: ConversationHistoryFormatter,
) -> ConversationHistoryFormatter:
    """Synthesise :meth:`trim_im_history_for_dag_with_context` on the
    fly when the installed formatter only implements the 5 core
    PR-E6 methods.  The synthesised impl delegates to
    :meth:`trim_im_history_for_dag` (ignoring the
    ``current_qa_id`` / ``current_query`` hints — the legacy 5-method
    contract didn't have access to them either).
    """
    if callable(getattr(formatter, "trim_im_history_for_dag_with_context", None)):
        return formatter

    # Build a tiny proxy that delegates everything to the wrapped
    # formatter and supplies the missing 6th method.
    class _PrE6bCompatProxy:
        def __init__(self, inner: ConversationHistoryFormatter) -> None:
            self._inner = inner

        def __getattr__(self, name: str):
            # Proxy all 5 core methods + any other attributes through.
            return getattr(self._inner, name)

        def trim_im_history_for_dag_with_context(
            self,
            history,
            *,
            current_qa_id=None,
            current_query="",
            max_supplement_turns=0,
        ):
            return self._inner.trim_im_history_for_dag(
                history, max_turns=max_supplement_turns
            )

    return _PrE6bCompatProxy(formatter)  # type: ignore[return-value]


def reset_conversation_history_formatter_for_test() -> None:
    """Test-only helper to clear the installed formatter between
    cases.

    NOT for production use.
    """
    global _conversation_history_formatter
    _conversation_history_formatter = None
    _LegacyLarkHistoryFormatter.reset_singleton_for_test()
    _NoOpFormatterSingleton.reset_for_test()


# ── NoOp impl (engine default) ─────────────────────────────────────────


class NoOpConversationHistoryFormatter:
    """Channel-neutral default — treats every turn as non-IM.

    - :meth:`is_im_bot_turn` always returns False
    - :meth:`query_wants_workspace_analysis` always returns False
    - :meth:`im_effective_history_turns` always returns None
    - :meth:`trim_im_history_for_dag` is the identity function
    - :meth:`format_im_history_for_dag_prompt` returns ``""``
    """

    def is_im_bot_turn(self) -> bool:
        return False

    def query_wants_workspace_analysis(self, query: str) -> bool:
        return False

    def im_effective_history_turns(self, query: str) -> Optional[int]:
        return None

    def trim_im_history_for_dag(
        self,
        history: List[Dict[str, Any]],
        *,
        max_turns: int,
    ) -> List[Dict[str, Any]]:
        return list(history)

    def trim_im_history_for_dag_with_context(
        self,
        history: List[Dict[str, Any]],
        *,
        current_qa_id: Optional[str],
        current_query: str,
        max_supplement_turns: int,
    ) -> List[Dict[str, Any]]:
        # PR-E6b NoOp — best-effort identity truncation, ignores
        # current-turn context. Engine-only deployments don't need IM
        # supplement semantics.
        cap = max(0, int(max_supplement_turns))
        if cap <= 0:
            return []
        return list(history)[:cap]

    def format_im_history_for_dag_prompt(
        self,
        history: List[Dict[str, Any]],
    ) -> str:
        return ""


class _NoOpFormatterSingleton:
    """Holds the singleton NoOp formatter for the fail-soft fallback."""

    _INSTANCE: Optional[NoOpConversationHistoryFormatter] = None

    @classmethod
    def get(cls) -> NoOpConversationHistoryFormatter:
        if cls._INSTANCE is None:
            cls._INSTANCE = NoOpConversationHistoryFormatter()
        return cls._INSTANCE

    @classmethod
    def reset_for_test(cls) -> None:
        cls._INSTANCE = None


# ── Legacy lark.history_policy adapter (fallback) ───────────────────────


class _LegacyLarkHistoryFormatter:
    """Adapter that exposes :mod:`lark.history_policy` via the
    :class:`ConversationHistoryFormatter` Protocol.

    Every method directly forwards to the matching
    ``lark.history_policy.<symbol>`` call with try/except returning
    the NoOp default on failure. Failures are logged at DEBUG
    (history-policy errors should be invisible to operators — they
    indicate a stale Lark integration, not an operational issue).
    """

    _SINGLETON: Optional["_LegacyLarkHistoryFormatter"] = None
    _NOOP: NoOpConversationHistoryFormatter = (
        NoOpConversationHistoryFormatter()
    )

    @classmethod
    def get_singleton(cls) -> "_LegacyLarkHistoryFormatter":
        if cls._SINGLETON is None:
            cls._SINGLETON = cls()
        return cls._SINGLETON

    @classmethod
    def reset_singleton_for_test(cls) -> None:
        cls._SINGLETON = None

    def is_im_bot_turn(self) -> bool:
        try:
            from lark.history_policy import is_lark_bot_turn
            return bool(is_lark_bot_turn())
        except Exception as exc:
            logger.debug(
                "_LegacyLarkHistoryFormatter.is_im_bot_turn failed: %s",
                type(exc).__name__,
            )
            return self._NOOP.is_im_bot_turn()

    def query_wants_workspace_analysis(self, query: str) -> bool:
        try:
            from lark.history_policy import query_wants_workspace_analysis
            return bool(query_wants_workspace_analysis(query))
        except Exception as exc:
            logger.debug(
                "_LegacyLarkHistoryFormatter."
                "query_wants_workspace_analysis failed: %s",
                type(exc).__name__,
            )
            return self._NOOP.query_wants_workspace_analysis(query)

    def im_effective_history_turns(self, query: str) -> Optional[int]:
        try:
            from lark.history_policy import lark_bot_effective_history_turns
            return lark_bot_effective_history_turns(query)
        except Exception as exc:
            logger.debug(
                "_LegacyLarkHistoryFormatter."
                "im_effective_history_turns failed: %s",
                type(exc).__name__,
            )
            return self._NOOP.im_effective_history_turns(query)

    def trim_im_history_for_dag(
        self,
        history: List[Dict[str, Any]],
        *,
        max_turns: int,
    ) -> List[Dict[str, Any]]:
        # The legacy Lark implementation requires current_qa_id /
        # current_query context (the in-flight QA row needs dropping +
        # self-contained-query detection skips supplement). Without
        # that context we delegate to the context-rich variant with
        # blank values; callers needing the full semantics should use
        # :meth:`trim_im_history_for_dag_with_context` directly.
        return self.trim_im_history_for_dag_with_context(
            history,
            current_qa_id=None,
            current_query="",
            max_supplement_turns=max_turns,
        )

    def trim_im_history_for_dag_with_context(
        self,
        history: List[Dict[str, Any]],
        *,
        current_qa_id: Optional[str],
        current_query: str,
        max_supplement_turns: int,
    ) -> List[Dict[str, Any]]:
        # PR-E6b: forward to ``lark.history_policy.trim_lark_im_history_for_dag``
        # with the full keyword surface. Fail-soft on adapter failure.
        try:
            from lark.history_policy import trim_lark_im_history_for_dag
            return trim_lark_im_history_for_dag(
                history,
                current_qa_id=current_qa_id,
                current_query=current_query,
                max_supplement_turns=max_supplement_turns,
            )
        except Exception as exc:
            logger.debug(
                "_LegacyLarkHistoryFormatter."
                "trim_im_history_for_dag_with_context failed: %s",
                type(exc).__name__,
            )
            return self._NOOP.trim_im_history_for_dag_with_context(
                history,
                current_qa_id=current_qa_id,
                current_query=current_query,
                max_supplement_turns=max_supplement_turns,
            )

    def format_im_history_for_dag_prompt(
        self,
        history: List[Dict[str, Any]],
    ) -> str:
        try:
            from lark.history_policy import format_lark_history_for_dag_prompt
            return format_lark_history_for_dag_prompt(history)
        except Exception as exc:
            logger.debug(
                "_LegacyLarkHistoryFormatter."
                "format_im_history_for_dag_prompt failed: %s",
                type(exc).__name__,
            )
            return self._NOOP.format_im_history_for_dag_prompt(history)


__all__ = [
    "ConversationHistoryFormatter",
    "ConversationHistoryFormatterNotInstalledError",
    "NoOpConversationHistoryFormatter",
    "set_conversation_history_formatter",
    "get_conversation_history_formatter",
    "reset_conversation_history_formatter_for_test",
]
# ``_LegacyLarkHistoryFormatter`` is intentionally NOT exported —
# matches the PR-E3/E4/E5 convention. Tests import it by name.
