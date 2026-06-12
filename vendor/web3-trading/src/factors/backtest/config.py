# -*- coding: utf-8 -*-
"""回测配置模型。"""

from pydantic import BaseModel, Field

from factors.enums import MarketType


class BacktestConfig(BaseModel):
    """回测参数配置。"""

    symbols: list[str] = Field(default_factory=lambda: ["BTC"], description="回测币种列表")
    market_type: MarketType = Field(default=MarketType.SPOT, description="市场类型")
    lookback_days: int = Field(default=30, ge=1, le=90, description="回看天数")
    granularity_horizon_map: dict[str, str] = Field(
        default_factory=lambda: {
            "5m": "1h",
            "15m": "4h",
            "1h": "4h",
            "4h": "1d",
            "1d": "3d",
        },
        description="因子数据粒度到评估持仓周期的映射",
    )
    min_snapshots: int = Field(default=20, ge=5, description="最少需要的快照数")
