"""tests/factors/ 共享 fixtures。"""

from __future__ import annotations

import copy
import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src")))

import numpy as np
import pytest

from factors.context import FactorContext
from factors.enums import (
    DataGranularity,
    FactorCategory,
    FactorTier,
    MarketType,
    SignalDirection,
)
from factors.models import (
    DecisionTrace,
    EvidenceLink,
    FactorMeta,
    FactorResult,
    KlineFrame,
    KlineSnapshot,
)


# ---------------------------------------------------------------------------
# 轻量级假数据对象（模拟 ValueScan API 返回的模型）
# ---------------------------------------------------------------------------


@dataclass
class FakeWhaleCostItem:
    cost: float = 100.0
    price: float = 95.0
    balance: float = 1_000_000.0
    timestamp: int = 1717200000


@dataclass
class FakeTradeDataItem:
    time_particle_enum: int = 101  # H1
    trade_inflow: float = 500_000.0
    total_trade: float = 2_000_000.0
    trade_inflow_change: float = -100_000.0
    trade_in: float = 800_000.0
    trade_out: float = 1_200_000.0
    trade_in_number: int = 150
    trade_out_number: int = 200
    trade_amount: float = 5_000_000.0


@dataclass
class FakeFundSnapshot:
    time_particle_enum: int = 124  # H24
    trade_inflow: float = 1_200_000.0
    total_trade: float = 8_000_000.0
    spot_goods_list: List[FakeTradeDataItem] | None = None
    contract_list: List[FakeTradeDataItem] | None = None


@dataclass
class FakeRealtimeFund:
    """Mock realtime_fund as a single object with goods lists (not a list)."""
    spot_goods_list: List[FakeTradeDataItem] = None
    contract_list: List[FakeTradeDataItem] = None
    spot_max_inflow: float = 10_000_000.0
    contract_max_inflow: float = 8_000_000.0

    def __post_init__(self):
        if self.spot_goods_list is None:
            self.spot_goods_list = [
                FakeTradeDataItem(time_particle_enum=5, trade_inflow=50_000.0),
                FakeTradeDataItem(time_particle_enum=15, trade_inflow=100_000.0),
                FakeTradeDataItem(time_particle_enum=101, trade_inflow=500_000.0),
                FakeTradeDataItem(time_particle_enum=124, trade_inflow=1_200_000.0),
            ]
        if self.contract_list is None:
            self.contract_list = [
                FakeTradeDataItem(time_particle_enum=5, trade_inflow=30_000.0),
                FakeTradeDataItem(time_particle_enum=15, trade_inflow=80_000.0),
                FakeTradeDataItem(time_particle_enum=101, trade_inflow=400_000.0),
                FakeTradeDataItem(time_particle_enum=124, trade_inflow=900_000.0),
            ]


@dataclass
class FakeAIOpportunity:
    deviation: float = -8.5
    grade: int = 2
    score: float = 72.0
    score_change: float = 3.5
    fomo: bool = False
    fomo_escalation: bool = False
    alpha: bool = True
    gains: int = 65
    declines: int = 35
    active: int = 5000
    newly: int = 200
    trade_type: int = 1
    reason: str = "AI opportunity detected"
    price_market_type: int = 1


@dataclass
class FakeSentimentItem:
    bullish_ratio: float = 0.62
    bearish_ratio: float = 0.38
    total_mentions: int = 1500


@dataclass
class FakeSocialContentItem:
    content_type: str = "news"
    sentiment: str = "positive"
    timestamp: int = 1717200000


@dataclass
class FakeLargeTransactionItem:
    amount_usd: float = 5_000_000.0
    count: int = 12
    direction: str = "in"


@dataclass
class FakeAddressActivityItem:
    active_addresses: int = 5000
    new_addresses: int = 200
    timestamp: int = 1717200000


@dataclass
class FakeHolderLabelItem:
    label: str = "whale"
    balance: float = 1_000_000.0
    percentage: float = 0.05


@dataclass
class FakeSectorItem:
    sector_name: str = "DeFi"
    rank: int = 3
    total_sectors: int = 20
    rotation_index: float = 0.15


@dataclass
class FakeGainsDeclinesItem:
    gains: int = 72
    declines: int = 28


@dataclass
class FakePriceIndicator:
    price: float = 95.0
    change_24h: float = -2.3
    high_24h: float = 98.0
    low_24h: float = 93.0
    volume_24h: float = 50_000_000.0
    market_cap: float = 1_000_000_000.0


