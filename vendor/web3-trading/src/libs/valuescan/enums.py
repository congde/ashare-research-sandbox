# -*- coding: utf-8 -*-
"""ValueScan enum definitions.

All finite string domains are modelled as StrEnum to enforce type safety
and prevent raw-string bugs at system boundaries.
"""

from __future__ import annotations

from enum import StrEnum


class BucketType(StrEnum):
    """K-line time window — seconds, minutes, hours, days, weeks, months."""

    SECOND = "1s"
    MINUTE_1 = "1m"
    MINUTE_5 = "5m"
    MINUTE_15 = "15m"
    MINUTE_30 = "30m"
    HOUR_1 = "1h"
    HOUR_4 = "4h"
    HOUR_12 = "12h"
    DAY_1 = "1d"
    WEEK_1 = "1w"
    MONTH_1 = "1M"


class KlineType(StrEnum):
    """K-line data source — identifies the exchange origin."""

    BINANCE_SPOT = "binance_spot"
    BINANCE_FUTURES = "binance_futures"
    KUCOIN_SPOT = "kucoin_spot"
    KUCOIN_FUTURES = "kucoin_futures"


class TimeParticleEnum(StrEnum):
    """Time-granularity enum used by coin-trade-flow endpoints.

    Values map to integer codes used by the API.
    """

    H1 = "101"
    H2 = "102"
    H4 = "104"
    M5 = "5"
    M15 = "15"
    M30 = "30"
    H24 = "124"


class PriceMarketType(StrEnum):
    """Price trend direction returned by getPriceMarketList."""

    UP = "1"
    DOWN = "2"


class TradeType(StrEnum):
    """Trade type — spot or futures/contract."""

    SPOT = "1"
    FUTURES = "2"


class FundsMovementType(StrEnum):
    """Funds movement classification."""

    INFLOW = "in"
    OUTFLOW = "out"
    NET = "net"
