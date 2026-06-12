# -*- coding: utf-8 -*-
"""Realtime market data knobs for live automation / LLM signal flows."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

_DEFAULT_KLINE_TFS = ("1min", "5min")
_DEFAULT_LIVE_MERGE_TFS = ("1min", "5min", "15min")
# Keep in sync with dashboard_service.KLINE_TIMEFRAMES_SIGNAL_FULL
_SIGNAL_KLINE_BASE: Tuple[str, ...] = ("15min", "1hour", "4hour", "1day")
_VALID_KLINE_TFS = frozenset({
    "1min", "3min", "5min", "15min", "30min",
    "1hour", "2hour", "4hour", "6hour", "8hour", "12hour", "1day", "1week",
})


def _coerce_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in ("false", "0", "no", "off", "")


def _parse_timeframe_list(raw: Any) -> Tuple[str, ...]:
    if isinstance(raw, (list, tuple)):
        items = [str(part).strip() for part in raw]
    else:
        items = [part.strip() for part in str(raw or "").replace(";", ",").split(",")]
    out: List[str] = []
    for item in items:
        if not item or item not in _VALID_KLINE_TFS or item in out:
            continue
        out.append(item)
    return tuple(out)


def resolve_realtime_options() -> Dict[str, Any]:
    """Read realtime data knobs from web.config and env (LIVE_REALTIME_*)."""
    enabled = _coerce_bool(os.getenv("LIVE_REALTIME_ENABLED"), True)
    kline_timeframes = _parse_timeframe_list(
        os.getenv("LIVE_REALTIME_KLINE_TIMEFRAMES") or ",".join(_DEFAULT_KLINE_TFS)
    )

    merge_timeframes = _parse_timeframe_list(
        os.getenv("LIVE_REALTIME_KLINE_MERGE_TIMEFRAMES") or ",".join(_DEFAULT_LIVE_MERGE_TFS)
    )
    if not kline_timeframes:
        kline_timeframes = _DEFAULT_KLINE_TFS
    if not merge_timeframes:
        merge_timeframes = _DEFAULT_LIVE_MERGE_TFS

    try:
        from web.config import config

        if getattr(config, "live_realtime_enabled", None) is not None:
            enabled = _coerce_bool(config.live_realtime_enabled, enabled)
        if getattr(config, "live_realtime_kline_timeframes", None) is not None:
            parsed = _parse_timeframe_list(config.live_realtime_kline_timeframes)
            if parsed:
                kline_timeframes = parsed
        if getattr(config, "live_realtime_kline_merge_timeframes", None) is not None:
            parsed = _parse_timeframe_list(config.live_realtime_kline_merge_timeframes)
            if parsed:
                merge_timeframes = parsed
    except Exception:
        pass

    return {
        "enabled": enabled,
        "kline_timeframes": kline_timeframes,
        "kline_merge_timeframes": merge_timeframes,
    }


def live_kline_merge_timeframes() -> Tuple[str, ...]:
    return resolve_realtime_options()["kline_merge_timeframes"]


def signal_kline_timeframes() -> Tuple[str, ...]:
    """Base signal K-line periods plus optional short-TF realtime candles."""
    opts = resolve_realtime_options()
    base = _SIGNAL_KLINE_BASE
    if not opts["enabled"]:
        return base
    extra = tuple(tf for tf in opts["kline_timeframes"] if tf not in base)
    return extra + base if extra else base


def _to_float(value: Any) -> float:
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def resolve_live_mark_price(data: Dict[str, Any]) -> float:
    """Prefer contract mark / L1 quote over stale 24h ticker for execution checks."""
    rt = data.get("realtime") if isinstance(data.get("realtime"), dict) else {}
    mark = rt.get("futuresMarkPrice") if isinstance(rt.get("futuresMarkPrice"), dict) else {}
    ticker = rt.get("futuresTicker") if isinstance(rt.get("futuresTicker"), dict) else {}
    level1 = rt.get("level1") if isinstance(rt.get("level1"), dict) else {}
    derivatives = data.get("derivatives") if isinstance(data.get("derivatives"), dict) else {}
    market = data.get("market") if isinstance(data.get("market"), dict) else {}

    for candidate in (
        mark.get("value"),
        mark.get("markPrice"),
        ticker.get("last"),
        level1.get("price"),
        derivatives.get("futuresLast"),
        market.get("last"),
    ):
        price = _to_float(candidate)
        if price > 0:
            return price
    return 0.0


async def fetch_signal_kline_signals(pair: str) -> Dict[str, Any]:
    """Fetch signal K-lines; merge L1 live price into short-TF forming bars when realtime is on."""
    from web.api.dashboard_service import fetch_kline_signals, fetch_orderbook_level1

    opts = resolve_realtime_options()
    timeframes = signal_kline_timeframes()
    live_price = 0.0
    merge_tfs: Tuple[str, ...] = ()
    if opts["enabled"]:
        merge_tfs = live_kline_merge_timeframes()
        try:
            level1 = await fetch_orderbook_level1(pair)
            live_price = _to_float(level1.get("price"))
        except Exception as exc:
            logger.warning("signal kline level1 for %s: %s", pair, exc)
    return await fetch_kline_signals(
        pair,
        timeframes=timeframes,
        live_price=live_price if live_price > 0 else None,
        merge_timeframes=merge_tfs if live_price > 0 else None,
    )


async def enrich_signal_data(aggregated: Dict[str, Any], pair: str) -> Dict[str, Any]:
    """Attach REST realtime snapshot (L1 book + futures mark/ticker)."""
    opts = resolve_realtime_options()
    if not opts["enabled"]:
        return aggregated

    from web.api.dashboard_service import fetch_realtime_snapshot

    try:
        aggregated["realtime"] = await fetch_realtime_snapshot(pair)
    except Exception as exc:
        logger.warning("realtime snapshot failed for %s: %s", pair, exc)
        aggregated["realtime"] = {"available": False, "error": str(exc)}
    return aggregated
