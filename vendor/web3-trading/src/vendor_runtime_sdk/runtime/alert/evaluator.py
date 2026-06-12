# -*- coding: utf-8 -*-
"""
AlertPolicyEvaluator — §T14-3 runtime engine.

Pipeline:
  1. ``list_active(workspace_id)`` from :class:`AlertPolicyDAO`
  2. Compute metrics (balance / monthly spend / fallback rate)
  3. Match each policy's ``(metric, operator, threshold)``
  4. Dedup by ``(workspace_id, policy_id)`` inside ``dedup_window_sec``
  5. Persist ``AlertEvent`` and (optionally) push to Lark

Design notes:
  - DAOs / metrics-provider / push-factory are injected so the evaluator
    is trivially unit-testable without Mongo/MySQL/Lark.
  - ``_fire`` is fail-closed: if the Lark push fails the event is still
    persisted with ``notified=False`` and ``error=<msg>`` so the audit
    trail is preserved.
  - Dedup is checked against ``alert_events`` (not just an in-memory cache)
    so restarts / multi-worker deployments still coalesce.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


SUPPORTED_METRICS = frozenset({
    "balance_pct",        # remaining budget as pct of monthly limit
    "balance_absolute",   # remaining budget in currency units
    "monthly_cost",       # spend this month in currency units
    "fallback_rate",      # fraction of recent LLM calls served by fallback
})

SUPPORTED_OPERATORS = frozenset({"lt", "lte", "gt", "gte", "eq"})


# ── Value objects ─────────────────────────────────────────────────────────────


@dataclass
class AlertMetrics:
    """Current metric snapshot used for policy evaluation."""

    workspace_id: str
    balance_pct: float = 100.0
    balance_absolute: float = 0.0
    monthly_cost: float = 0.0
    monthly_limit: float = 0.0
    fallback_rate: float = 0.0
    currency: str = "CNY"
    extras: Dict[str, Any] = field(default_factory=dict)

    def value_for(self, metric: str) -> Optional[float]:
        if metric in SUPPORTED_METRICS and hasattr(self, metric):
            return float(getattr(self, metric))
        return self.extras.get(metric)


@dataclass
class AlertFireResult:
    """Outcome of a single policy fire."""

    policy_id: str
    workspace_id: str
    metric: str
    value: float
    threshold: float
    operator: str
    fired: bool
    deduped: bool = False
    event_id: Optional[str] = None
    channel: Optional[str] = None
    notify_ref: Optional[str] = None
    error: Optional[str] = None


# ── Operator matching ─────────────────────────────────────────────────────────


def _match(operator: str, value: float, threshold: float) -> bool:
    if operator == "lt":
        return value < threshold
    if operator == "lte":
        return value <= threshold
    if operator == "gt":
        return value > threshold
    if operator == "gte":
        return value >= threshold
    if operator == "eq":
        return value == threshold
    return False


# ── Evaluator ─────────────────────────────────────────────────────────────────


MetricsProvider = Callable[[str], Awaitable[AlertMetrics]]
PushSender = Callable[[Dict[str, Any]], Awaitable[Optional[str]]]
PushSenderFactory = Callable[[], Awaitable[Optional[PushSender]]]


class AlertPolicyEvaluator:
    """
    Evaluate active policies for a workspace and dispatch notifications.

    The push layer is abstracted behind ``push_sender_factory`` — callers pass
    a coroutine that returns a callable accepting an ``AlertEvent``-shaped
    dict and returning an opaque message ref (or ``None`` on failure). In
    production this is wired to ``LarkPushService.push_alert``; in tests it's
    a plain ``AsyncMock``.
    """

    def __init__(
        self,
        policy_dao: Any,
        event_dao: Any,
        metrics_provider: MetricsProvider,
        push_sender_factory: Optional[PushSenderFactory] = None,
        dedup_window_sec: int = 3600,
        dashboard_url_builder: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._policies = policy_dao
        self._events = event_dao
        self._metrics = metrics_provider
        self._push_factory = push_sender_factory
        self._dedup_window = max(0, dedup_window_sec)
        self._build_dashboard_url = dashboard_url_builder or (lambda ws: "")

    async def evaluate_workspace(self, workspace_id: str) -> List[AlertFireResult]:
        """
        Evaluate every active policy for ``workspace_id``. Never raises — a
        failure in a single policy is captured on the returned
        :class:`AlertFireResult` (``error`` field) so the caller can still
        surface partial progress.
        """
        if not workspace_id:
            return []

        try:
            policies = await self._policies.list_active(workspace_id)
        except Exception as exc:
            logger.warning("AlertPolicyEvaluator.list_active failed: %s", exc)
            return []
        if not policies:
            return []

        try:
            metrics = await self._metrics(workspace_id)
        except Exception as exc:
            logger.warning("AlertPolicyEvaluator.metrics_provider failed: %s", exc)
            return []

        results: List[AlertFireResult] = []
        for policy in policies:
            try:
                result = await self._evaluate_one(policy, metrics, workspace_id)
                results.append(result)
            except Exception as exc:
                logger.warning(
                    "AlertPolicyEvaluator failed for policy=%s: %s",
                    policy.get("policy_id"), exc,
                )
                results.append(AlertFireResult(
                    policy_id=policy.get("policy_id", ""),
                    workspace_id=workspace_id,
                    metric=policy.get("metric", ""),
                    value=0.0,
                    threshold=float(policy.get("threshold", 0.0)),
                    operator=policy.get("operator", ""),
                    fired=False,
                    error=str(exc),
                ))
        return results

    async def _evaluate_one(
        self,
        policy: Dict[str, Any],
        metrics: AlertMetrics,
        workspace_id: str,
    ) -> AlertFireResult:
        policy_id = policy.get("policy_id", "")
        metric = policy.get("metric", "")
        operator = policy.get("operator", "")
        threshold = float(policy.get("threshold", 0.0))

        if metric not in SUPPORTED_METRICS and metric not in metrics.extras:
            return AlertFireResult(
                policy_id=policy_id, workspace_id=workspace_id, metric=metric,
                value=0.0, threshold=threshold, operator=operator,
                fired=False, error=f"unsupported metric: {metric}",
            )
        if operator not in SUPPORTED_OPERATORS:
            return AlertFireResult(
                policy_id=policy_id, workspace_id=workspace_id, metric=metric,
                value=0.0, threshold=threshold, operator=operator,
                fired=False, error=f"unsupported operator: {operator}",
            )

        value = metrics.value_for(metric)
        if value is None:
            return AlertFireResult(
                policy_id=policy_id, workspace_id=workspace_id, metric=metric,
                value=0.0, threshold=threshold, operator=operator,
                fired=False, error=f"metric {metric} missing from provider",
            )

        if not _match(operator, float(value), threshold):
            return AlertFireResult(
                policy_id=policy_id, workspace_id=workspace_id, metric=metric,
                value=float(value), threshold=threshold, operator=operator,
                fired=False,
            )

        return await self._fire(policy, metrics, workspace_id, float(value))

    async def _fire(
        self,
        policy: Dict[str, Any],
        metrics: AlertMetrics,
        workspace_id: str,
        value: float,
    ) -> AlertFireResult:
        policy_id = policy["policy_id"]
        metric = policy["metric"]
        operator = policy["operator"]
        threshold = float(policy["threshold"])

        # Dedup — skip if a recent event already fired for this (ws, policy).
        if self._dedup_window > 0:
            recent = await self._events.find_recent(
                workspace_id, policy_id, self._dedup_window,
            )
            if recent:
                return AlertFireResult(
                    policy_id=policy_id, workspace_id=workspace_id, metric=metric,
                    value=value, threshold=threshold, operator=operator,
                    fired=False, deduped=True,
                    event_id=recent.get("event_id"),
                )

        title, detail = self._format_message(policy, metrics, value)
        channel = (policy.get("channels") or ["lark"])[0]

        event_doc: Dict[str, Any] = {
            "policy_id": policy_id,
            "workspace_id": workspace_id,
            "metric": metric,
            "operator": operator,
            "threshold": threshold,
            "value": value,
            "title": title,
            "detail": detail,
            "channel": channel,
            "currency": metrics.currency,
            "triggered_at": time.time(),
            "notified": False,
        }
        event_id = await self._events.insert_event(event_doc)

        notify_ref: Optional[str] = None
        error: Optional[str] = None
        if channel == "lark":
            try:
                notify_ref = await self._push(event_doc)
            except Exception as exc:
                error = str(exc)
                logger.warning(
                    "AlertPolicyEvaluator push failed event=%s: %s", event_id, exc,
                )
        else:
            # Non-lark channels are recorded but not delivered here.
            logger.info(
                "AlertPolicyEvaluator: channel=%s not wired, event=%s recorded only",
                channel, event_id,
            )

        try:
            await self._events.mark_notified(
                event_id, channel=channel, notify_ref=notify_ref, error=error,
            )
        except Exception as exc:
            logger.warning("AlertEventDAO.mark_notified failed: %s", exc)

        return AlertFireResult(
            policy_id=policy_id, workspace_id=workspace_id, metric=metric,
            value=value, threshold=threshold, operator=operator,
            fired=True, deduped=False, event_id=event_id,
            channel=channel, notify_ref=notify_ref, error=error,
        )

    async def _push(self, event: Dict[str, Any]) -> Optional[str]:
        if self._push_factory is None:
            return None
        sender = await self._push_factory()
        if sender is None:
            return None
        return await sender(event)

    def _format_message(
        self,
        policy: Dict[str, Any],
        metrics: AlertMetrics,
        value: float,
    ) -> tuple[str, str]:
        name = policy.get("name") or policy.get("policy_id", "AlertPolicy")
        metric = policy["metric"]
        operator = policy["operator"]
        threshold = policy["threshold"]
        workspace_id = metrics.workspace_id

        title = f"[AlertPolicy] {name}"
        lines = [
            f"workspace: {workspace_id}",
            f"metric:    {metric}",
            f"operator:  {operator}",
            f"threshold: {threshold}",
            f"value:     {value}",
        ]
        if metric in {"balance_absolute", "monthly_cost"}:
            lines.append(f"currency:  {metrics.currency}")
        if metric == "balance_pct":
            lines.append(
                f"balance:   {metrics.balance_absolute:.2f} {metrics.currency} "
                f"(limit {metrics.monthly_limit:.2f})"
            )
        return title, "\n".join(lines)
