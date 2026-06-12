# -*- coding: utf-8 -*-
"""
Bus-driven AlertPolicy consumer — Sprint 2 (docs/多Agent优化实施方案-SDLC.md P1).

Background task that subscribes to :class:`A2ABus` gateway events and triggers
per-workspace alert evaluation. Complements the existing
:class:`CostTrackingHook` path (which fires on every post-LLM call) with an
event-driven path, so routing anomalies (e.g. a spike of BLOCKED events from
one workspace) also feed into the alert policy engine.

Architecture
────────────
    Gateway  ──publish_event──▶  A2ABus
                                    │
                                    ├─▶ AlertPolicyConsumer.run()   (this module)
                                    │        └─▶ evaluate_async(ws) (throttled)
                                    │
                                    └─▶ (future) analytics taps, audit log, etc.

Why a consumer (not a direct alert call inside Gateway)
───────────────────────────────────────────────────────
1. Decoupling — Gateway doesn't know about alerts. Any new subscriber
   (dashboards, audit, anomaly detection) can plug in without touching the
   Gateway hot path.
2. Throttling — the existing :func:`evaluate_async` already throttles per
   workspace; reusing it keeps rate-limiting semantics unchanged.
3. Failure isolation — a misbehaving consumer cannot impact dispatch, because
   it runs in its own asyncio task and catches every exception.

Lifecycle
─────────
    start()  — idempotent; spawns the consumer task if not already running
    stop()   — cancels the task and closes the subscription

The consumer is gated on the ``a2a_gateway_events`` toggle. When the toggle is
off, ``start()`` is a no-op.

Fail-closed
───────────
• Subscriber callback exceptions are logged as WARN and emit
  ``SpanType.BUS_SUBSCRIBER_ERROR`` telemetry, but never crash the loop.
• A malformed event (missing workspace_id) is dropped silently — the bus is
  best-effort semantic, not a replayable queue.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from vendor_runtime_sdk.agent.a2a.events import GATEWAY_AGENT_LABEL

logger = logging.getLogger(__name__)


class AlertPolicyConsumer:
    """Long-lived consumer that feeds A2ABus gateway events into the alert pipeline."""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._subscription: Optional[Any] = None
        self._stopped: bool = False
        self._events_consumed: int = 0
        self._errors: int = 0

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def start(self) -> bool:
        """Start the consumer task. Idempotent; returns True if started, False if skipped."""
        if self._task is not None and not self._task.done():
            return False

        # Toggle gate — mirror the publisher side.
        try:
            from vendor_runtime_sdk.runtime.config.guards import is_module_enabled
            if not is_module_enabled("a2a_gateway_events"):
                logger.info("AlertPolicyConsumer: a2a_gateway_events toggle off — not starting")
                return False
        except Exception as exc:
            logger.info("AlertPolicyConsumer: toggle check failed (%s) — not starting", exc)
            return False

        try:
            from vendor_runtime_sdk.agent.a2a.bus import get_a2a_bus
            bus = get_a2a_bus()
            # Subscribe to the canonical gateway label. Matches what the
            # publisher emits (agent_label="gateway").
            self._subscription = bus.subscribe_events(GATEWAY_AGENT_LABEL)
        except Exception as exc:
            logger.warning("AlertPolicyConsumer: subscribe_events failed: %s", exc)
            return False

        self._stopped = False
        self._task = asyncio.create_task(self._run(), name="alert-policy-consumer")
        logger.info("AlertPolicyConsumer: started, subscribed to label=%s", GATEWAY_AGENT_LABEL)
        return True

    async def stop(self) -> None:
        """Cancel the consumer task and close the subscription. Idempotent."""
        self._stopped = True
        sub = self._subscription
        if sub is not None:
            try:
                close = getattr(sub, "close", None)
                if close is not None:
                    close()
            except Exception:
                pass
            self._subscription = None

        task = self._task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None

    # ── Diagnostics ──────────────────────────────────────────────────────────

    def stats(self) -> dict[str, int]:
        return {
            "events_consumed": self._events_consumed,
            "errors":          self._errors,
        }

    # ── Internal loop ────────────────────────────────────────────────────────

    async def _run(self) -> None:
        """Consume events until cancelled or subscription closes. Never raises."""
        sub = self._subscription
        if sub is None:
            return
        try:
            async for event in sub:
                if self._stopped:
                    break
                await self._handle_event(event)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            # This is the last-resort catch for the loop itself. Individual
            # event handling is already wrapped in _handle_event.
            logger.warning("AlertPolicyConsumer: loop exited with error: %s", exc)

    async def _handle_event(self, event: Any) -> None:
        """Dispatch one event to the alert evaluator. Swallows all exceptions."""
        try:
            # AgentEvent.payload is a dict; workspace_id lives there by convention
            # (see agent.a2a.events factories).
            payload = getattr(event, "payload", None) or {}
            workspace_id = str(payload.get("workspace_id") or "")
            if not workspace_id:
                return

            from vendor_runtime_sdk.runtime.alert.service import evaluate_async
            await evaluate_async(workspace_id)
            self._events_consumed += 1
        except Exception as exc:
            self._errors += 1
            logger.warning("AlertPolicyConsumer: handler failed: %s", exc)
            _emit_subscriber_error_span(event, str(exc))


# ── Telemetry helper (mirrors gateway_publisher) ─────────────────────────────


def _emit_subscriber_error_span(event: Any, error: str) -> None:
    """Best-effort BUS_SUBSCRIBER_ERROR emission. Never raises."""
    try:
        from vendor_runtime_sdk.runtime.telemetry import SpanEvent, SpanType, get_recorder

        session_id = ""
        event_type = ""
        try:
            session_id = str(getattr(event, "session_id", "") or "")
            et = getattr(event, "event_type", None)
            event_type = getattr(et, "value", str(et) if et is not None else "")
        except Exception:
            pass

        get_recorder().record_span_event(
            SpanEvent(
                span_type=SpanType.BUS_SUBSCRIBER_ERROR,
                session_id=session_id,
                agent_id="alert-policy-consumer",
                metadata={
                    "event_type": event_type,
                    "error":      error,
                    "source":     "alert_policy_consumer",
                },
            )
        )
    except Exception:
        pass


# ── Process-wide singleton ───────────────────────────────────────────────────


_consumer: Optional[AlertPolicyConsumer] = None


def get_consumer() -> AlertPolicyConsumer:
    """Return the process-wide consumer instance (lazy init)."""
    global _consumer
    if _consumer is None:
        _consumer = AlertPolicyConsumer()
    return _consumer


def reset_consumer_for_tests() -> None:
    """Test hook — drop the cached singleton."""
    global _consumer
    _consumer = None


__all__ = [
    "AlertPolicyConsumer",
    "get_consumer",
    "reset_consumer_for_tests",
]
