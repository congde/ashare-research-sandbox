# -*- coding: utf-8 -*-
"""KuCoin OpenAPI Pydantic response models — K-line and derivatives only."""

from __future__ import annotations

from typing import Any, Optional, Union, get_args, get_origin, get_type_hints

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel


# ---------------------------------------------------------------------------
# Base model — identical pattern to VSBaseModel
# ---------------------------------------------------------------------------
class KCBaseModel(BaseModel):
    """Base for mutable KuCoin models.

    Provides automatic camelCase alias generation and coercion of
    empty-string / string-numeric values at the boundary.
    """

    model_config = ConfigDict(
        frozen=False, extra="ignore", populate_by_name=True,
        alias_generator=to_camel,
    )

    @model_validator(mode="before")
    @classmethod
    def _coerce_boundary_values(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        hints = get_type_hints(cls)
        for field_name, field_type in hints.items():
            keys = {field_name}
            field_info = cls.model_fields.get(field_name)
            if field_info and field_info.alias:
                keys.add(field_info.alias)
            for key in keys:
                raw = data.get(key)
                if raw is None:
                    continue
                if raw == "":
                    if cls._is_optional(field_type):
                        data[key] = None
                    elif field_type is float:
                        data[key] = 0.0
                    elif field_type is int:
                        data[key] = 0
                    continue
                if isinstance(raw, str) and field_type in (float, int):
                    try:
                        data[field_name] = field_type(raw)
                    except (ValueError, TypeError):
                        pass
        return data

    @staticmethod
    def _is_optional(tp: Any) -> bool:
        return get_origin(tp) is Union and type(None) in get_args(tp)


# ---------------------------------------------------------------------------
# K-line (candlestick)
# ---------------------------------------------------------------------------
class KlineCandle(KCBaseModel):
    """单根现货 K线数据。

    数据来源：GET /api/v1/market/candles
    KuCoin 返回格式：[time, open, close, high, low, volume, turnover]
    """

    time: int = Field(default=0, description="开盘时间（秒级时间戳）")
    open: float = Field(default=0.0, description="开盘价")
    close: float = Field(default=0.0, description="收盘价")
    high: float = Field(default=0.0, description="最高价")
    low: float = Field(default=0.0, description="最低价")
    volume: float = Field(default=0.0, description="成交量（基础币种）")
    turnover: float = Field(default=0.0, description="成交额（计价币种，USD）")


class FuturesKlineCandle(KCBaseModel):
    """单根合约 K线数据。

    数据来源：GET /api/v1/kline/query
    """

    time: int = Field(default=0, description="开盘时间（秒级时间戳）")
    open: float = Field(default=0.0, description="开盘价")
    close: float = Field(default=0.0, description="收盘价")
    high: float = Field(default=0.0, description="最高价")
    low: float = Field(default=0.0, description="最低价")
    volume: float = Field(default=0.0, description="成交量（合约张数）")
    turnover: float = Field(default=0.0, description="成交额 (USD)")


# ---------------------------------------------------------------------------
# Futures — Funding rate
# ---------------------------------------------------------------------------
class FundingRateItem(KCBaseModel):
    """资金费率历史数据项。

    数据来源：GET /api/v1/contract/funding-rates
    """

    symbol: str = Field(default="", description="合约符号")
    funding_rate: float = Field(default=0.0, description="资金费率")
    timepoint: int = Field(default=0, description="结算时间点（毫秒时间戳）")


class CurrentFundingRate(KCBaseModel):
    """当前资金费率。

    数据来源：GET /api/v1/funding-rate/{symbol}/current
    """

    symbol: str = Field(default="", description="合约符号")
    granularity: int = Field(default=0, description="结算周期（毫秒）")
    timepoint: int = Field(default=0, description="当前时间点（毫秒）")
    value: float = Field(default=0.0, description="当前资金费率")


# ---------------------------------------------------------------------------
# Futures — Open Interest
# ---------------------------------------------------------------------------
class OpenInterestStats(KCBaseModel):
    """当前总持仓量。

    数据来源：GET /api/v1/open-interest/{symbol}
    """

    symbol: str = Field(default="", description="合约符号")
    open_interest: float = Field(default=0.0, description="总持仓量（合约张数）")
    timestamp: int = Field(default=0, description="时间戳（毫秒）")
