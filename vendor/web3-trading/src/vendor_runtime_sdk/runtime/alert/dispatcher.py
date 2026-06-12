# -*- coding: utf-8 -*-
"""
AlertPolicy → notification dispatcher factory.

Builds a coroutine that accepts an ``AlertEvent``-shaped dict (as produced
by :class:`AlertPolicyEvaluator`) and forwards it through the engine's
:class:`runtime.protocols.NotificationDispatcher`. Returned callable is
fail-closed — it never raises; delivery failures surface as ``None``
return + logged warning, leaving the event recorded in MongoDB.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger(__name__)


PushSender = Callable[[Dict[str, Any]], Awaitable[Optional[str]]]


# PR-E6 (SDK extraction §5 PR-E6): lark.push_service / lark.integration_service /
# lark.models are now accessed via the NotificationDispatcher Protocol.
# The legacy lark.* call is still used via the
# _LegacyLarkNotificationDispatcher fallback so runtime behaviour is
# unchanged in Phase 0. Phase 2 removes the fallback when lark/ leaves
# the engine import surface.
async def build_lark_push_sender(
    integration_id: str = "default",
) -> Optional[PushSender]:
    """
    Build a fire-and-forget push sender. Returns ``None`` if no
    notification dispatcher is reachable — the evaluator then records
    events without attempting delivery.

    Name preserved for back-compat (``build_lark_push_sender``) — the
    underlying channel is now plug-replaceable via the
    :class:`NotificationDispatcher` Protocol.
    """
    try:
        from vendor_runtime_sdk.runtime.protocols.notification_dispatcher import (
            AlertNotification,
            get_notification_dispatcher,
        )

        dispatcher = get_notification_dispatcher()

        # When no real channel is configured (NoOp fallback OR a real
        # adapter whose underlying channel is unreachable), match the
        # historical contract of ``return None`` so the evaluator
        # skips push entirely.  Uses the capability sentinel rather
        # than an isinstance check — review feedback: isinstance leaks
        # the impl class and breaks any test subclass of NoOp.
        if not dispatcher.has_notification_channel():
            return None

        async def _send(event: Dict[str, Any]) -> Optional[str]:
            try:
                alert = AlertNotification(
                    kind="cost",
                    title=event.get("title") or "AlertPolicy triggered",
                    detail=event.get("detail") or "",
                    dashboard_url=event.get("dashboard_url") or "",
                )
                return await dispatcher.send_alert(alert)
            except Exception as exc:
                # Class name only — never the raw exception message
                # (may contain credentials / URLs / payload fragments).
                logger.warning(
                    "AlertPolicy: notification send_alert failed: %s",
                    type(exc).__name__,
                )
                return None

        return _send
    except Exception as exc:
        logger.warning(
            "AlertPolicy: failed to build notification sender: %s",
            type(exc).__name__,
        )
        return None
