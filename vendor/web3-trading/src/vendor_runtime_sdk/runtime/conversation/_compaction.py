# -*- coding: utf-8 -*-
"""
CompactionMixin — compaction events, memory flush

Auto-extracted from runtime/conversation.py during refactoring.
Part of the ConversationRuntime mixin chain.
"""

from __future__ import annotations

import asyncio
import logging

class CompactionMixin:
    """CompactionMixin — compaction events, memory flush"""

    def _build_compaction_event(
        self,
        *,
        passes: int,
        tokens_before: int,
        tokens_after: int,
    ) -> str:
        """Produce a StreamResponse JSON string that wraps a session.compression payload.

        The SSE push pipeline (chat.py push() → output_schema()) only accepts
        StreamResponse JSON. Pack the compaction metrics into extraInfo so the
        client can render "整理对话记忆…" without needing a new schema.
        """
        import json as _json
        from vendor_runtime_sdk.agent.schema import StepType, StreamResponse, StreamStatusType

        tokens_saved = max(0, int(tokens_before) - int(tokens_after))
        qa_id = getattr(getattr(self, "_agent_ref", None), "qa_id", None) or ""
        payload = StreamResponse(
            sessionId=self._session_id,
            qaId=qa_id or None,
            type=StepType.SYSTEM,
            status=StreamStatusType.PENDING,
            content=None,
            extraInfo={
                "event_type": "session.compression",
                "passes": int(passes),
                "tokens_before": int(tokens_before),
                "tokens_after": int(tokens_after),
                "tokens_saved": tokens_saved,
            },
            save=False,
        )
        # output_schema() handles both StreamResponse instances and JSON strings;
        # emitting a string avoids re-encoding / offset collisions downstream.
        return payload.model_dump_json(exclude={"save", "deliver", "checkSensitive"})

    def _handle_compactor_success(
        self,
        passes: int,
        tokens_before: int,
        tokens_after: int,
    ) -> None:
        """Observer callback fired by Compactor after an in-loop compact() success.

        The agent's ContextAssembler.compact_if_needed() runs inside agent.run(),
        after our preflight check has already returned. We cannot yield from a
        sync callback, so we stash the SSE payload and let the main loop drain
        it on the next yield.
        """
        try:
            self._compaction_triggered += 1
            self._pending_compaction_event = self._build_compaction_event(
                passes=int(passes or 1),
                tokens_before=int(tokens_before or 0),
                tokens_after=int(tokens_after or 0),
            )
            logger.info(
                "ConversationRuntime[%s]: compactor callback fired — "
                "pending session.compression event queued (passes=%d, before=%d, after=%d)",
                self._session_id, int(passes or 1),
                int(tokens_before or 0), int(tokens_after or 0),
            )
            if self._toggles.is_enabled("session_fsm") and not self._fsm.is_terminal:
                try:
                    self._fsm.mark_compacted()
                except Exception:
                    pass
        except Exception as exc:
            logger.debug(
                "ConversationRuntime[%s]: _handle_compactor_success failed: %s",
                self._session_id, exc,
            )

    def _handle_memory_flush(self, flush_content: str) -> None:
        """Mirror Compactor's memory-flush content into the agent-scope MemoryStore.

        The Compactor writes flush content to transcript + SESSION.md. For T5-2,
        we additionally persist it to the agent's session-scope MemoryStore so
        follow-up turns can recall the flushed state via `memory_search` /
        `memory_read`. Fail-soft: logs only; never raises back into compact().
        """
        if not flush_content:
            return
        agent = getattr(self, "_agent_ref", None)
        if agent is None:
            logger.debug(
                "ConversationRuntime[%s]: memory flush skipped — no agent_ref",
                self._session_id,
            )
            return
        # Prefer session-scope (most relevant); fall back to agent_instance/user/workspace.
        store = (
            getattr(agent, "_session_memory_store", None)
            or getattr(agent, "_agent_instance_memory_store", None)
            or getattr(agent, "_memory_store", None)
            or getattr(agent, "_workspace_memory_store", None)
        )
        if store is None:
            logger.debug(
                "ConversationRuntime[%s]: memory flush skipped — no memory store on agent",
                self._session_id,
            )
            return
        try:
            target = "MEMORY_FLUSH.md"
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                logger.debug(
                    "ConversationRuntime[%s]: memory flush skipped — no running loop",
                    self._session_id,
                )
                return
            loop.create_task(self._write_memory_flush(store, target, flush_content))
            self._mem_flush_count += 1
            logger.info(
                "ConversationRuntime[%s]: memory flush mirrored to store=%s target=%s (%d chars)",
                self._session_id,
                getattr(store, "scope", "?"),
                target,
                len(flush_content),
            )
            # Also notify MemoryProvider (keeps Mem0 / custom adapters in sync).
            if self._memory_provider is not None:
                try:
                    self._memory_provider.on_memory_write(
                        "create", target, flush_content
                    )
                except Exception as _mp_exc:
                    logger.debug(
                        "ConversationRuntime[%s]: memory_provider.on_memory_write failed: %s",
                        self._session_id, _mp_exc,
                    )
        except Exception as exc:
            logger.debug(
                "ConversationRuntime[%s]: _handle_memory_flush failed: %s",
                self._session_id, exc,
            )

    async def _write_memory_flush(self, store, target: str, content: str) -> None:
        """Async-safe write of flush content to a MemoryStore. Fail-soft."""
        try:
            writer = getattr(store, "write", None) or getattr(store, "memory_write", None)
            if writer is None:
                logger.debug(
                    "ConversationRuntime[%s]: MemoryStore lacks write() — skipping mirror",
                    self._session_id,
                )
                return
            maybe_coro = writer(target=target, content=content, mode="overwrite")
            if hasattr(maybe_coro, "__await__"):
                await maybe_coro
        except Exception as exc:
            logger.debug(
                "ConversationRuntime[%s]: MemoryStore.write failed for %s: %s",
                self._session_id, target, exc,
            )

    # ── Telemetry recorders (called from wrap_agent_stream / _run_loop) ─

logger = logging.getLogger(__name__)