@dataclass
class FakeMarketCapRatioItem:
    time_particle_enum: int = 124
    trade_inflow: float = 800_000.0
    market_cap: float = 1_000_000_000.0


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_test_kline_snapshot() -> KlineSnapshot:
    """Create a minimal KlineSnapshot for contract context testing."""
    np.random.seed(99)
    n = 60
    close = 100.0 * np.cumprod(1.0 + np.random.normal(0.001, 0.02, n))
    high = close * 1.01
    low = close * 0.99
    volume = np.ones(n) * 100
    tf_1h = KlineFrame(close=close, high=high, low=low, volume=volume)
    tf_1d = KlineFrame(close=close[:5], high=high[:5], low=low[:5], volume=volume[:5])
    return KlineSnapshot(tf_1h=tf_1h, tf_1d=tf_1d)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def spot_ctx() -> FactorContext:
    """标准现货上下文，包含所有主要数据源。"""
    return FactorContext(
        vs_token_id="token_btc_001",
        symbol="BTC",
        coin_key="bitcoin",
        fetched_at_ms=1717200000000,
        has_spot=True,
        has_contract=False,
        current_price=95.0,
        market_cap=1_000_000_000.0,
        market_type=MarketType.SPOT,
        data={
            "whale_cost": [
                FakeWhaleCostItem(cost=100.0, price=95.0, balance=1_000_000.0),
                FakeWhaleCostItem(cost=98.0, price=94.0, balance=1_100_000.0),
                FakeWhaleCostItem(cost=96.0, price=93.0, balance=1_200_000.0),
                FakeWhaleCostItem(cost=95.0, price=92.0, balance=1_300_000.0),
                FakeWhaleCostItem(cost=93.0, price=91.0, balance=1_400_000.0),
            ],
            "realtime_fund": FakeRealtimeFund(),
            "token_flow": type("FakeTokenFlow", (), {
                "items": [
                    FakeTradeDataItem(time_particle_enum=5, trade_inflow=50_000.0),
                ]
            })(),
            "fund_snapshot": FakeFundSnapshot(
                time_particle_enum=124,
                trade_inflow=1_200_000.0,
                spot_goods_list=[
                    FakeTradeDataItem(time_particle_enum=5, trade_inflow=50_000.0),
                    FakeTradeDataItem(time_particle_enum=15, trade_inflow=100_000.0),
                    FakeTradeDataItem(time_particle_enum=101, trade_inflow=500_000.0),
                ],
            ),
            "market_cap_ratio": type("FakeMCR", (), {
                "spot_market_cap_ratio": -0.008,
                "contract_market_cap_ratio": -0.005,
            })(),
            "ai_chance": FakeAIOpportunity(deviation=-8.5, grade=2, score=72.0, score_change=3.5, alpha=True),
            "ai_risk": FakeAIOpportunity(alpha=False),
            "ai_funds": FakeAIOpportunity(alpha=False),
            "social_sentiment": FakeSentimentItem(bullish_ratio=0.62, bearish_ratio=0.38),
            "social_content": [FakeSocialContentItem()],
            "large_transactions": [FakeLargeTransactionItem()],
            "address_activity": [FakeAddressActivityItem()],
            "holder_list": [FakeHolderLabelItem()],
            "sector_data": [FakeSectorItem()],
            "gains_declines": FakeGainsDeclinesItem(),
            "price_indicators": [FakePriceIndicator()],
        },
    )


