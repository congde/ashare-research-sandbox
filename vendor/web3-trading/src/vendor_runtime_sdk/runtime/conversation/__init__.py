# -*- coding: utf-8 -*-
"""
runtime.conversation — ConversationRuntime package.

Refactored from a single 2988-line file into mixin-based modules.
External import paths are preserved:
    from vendor_runtime_sdk.runtime.conversation import ConversationRuntime
    from vendor_runtime_sdk.runtime.conversation import _RUNTIME_REGISTRY
"""

from vendor_runtime_sdk.runtime.conversation._compaction import CompactionMixin  # noqa: F401
from vendor_runtime_sdk.runtime.conversation._helpers import (  # noqa: F401
    _BACKGROUND_TASKS,
    _LAST_RUNTIME,
    _LLM_FAILURE_MARKERS,
    _RUNTIME_REGISTRY,
    MAX_LLM_RETRIES,
    STALE_STREAM_TIMEOUT,
    TurnResult,
    _done_dict,
    _error_dict,
    _failed_event_is_llm_availability,
    _is_llm_availability_error,
)
from vendor_runtime_sdk.runtime.conversation._lifecycle import LifecycleMixin  # noqa: F401
from vendor_runtime_sdk.runtime.conversation._metrics import MetricsMixin  # noqa: F401
from vendor_runtime_sdk.runtime.conversation._skill_review import SkillReviewMixin  # noqa: F401
from vendor_runtime_sdk.runtime.conversation._snapshot import SnapshotMixin  # noqa: F401
from vendor_runtime_sdk.runtime.conversation._sse_parsing import SSEParsingMixin  # noqa: F401
from vendor_runtime_sdk.runtime.conversation._stream import StreamMixin  # noqa: F401
from vendor_runtime_sdk.runtime.conversation._turn import TurnMixin  # noqa: F401


class ConversationRuntime(
    LifecycleMixin,
    SnapshotMixin,
    CompactionMixin,
    MetricsMixin,
    TurnMixin,
    StreamMixin,
    SkillReviewMixin,
    SSEParsingMixin,
):
    """
    ConversationRuntime — core ReAct loop (§5.1).

    This class composes all mixin capabilities via multiple inheritance.
    The __init__ method lives in LifecycleMixin.

    CLI / TUI usage (Sprint 2 PR-O1, PR-O4)
    ---------------------------------------
    The runtime works in non-HTTP contexts too — ``__init__`` accepts
    ``workspace_id`` / ``user_id`` / ``storage`` / ``prompter`` as
    explicit kwargs rather than relying on the ``OwnershipMiddleware``
    ContextVar or off-process HITL resume.

    For convenience, use :meth:`for_local_context`::

        from cli.storage_backend import get_local_storage_backend
        from cli.tui.runtime_bridge import _build_broker_prompter
        from vendor_runtime_sdk.runtime.conversation import ConversationRuntime

        rt = ConversationRuntime.for_local_context(
            agent_loop=loop,
            session_id=session_id,
            workspace_id=cfg.workspace_id,
            user_id=cfg.user_id,
            storage=get_local_storage_backend(),
            prompter=_build_broker_prompter(broker),  # PR-K TUI broker
        )

    This factory also:
    * Sets the ``web.middleware`` ContextVar defensively so downstream
      DAO calls that consult it (``SessionModel.get``, etc.) see the
      same workspace.
    * Sets ``prefer_storage_for_hitl=True`` so HITL persistence routes
      through ``storage.hitl_gates`` instead of the legacy inline
      Mongo fallback (which would crash in a non-Mongo process).
    """

    @classmethod
    def for_local_context(
        cls,
        *,
        agent_loop,
        session_id: str,
        workspace_id: str,
        user_id: str,
        storage=None,
        prompter=None,
        **kwargs,
    ) -> "ConversationRuntime":
        """Sprint 2 PR-O1 — convenience factory for CLI / TUI callers.

        Differences vs the bare constructor:
        * Requires ``workspace_id`` and ``user_id`` (keyword-only) — CLI
          callers always have these from ``CliConfig``; the explicit
          requirement catches the "forgot to pass identity" bug at
          construction rather than mid-flight.
        * Calls ``web.middleware.set_ownership(workspace_id, user_id)``
          before returning so any DAO call that reads
          ``get_workspace_id()`` from the ContextVar sees the right
          tenant (defense in depth — if the CLI's outer
          ``set_ownership`` call was skipped or got overridden by
          another coroutine, this restores it).
        * ``set_ownership`` failure is fail-soft: caller still gets a
          valid runtime; only the ContextVar-using DAO paths will see
          an empty workspace. The ``__init__`` already wires
          ``self._workspace_id`` so explicit-arg DAO paths work
          regardless.

        Any other ``__init__`` kwarg flows through via ``**kwargs``.
        """
        try:
            # PR-E2b (SDK extraction §5 PR-E2b): owner_id / avatar_id /
            # set_ownership are now sourced from runtime.context.  The legacy
            # web.middleware.* call continues via the runtime.context
            # fallback path so runtime behaviour is unchanged in Phase 0.
            # Phase 2 removes the fallback when web/ leaves the engine
            # import surface.
            from vendor_runtime_sdk.runtime.context import set_ownership
            set_ownership(workspace_id, user_id)
        except Exception:  # noqa: BLE001 — fail-soft; explicit args still work
            pass
        # Sprint 2 PR-O2: CLI / TUI callers route HITL persistence through
        # ``storage.hitl_gates`` regardless of the global toggle, because
        # the fallback (inline Mongo write) would crash in a non-Mongo
        # process. Web continues to honour the toggle for rollout pacing.
        kwargs.setdefault("prefer_storage_for_hitl", True)
        return cls(
            agent_loop=agent_loop,
            session_id=session_id,
            workspace_id=workspace_id,
            user_id=user_id,
            storage=storage,
            prompter=prompter,
            **kwargs,
        )
