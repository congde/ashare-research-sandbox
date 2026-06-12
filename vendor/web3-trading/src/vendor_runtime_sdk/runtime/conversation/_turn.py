# -*- coding: utf-8 -*-
"""
TurnMixin — run_turn, preflight, preflight_compress, _run_loop, hook context

Auto-extracted from runtime/conversation.py during refactoring.
Part of the ConversationRuntime mixin chain.
"""

from __future__ import annotations

import time
import asyncio
import logging

from vendor_runtime_sdk.runtime.conversation._helpers import TurnResult, _done_dict, _error_dict
from vendor_runtime_sdk.runtime.tools.dedup import deduplicate_tool_calls
from vendor_runtime_sdk.runtime.tools.repair import repair_tool_calls
from vendor_runtime_sdk.runtime.hooks.base import HookContext, HookDispatcher
from vendor_runtime_sdk.runtime.budget.warning import strip_budget_warnings
from typing import AsyncGenerator, List, Optional
from vendor_runtime_sdk.runtime.budget.pressure import BudgetPressure, inject_into_last_tool_result
from vendor_runtime_sdk.runtime.session.fsm import IllegalTransitionError, SessionFSM, SessionState

class TurnMixin:
    """TurnMixin — run_turn, preflight, preflight_compress, _run_loop, hook context"""

    async def run_turn(
        self,
        messages: list[dict],
        system_prompt: Optional[str] = None,
    ) -> AsyncGenerator[dict, None]:
        """
        Execute one conversation turn as an async generator of SSE-compatible dicts.

        Pre-turn steps (always run, regardless of toggles):
          1. restore_primary  — undo any fallback from previous turn
          2. strip_warnings   — remove stale budget markers from history
          3. reset_pressure   — reset budget pressure level tracker

        Then delegates to _run_loop() which fires the actual ReAct iterations.

        Yields
        ------
        dict
            SSE-compatible dicts; consumers convert via web/sse.SseEvent.
        """
        start_ts = time.time()

        # ── Pre-turn reliability hooks ─────────────────────────────────────────
        self._preflight(messages)

        # ── Preflight compression (§5.1) ───────────────────────────────────────
        # Run async compaction check after the sync preflight. Uses Compactor if
        # injected; no-ops if compaction is disabled or compactor is None.
        if self._compactor and self._toggles.is_enabled("compaction"):
            await self._preflight_compress(messages, system_prompt=system_prompt)

        # ── Drain pending compression SSE event ────────────────────────────────
        if self._pending_compaction_event is not None:
            yield self._pending_compaction_event
            self._pending_compaction_event = None

        # ── Transition FSM to running ──────────────────────────────────────────
        if self._toggles.is_enabled("session_fsm"):
            try:
                self._fsm.mark_running()
            except IllegalTransitionError as e:
                logger.error("ConversationRuntime FSM: %s", e)
                yield _error_dict(str(e), session_id=self._session_id)
                return

        # ── Fire session-start hooks ───────────────────────────────────────────
        if self._toggles.is_enabled("plugin_hooks"):
            self._dispatcher.fire_session_start(self._session_id, self._workspace_id)

        # ── Run the ReAct loop ─────────────────────────────────────────────────
        turn_result: Optional[TurnResult] = None
        try:
            async for event_dict in self._run_loop(messages, system_prompt):
                yield event_dict
                if event_dict.get("event_type") == "done":
                    stop_reason = event_dict.get("stop_reason", "end_turn")
                    turn_result = TurnResult(
                        text=event_dict.get("data", {}).get("summary", ""),
                        stop_reason=stop_reason,
                        elapsed_ms=int((time.time() - start_ts) * 1000),
                        is_fallback=self._fallback.is_fallback_active if self._fallback else False,
                        fallback_attempt=self._fallback.fallback_attempt if self._fallback else 0,
                    )
        except asyncio.CancelledError:
            logger.info("ConversationRuntime[%s]: turn cancelled", self._session_id)
            self._fsm.mark_terminated()
            yield _done_dict("cancelled", session_id=self._session_id)
            return
        except Exception as exc:
            logger.exception("ConversationRuntime[%s]: unhandled error in turn", self._session_id)
            self._fsm.mark_terminated()
            yield _error_dict(str(exc), session_id=self._session_id)
            yield _done_dict("error", session_id=self._session_id)
            return

        # ── Post-turn FSM transition ───────────────────────────────────────────
        if self._toggles.is_enabled("session_fsm") and not self._fsm.is_terminal:
            stop = turn_result.stop_reason if turn_result else "end_turn"
            if stop in ("cancelled", "error", "expired", "perm_error"):
                self._fsm.mark_terminated()
            elif stop == "requires_approval":
                self._fsm.mark_requires_approval()
            # For "end_turn" / "budget_exceeded" / "context_overflow" the FSM
            # stays RUNNING until the next turn or explicit close

        # ── Fire session-end hooks ─────────────────────────────────────────────
        if self._toggles.is_enabled("plugin_hooks"):
            stop_reason = turn_result.stop_reason if turn_result else "error"
            self._dispatcher.fire_session_end(self._session_id, self._workspace_id, stop_reason)

    # ── Pre-turn ────────────────────────────────────────────────────────────────

    def _preflight(self, messages: list[dict]) -> None:
        """Run all pre-turn reliability steps (§5.1 run_turn preamble)."""

        # 1. Restore primary model (undo last-turn fallback)
        if self._fallback and self._toggles.is_enabled("fallback_restore"):
            self._fallback.restore_primary()
            # Also revert the loop's LLM client to primary
            if self._primary_llm_snapshot:
                self._loop.llm, self._loop.model_name = self._primary_llm_snapshot

        # 2. Strip stale budget warnings from previous turns
        if self._toggles.is_enabled("budget_stripping"):
            n = strip_budget_warnings(messages)
            if n:
                logger.debug("ConversationRuntime: stripped budget warnings from %d message(s)", n)

        # 3. Reset per-turn budget pressure tracker
        self._budget_pressure.reset()
        # Also clear any pending budget-warning append on the agent — it is
        # a per-turn signal, never carried across turns.
        try:
            if self._agent_ref is not None and hasattr(self._agent_ref, "_runtime_injected_append_prompt"):
                setattr(self._agent_ref, "_runtime_injected_append_prompt", "")
        except Exception:
            pass

        # 4. Reset interrupt flag for this turn
        self._interrupt_requested = False
        self._interrupt_reason = ""

        # 5. Reset per-turn token quota counter
        if self._token_quota:
            self._token_quota.reset_turn(self._session_id)

        self._activity.touch("turn started")

    async def _preflight_compress(
        self,
        messages: list[dict],
        system_prompt: Optional[str] = None,
    ) -> None:
        """
        Async preflight compression (§5.6).

        Estimates tokens for the full request payload (messages + system_prompt +
        tool schemas) and runs up to 3 compaction passes until the estimate drops
        below the compactor's threshold or compaction can make no further progress.

        Matches the spec loop::

            for _pass in range(3):
                est = estimate(messages + system_prompt + tools)
                if est < threshold: break
                original_len = len(messages)
                compact(messages)
                if len(messages) >= original_len: break  # no progress

        No-ops gracefully on any exception so it never blocks a turn.
        """
        try:
            from vendor_runtime_sdk.runtime.context_probe import _estimate_messages_tokens

            # Token count for the system prompt (not in the messages list)
            extra_tokens = 0
            if system_prompt:
                extra_tokens += _estimate_messages_tokens(
                    [{"role": "system", "content": system_prompt}]
                )

            # Token count for tool schemas exposed by this loop's registry
            registry = getattr(self._loop, "tool_registry", None)
            if registry:
                try:
                    # ToolRegistry exposes schema dicts via .get_tool_schemas()
                    # or similar; fall back gracefully if not available.
                    schemas = []
                    if hasattr(registry, "get_tool_schemas"):
                        schemas = registry.get_tool_schemas()
                    elif hasattr(registry, "_tools"):
                        for tool in registry._tools.values():
                            if hasattr(tool, "schema"):
                                schemas.append(tool.schema())
                    for schema in schemas:
                        extra_tokens += _estimate_messages_tokens(
                            [{"role": "system", "content": str(schema)}]
                        )
                except Exception:
                    pass  # tool schema estimation is best-effort

            any_compacted = False
            passes_ran = 0
            tokens_before = _estimate_messages_tokens(messages) + extra_tokens
            _pre_compress_fired = False
            for _pass in range(3):  # §5.6: 最多压缩 3 轮
                current_tokens = _estimate_messages_tokens(messages) + extra_tokens
                if not self._compactor.should_compact(current_tokens):
                    break

                # P2-3: fire memory-provider pre-compress hook once, before
                # the first real compaction pass. Any exception is swallowed
                # so memory-flush failures never block compaction itself.
                if (
                    not _pre_compress_fired
                    and self._memory_provider is not None
                    and self._toggles.is_enabled("memory_provider")
                ):
                    _pre_compress_fired = True
                    try:
                        if self._memory_provider.is_available():
                            await asyncio.to_thread(
                                self._memory_provider.on_pre_compress,
                                list(messages),
                            )
                            self._mem_flush_count += 1
                    except Exception as _mp_exc:
                        logger.warning(
                            "ConversationRuntime[%s]: memory_provider.on_pre_compress failed: %s",
                            self._session_id, _mp_exc,
                        )

                prev_msg_count = len(messages)
                compacted = await self._compactor.compact_if_needed(current_tokens)
                if not compacted:
                    break  # threshold not exceeded (race — another path already compacted)

                any_compacted = True
                passes_ran += 1
                logger.info(
                    "ConversationRuntime[%s]: preflight compaction pass %d "
                    "(est. %d tokens, pass %d/3)",
                    self._session_id,
                    _pass + 1,
                    current_tokens,
                    _pass + 1,
                )

                # If message count hasn't shrunk there's no point in more passes
                # (MongoDB transcript was compacted, but in-memory list is unchanged —
                # next turn will load the shortened history from DB)
                if len(messages) >= prev_msg_count:
                    break

            if any_compacted:
                self._compaction_triggered += 1
                tokens_after = _estimate_messages_tokens(messages) + extra_tokens
                self._pending_compaction_event = self._build_compaction_event(
                    passes=passes_ran,
                    tokens_before=tokens_before,
                    tokens_after=tokens_after,
                )
                if self._toggles.is_enabled("session_fsm") and not self._fsm.is_terminal:
                    self._fsm.mark_compacted()

        except Exception as exc:
            logger.warning(
                "ConversationRuntime[%s]: preflight compaction failed — %s",
                self._session_id,
                exc,
            )

    # ── ReAct loop ──────────────────────────────────────────────────────────────

    # Maximum times to retry a single turn after a stale stream is detected.
    _MAX_STALE_RETRIES: int = 2

    async def _run_loop(
        self,
        messages: list[dict],
        system_prompt: Optional[str],
    ) -> AsyncGenerator[dict, None]:
        """
        Drive the AgentLoop with all reliability guardrails applied.

        Reliability features active in this method:
          §5.2  Stale-stream detection — per-event ``asyncio.wait_for`` with
                automatic retry up to ``_MAX_STALE_RETRIES`` times.
          §5.3  Proactive context-length probe before the first LLM call.
          §5.12 Reactive context-length error handling — parse limit from API
                error, update cache, trigger compaction, yield context_overflow.

        Yielded dicts are in the SSE event shape expected by web/sse.
        """
        from vendor_runtime_sdk.agent.tools.loop import LoopEventType
        from vendor_runtime_sdk.runtime.context_probe import (
            get_next_probe_tier,
            is_context_length_error,
            parse_context_limit_from_error,
            probe_context,
            save_confirmed_limit,
        )

        model_name: str = getattr(self._loop, "model_name", "")
        base_url: str = getattr(self._loop, "base_url", "")
        registry = getattr(self._loop, "tool_registry", None)
        known_tool_names = list(registry._tools.keys()) if registry is not None else []

        # ── §5.3 Proactive context length probe ─────────────────────────────────
        if self._toggles.is_enabled("context_probe"):
            probe = probe_context(messages, model_name=model_name)
            if probe.over_limit:
                logger.warning(
                    "ConversationRuntime[%s]: proactive context overflow — "
                    "%d tokens (safe limit %d, model=%s). Triggering compaction.",
                    self._session_id,
                    probe.estimated_tokens,
                    probe.safe_limit,
                    model_name or "unknown",
                )
                if self._compactor:
                    try:
                        await self._preflight_compress(messages, system_prompt)
                    except Exception:
                        pass
                yield _done_dict("context_overflow", session_id=self._session_id)
                return

        iteration = 0
        stale_retries = 0

        # ── Outer retry loop: stale-stream (§5.2) + context-overflow (§5.12) ────
        # Normal turns execute the inner while exactly once.  Stale-stream and
        # context-length errors break out of the inner loop and may continue here.
        while True:
            stale_hit = False
            context_length_hit = False

            stream = self._loop.run(messages, system_prompt)

            try:
                # ── Inner event loop ───────────────────────────────────────────
                while True:
                    # §5.2: per-event timeout — detects a hung LLM stream
                    try:
                        loop_event = await asyncio.wait_for(
                            stream.__anext__(),
                            timeout=self._stale_timeout,
                        )
                    except StopAsyncIteration:
                        break
                    except asyncio.TimeoutError:
                        stale_hit = True
                        logger.warning(
                            "ConversationRuntime[%s]: stale stream after %.0fs "
                            "(attempt %d/%d) — reconnecting",
                            self._session_id,
                            self._stale_timeout,
                            stale_retries + 1,
                            self._MAX_STALE_RETRIES,
                        )
                        yield {
                            "event_type": "status",
                            "data": {"message": "Stream stale — reconnecting…"},
                            "session_id": self._session_id,
                        }
                        break  # exit inner loop; outer loop decides whether to retry

                    # ── Interrupt check ────────────────────────────────────────
                    if self._interrupt_requested:
                        logger.info(
                            "ConversationRuntime[%s]: interrupt at iteration %d — %s",
                            self._session_id,
                            iteration,
                            self._interrupt_reason,
                        )
                        yield _done_dict("cancelled", session_id=self._session_id)
                        return

                    event_type = loop_event.type

                    # ── Tool call: dedup + repair + hooks ──────────────────────
                    if event_type == LoopEventType.TOOL_CALL:
                        iteration += 1
                        calls = loop_event.tool_calls

                        if self._toggles.is_enabled("tool_repair") and known_tool_names:
                            call_dicts = [{"name": c.name, "arguments": c.arguments} for c in calls]
                            repaired, n_repairs = repair_tool_calls(call_dicts, known_tool_names)
                            if n_repairs:
                                for i, repaired_dict in enumerate(repaired):
                                    calls[i].name = repaired_dict.get("name", calls[i].name)

                        if self._toggles.is_enabled("tool_dedup"):
                            before = len(calls)
                            calls = deduplicate_tool_calls(calls)
                            if len(calls) < before:
                                loop_event.tool_calls = calls

                        self._activity.touch(f"tool calls: {[c.name for c in calls]}")

                        if self._toggles.is_enabled("plugin_hooks"):
                            ctx = self._make_hook_context(iteration)
                            extra_ctx = self._dispatcher.fire_pre_llm_call(ctx)
                            if extra_ctx and messages:
                                last_user = next(
                                    (i for i in range(len(messages) - 1, -1, -1) if messages[i].get("role") == "user"),
                                    None,
                                )
                                if last_user is not None:
                                    messages[last_user] = dict(
                                        messages[last_user],
                                        content=messages[last_user].get("content", "") + "\n\n" + extra_ctx,
                                    )

                        yield {
                            "event_type": "tool_use",
                            "data": {
                                "tools": [{"name": c.name, "args": c.arguments} for c in calls],
                                "iteration": iteration,
                            },
                            "session_id": self._session_id,
                        }

                    # ── Tool result: budget pressure injection ─────────────────
                    elif event_type == LoopEventType.TOOL_RESULT:
                        if self._toggles.is_enabled("budget_pressure"):
                            warning = self._budget_pressure.get_pressure(iteration)
                            if warning:
                                inject_into_last_tool_result(messages, warning)

                        results = loop_event.tool_results
                        self._activity.touch(f"tool results received ({len(results)} tools)")

                        yield {
                            "event_type": "tool_result",
                            "data": {
                                "results": [
                                    {"name": r.name, "success": r.result.success, "elapsed_ms": r.elapsed_ms}
                                    for r in results
                                ],
                                "iteration": iteration,
                            },
                            "session_id": self._session_id,
                        }

                    # ── Final response ─────────────────────────────────────────
                    elif event_type == LoopEventType.FINAL_RESPONSE:
                        text = loop_event.content or ""
                        self._activity.touch("final response generated")

                        if self._toggles.is_enabled("plugin_hooks"):
                            ctx = self._make_hook_context(iteration)
                            self._dispatcher.fire_post_llm_call(ctx, text)

                        yield {
                            "event_type": "text_delta",
                            "data": {"text": text},
                            "session_id": self._session_id,
                        }
                        yield _done_dict("end_turn", session_id=self._session_id, summary=text[:200])
                        return

                    # ── HITL gate: PolicyEngine ask action ────────────────────
                    elif event_type == LoopEventType.REQUIRES_APPROVAL:
                        tool_name = loop_event.metadata.get("tool_name", "unknown")
                        reason = loop_event.metadata.get("reason", "Human approval required")
                        rule_id = loop_event.metadata.get("rule_id")
                        logger.info(
                            "ConversationRuntime[%s]: HITL gate — tool=%s rule=%s",
                            self._session_id, tool_name, rule_id,
                        )
                        self._activity.touch(f"hitl gate: {tool_name}")
                        yield {
                            "event_type": "status",
                            "data": {
                                "message": f"Tool '{tool_name}' requires human approval",
                                "tool_name": tool_name,
                                "reason": reason,
                                "rule_id": rule_id,
                                "session_id": self._session_id,
                            },
                            "session_id": self._session_id,
                        }
                        yield _done_dict("requires_approval", session_id=self._session_id)
                        return

                    # ── Max iterations reached ─────────────────────────────────
                    elif event_type == LoopEventType.MAX_ITERATIONS:
                        logger.warning(
                            "ConversationRuntime[%s]: max_iterations=%d reached",
                            self._session_id,
                            self._max_iterations,
                        )
                        last_text = ""
                        for msg in reversed(messages):
                            if msg.get("role") == "assistant" and msg.get("content"):
                                last_text = msg["content"]
                                break
                        if last_text:
                            yield {
                                "event_type": "text_delta",
                                "data": {"text": last_text},
                                "session_id": self._session_id,
                            }
                        yield _done_dict("budget_exceeded", session_id=self._session_id)
                        return

                    # ── Error ──────────────────────────────────────────────────
                    elif event_type == LoopEventType.ERROR:
                        error_msg = loop_event.error or "unknown error"
                        logger.error(
                            "ConversationRuntime[%s]: loop error at iteration %d — %s",
                            self._session_id,
                            iteration,
                            error_msg,
                        )
                        self._activity.touch(f"error: {error_msg[:80]}")

                        # §5.12 Reactive context-length error detection ─────────
                        if self._toggles.is_enabled("context_probe") and is_context_length_error(error_msg):
                            parsed = parse_context_limit_from_error(error_msg)
                            if parsed:
                                save_confirmed_limit(model_name, base_url, parsed)
                                effective_limit = parsed
                            else:
                                # Cannot parse exact limit — step down one tier
                                from vendor_runtime_sdk.runtime.context_probe import _lookup_context_window
                                effective_limit = get_next_probe_tier(
                                    _lookup_context_window(model_name)
                                )
                            logger.warning(
                                "ConversationRuntime[%s]: context length error — "
                                "detected limit=%d. Triggering compaction.",
                                self._session_id,
                                effective_limit,
                            )
                            if self._compactor:
                                try:
                                    await self._preflight_compress(messages, system_prompt)
                                except Exception:
                                    pass
                            yield {
                                "event_type": "status",
                                "data": {
                                    "message": f"Context limit reached ({effective_limit:,} tokens) — compacting…"
                                },
                                "session_id": self._session_id,
                            }
                            # Yield context_overflow so caller knows to reload history
                            yield _done_dict("context_overflow", session_id=self._session_id)
                            return

                        # Regular error — attempt model fallback ───────────────
                        if self._fallback and self._toggles.is_enabled("fallback_restore"):
                            if self._fallback.try_fallback():
                                # Apply fallback model to the loop's LLM client
                                _fb_cur = self._fallback.current
                                try:
                                    from vendor_runtime_sdk.llm.base import create_llm as _create_llm
                                    _fb_llm, _fb_model = _create_llm(
                                        api_key=_fb_cur.api_key,
                                        base_url=_fb_cur.base_url,
                                        model_name=_fb_cur.model,
                                    )
                                    self._loop.llm = _fb_llm
                                    self._loop.model_name = _fb_model
                                except Exception as _fb_exc:
                                    logger.error("Failed to create fallback LLM client: %s", _fb_exc)
                                    yield _error_dict(
                                        f"Fallback model init failed: {_fb_exc}",
                                        session_id=self._session_id,
                                    )
                                    yield _done_dict("error", session_id=self._session_id)
                                    return
                                logger.info(
                                    "ConversationRuntime[%s]: switched to fallback '%s' (base_url=%s)",
                                    self._session_id,
                                    self._fallback.current.model,
                                    _fb_cur.base_url,
                                )
                                yield {
                                    "event_type": "status",
                                    "data": {"message": f"Retrying with fallback model {_fb_cur.model}…"},
                                    "session_id": self._session_id,
                                }
                                context_length_hit = True  # reuse outer loop for retry
                                break
                            else:
                                yield _error_dict(error_msg, session_id=self._session_id)
                                yield _done_dict("error", session_id=self._session_id)
                                return
                        else:
                            yield _error_dict(error_msg, session_id=self._session_id)
                            yield _done_dict("error", session_id=self._session_id)
                            return

                    # ── ITERATION_START: activity ping ─────────────────────────
                    elif event_type == LoopEventType.ITERATION_START:
                        self._activity.record_api_call()
                        self._activity.touch(f"iteration {loop_event.iteration} started")

            finally:
                # Always close the async generator to release HTTP connections.
                try:
                    await stream.aclose()
                except Exception:
                    pass

            # ── Retry decision ─────────────────────────────────────────────────
            if stale_hit and stale_retries < self._MAX_STALE_RETRIES:
                stale_retries += 1
                self._activity.touch(f"stale stream retry {stale_retries}/{self._MAX_STALE_RETRIES}")
                continue  # re-enter with fresh stream; same messages

            if context_length_hit:
                # Fallback model switch: re-enter loop once with the new model active.
                # Reset context_length_hit so we don't loop forever.
                context_length_hit = False
                continue

            # Natural loop end (StopAsyncIteration with no retry needed)
            break

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _make_hook_context(self, iteration: int) -> HookContext:
        model = ""
        is_fallback = False
        if self._fallback:
            model = self._fallback.current.model
            is_fallback = self._fallback.is_fallback_active
        # Extract agent metadata for cost attribution (P4)
        agent_type = ""
        parent_agent_id = None
        if self._agent_ref:
            _name = getattr(self._agent_ref, "NAME", None)
            agent_type = _name.value if hasattr(_name, "value") else str(_name or "")
            parent_agent_id = getattr(self._agent_ref, "parent_agent_id", None)

        metadata: dict = {
            "agent_type": agent_type,
            "parent_agent_id": parent_agent_id,
            "turn_number": getattr(self, "_current_iteration", iteration),
            "agent_id": getattr(self._agent_ref, "agent_id", None) if self._agent_ref else None,
            "user_id": getattr(self._agent_ref, "user_id", None) if self._agent_ref else None,
            "request_id": getattr(self._agent_ref, "request_id", None) if self._agent_ref else None,
            # CostTrackingHook needs these fields (§14.8)
            "requested_model": getattr(self._fallback, "_requested_model", model) if self._fallback else model,
            "fallback_attempt": getattr(self._fallback, "fallback_attempt", 0) if self._fallback else 0,
        }

        # Include last known usage for cost tracking
        if hasattr(self, "_last_usage_raw"):
            metadata["usage"] = self._last_usage_raw

        # Gap 5 — propagate cost attribution into metadata.  Explicit-None keys
        # for avatar/issue are intentionally omitted so CostTrackingHook's
        # ``meta.get("avatar_id")`` returns None (not inserted as literal None
        # into cost_records). Runtime-injected agent_id/user_id override
        # agent_ref-derived values when set on the runtime (V1 onboarding path).
        if self._avatar_id is not None:
            metadata["avatar_id"] = self._avatar_id
        if self._issue_id is not None:
            metadata["issue_id"] = self._issue_id
        if self._agent_id is not None:
            metadata["agent_id"] = self._agent_id
        if self._user_id is not None:
            metadata["user_id"] = self._user_id

        return HookContext(
            session_id=self._session_id,
            workspace_id=self._workspace_id,
            iteration=iteration,
            model=model,
            is_fallback=is_fallback,
            metadata=metadata,
        )

    # ── Legacy stream wrapper (C1 review fix) ──────────────────────────────────


logger = logging.getLogger(__name__)
