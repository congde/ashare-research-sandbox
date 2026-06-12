# -*- coding: utf-8 -*-
"""Match KuCoin positions with ValueScan risk/opportunity signals → actionable alerts."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

_AI_LIST_TTL_SEC = 90
_ai_lists_cache: Dict[str, Any] = {"ts": 0.0, "chance": [], "risk": [], "funds": []}

_RISK_MSG_TYPES = {9, 10, 11, 12, 15, 21, 22, 23, 24, 25}
_CHANCE_BULL_TYPES = {1, 3, 5, 14, 16, 17, 18, 28, 30}
_FUNDS_BULL_TYPES = {1, 2, 3, 13}


def _normalize_symbol(value: str) -> str:
    raw = str(value or "").strip().upper()
    if raw == "XBT":
        return "BTC"
    return raw.split("-")[0].split("/")[0].split(":")[0]


def _symbol_from_list_item(item: Dict[str, Any]) -> str:
    return _normalize_symbol(
        item.get("symbol") or item.get("tokenSymbol") or item.get("name") or ""
    )


async def _get_global_ai_lists() -> Tuple[List[Dict], List[Dict], List[Dict]]:
    now = time.time()
    if now - float(_ai_lists_cache.get("ts") or 0) < _AI_LIST_TTL_SEC:
        return (
            _ai_lists_cache.get("chance") or [],
            _ai_lists_cache.get("risk") or [],
            _ai_lists_cache.get("funds") or [],
        )
    from web.api import valuescan_service as vs

    chance, risk, funds = await asyncio.gather(
        vs.get_chance_coin_list(),
        vs.get_risk_coin_list(),
        vs.get_funds_coin_list(),
        return_exceptions=True,
    )
    if isinstance(chance, Exception):
        chance = []
    if isinstance(risk, Exception):
        risk = []
    if isinstance(funds, Exception):
        funds = []
    _ai_lists_cache.update(
        {"ts": now, "chance": chance or [], "risk": risk or [], "funds": funds or []}
    )
    return chance or [], risk or [], funds or []


def _index_by_symbol(items: List[Dict]) -> Dict[str, Dict]:
    out: Dict[str, Dict] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        sym = _symbol_from_list_item(item)
        if sym:
            out[sym] = item
    return out


def _msg_type_from_sse(event: Dict[str, Any]) -> int:
    parsed = event.get("parsed") if isinstance(event.get("parsed"), dict) else {}
    for key in (
        "riskMessageType",
        "chanceMessageType",
        "fundsMessageType",
        "fundsMovementType",
    ):
        if parsed.get(key) is not None:
            try:
                return int(parsed[key])
            except (TypeError, ValueError):
                pass
    return 0


def _sse_channel(event: Dict[str, Any]) -> str:
    raw = str(event.get("type") or "").upper()
    if "RISK" in raw:
        return "risk"
    if "OPPORTUNITY" in raw or "CHANCE" in raw:
        return "chance"
    if "FUND" in raw:
        return "funds"
    return ""


async def fetch_futures_positions_brief(account_id: str) -> List[Dict[str, Any]]:
    from web.api.llm_futures_executor import _fetch_open_futures_positions

    try:
        raw = await _fetch_open_futures_positions(account_id, [])
    except Exception as exc:
        logger.warning("position alerts: futures fetch failed: %s", exc)
        return []
    positions: List[Dict[str, Any]] = []
    for sym, row in (raw or {}).items():
        base = _normalize_symbol(sym)
        if not base:
            continue
        positions.append({
            "symbol": base,
            "side": str(row.get("side") or "long").lower(),
            "contracts": row.get("contracts"),
            "entryPrice": row.get("entryPrice"),
            "markPrice": row.get("markPrice"),
            "unrealizedPnlPct": row.get("unrealizedPnlPct"),
            "unrealisedPnl": row.get("unrealisedPnl"),
        })
    return positions


async def collect_watch_symbols_for_sse(extra: List[str]) -> List[str]:
    """Symbols for SSE worker: defaults + automation config + open futures positions."""
    seen: Set[str] = set()
    ordered: List[str] = []

    def _add(sym: str) -> None:
        base = _normalize_symbol(sym)
        if base and base not in seen:
            seen.add(base)
            ordered.append(base)

    for sym in extra:
        _add(sym)

    try:
        from web.api.live_automation_runner import get_status

        st = get_status()
        cfg = st.get("config") or {}
        for sym in cfg.get("symbols") or []:
            if isinstance(sym, str):
                _add(sym)
            elif isinstance(sym, list):
                for s in sym:
                    _add(str(s))
    except Exception:
        pass

    account_id = "claude"
    try:
        from web.api.live_trading_routes import _resolve_live_futures_account_id

        account_id = _resolve_live_futures_account_id({})
    except Exception:
        pass

    for pos in await fetch_futures_positions_brief(account_id):
        _add(pos["symbol"])

    return ordered


def _make_alert(
    *,
    symbol: str,
    severity: str,
    category: str,
    title: str,
    detail: str,
    suggested_action: str,
    position: Optional[Dict[str, Any]] = None,
    vs_source: str = "",
    ref_price: Optional[float] = None,
) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "symbol": symbol,
        "severity": severity,
        "category": category,
        "title": title,
        "detail": detail,
        "suggestedAction": suggested_action,
        "vsSource": vs_source,
        "ts": int(time.time() * 1000),
    }
    if position:
        row["positionSide"] = position.get("side")
        row["unrealizedPnlPct"] = position.get("unrealizedPnlPct")
    if ref_price and ref_price > 0:
        row["refPrice"] = ref_price
    return row


async def build_position_vs_alerts(
    account_id: str = "claude",
    extra_symbols: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    持仓 × ValueScan：风险榜 / 机会榜 / 资金异动 + SSE 实时推送 → 排序后的告警列表。
    """
    from web.api.valuescan_signal_digest import build_valuescan_digest
    from web.api.valuescan_sse_worker import (
        get_cached_signal_events,
        get_worker_status,
        update_watch_symbols,
    )

    symbols_watch = list(extra_symbols or [])
    positions = await fetch_futures_positions_brief(account_id)
    held_symbols = {p["symbol"] for p in positions}
    for sym in held_symbols:
        if sym not in symbols_watch:
            symbols_watch.append(sym)

    await update_watch_symbols(symbols_watch)

    chance_list, risk_list, funds_list = await _get_global_ai_lists()
    chance_idx = _index_by_symbol(chance_list)
    risk_idx = _index_by_symbol(risk_list)
    funds_idx = _index_by_symbol(funds_list)

    alerts: List[Dict[str, Any]] = []
    severity_rank = {"high": 0, "medium": 1, "low": 2}

    for pos in positions:
        sym = pos["symbol"]
        side = pos.get("side") or "long"

        if sym in risk_idx:
            alerts.append(_make_alert(
                symbol=sym,
                severity="high",
                category="risk",
                title="下跌风险预警",
                detail="ValueScan 风险代币榜命中，建议关注仓位并考虑减仓或收紧止损",
                suggested_action="reduce_or_stop",
                position=pos,
                vs_source="risk_list",
            ))

        if sym in chance_idx and side == "long":
            item = chance_idx[sym]
            cost = item.get("cost")
            detail = "ValueScan 机会榜命中，持仓多单可观察加仓或移动止盈"
            if cost:
                detail += f"（主力成本参考 ${float(cost):,.0f}）"
            alerts.append(_make_alert(
                symbol=sym,
                severity="medium",
                category="opportunity",
                title="机会榜共振",
                detail=detail,
                suggested_action="trail_stop_or_add",
                position=pos,
                vs_source="chance_list",
            ))

        if sym in funds_idx:
            alerts.append(_make_alert(
                symbol=sym,
                severity="medium",
                category="funds",
                title="资金异动",
                detail="ValueScan 资金异动榜命中，主力流向异常",
                suggested_action="watch",
                position=pos,
                vs_source="funds_list",
            ))

        for evt in get_cached_signal_events(symbol=sym, limit=5):
            channel = _sse_channel(evt)
            msg_type = _msg_type_from_sse(evt)
            parsed = evt.get("parsed") if isinstance(evt.get("parsed"), dict) else {}
            price_raw = parsed.get("price") or evt.get("price")
            try:
                ref_price = float(price_raw) if price_raw else None
            except (TypeError, ValueError):
                ref_price = None

            if channel == "risk" or msg_type in _RISK_MSG_TYPES:
                alerts.append(_make_alert(
                    symbol=sym,
                    severity="high",
                    category="risk",
                    title="VS 实时风险信号",
                    detail=f"SSE 推送风险类信号（type={msg_type or 'risk'}）",
                    suggested_action="reduce_or_stop",
                    position=pos,
                    vs_source="sse_risk",
                    ref_price=ref_price,
                ))
            elif side == "long" and (
                channel == "chance" or msg_type in _CHANCE_BULL_TYPES or msg_type in _FUNDS_BULL_TYPES
            ):
                alerts.append(_make_alert(
                    symbol=sym,
                    severity="medium",
                    category="reversal",
                    title="趋势加强 / 主力活跃",
                    detail=f"SSE 推送机会/资金异动（type={msg_type or channel}）",
                    suggested_action="trail_stop_or_add",
                    position=pos,
                    vs_source="sse_bullish",
                    ref_price=ref_price,
                ))

    digest_by_sym: Dict[str, Dict[str, Any]] = {}
    if positions:
        from web.api.dashboard_service import fetch_valuescan_signal_data

        async def _digest_for(p: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
            sym = p["symbol"]
            try:
                vs_data = await fetch_valuescan_signal_data(sym)
                return sym, build_valuescan_digest(vs_data, float(p.get("markPrice") or 0))
            except Exception as exc:
                logger.debug("digest alert %s: %s", sym, exc)
                return sym, {}

        pairs = await asyncio.gather(*[_digest_for(p) for p in positions])
        digest_by_sym = {sym: d for sym, d in pairs if d}

    for pos in positions:
        sym = pos["symbol"]
        side = pos.get("side") or "long"
        digest = digest_by_sym.get(sym) or {}
        if digest.get("actionBias") == "risk_off" and side == "long":
            alerts.append(_make_alert(
                symbol=sym,
                severity="high",
                category="risk",
                title="VS 综合倾向偏风险",
                detail=digest.get("primaryAlert") or "追踪摘要提示风险升高",
                suggested_action="reduce_or_stop",
                position=pos,
                vs_source="digest_risk_off",
            ))
        plan = digest.get("suggestedPlan") or {}
        mark = float(pos.get("markPrice") or 0)
        support = float(plan.get("support") or 0)
        if side == "long" and mark > 0 and support > 0:
            dist_pct = (mark - support) / mark * 100
            if dist_pct <= 1.5 and digest.get("signalHits", {}).get("chance"):
                alerts.append(_make_alert(
                    symbol=sym,
                    severity="medium",
                    category="opportunity",
                    title="接近 VS 支撑位 + 机会信号",
                    detail=f"现价距支撑约 {dist_pct:.2f}%，可考虑分批介入或保护性止损",
                    suggested_action="limit_buy_near_support",
                    position=pos,
                    vs_source="support_chance",
                    ref_price=support,
                ))
        resist = float(plan.get("resistance") or 0)
        if side == "long" and mark > 0 and resist > 0:
            dist_pct = (resist - mark) / mark * 100
            if dist_pct <= 1.2:
                alerts.append(_make_alert(
                    symbol=sym,
                    severity="medium",
                    category="take_profit",
                    title="接近 VS 压力位",
                    detail=f"距压力约 {dist_pct:.2f}%，可考虑部分止盈或跟踪止损",
                    suggested_action="take_profit",
                    position=pos,
                    vs_source="near_resistance",
                    ref_price=resist,
                ))

    deduped: Dict[str, Dict[str, Any]] = {}
    for alert in alerts:
        key = f"{alert['symbol']}:{alert['category']}:{alert['vsSource']}:{alert['title']}"
        prev = deduped.get(key)
        if not prev or severity_rank.get(alert["severity"], 9) < severity_rank.get(prev["severity"], 9):
            deduped[key] = alert

    final = sorted(
        deduped.values(),
        key=lambda a: (severity_rank.get(a.get("severity"), 9), a.get("symbol", "")),
    )

    return {
        "ok": True,
        "accountId": account_id,
        "positionCount": len(positions),
        "positions": positions,
        "alerts": final,
        "alertCount": len(final),
        "sseWorker": get_worker_status(),
        "globalHits": {
            "chanceSymbols": list(chance_idx.keys())[:20],
            "riskSymbols": list(risk_idx.keys())[:20],
        },
    }
