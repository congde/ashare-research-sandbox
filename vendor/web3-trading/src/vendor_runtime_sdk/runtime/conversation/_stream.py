# -*- coding: utf-8 -*-
"""
StreamMixin — wrap_agent_stream (the main SSE streaming method)

Auto-extracted from runtime/conversation.py during refactoring.
Part of the ConversationRuntime mixin chain.
"""

from __future__ import annotations

from vendor_runtime_sdk.runtime.fallback.manager import FallbackManager

import time
import asyncio
import logging
import os
from contextvars import ContextVar


# Chained-V2-HITL fix: when ``continue_after_hitl_approval`` runs a V2
# resumed agent and that agent pauses at ANOTHER HITL gate, the
# in-stream ``_maybe_handle_passthrough_requires_approval`` handler
# would otherwise persist ``hitl_pending.qa_id`` as the V2-spawned
# qa's id (Q2 / Q3 / …). The next ``/hitl/decide`` would then drive
# ``continue_after_hitl_approval`` against THAT inner qa_id, and the
# terminal SSE update would land on a cache key the original
# ``/chat/local_query`` SSE consumer never reads — the chat bubble
# stays at "处理中" forever even though the backend completed.
#
# Workaround: ``continue_after_hitl_approval`` sets this ContextVar
# to the ORIGINAL qa_id (the one the SSE consumer is on) before
# running the V2 stream, so the persister can override the agent's
# local qa_id with it.
_ORIGINAL_SSE_QA_ID: ContextVar[str] = ContextVar(
    "_aibuddy_hitl_original_sse_qa_id", default=""
)

from vendor_runtime_sdk.runtime.conversation._helpers import _RUNTIME_REGISTRY, _is_llm_availability_error, _failed_event_is_llm_availability
from typing import AsyncGenerator, List, Optional
from vendor_runtime_sdk.runtime.budget.pressure import BudgetPressure, inject_into_last_tool_result
from vendor_runtime_sdk.runtime.session.fsm import IllegalTransitionError, SessionFSM, SessionState

