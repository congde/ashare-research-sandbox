from __future__ import annotations

import logging

from dashboard import market, valuescan
from dashboard.persist import maybe_persist
from dashboard.valuescan_full import fetch_full_token_data, fetch_global_valuescan_data

logger = logging.getLogger(__name__)


def persist_valuescan_token_full(symbol: str) -> None:
    if not valuescan.configured():
        return
    sym = symbol.strip().upper()
    try:
        full = fetch_full_token_data(sym)
        if not full.get("vsTokenId"):
            return
        payload = {"ok": True, "source": "live", "full": True, **full}
        maybe_persist("valuescan_token_full", payload, symbol=sym)
    except Exception as exc:
        logger.warning("persist valuescan_token_full %s failed: %s", sym, exc)


def persist_valuescan_global() -> None:
    if not valuescan.configured():
        return
    try:
        payload = fetch_global_valuescan_data()
        maybe_persist("valuescan_global", payload)
    except Exception as exc:
        logger.warning("persist valuescan_global failed: %s", exc)


def persist_kucoin_markets() -> None:
    try:
        payload = market.fetch_kucoin_markets()
        maybe_persist("kucoin_markets", payload)
    except Exception as exc:
        logger.warning("persist kucoin_markets failed: %s", exc)


def persist_kucoin_bundle(quote: str = "USDT") -> None:
    """全量 tickers + markets 元数据。"""
    try:
        tickers = market.fetch_market_tickers(quote=quote, limit=None)
        maybe_persist("market_tickers", tickers)
    except Exception as exc:
        logger.warning("persist market_tickers failed: %s", exc)
    persist_kucoin_markets()
