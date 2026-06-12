# -*- coding: utf-8 -*-
"""
Default metrics provider — wraps CostRecordDao + AlertConfigDao to build
an :class:`AlertMetrics` snapshot for a workspace.

Kept separate from the evaluator so tests can inject a plain coroutine and
so production wiring stays a single function call.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, Optional

from vendor_runtime_sdk.runtime.alert.evaluator import AlertMetrics

logger = logging.getLogger(__name__)


async def build_workspace_metrics(workspace_id: str) -> AlertMetrics:
    """
    Produce a metrics snapshot for ``workspace_id``. Never raises — returns
    a zero-valued snapshot if any underlying DAO is unavailable.
    """
    monthly_cost = 0.0
    monthly_limit = 0.0
    currency = "CNY"
    fallback_rate = 0.0

    try:
        # PR-E4 (SDK extraction §5 PR-E4): CostRecordDao is now accessed via the
        # CostRecordRepository Protocol.  The legacy dao.mysql.cost_record is still
        # used via the _LegacyCostRecordRepository fallback so runtime behaviour
        # is unchanged in Phase 0.  Phase 2 removes the fallback when dao/ leaves
        # the engine import surface.
        from vendor_runtime_sdk.runtime.protocols.cost_record_repository import (
            get_cost_record_repository,
        )
        cost_repo = get_cost_record_repository()
        monthly_cost = _as_float(
            await cost_repo.get_monthly_cost(workspace_id=workspace_id)
        )
    except Exception as exc:
        logger.debug("metrics: get_monthly_cost failed: %s", exc)

    try:
        from dao.mysql.alert_config import get_alert_config_dao
        ac_dao = get_alert_config_dao()
        cfg = await ac_dao.get_budget_config()
        monthly_limit = _as_float(cfg.get("monthly_limit", 0.0))
        currency = str(cfg.get("currency", "CNY"))
    except Exception as exc:
        logger.debug("metrics: budget config fetch failed: %s", exc)

    balance_absolute = max(0.0, monthly_limit - monthly_cost)
    balance_pct = (
        (balance_absolute / monthly_limit * 100.0)
        if monthly_limit > 0 else 100.0
    )

    return AlertMetrics(
        workspace_id=workspace_id,
        balance_pct=round(balance_pct, 4),
        balance_absolute=round(balance_absolute, 4),
        monthly_cost=round(monthly_cost, 4),
        monthly_limit=round(monthly_limit, 4),
        fallback_rate=round(fallback_rate, 4),
        currency=currency,
    )


def _as_float(val: Any) -> float:
    if val is None:
        return 0.0
    if isinstance(val, Decimal):
        return float(val)
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0
