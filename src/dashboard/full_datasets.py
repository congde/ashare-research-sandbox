from __future__ import annotations

from typing import Any

from config.web3_trading import primary_market_symbol
from dashboard import dexscan, market, opportunity, valuescan
from dashboard.valuescan_full import fetch_full_token_data, fetch_global_valuescan_data


def fetch_full_market_tickers(*, quote: str = "USDT") -> dict[str, Any]:
    return market.fetch_market_tickers(quote=quote, limit=None)


def fetch_full_dex_trending(*, chain: str = "solana") -> dict[str, Any]:
    return dexscan.get_dex_trending(chain=chain, limit=None)


def fetch_full_opportunity_scan(*, min_volume_24h: float = 200_000) -> dict[str, Any]:
    return opportunity.scan_opportunities_full(min_volume_24h=min_volume_24h)


def fetch_full_market_candles(
    symbol: str | None = None,
    *,
    kline_type: str = "1day",
) -> dict[str, Any]:
    pair = (symbol or primary_market_symbol()).strip().upper()
    return market.fetch_candles(pair, kline_type=kline_type, limit=None)


def fetch_full_kucoin_markets() -> dict[str, Any]:
    return market.fetch_kucoin_markets()


def fetch_full_valuescan_global() -> dict[str, Any]:
    return fetch_global_valuescan_data()


def fetch_full_valuescan_token(symbol: str = "BTC") -> dict[str, Any]:
    sym = symbol.strip().upper()
    full = fetch_full_token_data(sym)
    if not full.get("vsTokenId"):
        return {"ok": False, "message": f"Token {sym} not found in ValueScan", "symbol": sym}
    return {"ok": True, "source": "live", "full": True, **full}
