# -*- coding: utf-8 -*-
"""
Opportunity Scanner — multi-coin signal scanning service.

Scans a batch of symbols in parallel using rule-based signal analysis,
optionally enriched with ValueScan data and TradingAgents debate,
to identify the top trading opportunities.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from web.api.signal_schema import (
    OpportunityItem,
    OpportunityScanResult,
    TradePlan,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_TOP_K = 10
MAX_SYMBOLS = 100
MAX_CONCURRENT = 20  # Max parallel data-fetch tasks
MIN_VOLUME_DEFAULT = 100_000  # $100k minimum 24h volume


# ---------------------------------------------------------------------------
# Candidate sourcing
# ---------------------------------------------------------------------------
async def _fetch_top_tickers(
    quote: str = "USDT",
    limit: int = 50,
    min_volume: float = MIN_VOLUME_DEFAULT,
) -> List[Dict[str, Any]]:
    """
    Fetch top tickers by 24h volume from KuCoin allTickers.
    Returns list of normalized ticker dicts.
    """
    from web.api.dashboard_service import kucoin_get, normalize_tickers

    data = await kucoin_get("/api/v1/market/allTickers")
    raw = (data.get("data") or {}).get("ticker") or []
    tickers = normalize_tickers(raw, quote=quote, search="", limit=1000)

    # Filter by minimum volume and sort
    filtered = [
        t for t in tickers
        if float(t.get("volValue") or 0) >= min_volume
    ]
    filtered.sort(key=lambda x: float(x.get("volValue") or 0), reverse=True)
    return filtered[:limit]


def _extract_symbol(pair: str) -> str:
    """Extract base symbol from pair like 'BTC-USDT' -> 'BTC'."""
    return pair.split("-")[0] if "-" in pair else pair


# ---------------------------------------------------------------------------
# Per-symbol data fetching + scoring
# ---------------------------------------------------------------------------
async def _analyze_single_symbol(
    sym: str,
    pair: str,
    ticker_data: Optional[Dict[str, Any]] = None,
    use_valuescan: bool = True,
) -> Tuple[Optional[OpportunityItem], Optional[str]]:
    """
    Fetch data and compute signal for a single symbol.
    Returns (OpportunityItem, None) on success or (None, error_msg) on failure.
    """
    from web.api.dashboard_service import (
        fetch_kline_signals,
        fetch_market_stats,
        fetch_valuescan_signal_data,
    )
    from web.api.signal_analyzer import compute_signal

    try:
        # Parallel data fetch
        kline_task = fetch_kline_signals(pair)
        market_task = fetch_market_stats(pair) if not ticker_data else _noop(ticker_data)
        vs_task = fetch_valuescan_signal_data(sym) if use_valuescan else _noop({})

        kline, market, vs_data = await asyncio.gather(
            kline_task, market_task, vs_task,
            return_exceptions=True,
        )

        if isinstance(kline, Exception):
            kline = {}
        if isinstance(market, Exception):
            market = ticker_data or {}
        if isinstance(vs_data, Exception):
            vs_data = {}

        # Use ticker_data for market if we have it
        if ticker_data and not market:
            market = ticker_data

        aggregated = {
            "symbol": sym,
            "pair": pair,
            "market": market if isinstance(market, dict) else {},
            "kline": kline if isinstance(kline, dict) else {},
            "news": [],
            "onchain": {"summary": "", "extra": {}},
            "onchainMetrics": {},
            "valuescan": vs_data if isinstance(vs_data, dict) else {},
        }

        # Rule-based signal
        result = compute_signal(aggregated)

        # Extract market stats
        m = aggregated["market"]
        change_rate = float(m.get("changeRate") or 0)
        vol_value = float(m.get("volValue") or 0)
        last_price = float(m.get("last") or 0)

        # Determine risk level from score magnitude and confidence
        abs_score = abs(result.score)
        if abs_score >= 40 and result.confidence >= 65:
            risk_level = "low"  # Strong conviction = lower risk
        elif abs_score <= 15 or result.confidence < 40:
            risk_level = "high"  # Weak signal = higher risk
        else:
            risk_level = "medium"

        # Determine bias
        if result.signal in ("BUY", "WEAK_BUY"):
            bias = "bullish"
        elif result.signal in ("SELL", "WEAK_SELL"):
            bias = "bearish"
        else:
            bias = "neutral"

        # Build trade plan from result
        trade_plan = None
        if result.trade_plan and isinstance(result.trade_plan, dict):
            trade_plan = TradePlan(**result.trade_plan)

        item = OpportunityItem(
            symbol=sym,
            pair=pair,
            signal=result.signal,
            label=result.label,
            score=result.score,
            confidence=result.confidence,
            change24h=change_rate,
            volume24h=vol_value,
            last=last_price,
            keyReasons=result.reasons[:3],
            tradePlan=trade_plan,
            riskLevel=risk_level,
            bias=bias,
            marketState="uncertain",
        )
        return item, None

    except Exception as e:
        logger.warning("Opportunity scan failed for %s: %s", sym, e)
        return None, f"{sym}: {e!s}"


async def _noop(value: Any) -> Any:
    """Async noop helper that returns a value."""
    return value


# ---------------------------------------------------------------------------
# Market overview generation
# ---------------------------------------------------------------------------
def _build_market_overview(items: List[OpportunityItem], total_scanned: int) -> str:
    """Generate a brief market overview summary from scan results."""
    if not items:
        return "暂无足够数据生成市场概览。"

    buy_count = sum(1 for i in items if i.signal in ("BUY", "WEAK_BUY"))
    sell_count = sum(1 for i in items if i.signal in ("SELL", "WEAK_SELL"))
    neutral_count = sum(1 for i in items if i.signal == "NEUTRAL")

    # Overall market sentiment
    if buy_count > sell_count * 2:
        sentiment = "整体偏多"
    elif sell_count > buy_count * 2:
        sentiment = "整体偏空"
    elif buy_count > sell_count:
        sentiment = "偏多但分化"
    elif sell_count > buy_count:
        sentiment = "偏空但存在结构性机会"
    else:
        sentiment = "方向不明，以震荡为主"

    # Top opportunities
    top3 = items[:3]
    top_desc = "、".join(
        f"{i.symbol}({i.label}, 得分{i.score:.0f})"
        for i in top3
    )

    # Volume leaders
    vol_sorted = sorted(items, key=lambda x: x.volume24h, reverse=True)[:3]
    vol_desc = "、".join(f"{i.symbol}" for i in vol_sorted)

    # Average change
    changes = [i.change24h for i in items if i.change24h != 0]
    avg_change = sum(changes) / len(changes) * 100 if changes else 0

    parts = [
        f"扫描 {total_scanned} 个币种，市场{sentiment}。",
        f"多头信号 {buy_count} 个，空头信号 {sell_count} 个，中性 {neutral_count} 个。",
        f"综合得分最高：{top_desc}。" if top_desc else "",
        f"成交额领先：{vol_desc}。" if vol_desc else "",
        f"平均 24h 涨跌: {avg_change:+.2f}%。" if changes else "",
    ]
    return "".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
async def scan_opportunities(
    symbols: Optional[List[str]] = None,
    top_k: int = DEFAULT_TOP_K,
    min_volume: float = MIN_VOLUME_DEFAULT,
    use_valuescan: bool = True,
    max_symbols: int = MAX_SYMBOLS,
) -> OpportunityScanResult:
    """
    Scan multiple symbols for trading opportunities.

    Args:
        symbols: Explicit list of base symbols (e.g. ["BTC", "ETH"]).
                 If None, auto-fetches top tickers by volume.
        top_k: Return top-K results by score.
        min_volume: Minimum 24h volume in USDT to include.
        use_valuescan: Whether to fetch ValueScan data per symbol.
        max_symbols: Maximum symbols to scan.

    Returns:
        OpportunityScanResult with ranked opportunities.
    """
    t0 = time.time()
    errors: List[str] = []

    # 1. Resolve candidate list
    ticker_map: Dict[str, Dict[str, Any]] = {}
    if symbols:
        # User-specified symbols
        candidates = [
            (s.upper().replace("-USDT", ""), f"{s.upper().replace('-USDT', '')}-USDT")
            for s in symbols[:max_symbols]
        ]
    else:
        # Auto-discover from KuCoin tickers
        try:
            tickers = await _fetch_top_tickers(
                limit=min(max_symbols, MAX_SYMBOLS),
                min_volume=min_volume,
            )
            candidates = []
            for t in tickers:
                sym_pair = t.get("symbol", "")
                base = _extract_symbol(sym_pair)
                if base:
                    candidates.append((base, sym_pair))
                    ticker_map[base] = t
        except Exception as e:
            logger.exception("Failed to fetch tickers for opportunity scan")
            return OpportunityScanResult(
                scanTime=datetime.now(timezone.utc).isoformat(),
                errors=[f"Failed to fetch tickers: {e!s}"],
                scanDurationMs=int((time.time() - t0) * 1000),
            )

    if not candidates:
        return OpportunityScanResult(
            scanTime=datetime.now(timezone.utc).isoformat(),
            errors=["No candidate symbols found"],
            scanDurationMs=int((time.time() - t0) * 1000),
        )

    total_scanned = len(candidates)
    logger.info("Opportunity scan: %d candidates, topK=%d, vs=%s", total_scanned, top_k, use_valuescan)

    # 2. Parallel analysis with concurrency limit
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    async def _limited_analyze(sym: str, pair: str) -> Tuple[Optional[OpportunityItem], Optional[str]]:
        async with semaphore:
            return await _analyze_single_symbol(
                sym, pair,
                ticker_data=ticker_map.get(sym),
                use_valuescan=use_valuescan,
            )

    tasks = [_limited_analyze(sym, pair) for sym, pair in candidates]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 3. Collect results
    items: List[OpportunityItem] = []
    for r in results:
        if isinstance(r, Exception):
            errors.append(str(r))
            continue
        item, err = r
        if err:
            errors.append(err)
        if item:
            items.append(item)

    # 4. Sort by absolute score (best opportunities first), then by confidence
    items.sort(key=lambda x: (abs(x.score), x.confidence), reverse=True)

    # 5. Assign ranks and take top-K
    for i, item in enumerate(items):
        item.rank = i + 1
    top_items = items[:top_k]

    # 6. Generate market overview
    overview = _build_market_overview(items, total_scanned)

    scan_ms = int((time.time() - t0) * 1000)
    logger.info(
        "Opportunity scan completed: %d/%d symbols, %d opportunities, %dms",
        len(items), total_scanned, len(top_items), scan_ms,
    )

    return OpportunityScanResult(
        scanTime=datetime.now(timezone.utc).isoformat(),
        totalScanned=total_scanned,
        topK=top_k,
        opportunities=top_items,
        marketOverview=overview,
        scanDurationMs=scan_ms,
        engine="rule",
        errors=errors[:10],  # Cap error list
    )