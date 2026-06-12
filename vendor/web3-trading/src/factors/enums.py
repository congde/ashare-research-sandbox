"""因子计算层的领域枚举。"""

from enum import IntEnum, StrEnum


class FactorTier(StrEnum):
    """因子重要层级 — 驱动默认权重和管线筛选。"""

    TIER_1 = "tier_1"  # 核心 — 策略收益的主要驱动力
    TIER_2 = "tier_2"  # 强辅助 — 确认/否定 Tier 1 信号
    TIER_3 = "tier_3"  # 上下文 — 在特定市场状态下提供增量价值
    TIER_4 = "tier_4"  # 验证 — 过滤噪音、拒绝虚假信号
    TIER_5 = "tier_5"  # 元数据 — 数据质量标记，无直接信号


class SignalDirection(StrEnum):
    """因子计算输出的方向性信号。"""

    STRONG_BULLISH = "strong_bullish"
    BULLISH = "bullish"
    NEUTRAL_BULLISH = "neutral_bullish"
    NEUTRAL = "neutral"
    NEUTRAL_BEARISH = "neutral_bearish"
    BEARISH = "bearish"
    STRONG_BEARISH = "strong_bearish"
    INCONCLUSIVE = "inconclusive"


class FactorCategory(StrEnum):
    """因子的数据来源分类。"""

    FUND_FLOW = "fund_flow"
    WHALE_COST = "whale_cost"
    AI_COMPOSITE = "ai_composite"
    ONCHAIN = "onchain"
    SOCIAL = "social"
    MARKET_STRUCTURE = "market_structure"
    SECTOR = "sector"
    TECHNICAL = "technical"
    DERIVATIVES = "derivatives"
    META = "meta"


class DataGranularity(StrEnum):
    """源数据的时间粒度。"""

    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H2 = "2h"
    H4 = "4h"
    H8 = "8h"
    H12 = "12h"
    H24 = "24h"
    D2 = "2d"
    D3 = "3d"
    D7 = "7d"
    D10 = "10d"
    D15 = "15d"
    D30 = "30d"
    D60 = "60d"
    D90 = "90d"
    D120 = "120d"
    D180 = "180d"
    Y1 = "1y"
    Y2 = "2y"
    Y3 = "3y"


class GranularityWeight(IntEnum):
    """多粒度因子中各粒度的默认权重系数。"""

    M5 = 0.5
    M15 = 0.5
    M30 = 0.6
    H1 = 0.8
    H6 = 1.0
    H24 = 1.5
    D3 = 1.2
    D7 = 1.0
    D90 = 0.8


class MarketType(StrEnum):
    """因子计算的目标市场 — 现货 vs 合约（永续）。"""

    SPOT = "spot"
    CONTRACT = "contract"
