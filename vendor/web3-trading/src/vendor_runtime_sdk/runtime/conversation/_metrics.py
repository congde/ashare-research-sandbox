# -*- coding: utf-8 -*-
"""
MetricsMixin — token recording, fallback recording, FSM transitions, interrupt

Auto-extracted from runtime/conversation.py during refactoring.
Part of the ConversationRuntime mixin chain.
"""

from __future__ import annotations

import time
import logging

class MetricsMixin:
    """MetricsMixin — token recording, fallback recording, FSM transitions, interrupt"""

    def _record_tokens(self, input_tokens: int = 0, output_tokens: int = 0) -> None:
        """Update live token counters."""
        if input_tokens:
            self._input_tokens_last = int(input_tokens)
            self._tokens_total += int(input_tokens)
        if output_tokens:
            self._output_tokens_last = int(output_tokens)
            self._tokens_total += int(output_tokens)

    def _record_fallback(self, model: str, reason: str = "") -> None:
        """Update fallback counters on trigger."""
        self._fallback_count += 1
        self._last_fallback_reason = reason or "unspecified"

    def _record_fsm_transition(self, to_state: str) -> None:
        """Record an FSM transition for the snapshot log."""
        import time as _t
        from_state = self._fsm.state.value if hasattr(self._fsm.state, "value") else str(self._fsm.state)
        self._fsm_transitions.append((round(_t.time(), 3), from_state, to_state))

    # ── Public API ─────────────────────────────────────────────────────────────

    def request_interrupt(self, reason: str = "user_cancel") -> None:
        """
        Signal the runtime to stop at the next safe checkpoint.

        Thread-safe (attribute write is atomic in CPython).
        """
        self._interrupt_requested = True
        self._interrupt_reason = reason
        logger.info(
            "ConversationRuntime[%s]: interrupt requested — %s",
            self._session_id,
            reason,
        )


logger = logging.getLogger(__name__)