@pytest.fixture
def contract_ctx() -> FactorContext:
    """标准合约上下文。"""
    return FactorContext(
        vs_token_id="token_btc_001",
        symbol="BTC",
        coin_key="bitcoin",
        fetched_at_ms=1717200000000,
        has_spot=False,
        has_contract=True,
        current_price=95.0,
        market_cap=1_000_000_000.0,
        market_type=MarketType.CONTRACT,
        data={
            "whale_cost": [
                FakeWhaleCostItem(cost=100.0, price=95.0, balance=1_000_000.0),
                FakeWhaleCostItem(cost=98.0, price=94.0, balance=1_100_000.0),
            ],
            "realtime_fund": FakeRealtimeFund(),
            "token_flow": type("FakeTokenFlow", (), {
                "items": [
                    FakeTradeDataItem(time_particle_enum=5, trade_inflow=30_000.0),
                ]
            })(),
            "fund_snapshot": FakeFundSnapshot(
                time_particle_enum=124,
                trade_inflow=1_200_000.0,
                contract_list=[
                    FakeTradeDataItem(time_particle_enum=5, trade_inflow=50_000.0),
                    FakeTradeDataItem(time_particle_enum=15, trade_inflow=100_000.0),
                    FakeTradeDataItem(time_particle_enum=101, trade_inflow=500_000.0),
                ],
            ),
            "market_cap_ratio": type("FakeMCR", (), {
                "spot_market_cap_ratio": -0.005,
                "contract_market_cap_ratio": -0.008,
            })(),
            "ai_chance": FakeAIOpportunity(),
            "ai_risk": FakeAIOpportunity(alpha=False),
            "ai_funds": FakeAIOpportunity(alpha=False),
            "social_sentiment": FakeSentimentItem(),
            "large_transactions": [FakeLargeTransactionItem()],
            "address_activity": [FakeAddressActivityItem()],
            "holder_list": [FakeHolderLabelItem()],
            "sector_data": [FakeSectorItem()],
            "gains_declines": FakeGainsDeclinesItem(),
            "price_indicators": [FakePriceIndicator()],
            "kline": _make_test_kline_snapshot(),  # 合约 OI 因子需要
            "funding_rate": [0.0001, 0.00015, 0.0002, 0.0001, -0.00005],
            "open_interest": [100_000_000.0, 105_000_000.0, 110_000_000.0, 108_000_000.0, 112_000_000.0],
        },
    )


@pytest.fixture
def empty_ctx() -> FactorContext:
    """空上下文，用于测试无数据时的优雅降级。"""
    return FactorContext(
        vs_token_id="token_empty",
        symbol="EMPTY",
        coin_key="empty",
        fetched_at_ms=1717200000000,
        has_spot=False,
        has_contract=False,
        current_price=0.0,
        market_type=MarketType.SPOT,
        data={},
    )


@pytest.fixture
def kline_frame_1h() -> KlineFrame:
    """标准 1h K线帧 — 50 根看涨 K线。"""
    np.random.seed(42)
    n = 50
    close = 100.0 * np.cumprod(1.0 + np.random.normal(0.001, 0.02, n))
    high = close * (1.0 + np.abs(np.random.normal(0, 0.01, n)))
    low = close * (1.0 - np.abs(np.random.normal(0, 0.01, n)))
    volume = np.random.uniform(100, 1000, n)
    return KlineFrame(close=close, high=high, low=low, volume=volume)


@pytest.fixture
def kline_frame_1d() -> KlineFrame:
    """标准 1d K线帧 — 200 根数据。"""
    np.random.seed(123)
    n = 200
    close = 100.0 * np.cumprod(1.0 + np.random.normal(0.0005, 0.03, n))
    high = close * (1.0 + np.abs(np.random.normal(0, 0.015, n)))
    low = close * (1.0 - np.abs(np.random.normal(0, 0.015, n)))
    volume = np.random.uniform(500, 5000, n)
    return KlineFrame(close=close, high=high, low=low, volume=volume)


@pytest.fixture
def kline_snapshot(kline_frame_1h, kline_frame_1d) -> KlineSnapshot:
    """完整 K线快照（1h + 1d）。"""
    return KlineSnapshot(tf_1h=kline_frame_1h, tf_1d=kline_frame_1d)


@pytest.fixture
def sample_evidence() -> EvidenceLink:
    return EvidenceLink(
        data_point="偏离度=-8.5%",
        interpretation="价格低于主力成本",
        implication="主力可能护盘或吸筹，利好上涨",
        confidence=0.85,
    )


@pytest.fixture
def sample_trace() -> DecisionTrace:
    return DecisionTrace(
        factor_name="test_factor",
        raw_inputs={"price": 95.0, "cost": 100.0},
        evidence_chain=[
            EvidenceLink(
                data_point="价格=95, 成本=100",
                interpretation="价格低于成本",
                implication="看涨",
                confidence=0.8,
            )
        ],
        conclusion="偏多信号",
        suggested_action="考虑买入",
        limitations=["数据可能滞后"],
        counter_argument="主力可能已离场",
    )


@pytest.fixture
def sample_result(sample_trace) -> FactorResult:
    return FactorResult(
        factor_name="test_factor",
        factor_index=1,
        factor_tier=FactorTier.TIER_1,
        category=FactorCategory.WHALE_COST,
        display_name="测试因子",
        signal_direction=SignalDirection.BULLISH,
        normalized_score=0.6,
        raw_value=-8.5,
        confidence=0.85,
        data_freshness_ms=0,
        data_completeness=1.0,
        weight=7.0,
        trace=sample_trace,
    )
