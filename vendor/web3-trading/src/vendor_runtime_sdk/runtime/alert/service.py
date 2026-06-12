# -*- coding: utf-8 -*-
"""
AlertPolicy service factory + throttled per-workspace evaluator.

Responsibilities:
  - Lazily build a singleton :class:`AlertPolicyEvaluator` wired to the real
    DAOs, metrics provider, and Lark push factory.
  - Throttle per-workspace evaluations so each ``on_post_llm_call`` doesn't
    round-trip to Mongo on every token. Per-workspace min interval defaults
    to 30s — configurable via ``ALERT_POLICY_MIN_INTERVAL_SEC``.

Fire-and-forget: the hook schedules ``evaluate_async(workspace_id)`` as a
task; exceptions never bubble up to the agent loop.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# Module-level singletons
_evaluator: Optional[Any] = None
_evaluator_lock: Optional[asyncio.Lock] = None
_last_eval_at: Dict[str, float] = {}


def _lock() -> asyncio.Lock:
    global _evaluator_lock
    if _evaluator_lock is None:
        _evaluator_lock = asyncio.Lock()
    return _evaluator_lock


def _min_interval_sec() -> int:
    try:
        return int(os.environ.get("ALERT_POLICY_MIN_INTERVAL_SEC", "30"))
    except ValueError:
        return 30


def _dedup_window_sec() -> int:
    try:
        return int(os.environ.get("ALERT_POLICY_DEDUP_WINDOW_SEC", "3600"))
    except ValueError:
        return 3600


def _mongo_db_name() -> str:
    return os.environ.get("MONGO_DB_NAME") or "ai-assistant"


async def get_evaluator() -> Optional[Any]:
    """
    Return the runtime evaluator singleton. ``None`` if Mongo / the required
    infra is not reachable.
    """
    global _evaluator
    if _evaluator is not None:
        return _evaluator

    async with _lock():
        if _evaluator is not None:
            return _evaluator

        try:
            # PR-E5 — engine reads Mongo via BackendClientProvider
            # instead of importing web.component directly.
            from vendor_runtime_sdk.runtime.protocols.backend_provider import get_backend_provider
            from dao.alert_policy_dao import AlertPolicyDAO, AlertEventDAO
            from vendor_runtime_sdk.runtime.alert.evaluator import AlertPolicyEvaluator
            from vendor_runtime_sdk.runtime.alert.metrics import build_workspace_metrics
            from vendor_runtime_sdk.runtime.alert.dispatcher import build_lark_push_sender

            mongo_client = await get_backend_provider().get_mongo_client()
            db = mongo_client[_mongo_db_name()]
            policy_dao = AlertPolicyDAO(db)
            event_dao = AlertEventDAO(db)
            # best-effort; failures are swallowed inside ensure_indexes
            await policy_dao.ensure_indexes()
            await event_dao.ensure_indexes()

            _evaluator = AlertPolicyEvaluator(
                policy_dao=policy_dao,
                event_dao=event_dao,
                metrics_provider=build_workspace_metrics,
                push_sender_factory=build_lark_push_sender,
                dedup_window_sec=_dedup_window_sec(),
            )
            return _evaluator
        except Exception as exc:
            logger.info("AlertPolicy evaluator unavailable: %s", exc)
            return None


def reset_evaluator_for_tests() -> None:
    """Test-only: drop the cached singleton and throttle state."""
    global _evaluator, _evaluator_lock, _last_eval_at
    _evaluator = None
    _evaluator_lock = None
    _last_eval_at = {}


async def evaluate_async(workspace_id: str) -> None:
    """
    Fire-and-forget entry point used by hooks (see CostTrackingHook).

    Throttles per-workspace: subsequent calls within
    ``ALERT_POLICY_MIN_INTERVAL_SEC`` are dropped. Never raises.
    """
    if not workspace_id:
        return

    now = time.time()
    last = _last_eval_at.get(workspace_id, 0.0)
    if now - last < _min_interval_sec():
        return
    _last_eval_at[workspace_id] = now

    try:
        evaluator = await get_evaluator()
        if evaluator is None:
            return
        await evaluator.evaluate_workspace(workspace_id)
    except Exception as exc:
        logger.warning("AlertPolicy evaluate_async failed ws=%s: %s", workspace_id, exc)


def schedule_evaluation(workspace_id: Optional[str]) -> None:
    """
    Schedule an async evaluation from a synchronous context (PluginHook).
    Safe no-op if no event loop is running.
    """
    if not workspace_id:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(evaluate_async(workspace_id))
