from __future__ import annotations

import logging
from typing import Any

from dashboard import valuescan as vs

logger = logging.getLogger(__name__)

_H24_TIME_PARTICLE = 24


def _sector_h24_inflow(sector: dict[str, Any]) -> float:
    total = 0.0
    for rec in sector.get("categoriesTradeDataList") or sector.get("categories_trade_data_list") or []:
        if not isinstance(rec, dict):
            continue
        tpe = rec.get("timeParticleEnum") or rec.get("time_particle_enum") or 0
        if int(tpe) == _H24_TIME_PARTICLE:
            total += float(rec.get("tradeInflow") or rec.get("trade_inflow") or 0)
    if total == 0.0:
        for rec in sector.get("categoriesTradeDataList") or sector.get("categories_trade_data_list") or []:
            if isinstance(rec, dict):
                total += float(rec.get("tradeInflow") or rec.get("trade_inflow") or 0)
    return total


def _top_sector_tags(sectors: list[dict[str, Any]], limit: int = 3) -> list[str]:
    scored: list[tuple[float, str]] = []
    for sector in sectors:
        tag = str(sector.get("tag") or sector.get("tagsSimplified") or "").strip()
        if tag:
            scored.append((_sector_h24_inflow(sector), tag))
    scored.sort(key=lambda item: item[0], reverse=True)
    seen: set[str] = set()
    tags: list[str] = []
    for _, tag in scored:
        if tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
        if len(tags) >= limit:
            break
    return tags


def _assign(result: dict[str, Any], key: str, value: Any, expected: type) -> None:
    if expected is list:
        if isinstance(value, list) and value:
            result[key] = value
    elif expected is dict:
        if isinstance(value, dict) and value:
            result[key] = value


def fetch_full_token_data(symbol: str) -> dict[str, Any]:
    """
  对齐 vendor ``fetch_full_token_data``：单币 ValueScan REST 全量（不含 SSE Worker）。
    """
    sym = (symbol or "BTC").strip().upper()
    result: dict[str, Any] = {"symbol": sym, "fetchedAt": vs._now_ms()}

    vs_id = vs.get_vs_token_id(sym)
    if not vs_id:
        return result
    result["vsTokenId"] = vs_id

    try:
        _assign(result, "tokenDetail", vs.get_token_detail(vs_id), dict)
        _assign(result, "fund", vs.get_realtime_fund(vs_id), dict)
        _assign(result, "fundRatio", vs.get_fund_market_cap_ratio(vs_id), dict)
        _assign(result, "tokenFlow", vs.get_token_flow(vs_id), dict)
        _assign(result, "sentiment", vs.get_social_sentiment(vs_id), dict)
        _assign(result, "supportResistance", vs.get_support_resistance(vs_id, days=30), list)
        _assign(result, "whaleCost", vs.get_whale_cost(vs_id, days=90), list)
        _assign(result, "priceIndicators", vs.get_price_indicators(vs_id, days=90), list)
        _assign(result, "largeTransactions", vs.get_large_transactions(vs_id, page=1, page_size=50), list)
        _assign(result, "holderList", vs.get_holder_list(vs_id, page=1, page_size=50), list)
        _assign(result, "fundSnapshot", vs.get_fund_snapshot(vs_id), dict)

        ai_messages: dict[str, Any] = {}
        for msg_type in ("chance", "risk", "funds"):
            msgs = vs.get_ai_messages(vs_id, msg_type)
            if msgs:
                ai_messages[msg_type] = msgs[:50]
        if ai_messages:
            result["aiMessages"] = ai_messages

        for bucket, days, out_key in (
            ("15m", 7, "vsKline15m7d"),
            ("1h", 14, "vsKline1h14d"),
            ("4h", 30, "vsKline4h30d"),
            ("1d", 90, "vsKline1d90d"),
        ):
            kline = vs.get_trade_kline(vs_id, bucket_type=bucket, days=days)
            _assign(result, out_key, kline, list)

        holders = result.get("holderList") or []
        top_addrs = [
            str(row.get("address") or "").strip()
            for row in holders[:3]
            if isinstance(row, dict) and row.get("address")
        ]
        if top_addrs:
            addr_trends: list[dict[str, Any]] = []
            for addr in top_addrs:
                entry: dict[str, Any] = {"address": addr}
                bal = vs._address_trend(vs_id, addr, "/chain/trade/token/balanceTrend")
                pnl = vs._address_trend(vs_id, addr, "/chain/trade/token/profitLossTrend")
                hold = vs._address_trend(vs_id, addr, "/chain/trade/token/holdTrend")
                trade_count = vs._address_trend(vs_id, addr, "/chain/trade/token/tradeCountTrend")
                if bal:
                    entry["balanceTrend"] = bal
                if pnl:
                    entry["profitLossTrend"] = pnl
                if hold:
                    entry["holdTrend"] = hold
                if trade_count:
                    entry["tradeCountTrend"] = trade_count
                if len(entry) > 1:
                    addr_trends.append(entry)
            if addr_trends:
                result["topHolderAddressTrends"] = addr_trends
    except Exception as exc:
        logger.warning("valuescan full token fetch partial failure for %s: %s", sym, exc)

    return result


def fetch_global_valuescan_data() -> dict[str, Any]:
    """全局 ValueScan 数据集：板块现货/合约、AI 列表、大盘解析历史。"""
    sector_spot = vs.get_sector_fund(1).get("sectors") or []
    sector_fut = vs.get_sector_fund(2).get("sectors") or []
    picks = vs.get_ai_picks()
    history = vs.get_ai_market_analyse_history(page=1, page_size=30)

    sector_coin_spot: dict[str, list[Any]] = {}
    sector_coin_fut: dict[str, list[Any]] = {}
    for tag in _top_sector_tags(sector_spot if isinstance(sector_spot, list) else [], 3):
        coins = vs.get_sector_coin_trade_list(tag, 1)
        if coins:
            sector_coin_spot[tag] = coins[:30]
    for tag in _top_sector_tags(sector_fut if isinstance(sector_fut, list) else [], 3):
        coins = vs.get_sector_coin_trade_list(tag, 2)
        if coins:
            sector_coin_fut[tag] = coins[:30]

    body: dict[str, Any] = {
        "ok": True,
        "source": "live",
        "full": True,
        "chance": picks.get("chance") or [],
        "risk": picks.get("risk") or [],
        "funds": picks.get("funds") or [],
        "sectorFundListSpot": sector_spot[:25] if isinstance(sector_spot, list) else [],
        "sectorFundListFutures": sector_fut[:25] if isinstance(sector_fut, list) else [],
        "aiMarketAnalyseHistory": history,
    }
    if sector_coin_spot:
        body["sectorCoinTradeSpot"] = sector_coin_spot
    if sector_coin_fut:
        body["sectorCoinTradeFutures"] = sector_coin_fut
    return body
