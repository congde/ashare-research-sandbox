# -*- coding: utf-8 -*-
"""KuCoin OpenAPI SDK — public API surface (K-line + derivatives, no-auth).

Usage::

    from libs.kucoin_openapi import KuCoinClient, KlineGranularity
    client = KuCoinClient()
    candles = await client.get_kline("BTC-USDT", KlineGranularity.H1)
    fr = await client.get_current_funding_rate("XBTUSDTM")
"""

from .client import KuCoinClient
from .enums import (
    FuturesKlineGranularity,
    KlineGranularity,
    MarketType,
)
from .exceptions import (
    KuCoinConnectionError,
    KuCoinError,
    KuCoinTimeoutError,
)
from .models import (
    CurrentFundingRate,
    FundingRateItem,
    FuturesKlineCandle,
    KlineCandle,
    OpenInterestStats,
)

__all__ = [
    # client
    "KuCoinClient",
    # enums
    "FuturesKlineGranularity",
    "KlineGranularity",
    "MarketType",
    # exceptions
    "KuCoinError",
    "KuCoinTimeoutError",
    "KuCoinConnectionError",
    # models
    "CurrentFundingRate",
    "FundingRateItem",
    "FuturesKlineCandle",
    "KlineCandle",
    "OpenInterestStats",
]
