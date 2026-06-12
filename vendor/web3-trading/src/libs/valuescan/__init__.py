# -*- coding: utf-8 -*-
"""ValueScan SDK — public API surface.

Usage::

    from libs.valuescan import ValueScanClient, PriceMarketType
    client = ValueScanClient.from_env()
    flow = await client.get_token_flow(1)
"""

from .client import ValueScanClient, _TTLCache
from .enums import (
    BucketType,
    FundsMovementType,
    KlineType,
    PriceMarketType,
    TimeParticleEnum,
    TradeType,
)
from .exceptions import (
    ValueScanAuthError,
    ValueScanConnectionError,
    ValueScanError,
    ValueScanTimeoutError,
)
from .models import (
    AiCoinItem,
    BalanceTrendItem,
    CoinInfo,
    CoinTradeCostItem,
    CoinTradeFlowData,
    CoinTradeFlowItem,
    DenseAreaItem,
    HoldPageItem,
    KlineItem,
    LabelInfo,
    LargeTransactionItem,
    PriceMarketItem,
    ProfitLossTrendItem,
    SocialSentimentData,
    TokenDetail,
    TokenInfo,
    TradeCountTrendItem,
    VSResponse,
)

__all__ = [
    # client
    "ValueScanClient",
    "_TTLCache",
    # enums
    "BucketType",
    "FundsMovementType",
    "KlineType",
    "PriceMarketType",
    "TimeParticleEnum",
    "TradeType",
    # exceptions
    "ValueScanError",
    "ValueScanAuthError",
    "ValueScanTimeoutError",
    "ValueScanConnectionError",
    # models
    "AiCoinItem",
    "BalanceTrendItem",
    "CoinInfo",
    "CoinTradeCostItem",
    "CoinTradeFlowData",
    "CoinTradeFlowItem",
    "DenseAreaItem",
    "HoldPageItem",
    "KlineItem",
    "LabelInfo",
    "LargeTransactionItem",
    "PriceMarketItem",
    "ProfitLossTrendItem",
    "SocialSentimentData",
    "TokenDetail",
    "TokenInfo",
    "TradeCountTrendItem",
    "VSResponse",
]