class StreamMixin:
    """StreamMixin — wrap_agent_stream (the main SSE streaming method)"""

    async def wrap_agent_stream(
        self,
        agent_stream: AsyncGenerator,
        agent_ref=None,
    ) -> AsyncGenerator:
        """
        Wrap a legacy agent.run() async generator with runtime lifecycle guardrails.

        This enables incremental migration: the agent still drives its own internal
        loop (planning, DAG, tool calls), but the runtime adds:
          - Session FSM transitions (IDLE → RUNNING → TERMINATED)
          - Plugin hooks (session_start / session_end)
          - Activity tracking (per-event touch)
          - Telemetry recording (turn metrics)
          - PolicyEngine integration point (future: per-tool-call check)
          - Interrupt handling (dead connection → cancel)

        Usage in chat.py::

            _runtime = ConversationRuntime(session_id=..., ...)
            async for event in _runtime.wrap_agent_stream(agent.run()):
                yield event  # SSE to client
        """
        start_ts = time.time()

        # Store agent reference so trajectory/telemetry can access query + response
        if agent_ref is not None:
            self._agent_ref = agent_ref

        # Re-register in case a prior turn unregistered us
        if self._session_id:
            _RUNTIME_REGISTRY[self._session_id] = self

        # Bridge our FallbackManager into the per-task ContextVar so
        # ``llm.stream_llm`` can swap to the next model in-place when an
        # LLM call hits a 429 / availability error — instead of bubbling
        # the failure up to ``agent.run()``, yielding FAILED, and forcing
        # ``ConversationRuntime`` to restart the entire agent generator
        # from scratch (which used to re-run coordinator dispatch_all
        # for nothing). The token is reset in the finally below so this
        # never bleeds across turns or sessions.
        from vendor_runtime_sdk.runtime.conversation._llm_context import (
            set_active_fallback_manager as _set_fb_ctx,
            reset_active_fallback_manager as _reset_fb_ctx,
        )
        _fb_ctx_token = _set_fb_ctx(self._fallback)

        # ── Pre-turn reliability hooks (consolidated from _preflight) ─────
        self._preflight([])

        # ── Preflight compression (§5.6 — live SSE path) ──────────────────
        # The live path doesn't own a messages list — compaction is driven by
        # the agent's ContextAssembler (which reads MongoDB transcript events).
        # We still probe via Compactor.compact_if_needed() using an estimate
        # from the transcript so we can surface session.compression SSE events
        # to the client even on the wrap path.
        if self._compactor and self._toggles.is_enabled("compaction"):
            try:
                reader = getattr(self._compactor, "_reader", None)
                if reader is not None:
                    _events = await reader.load_events(limit=500)
                    _tokens_before = sum(
                        len(getattr(e, "content", "") or "") for e in _events
                    ) // 4  # heuristic — assembler has a proper estimator but this is
                            # enough to reach the should_compact threshold
                    if self._compactor.should_compact(
                        _tokens_before, event_count=len(_events)
                    ):
                        # P2-3: fire memory-provider pre-compress hook before
                        # compacting so critical state (user preferences, pending
                        # items) survives into cross-session memory scope.
                        if (
                            self._memory_provider is not None
                            and self._toggles.is_enabled("memory_provider")
                        ):
                            try:
                                if self._memory_provider.is_available():
                                    _msgs_for_flush = [
                                        {"role": "user" if "user" in str(getattr(e, "event_type", "")) else "assistant",
                                         "content": getattr(e, "content", "") or ""}
                                        for e in _events
                                    ]
                                    await asyncio.to_thread(
                                        self._memory_provider.on_pre_compress,
                                        _msgs_for_flush,
                                    )
                                    self._mem_flush_count += 1
                            except Exception as _mp_exc:
                                logger.warning(
                                    "ConversationRuntime[%s]: wrap-path on_pre_compress failed: %s",
                                    self._session_id, _mp_exc,
                                )

                        _summary = await self._compactor.compact(_events)
                        if _summary:
                            self._compaction_triggered += 1
                            self._pending_compaction_event = self._build_compaction_event(
                                passes=1,
                                tokens_before=_tokens_before,
                                tokens_after=max(0, _tokens_before - len(_summary) // 4),
                            )
                            if self._toggles.is_enabled("session_fsm") and not self._fsm.is_terminal:
                                self._fsm.mark_compacted()
            except Exception as _compact_exc:
                logger.debug(
                    "ConversationRuntime[%s]: wrap-path preflight compaction no-op: %s",
                    self._session_id, _compact_exc,
                )

        # ── Drain pending compression SSE event ────────────────────────────
        if self._pending_compaction_event is not None:
            logger.info(
                "ConversationRuntime[%s]: draining pending session.compression (preflight drain)",
                self._session_id,
            )
            yield self._pending_compaction_event
            self._pending_compaction_event = None

        # ── Pre-turn lifecycle ────────────────────────────────────────────
        if self._toggles.is_enabled("session_fsm"):
            try:
                self._record_fsm_transition("running")
                self._fsm.mark_running()
            except IllegalTransitionError as e:
                logger.error("ConversationRuntime FSM: %s", e)
                self._unregister()
                return

        if self._toggles.is_enabled("plugin_hooks"):
            self._dispatcher.fire_session_start(self._session_id, self._workspace_id)

        # ── [集成点 D] MemoryProvider pre-turn hook ────────────────────
        if self._memory_provider and self._toggles.is_enabled("memory_provider"):
            try:
                if self._memory_provider.is_available():
                    await asyncio.to_thread(self._memory_provider.initialize, self._session_id)
                    await asyncio.to_thread(self._memory_provider.on_session_start, [])
            except Exception as _mp_exc:
                logger.debug("ConversationRuntime: memory_provider.on_session_start failed: %s", _mp_exc)

        self._activity.touch("agent stream started")
        self._last_response_text = ""  # capture response for outcome_grader
        iteration = 0
        self._current_iteration = 0

        # Snapshot fallback count at turn start so we can detect new triggers
        _initial_fallback_attempt = 0
        if self._fallback is not None:
            _initial_fallback_attempt = int(getattr(self._fallback, "fallback_attempt", 0) or 0)

        # Semantic ReAct step types — only these START events count as "one iteration"
        # for budget pressure purposes. This matches the original design intent of
        # BudgetPressure (max_iterations=10 = max 10 ReAct rounds per turn) rather
        # than counting every raw SSE event (which would include e.g. 50+ CONTENT
        # chunks for a long streaming answer).
        # Phase 6.3: per-turn tool call log for activity distillation
        self._tool_calls_in_turn = []

        # ── [§7.1] OTEL agent turn span ───────────────────────────────────────
        # Fail-soft: any OTEL error must not affect the live stream path.
        _otel_turn_ctx = None
        try:
            from vendor_runtime_sdk.runtime.otel import agent_turn_span as _agent_turn_span
            _agent_ref_now = getattr(self, "_agent_ref", None)
            _otel_turn_ctx = _agent_turn_span(
                session_id=self._session_id,
                user_id=getattr(_agent_ref_now, "user_id", "") or "",
                query=getattr(_agent_ref_now, "query", "") or "",
                agent_type=getattr(_agent_ref_now, "agent_type", "") or "",
            )
            _otel_turn_ctx.__enter__()
        except Exception:
            _otel_turn_ctx = None

        # Per-turn active tool span (nested child of agent_turn span)
        _otel_tool_ctx: object = None

        SEMANTIC_ITERATION_TYPES = {
            "QUERY_ANALYSIS",           # initial query parsing
            "RESEARCH_DECOMPOSITION",   # research sub-task breakdown
            "DEEP_THINK",               # reasoning step
            "TOOL_EXECUTION",           # tool call (ReAct) or DAG batch start
            "TOOL_CALL",                # individual DAG task start — without this,
                                        # DAG agents that batch 20 tools inside one
                                        # TOOL_EXECUTION step never push the budget
                                        # pressure above NORMAL.
            "ANSWER_RESPONSE",          # final answer generation
            "REPORT",                   # research report generation
            "PROGRESS",                 # orchestration progress
        }

        # ── Environment timeout — derived from snapshot if available ────────
        # Wall-clock enforcement: we compute a hard deadline and wrap each
        # agent_stream.__anext__() in asyncio.wait_for() with the remaining
        # budget. This guarantees the timeout fires on time even when the
        # agent is stuck inside a long LLM call producing no intermediate
        # events (replaces the prior per-event polling which could overshoot
        # the configured timeout by the duration of one LLM call).
        _env_timeout = None
        _deadline: Optional[float] = None
        if self._env_snapshot:
            _env_timeout = self._env_snapshot.config.resources.timeout_seconds
            if _env_timeout and _env_timeout > 0:
                _deadline = start_ts + float(_env_timeout)

        # ── Stream events with runtime guardrails ─────────────────────────
        stop_reason = "end_turn"
        try:
            _stream_iter = agent_stream.__aiter__()
            while True:
                # Interrupt check (polled before each event wait)
                if self._interrupt_requested:
                    logger.info(
                        "ConversationRuntime[%s]: interrupt during agent stream — %s",
                        self._session_id, self._interrupt_reason,
                    )
                    stop_reason = "cancelled"
                    break

                # HITL Redesign — operator pressed Cancel run on the
                # frontend. ``_cancel_requested`` is set by the
                # ``/api/v1/sessions/{id}/cancel`` endpoint. Polled here
                # so we stop on the next event boundary even when the
                # agent stream itself is mid-tool-execution. We do NOT
                # interrupt the in-flight tool — that would corrupt
                # arbitrary state; we just stop emitting events and
                # flip the FSM. Tools that finish after this point have
                # their results discarded.
                if getattr(self, "_cancel_requested", False):
                    logger.info(
                        "ConversationRuntime[%s]: cancel_requested — terminating stream",
                        self._session_id,
                    )
                    stop_reason = "cancelled"
                    try:
                        if self._fsm.can_transition(SessionState.TERMINATED):
                            self._fsm.transition(SessionState.TERMINATED)
                    except Exception:
                        pass
                    break

                # Wall-clock deadline — preempts even unbounded LLM waits.
                try:
                    if _deadline is not None:
                        _remaining = _deadline - time.time()
                        if _remaining <= 0:
                            logger.warning(
                                "ConversationRuntime[%s]: Environment timeout (%ds) "
                                "exceeded before next event",
                                self._session_id, _env_timeout,
                            )
                            stop_reason = "environment_timeout"
                            break
                        event = await asyncio.wait_for(
                            _stream_iter.__anext__(), timeout=_remaining,
                        )
                    else:
                        event = await _stream_iter.__anext__()
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    logger.warning(
                        "ConversationRuntime[%s]: Environment timeout (%ds) exceeded "
                        "while awaiting next agent event (cancelling stream)",
                        self._session_id, _env_timeout,
                    )
                    stop_reason = "environment_timeout"
                    # Best-effort: signal cancellation to the underlying stream
                    # so HTTP/LLM connections can be closed.
                    try:
                        aclose = getattr(agent_stream, "aclose", None)
                        if aclose is not None:
                            await aclose()
                    except Exception as _aclose_exc:
                        logger.debug(
                            "ConversationRuntime[%s]: aclose after timeout failed: %s",
                            self._session_id, _aclose_exc,
                        )
                    break
                except Exception as _stream_exc:
                    # T4-1: LLM auto-fallback in the live SSE path.
                    # When the agent's internal LLM call throws an error
                    # that's a model-availability problem (auth / rate /
                    # 5xx / connection), swap to the next model in the
                    # FallbackManager chain and restart agent.run() from
                    # scratch. Non-LLM errors propagate as before.
                    if (
                        agent_ref is not None
                        and self._fallback is not None
                        and self._toggles.is_enabled("fallback_restore")
                        and _is_llm_availability_error(_stream_exc)
                        and self._fallback.try_fallback()
                    ):
                        _fb_cur = self._fallback.current
                        try:
                            from vendor_runtime_sdk.llm.base import create_llm as _create_llm
                            _fb_llm, _fb_model = _create_llm(
                                api_key=_fb_cur.api_key,
                                base_url=_fb_cur.base_url,
                                model_name=_fb_cur.model,
                            )
                        except Exception as _build_exc:
                            logger.error(
                                "ConversationRuntime[%s]: failed to build "
                                "fallback LLM client (%s) — re-raising original error",
                                self._session_id, _build_exc,
                            )
                            raise _stream_exc
                        # Hot-swap the agent's LLM ref + the loop's snapshot
                        try:
                            setattr(agent_ref, "llm", _fb_llm)
                            setattr(agent_ref, "model_name", _fb_model)
                        except Exception:
                            pass
                        if self._loop is not None:
                            try:
                                self._loop.llm = _fb_llm
                                self._loop.model_name = _fb_model
                            except Exception:
                                pass
                        self._record_fallback(_fb_model, "llm_availability_error")
                        logger.warning(
                            "ConversationRuntime[%s]: live-path fallback #%d — "
                            "switched to '%s' (base_url=%s) after %s",
                            self._session_id,
                            self._fallback.fallback_attempt,
                            _fb_model,
                            _fb_cur.base_url,
                            type(_stream_exc).__name__,
                        )
                        # Best-effort close the dead generator.
                        try:
                            _aclose = getattr(agent_stream, "aclose", None)
                            if _aclose is not None:
                                await _aclose()
                        except Exception:
                            pass
                        # Restart from a fresh agent.run() — re-emits any
                        # events streamed before the failure (frontend
                        # de-dupes via qaId+offset).
                        try:
                            agent_stream = agent_ref.run()
                            _stream_iter = agent_stream.__aiter__()
                        except Exception as _restart_exc:
                            logger.error(
                                "ConversationRuntime[%s]: failed to restart "
                                "agent.run() after fallback (%s)",
                                self._session_id, _restart_exc,
                            )
                            raise _stream_exc
                        # Reset per-turn iteration counters so budget
                        # pressure re-tracks the retry cleanly.
                        iteration = 0
                        self._current_iteration = 0
                        self._synthesis_grace_used = False
                        self._conclude_directive_injected = False
                        continue
                    # Not a fallback-eligible error or chain exhausted —
                    # let it bubble to the outer try/except.
                    raise

                # Parse event FIRST so iteration counting can gate on semantic types.
                # Events yielded from agent.run() are pre-serialized SSE strings like
                # 'data: {...}\n\n'. Parse to extract type/status/content.
                parsed = self._parse_sse_event(event)

                event_type_str = ""
                status = ""
                if parsed:
                    event_type_str = str(parsed.get("type", "") or parsed.get("event_type", "") or "")
                    status = str(parsed.get("status", "") or "")
                elif hasattr(event, "event_type"):
                    event_type_str = str(getattr(event, "event_type", None) or getattr(event, "type", "") or "")
                elif hasattr(event, "type"):
                    event_type_str = str(getattr(event, "type", "") or "")
                elif isinstance(event, dict):
                    event_type_str = str(event.get("type", "") or event.get("event_type", "") or "")
                    status = str(event.get("status", "") or "")

                event_type_upper = event_type_str.upper()
                event_type_lower = event_type_str.lower()
                status_upper = status.upper()

                # T4-1: Live-path LLM fallback via FAILED-event sniffing.
                # agent.base.run() catches LLM auth/rate/5xx errors in its
                # own try/except and yields a FAILED StreamResponse rather
                # than raising. The outer `except` can't see those — so we
                # intercept here, advance the fallback chain, rebuild the
                # LLM client, restart agent.run(), and swallow the FAILED
                # event so the client sees a clean stream.
                if (
                    status_upper == "FAILED"
                    and agent_ref is not None
                    and self._fallback is not None
                    and self._toggles.is_enabled("fallback_restore")
                    and _failed_event_is_llm_availability(parsed)
                    and self._fallback.try_fallback()
                ):
                    _fb_cur = self._fallback.current
                    try:
                        from vendor_runtime_sdk.llm.base import create_llm as _create_llm
                        _fb_llm, _fb_model = _create_llm(
                            api_key=_fb_cur.api_key,
                            base_url=_fb_cur.base_url,
                            model_name=_fb_cur.model,
                        )
                    except Exception as _build_exc:
                        logger.error(
                            "ConversationRuntime[%s]: failed to build fallback "
                            "LLM client for FAILED-event path (%s) — letting "
                            "FAILED event propagate",
                            self._session_id, _build_exc,
                        )
                    else:
                        # Patch instance-level refs so the rebuilt agent sees the new client.
                        try:
                            setattr(agent_ref, "llm", _fb_llm)
                            setattr(agent_ref, "model_name", _fb_model)
                        except Exception:
                            pass
                        if self._loop is not None:
                            try:
                                self._loop.llm = _fb_llm
                                self._loop.model_name = _fb_model
                            except Exception:
                                pass
                        # Patch module-level globals too — agent.base._destroy
                        # does `llm, model_name = create_llm()` in its finally
                        # block which re-reads env vars from the primary.
                        try:
                            import vendor_runtime_sdk.agent.base as _agent_base_mod
                            _agent_base_mod.llm = _fb_llm
                            _agent_base_mod.model_name = _fb_model
                        except Exception:
                            pass
                        self._record_fallback(_fb_model, "llm_availability_error")
                        logger.warning(
                            "ConversationRuntime[%s]: live-path fallback #%d via "
                            "FAILED-event sniff — switched to '%s' (base_url=%s); "
                            "restarting agent.run()",
                            self._session_id,
                            self._fallback.fallback_attempt,
                            _fb_model,
                            _fb_cur.base_url,
                        )
                        # Best-effort close the dead generator.
                        try:
                            _aclose = getattr(agent_stream, "aclose", None)
                            if _aclose is not None:
                                await _aclose()
                        except Exception:
                            pass
                        try:
                            agent_stream = agent_ref.run()
                            _stream_iter = agent_stream.__aiter__()
                        except Exception as _restart_exc:
                            logger.error(
                                "ConversationRuntime[%s]: failed to restart "
                                "agent.run() after FAILED-event fallback (%s) — "
                                "letting FAILED event propagate",
                                self._session_id, _restart_exc,
                            )
                        else:
                            iteration = 0
                            self._current_iteration = 0
                            self._synthesis_grace_used = False
                            self._conclude_directive_injected = False
                            # Swallow the FAILED event and pull the next one.
                            continue

                # Activity tracking (every event advances the heartbeat)
                self._activity.touch(f"agent event: {event_type_str or 'stream'}")

                # Iteration counter — increments on semantic step boundaries
                # (START of a major phase). For ReAct agents this is 1 per
                # tool round; for DAG agents each TOOL_CALL task_start counts
                # too, so a 20-task DAG pushes iteration up to ~23.
                if status_upper == "START" and event_type_upper in SEMANTIC_ITERATION_TYPES:
                    iteration += 1
                    self._current_iteration = iteration
                    # Synthesis event types — permitted once past the
                    # hard cap as a grace slot so the agent can wrap up.
                    _SYNTHESIS_TYPES = {"ANSWER_RESPONSE", "REPORT"}
                    _is_synthesis = event_type_upper in _SYNTHESIS_TYPES
                    # T3-2: Hard cap — `hard_max_iterations` is an absolute
                    # safety net, not a guillotine.
                    #   1. When iteration == hard_max, force-inject a
                    #      critical "CONCLUDE NOW" directive (belt-and-
                    #      suspenders on top of the T3-1 critical tier).
                    #   2. When iteration > hard_max, allow exactly one
                    #      synthesis event (ANSWER_RESPONSE / REPORT) to
                    #      pass through as a grace slot so the agent can
                    #      emit its final answer.
                    #   3. Any further semantic event past the cap trips
                    #      stop_reason=budget_exceeded and the stream is
                    #      closed.
                    if self._hard_max_iterations is not None:
                        # --- Past-the-cap: grace OR terminate -----------
                        if iteration > self._hard_max_iterations:
                            if _is_synthesis and not self._synthesis_grace_used:
                                self._synthesis_grace_used = True
                                logger.info(
                                    "ConversationRuntime[%s]: synthesis grace "
                                    "event allowed past hard_max_iterations=%d "
                                    "(iteration=%d type=%s)",
                                    self._session_id,
                                    self._hard_max_iterations,
                                    iteration,
                                    event_type_upper,
                                )
                                # fall through — let this event stream
                            else:
                                logger.warning(
                                    "ConversationRuntime[%s]: hard_max_iterations=%d "
                                    "exceeded (iteration=%d type=%s) — stop_reason=budget_exceeded",
                                    self._session_id,
                                    self._hard_max_iterations,
                                    iteration,
                                    event_type_upper,
                                )
                                stop_reason = "budget_exceeded"
                                try:
                                    from vendor_runtime_sdk.agent.schema import StepType, StreamResponse, StreamStatusType

                                    _qa_id = None
                                    _agent = getattr(self, "_agent_ref", None)
                                    if _agent is not None:
                                        _qa_id = getattr(_agent, "qa_id", None) or (
                                            getattr(getattr(_agent, "qa", None), "id", None)
                                        )
                                    _be_event = StreamResponse(
                                        sessionId=self._session_id,
                                        qaId=_qa_id,
                                        type=StepType.SYSTEM,
                                        status=StreamStatusType.FAILED,
                                        content="",
                                        log="budget_exceeded",
                                        extraInfo={
                                            "stop_reason": "budget_exceeded",
                                            "hard_max_iterations": self._hard_max_iterations,
                                            "iteration": iteration,
                                            "synthesis_grace_used": self._synthesis_grace_used,
                                        },
                                    ).model_dump_json(exclude={"save", "deliver"})
                                    yield _be_event
                                except Exception as _emit_exc:
                                    logger.warning(
                                        "ConversationRuntime[%s]: failed to emit "
                                        "budget_exceeded event — %s",
                                        self._session_id, _emit_exc,
                                    )
                                try:
                                    aclose = getattr(agent_stream, "aclose", None)
                                    if aclose is not None:
                                        await aclose()
                                except Exception as _aclose_exc:
                                    logger.debug(
                                        "ConversationRuntime[%s]: aclose after "
                                        "budget_exceeded failed: %s",
                                        self._session_id, _aclose_exc,
                                    )
                                break
                        # --- At-the-cap: force the "conclude now" note -
                        elif (
                            iteration == self._hard_max_iterations
                            and not self._conclude_directive_injected
                            and self._agent_ref is not None
                            and self._toggles.is_enabled("budget_pressure")
                        ):
                            try:
                                _final_notice = (
                                    "<budget_warning level='critical'>"
                                    "You have reached the hard iteration cap "
                                    f"({self._hard_max_iterations}). DO NOT plan "
                                    "or invoke any more tools. Synthesize a "
                                    "final answer from the information already "
                                    "gathered, state any remaining uncertainty "
                                    "explicitly, and conclude this turn now."
                                    "</budget_warning>"
                                )
                                _prev = getattr(
                                    self._agent_ref,
                                    "_runtime_injected_append_prompt",
                                    "",
                                ) or ""
                                if _final_notice not in _prev:
                                    merged = (
                                        (_prev + "\n\n" + _final_notice)
                                        if _prev
                                        else _final_notice
                                    )
                                    setattr(
                                        self._agent_ref,
                                        "_runtime_injected_append_prompt",
                                        merged,
                                    )
                                self._conclude_directive_injected = True
                                logger.info(
                                    "ConversationRuntime[%s]: injected "
                                    "forced-conclude directive at iteration=%d "
                                    "(hard_max=%d)",
                                    self._session_id,
                                    iteration,
                                    self._hard_max_iterations,
                                )
                            except Exception as _inj_exc:
                                logger.debug(
                                    "ConversationRuntime[%s]: conclude directive "
                                    "injection failed: %s",
                                    self._session_id, _inj_exc,
                                )
                    # Auto-expand max_iterations when the stream produces
                    # more iterations than the initial estimate. DAG agents
                    # batch many tool calls whose count is unknown at init
                    # time. Without expansion the ratio would cap at 1.0 too
                    # early and the pressure indicator would flatline at RED
                    # while the agent still has work to do.
                    if iteration >= self._max_iterations:
                        # Never expand past the hard cap (if one is set).
                        _new_max = iteration + 3
                        if self._hard_max_iterations is not None:
                            _new_max = min(_new_max, self._hard_max_iterations)
                        if _new_max > self._max_iterations:
                            self._max_iterations = _new_max
                            self._budget_pressure = BudgetPressure(
                                max_iterations=self._max_iterations,
                            )
                    # §5.8 Budget pressure injection for the live path.
                    # _run_loop (ReAct) calls inject_into_last_tool_result on
                    # its own messages buffer; wrap_agent_stream doesn't own
                    # that buffer. Instead we stash the warning on the agent
                    # via `_runtime_injected_append_prompt`, which
                    # response_mixin._build_llm_context merges into
                    # append_system_prompt on the next LLM call (usually
                    # the ANSWER_RESPONSE synthesis). Fail-soft: any error
                    # here is dropped — the indicator still updates via
                    # get_pressure's side effect on _last_injected_level.
                    try:
                        _warn = self._budget_pressure.get_pressure(iteration)
                        if _warn and self._toggles.is_enabled("budget_pressure") and self._agent_ref is not None:
                            _prev = getattr(self._agent_ref, "_runtime_injected_append_prompt", "") or ""
                            # Avoid duplicating the same tier warning if the
                            # agent hasn't consumed the previous one yet.
                            if _warn not in _prev:
                                merged = (_prev + "\n\n" + _warn) if _prev else _warn
                                try:
                                    setattr(self._agent_ref, "_runtime_injected_append_prompt", merged)
                                except Exception:
                                    pass
                    except Exception:
                        pass
                if "tool" in event_type_lower and status_upper == "START":
                    # set_current_tool increments tool_call_count internally
                    tool_name = ""
                    if parsed:
                        tool_name = str(parsed.get("content", "") or parsed.get("tool_name", "") or "")[:80]
                    self._activity.set_current_tool(tool_name or "unknown")
                    # Phase 6.3: capture tool name + success for activity distillation
                    if not hasattr(self, "_tool_calls_in_turn"):
                        self._tool_calls_in_turn = []
                    if tool_name:
                        self._tool_calls_in_turn.append({"name": tool_name, "success": True})
                    # §7.1 OTEL: open child tool_call span
                    try:
                        from vendor_runtime_sdk.runtime.otel import tool_call_span as _tool_call_span
                        _otel_tool_ctx = _tool_call_span(
                            tool_name=tool_name or "unknown",
                            session_id=self._session_id,
                        )
                        _otel_tool_ctx.__enter__()  # type: ignore[union-attr]
                    except Exception:
                        _otel_tool_ctx = None
                if "tool" in event_type_lower and status_upper == "END":
                    self._activity.clear_current_tool()
                    # Phase 6.3: detect tool failure from event log/status
                    _tool_success = True
                    if parsed and self._tool_calls_in_turn:
                        log_text = str(parsed.get("log", "")).lower()
                        if "fail" in log_text or "error" in log_text or "success=false" in log_text:
                            self._tool_calls_in_turn[-1]["success"] = False
                            _tool_success = False
                    # §7.1 OTEL: close child tool_call span
                    if _otel_tool_ctx is not None:
                        try:
                            _otel_tool_ctx.__exit__(None, None, None)  # type: ignore[union-attr]
                        except Exception:
                            pass
                        _otel_tool_ctx = None
                # Count LLM-like events as API calls (DEEP_THINK, ANSWER_RESPONSE, QUERY_ANALYSIS, etc.)
                if any(k in event_type_lower for k in ("answer", "deep_think", "query_analysis", "report", "research")):
                    if status_upper == "START":
                        self._activity.record_api_call()

                # Capture response text for outcome_grader (last CONTENT/ANSWER_RESPONSE chunk)
                if event_type_upper in ("CONTENT", "ANSWER_RESPONSE") and status_upper == "PENDING":
                    _content = ""
                    if parsed and isinstance(parsed.get("content"), str):
                        _content = parsed["content"]
                    if _content:
                        self._last_response_text = _content

                # Best-effort token extraction: use parsed dict if available,
                # else fall back to the raw event.
                self._maybe_extract_tokens(parsed if parsed else event)

                # P5: Record token usage to quota manager
                if self._token_quota and (self._input_tokens_last or self._output_tokens_last):
                    try:
                        _agent_ref = getattr(self, "_agent_ref", None)
                        _user_id = getattr(_agent_ref, "user_id", "") or ""
                        asyncio.create_task(
                            self._token_quota.record_usage(
                                user_id=_user_id,
                                workspace_id=self._workspace_id,
                                session_id=self._session_id,
                                tokens=self._input_tokens_last + self._output_tokens_last,
                            )
                        )
                    except Exception:
                        pass

                # P5: Pre-LLM quota check on semantic iteration start
                if status_upper == "START" and event_type_upper in SEMANTIC_ITERATION_TYPES:
                    if self._token_quota and self._toggles.is_enabled("token_quota"):
                        try:
                            _agent_ref = getattr(self, "_agent_ref", None)
                            _user_id = getattr(_agent_ref, "user_id", "") or ""
                            quota_result = await self._token_quota.check_quota(
                                user_id=_user_id,
                                workspace_id=self._workspace_id,
                                session_id=self._session_id,
                                estimated_tokens=0,  # no pre-estimation, check current
                            )
                            if quota_result.is_hard_limit and self._token_quota._config.enforce_hard_limit:
                                logger.warning(
                                    "ConversationRuntime[%s]: token quota exceeded — %s",
                                    self._session_id, quota_result.message,
                                )
                                # Prometheus: record quota rejection
                                try:
                                    from vendor_runtime_sdk.libs.agent_metrics import record_quota_rejection
                                    record_quota_rejection(quota_result.scope)
                                except Exception:
                                    pass
                                stop_reason = "quota_exceeded"
                                yield {
                                    "event_type": "status",
                                    "data": {"message": quota_result.message},
                                    "session_id": self._session_id,
                                }
                                break
                        except Exception:
                            pass  # quota check is advisory, never block

                # Detect fallback trigger by watching fallback manager state
                if self._fallback is not None:
                    try:
                        cur_attempt = int(getattr(self._fallback, "fallback_attempt", 0) or 0)
                        if cur_attempt > _initial_fallback_attempt + self._fallback_count:
                            cur_model = ""
                            _cur = getattr(self._fallback, "current", None)
                            if _cur is not None:
                                cur_model = getattr(_cur, "model", "") or getattr(_cur, "model_name", "")
                            self._record_fallback(cur_model, "chain_step")
                    except Exception:
                        pass

                # Drain pending session.compression event — Compactor may have
                # fired inside agent.run() (via ContextAssembler) after the
                # preflight check; surface it on the next outgoing yield.
                if self._pending_compaction_event is not None:
                    logger.info(
                        "ConversationRuntime[%s]: draining pending session.compression SSE event",
                        self._session_id,
                    )
                    yield self._pending_compaction_event
                    self._pending_compaction_event = None

                # HITL Redesign — Coder milestone branch (and other
                # agents that surface REQUIRES_APPROVAL by direct SSE
                # passthrough rather than raising HITLRequiredError)
                # bypass the exception-path persist + FSM flip below.
                # Catch them here so /hitl/decide always finds a
                # populated ``hitl_pending`` row.
                if status_upper == "REQUIRES_APPROVAL":
                    try:
                        await self._maybe_handle_passthrough_requires_approval(parsed)
                    except Exception as _hitl_exc:
                        logger.debug(
                            "ConversationRuntime[%s]: passthrough HITL handler failed: %s",
                            self._session_id, _hitl_exc,
                        )

                yield event

        except asyncio.CancelledError:
            logger.info("ConversationRuntime[%s]: agent stream cancelled", self._session_id)
            stop_reason = "cancelled"
        except Exception as exc:
            # ── HITL gate: HITLRequiredError propagated from ToolMixin ────────
            _is_hitl = False
            try:
                from vendor_runtime_sdk.runtime.policy.exceptions import HITLRequiredError as _HITLErr
                _is_hitl = isinstance(exc, _HITLErr)
            except ImportError:
                pass
            if _is_hitl:
                logger.info(
                    "ConversationRuntime[%s]: HITL gate — tool=%s rule=%s",
                    self._session_id,
                    getattr(exc, "tool_name", "unknown"),
                    getattr(exc, "rule_id", None),
                )
                stop_reason = "requires_approval"
                # Emit REQUIRES_APPROVAL SSE event for the frontend
                # (docs/frontend-hitl-spec.md).  Fail-soft: never break the
                # stream if the schema import is somehow unavailable.
                try:
                    from vendor_runtime_sdk.agent.schema import StepType, StreamResponse, StreamStatusType

                    _qa_id = None
                    _agent = getattr(self, "_agent_ref", None)
                    if _agent is not None:
                        _qa_id = getattr(_agent, "qa_id", None) or (
                            getattr(getattr(_agent, "qa", None), "id", None)
                        )
                    # ``hitl_v2_protocol`` (default ON) gates the V2 envelope
                    # fields. When OFF, downgrade to V1 schema (only
                    # ``tool_args`` + ``policy_message`` + ``rule_id``) so
                    # the legacy frontend keeps working unchanged.
                    try:
                        from vendor_runtime_sdk.runtime.config.guards import (
                            is_module_enabled as _is_v2_enabled,
                        )
                        _v2 = _is_v2_enabled("hitl_v2_protocol")
                    except Exception:
                        _v2 = True
                    # Sprint 2 PR-M2 — envelope construction lives in
                    # ``runtime.hitl.dispatch`` so both Web (inline emit
                    # path) and any future runtime share one
                    # implementation.
                    from vendor_runtime_sdk.runtime.hitl.dispatch import (
                        build_envelope_from_hitl_exception,
                    )
                    _extra = build_envelope_from_hitl_exception(exc, v2=_v2)
                    _hitl_event = StreamResponse(
                        sessionId=self._session_id,
                        qaId=_qa_id,
                        type=StepType.SYSTEM,
                        status=StreamStatusType.REQUIRES_APPROVAL,
                        content="",
                        log=getattr(exc, "reason", "") or "Human approval required",
                        extraInfo=_extra,
                    ).model_dump_json(exclude={"save", "deliver"})
                    logger.info("HITL-MARKER-2026-04-17b: about to yield REQUIRES_APPROVAL event=%s", _hitl_event[:200])
                    yield _hitl_event
                    logger.info("HITL-MARKER-2026-04-17b: REQUIRES_APPROVAL yielded")

                    # Persist + flip FSM. The frontend's /hitl/decide
                    # POST reads ``hitl_pending`` to know what to
                    # re-execute. Without this the "approve" button
                    # would only flip an in-memory flag and the paused
                    # tool would never run.
                    try:
                        await self._persist_hitl_pending(
                            qa_id=_qa_id,
                            envelope=_extra,
                        )
                    except Exception as _persist_exc:
                        logger.warning(
                            "ConversationRuntime[%s]: failed to persist hitl_pending — %s",
                            self._session_id,
                            _persist_exc,
                        )
                    self._flip_fsm_to_requires_approval()
                except Exception as _emit_exc:
                    logger.warning(
                        "ConversationRuntime[%s]: failed to emit REQUIRES_APPROVAL event — %s",
                        self._session_id,
                        _emit_exc,
                    )
            else:
                logger.exception("ConversationRuntime[%s]: agent stream error — %s", self._session_id, exc)
                stop_reason = "error"

        # ── Post-turn compaction check ────────────────────────────────────
        # After the agent finishes, check whether the accumulated context
        # exceeds the compaction threshold. If so, run compaction so the
        # *next* turn loads a compressed history from MongoDB.
        if self._compactor and stop_reason == "end_turn":
            try:
                from vendor_runtime_sdk.agent.context.token_budget import estimate_tokens
                est = estimate_tokens("") if not self._tokens_total else self._tokens_total
                # Use the authoritative input token count as a proxy for
                # context size — it reflects what was actually sent to the LLM.
                ctx_tokens = self._input_tokens_last or est
                if self._compactor.should_compact(ctx_tokens):
                    logger.info(
                        "ConversationRuntime[%s]: post-turn compaction triggered "
                        "(ctx_tokens=%d, threshold=%.0f%%)",
                        self._session_id,
                        ctx_tokens,
                        self._compactor._threshold * 100,
                    )
                    compacted = await self._compactor.compact_if_needed(ctx_tokens)
                    if compacted:
                        self._compaction_triggered += 1
                        if getattr(self._compactor, "_flush_before_compact", True):
                            self._mem_flush_count += 1
                        logger.info(
                            "ConversationRuntime[%s]: compaction completed (#%d)",
                            self._session_id,
                            self._compaction_triggered,
                        )
            except Exception as exc:
                logger.warning(
                    "ConversationRuntime[%s]: post-turn compaction failed — %s",
                    self._session_id,
                    exc,
                )

        # ── Post-turn lifecycle ───────────────────────────────────────────
        elapsed_ms = int((time.time() - start_ts) * 1000)
        self._activity.touch(f"agent stream ended ({stop_reason}, {elapsed_ms}ms)")

        if self._toggles.is_enabled("session_fsm") and not self._fsm.is_terminal:
            # Transition to a terminal state on every exit path so the dashboard
            # can observe turn completion. Mapping:
            #   end_turn           → terminated        (normal completion)
            #   cancelled          → terminated        (user interrupt / client disconnect)
            #   error              → failed→terminated (exception during stream)
            #   requires_approval  → requires_approval (HITL gate — paused, not terminal)
            #   environment_timeout→ terminated        (env wall-clock exceeded)
            #
            # Special case — passthrough HITL pause: when the agent emits a
            # ``REQUIRES_APPROVAL`` SSE event WITHOUT raising
            # ``HITLRequiredError`` (the CoderAgent milestone branch path —
            # see ``_maybe_handle_passthrough_requires_approval`` above), the
            # in-stream handler already flipped the FSM to REQUIRES_APPROVAL
            # but the local ``stop_reason`` still says ``end_turn`` because
            # the generator exited cleanly. Without this guard, the ``else``
            # branch below would then call ``mark_terminated()`` and
            # overwrite the HITL pause — so /hitl/decide would see FSM
            # state=terminated and refuse the operator's approval, leaving
            # the session permanently stuck. Honour the FSM state's signal
            # over the stream's local stop_reason here.
            if self._fsm.requires_approval:
                logger.debug(
                    "ConversationRuntime[%s]: stream ended with stop_reason=%s "
                    "but FSM is REQUIRES_APPROVAL (passthrough HITL); skipping "
                    "terminal transition so /hitl/decide can drive next step",
                    self._session_id, stop_reason,
                )
            else:
                try:
                    if stop_reason == "error":
                        self._record_fsm_transition("failed")
                        self._fsm.mark_failed()
                        self._record_fsm_transition("terminated")
                        self._fsm.mark_terminated()
                    elif stop_reason == "requires_approval":
                        self._record_fsm_transition("requires_approval")
                        self._fsm.mark_requires_approval()
                    else:
                        self._record_fsm_transition("terminated")
                        self._fsm.mark_terminated()
                except IllegalTransitionError as exc:
                    logger.debug("ConversationRuntime FSM final transition skipped: %s", exc)

        if self._toggles.is_enabled("plugin_hooks"):
            self._dispatcher.fire_session_end(self._session_id, self._workspace_id, stop_reason)

        # Record telemetry turn metrics (补全缺失指标)
        _activity_summary = self._activity.get_summary()
        try:
            from vendor_runtime_sdk.runtime.telemetry import TurnMetrics, get_recorder
            recorder = get_recorder()
            # Sprint 1 PR-G — surface backend identity to telemetry so
            # dashboards can partition by storage (``mongo`` vs ``sqlite``)
            # and alert on the ratio of ``None`` turns in environments where
            # storage injection is mandatory. ``None`` when storage was not
            # wired (pre-Sprint-0 baseline / passive injection failed).
            _storage_name = getattr(getattr(self, "_storage", None), "name", None)
            metrics = TurnMetrics(
                first_token_ms=elapsed_ms,
                tool_calls=_activity_summary.tool_call_count,
                tool_successes=sum(
                    1 for t in getattr(self, "_tool_calls_in_turn", []) if t.get("success")
                ),
                llm_calls=_activity_summary.api_call_count or 1,
                llm_successes=(_activity_summary.api_call_count or 1) if stop_reason == "end_turn" else 0,
                recovery_attempts=self._fallback_count,
                recovery_successes=self._fallback_count if stop_reason == "end_turn" else 0,
                compaction_savings_ratio=0.0,
                request_success=stop_reason not in ("error", "cancelled"),
                storage_backend_name=_storage_name,
            )
            recorder.record_turn(metrics)
        except Exception:
            pass  # telemetry is best-effort

        # ── [集成点 D] MemoryProvider post-turn hook ───────────────────
        if self._memory_provider and self._toggles.is_enabled("memory_provider"):
            try:
                if self._memory_provider.is_available():
                    await asyncio.to_thread(self._memory_provider.on_session_end, [])
            except Exception as _mp_exc:
                logger.debug("ConversationRuntime: memory_provider.on_session_end failed: %s", _mp_exc)

        # Checkpoint: save session state snapshot (§5.5)
        # Uses asyncio.to_thread to avoid blocking the event loop with sync I/O
        if self._checkpoint:
            try:
                _ckpt_state = {
                    "fsm_state": self._fsm.state.value if hasattr(self._fsm.state, "value") else str(self._fsm.state),
                    "iteration": self._current_iteration,
                    "tokens_total": self._tokens_total,
                    "fallback_count": self._fallback_count,
                    "stop_reason": stop_reason,
                }
                _ckpt_meta = {
                    "elapsed_ms": elapsed_ms,
                    "tool_calls": _activity_summary.tool_call_count,
                    "api_calls": _activity_summary.api_call_count,
                }
                await asyncio.to_thread(
                    self._checkpoint.save,
                    session_id=self._session_id,
                    state=_ckpt_state,
                    metadata=_ckpt_meta,
                )
                self._checkpoint_count = getattr(self, "_checkpoint_count", 0) + 1
                try:
                    from vendor_runtime_sdk.runtime.telemetry import SpanEvent, get_recorder
                    get_recorder().record_span_event(SpanEvent(
                        span_type="checkpoint_saved",
                        session_id=self._session_id,
                        metadata={"count": self._checkpoint_count},
                    ))
                except Exception:
                    pass
            except Exception as exc:
                logger.debug("ConversationRuntime: checkpoint save failed: %s", exc)

        # Trajectory: record turn for fine-tuning data collection (§10.3)
        # Record actual conversation messages for trajectory (fine-tuning data collection).
        # Uses asyncio.to_thread to avoid blocking the event loop with sync I/O.
        if self._trajectory:
            try:
                import uuid as _uuid
                _turn_id = _uuid.uuid4().hex[:8]
                _human_value = getattr(self._agent_ref, "query", "") or f"session={self._session_id}"
                _gpt_value = getattr(self, "_last_response_text", "") or ""
                _messages = [
                    {"from": "human", "value": _human_value},
                    *(
                        [{"from": "gpt", "value": _gpt_value}]
                        if _gpt_value else []
                    ),
                ]
                if stop_reason in ("end_turn",):
                    await asyncio.to_thread(
                        self._trajectory.record_turn,
                        session_id=self._session_id,
                        turn_id=_turn_id,
                        messages=_messages,
                        outcome="success",
                        metadata={"iterations": self._current_iteration, "elapsed_ms": elapsed_ms},
                    )
                    self._trajectory_success = getattr(self, "_trajectory_success", 0) + 1
                else:
                    await asyncio.to_thread(
                        self._trajectory.record_failure,
                        session_id=self._session_id,
                        turn_id=_turn_id,
                        messages=_messages,
                        error=stop_reason,
                        metadata={"iterations": self._current_iteration, "elapsed_ms": elapsed_ms},
                    )
                    self._trajectory_failed = getattr(self, "_trajectory_failed", 0) + 1
                try:
                    from vendor_runtime_sdk.runtime.telemetry import SpanEvent, get_recorder
                    get_recorder().record_span_event(SpanEvent(
                        span_type="trajectory_saved",
                        session_id=self._session_id,
                        metadata={
                            "outcome": "success" if stop_reason == "end_turn" else stop_reason,
                            "success_count": getattr(self, "_trajectory_success", 0),
                            "failed_count": getattr(self, "_trajectory_failed", 0),
                        },
                    ))
                except Exception:
                    pass
            except Exception as exc:
                logger.debug("ConversationRuntime: trajectory record failed: %s", exc)

        # ── [集成点 P] Activity Distillation (§6.3) ─────────────────────────
        # Condense L2 activity into L3 user preferences + L4 agent_instance
        # patterns. distill_turn() owns the toggle check; fail-soft here.
        try:
            _agent_ref = getattr(self, "_agent_ref", None)
            if _agent_ref is not None:
                from vendor_runtime_sdk.runtime.activity.distiller import TurnDigest, distill_turn

                activity = self._activity.get_summary()
                _tool_calls_log = list(getattr(self, "_tool_calls_in_turn", []))

                digest = TurnDigest(
                    session_id=self._session_id,
                    user_id=getattr(_agent_ref, "user_id", "") or "",
                    workspace_id=self._workspace_id,
                    query=getattr(_agent_ref, "query", "") or "",
                    timestamp=time.time(),
                    tool_calls=_tool_calls_log,  # empty list is fine; distiller handles it
                    api_call_count=activity.api_call_count,
                    final_status="success" if stop_reason == "end_turn" else stop_reason,
                )
                await distill_turn(
                    digest,
                    user_store=getattr(_agent_ref, "_memory_store", None),
                    agent_instance_store=getattr(_agent_ref, "_agent_instance_memory_store", None),
                )
        except Exception as exc:
            logger.warning("ConversationRuntime: activity distillation failed: %s", exc)

        # ── [集成点 N] Outcome Grader — optional post-turn quality evaluation ──
        # When ``grader_retry_loop`` is also enabled, a failed first evaluation
        # silently triggers a Generator-Verifier retry (P0, docs/多Agent优化
        # 实施方案-SDLC.md Sprint 1). The retry replays agent.run() with a
        # feedback prompt; user-visible SSE output is NOT re-streamed — the
        # retry outcome is captured in telemetry only so that dashboards can
        # observe FAIL→PASS turnaround without disturbing the live response.
        if self._toggles.is_enabled("outcome_grader") and stop_reason == "end_turn":
            try:
                from vendor_runtime_sdk.agent.evaluation.grader import Grader
                from vendor_runtime_sdk.agent.evaluation.outcome import (
                    EvaluationStatus,
                    Rubric,
                    RubricCriterion,
                )

                _rubric = getattr(self, "_rubric", None)
                if _rubric is None:
                    _rubric = Rubric(
                        task_description="Evaluate the agent response quality",
                        criteria=[
                            RubricCriterion(name="relevance", description="Response addresses the user's question", weight=2.0),
                            RubricCriterion(name="completeness", description="Response covers the key aspects", weight=1.5),
                            RubricCriterion(name="accuracy", description="No factual errors or hallucinations", weight=2.0),
                        ],
                        pass_threshold=60.0,
                    )

                # Use captured response text; fall back to metadata summary
                _agent_output = getattr(self, "_last_response_text", "") or (
                    f"session={self._session_id}, iterations={self._current_iteration}"
                )

                import os
                _eval_model = os.environ.get("EVAL_MODEL", "")
                _eval_base = os.environ.get("OPENAI_API_BASE", "")
                if _eval_model and _eval_base:
                    # Lazy-init shared eval client (reused across turns)
                    if not hasattr(self, "_eval_llm") or self._eval_llm is None:
                        from openai import AsyncOpenAI
                        from httpx import AsyncClient as _HC
                        # nosec B501 — internal KuCoin LLM proxy, self-signed cert
                        self._eval_llm = AsyncOpenAI(
                            api_key=os.environ.get("OPENAI_API_KEY", ""),
                            base_url=_eval_base,
                            timeout=30.0,
                            http_client=_HC(verify=False),
                        )
                    _grader = Grader(llm=self._eval_llm, model=_eval_model)

                    _retry_enabled = (
                        self._toggles.is_enabled("grader_retry_loop")
                        and getattr(self, "_agent_ref", None) is not None
                    )

                    if _retry_enabled:
                        _report = await self._run_generator_verifier_loop(
                            grader=_grader,
                            rubric=_rubric,
                            initial_output=_agent_output,
                        )
                    else:
                        _report = await _grader.evaluate(
                            session_id=self._session_id,
                            agent_id="runtime",
                            agent_output=_agent_output,
                            rubric=_rubric,
                        )

                    self._last_grader_score = _report.score
                    # Expose the final status for telemetry consumers / tests.
                    self._last_grader_status = _report.status
                    logger.info(
                        "ConversationRuntime[%s]: grader result — score=%.1f status=%s%s",
                        self._session_id, _report.score, _report.status.value,
                        " (retry-loop)" if _retry_enabled else "",
                    )
                    # Suppress unused-import warning for EvaluationStatus when
                    # retry path is disabled at runtime.
                    _ = EvaluationStatus
            except Exception as _gr_exc:
                logger.debug("ConversationRuntime: outcome_grader skipped: %s", _gr_exc)

        # ── Self-evolution nudge — trigger background skill review ────────
        if stop_reason == "end_turn":
            self._turns_since_nudge += 1
            if self._turns_since_nudge >= self._compute_nudge_interval():
                self._turns_since_nudge = 0
                self._nudge_count += 1
                try:
                    from vendor_runtime_sdk.runtime.telemetry import get_recorder
                    get_recorder().record_evolution_event("nudge")
                except Exception:
                    pass
                asyncio.ensure_future(self._background_skill_review())

        # §7.1 OTEL: close agent turn span — fail-soft, must not affect shutdown path
        if _otel_turn_ctx is not None:
            try:
                _otel_turn_ctx.__exit__(None, None, None)
            except Exception:
                pass

        # §3.1: persist the final snapshot to Redis so /runtime/snapshot
        # can serve it from any pod while the delayed-unregister window is
        # open. Kept inside the 3 s sleep so TTL-refresh stays ahead.
        try:
            await self._persist_snapshot_if_enabled()
        except Exception:
            pass

        # Keep registered briefly so the frontend can fetch the final snapshot,
        # then unregister to avoid stale "active session" counts.
        async def _delayed_unregister():
            try:
                await asyncio.sleep(3)
            except Exception:
                pass
            self._unregister()
        asyncio.ensure_future(_delayed_unregister())

        # Release the FallbackManager ContextVar bridge set at the top of
        # this method. Best-effort: if the generator was closed mid-stream
        # (GeneratorExit) we may not reach here, but the ContextVar lives
        # in the caller's task Context which is released on task end —
        # there is no cross-session leak path. Explicit reset keeps Context
        # tidy when wrap_agent_stream is reused on the same task.
        try:
            _reset_fb_ctx(_fb_ctx_token)
        except Exception:
            pass

        # Clear per-session driver state (bash_history / touched_paths)
        # the CoderAgent milestone driver accumulated across any
        # fallback-restart of this same turn. Mid-restart MUST keep it
        # (that's the whole point — the post-restart driver reads back
        # what the pre-restart driver wrote), but once the turn truly
        # terminates we drop it so the next chat turn under the same
        # session starts clean. Fail-soft: missing module, missing
        # key, anything — never block teardown.
        try:
            from vendor_runtime_sdk.agent.coder._turn_state import clear_session as _coder_clear
            _coder_clear(self._session_id)
        except Exception:
            pass

    # ── HITL Redesign helpers ─────────────────────────────────────────────
    async def _persist_hitl_pending(
        self,
        *,
        qa_id,
        envelope: dict,
    ) -> None:
        """Write the pending HITL gate.

        Two paths (chosen at call time, not init time — supports toggle
        flipping without process restart):

        1. **StorageBackend path** (Sprint 1 PR-E) — when
           ``hitl_storage_backend`` toggle is ON AND ``self._storage`` is
           wired (Sprint 0 PR-B passive injection), route through
           ``self._storage.hitl_gates.save_pending(...)``. The same write
           goes to Mongo (server) or SQLite (CLI / TUI) depending on
           backend. Fail-soft: if the Protocol call raises, fall back to
           the inline write so the gate still works.

        2. **Inline path** (legacy / fallback) — direct
           ``ai_assistant_db.kia_sessions.add_or_update_one`` write to
           Mongo. This is the pre-Sprint-0 behaviour and remains the
           default until PR-G flips the toggle ON across environments.

        ``envelope`` is the same dict that just went out on the SSE
        wire so the resume endpoint can recreate the call faithfully.
        Stores both the new ``arguments`` field and the legacy
        ``tool_args`` mirror for back-compat with rolling deploys.

        Chained-V2-HITL fix: when this runtime is itself driving a V2
        resumed agent (i.e. ``continue_after_hitl_approval`` is the
        current entry point), ``_ORIGINAL_SSE_QA_ID`` ContextVar is
        set to the qa_id the SSE consumer is listening on. Overriding
        the incoming ``qa_id`` with it ensures the NEXT
        ``/hitl/decide`` cycle drives ``continue_after_hitl_approval``
        with the right qa_id so its terminal status update lands on
        the cache key the SSE consumer reads. Without this override,
        the inner V2 qa is stored, the next continuation pushes to
        the wrong cache, and the chat bubble hangs at "处理中".
        """
        _qa_id_override = _ORIGINAL_SSE_QA_ID.get("")
        if _qa_id_override and _qa_id_override != qa_id:
            logger.debug(
                "ConversationRuntime[%s]: persist_hitl_pending qa_id override "
                "%s → %s (chained V2 HITL — pinning to original SSE qa_id)",
                self._session_id, qa_id, _qa_id_override,
            )
            qa_id = _qa_id_override

        # ── Path 1: StorageBackend Protocol (toggle-gated, opt-in) ────
        if self._should_use_storage_for_hitl():
            try:
                await self._storage.hitl_gates.save_pending(
                    session_id=self._session_id,
                    workspace_id=self._workspace_id or "",
                    qa_id=qa_id,
                    envelope=envelope,
                )
                return
            except Exception as _exc:  # noqa: BLE001 — fail-soft to inline
                logger.warning(
                    "ConversationRuntime[%s]: storage.hitl_gates.save_pending "
                    "failed (%s); falling back to inline Mongo write",
                    self._session_id, _exc,
                )
                # Fall through to inline write below.

        # ── Path 2: Inline Mongo write (legacy / fallback) ────────────
        # PR-E3 (SDK extraction §5 PR-E3): ai_assistant_db is now accessed
        # via the ContextStore Protocol.  The legacy
        # dao.mongo.dbs.ai_assistant_db is still used via the
        # _LegacyContextStoreProvider fallback so runtime behaviour is
        # unchanged in Phase 0.  Phase 2 removes the fallback when dao/
        # leaves the engine import surface.
        from vendor_runtime_sdk.agent.schema import get_timestamp
        from vendor_runtime_sdk.runtime.protocols.context_store import get_context_store

        _arguments = envelope.get("arguments") or envelope.get("tool_args") or {}
        await get_context_store().get_collection("kia_sessions").add_or_update_one(
            matcher={"id": self._session_id},
            data={
                "hitl_pending": {
                    "approval_id": envelope.get("approval_id") or "",
                    "tool_name": envelope.get("tool_name", ""),
                    "tool_call_id": envelope.get("tool_call_id"),
                    "arguments": _arguments,
                    # Legacy mirror — readers should prefer ``arguments``.
                    "tool_args": _arguments,
                    "rule_id": envelope.get("rule_id"),
                    "policy_message": envelope.get("policy_message", ""),
                    "risk_level": envelope.get("risk_level", "low"),
                    "editable_args": list(envelope.get("editable_args") or []),
                    "scope_options": list(
                        envelope.get("scope_options") or ["once", "session", "forever"]
                    ),
                    "qa_id": qa_id,
                    "saved_at": get_timestamp(),
                },
                "updateTime": get_timestamp(),
            },
        )

    def _should_use_storage_for_hitl(self) -> bool:
        """Decide whether to route ``_persist_hitl_pending`` through
        ``self._storage.hitl_gates`` vs the inline Mongo path.

        Two preconditions, both required (AND):
        * ``self._storage`` is wired (Sprint 0 PR-B passive injection;
          PR-B is on the request path but the toggle defaults OFF, so
          ``_storage`` is set yet the new path is dormant).
        * ``hitl_storage_backend`` toggle is ON. Re-read on every call
          so operators can flip mid-process without restarting.

        Failure to import the toggle module (highly unlikely) → False
        (legacy path). Toggle resolution exceptions → False (legacy
        path). Never crashes the gate.
        """
        if getattr(self, "_storage", None) is None:
            return False
        # ``self._storage.hitl_gates`` must exist; backends without it
        # (in tests, partial mocks) skip the new path.
        if not hasattr(self._storage, "hitl_gates"):
            return False
        # Sprint 2 PR-O2: CLI / TUI contexts force the storage path
        # even when the toggle is OFF — because the fallback (inline
        # Mongo write) would crash in CLI (no Mongo connection). The
        # ``for_local_context`` factory sets ``_prefer_storage_for_hitl``
        # at construction. Web contexts continue to respect the toggle
        # for the gradual rollout.
        if getattr(self, "_prefer_storage_for_hitl", False):
            return True
        try:
            from vendor_runtime_sdk.runtime.config.guards import is_module_enabled
            return bool(is_module_enabled("hitl_storage_backend"))
        except Exception:  # noqa: BLE001 — fail-closed to legacy
            return False

    def _flip_fsm_to_requires_approval(self) -> None:
        """Move the in-memory FSM into REQUIRES_APPROVAL.

        Idempotent: if the runtime has already transitioned (e.g. a
        race between the exception path and the SSE-passthrough path)
        the no-op is silently absorbed via ``can_transition``.
        """
        try:
            fsm = getattr(self, "_fsm", None)
            if fsm is None:
                return
            if fsm.can_transition(SessionState.REQUIRES_APPROVAL):
                fsm.transition(SessionState.REQUIRES_APPROVAL)
        except IllegalTransitionError:
            # Already in / past requires_approval — fine.
            pass
        except Exception as _exc:
            logger.warning(
                "ConversationRuntime[%s]: FSM flip to REQUIRES_APPROVAL failed — %s",
                getattr(self, "_session_id", "?"), _exc,
            )

    async def _maybe_handle_passthrough_requires_approval(
        self,
        parsed: dict | None,
    ) -> None:
        """Detect a passthrough ``REQUIRES_APPROVAL`` SSE event (i.e.
        produced by the Coder milestone branch directly, not via the
        ``HITLRequiredError`` exception path) and persist + flip FSM.

        Idempotent on ``approval_id`` so a duplicate event from the
        agent layer doesn't overwrite the persisted record.
        """
        if not parsed:
            return
        if str(parsed.get("status", "")).upper() != "REQUIRES_APPROVAL":
            return
        extra = parsed.get("extraInfo") or parsed.get("extra_info") or {}
        if not isinstance(extra, dict):
            return
        # Tolerate both modern and legacy shapes.
        envelope = {
            "approval_id": extra.get("approval_id") or "",
            "tool_name": extra.get("tool_name") or "",
            "tool_call_id": extra.get("tool_call_id"),
            "arguments": extra.get("arguments") or extra.get("tool_args") or {},
            "tool_args": extra.get("arguments") or extra.get("tool_args") or {},
            "rule_id": extra.get("rule_id"),
            "policy_message": extra.get("policy_message") or extra.get("reason") or "",
            "risk_level": extra.get("risk_level") or "low",
            "editable_args": list(extra.get("editable_args") or []),
            "scope_options": list(
                extra.get("scope_options") or ["once", "session", "forever"]
            ),
        }
        # CoderAgent emits two REQUIRES_APPROVAL envelopes: (1) SYSTEM from
        # AgentLoop with full extraInfo (tool_name, arguments, …); (2) a
        # terminal TOOL_EXECUTION summary with status REQUIRES_APPROVAL but
        # no extraInfo.  Persisting (2) would overwrite Mongo hitl_pending
        # with an empty tool_name and break POST /hitl/decide resume.
        if not str(envelope.get("tool_name") or "").strip():
            return
        try:
            await self._persist_hitl_pending(
                qa_id=parsed.get("qaId") or parsed.get("qa_id") or "",
                envelope=envelope,
            )
        except Exception as _exc:
            logger.warning(
                "ConversationRuntime[%s]: passthrough hitl_pending persist failed — %s",
                getattr(self, "_session_id", "?"), _exc,
            )
        self._flip_fsm_to_requires_approval()


logger = logging.getLogger(__name__)
