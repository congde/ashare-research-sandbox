# -*- coding: utf-8 -*-
"""KuCoin OpenAPI enum definitions.

All finite string domains are modelled as StrEnum to enforce type safety
and prevent raw-string bugs at system boundaries.
"""

from __future__ import annotations

from enum import StrEnum


class MarketType(StrEnum):
    """Base URL selector — spot or futures."""

    SPOT = "spot"
    FUTURES = "futures"


class KlineGranularity(StrEnum):
    """Candlestick time granularity supported by KuCoin.

    Values match the ``type`` parameter of ``/api/v1/market/candles``.
    """

    M1 = "1min"
    M3 = "3min"
    M5 = "5min"
    M15 = "15min"
    M30 = "30min"
    H1 = "1hour"
    H2 = "2hour"
    H4 = "4hour"
    H6 = "6hour"
    H8 = "8hour"
    H12 = "12hour"
    D1 = "1day"
    W1 = "1week"


class FuturesKlineGranularity(StrEnum):
    """Candlestick time granularity supported by KuCoin Futures.

    Values match the ``granularity`` parameter of ``/api/v1/kline/query``.
    """

    M1 = "1"
    M5 = "5"
    M15 = "15"
    M30 = "30"
    H1 = "60"
    H2 = "120"
    H4 = "240"
    H8 = "480"
    H12 = "720"
    D1 = "1440"
    W1 = "10080"
