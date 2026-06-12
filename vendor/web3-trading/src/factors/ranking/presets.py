"""内置排名配置文件 — 基于 docs/因子分析/核心因子/ 的排序。

现货默认配置：侧重持仓趋势、成本偏离、大额转账
合约默认配置：侧重情绪指标、FOMO、Alpha
"""

from ..enums import FactorTier, MarketType
from .profile import FactorEntry, RankingProfile

# ── 现货 Tier → 权重映射 ─────────────────────────────────────────
# 现货侧重：资金流向和链上筹码是核心驱动力，社媒情绪为噪音。
# 相邻 Tier 比率: T2/T1=0.57, T3/T2=0.50, T4/T3=0.50, T5/T4=0.40
_SPOT_TIER_WEIGHT = {
    FactorTier.TIER_1: 7.0,   # 7因子 → 49.0
    FactorTier.TIER_2: 4.0,   # 7因子 → 28.0
    FactorTier.TIER_3: 2.0,   # 7因子 → 14.0
    FactorTier.TIER_4: 1.0,   # 5因子 →  5.0
    FactorTier.TIER_5: 0.4,   # 5因子 →  2.0
}

# ── 合约 Tier → 权重映射 ─────────────────────────────────────────
# 合约侧重：情绪、FOMO、多维度验证，短周期下 T3/T4/T5 权重提升。
# 相邻 Tier 比率: T2/T1=0.67, T3/T2=0.60, T4/T3=0.54, T5/T4=0.38
_CONTRACT_TIER_WEIGHT = {
    FactorTier.TIER_1: 6.0,   # 7因子 → 42.0
    FactorTier.TIER_2: 4.0,   # 6因子 → 24.0
    FactorTier.TIER_3: 2.4,   # 7因子 → 16.8
    FactorTier.TIER_4: 1.3,   # 5因子 →  6.5
    FactorTier.TIER_5: 0.5,   # 6因子 →  3.0
}


def _build_factors(
    entries: list[tuple[str, FactorTier]],
    tier_weight: dict[FactorTier, float],
) -> list[FactorEntry]:
    """根据列表顺序自动分配 rank（从 1 开始），权重由 tier 和 market 决定。"""
    return [
        FactorEntry(factor_name=name, rank=i, weight=tier_weight[tier], tier=tier)
        for i, (name, tier) in enumerate(entries, start=1)
    ]


# ═══════════════════════════════════════════════════════════════════
# 现货默认排序（31 项）
# 来源：docs/因子分析/核心因子/现货因子.md
# ═══════════════════════════════════════════════════════════════════

SPOT_DEFAULT_PROFILE = RankingProfile(
    profile_id="spot_default",
    market_type=MarketType.SPOT,
    description="现货交易默认因子排序 — 侧重持仓趋势、成本偏离、长期资金行为",
    factors=_build_factors([
        # Tier 1 — 核心（7项）
        ("spot_consistency", FactorTier.TIER_1),
        ("spot_trade_inflow", FactorTier.TIER_1),
        ("deviation", FactorTier.TIER_1),
        ("balance_trend", FactorTier.TIER_1),
        ("spot_market_cap_ratio", FactorTier.TIER_1),
        ("score_and_change", FactorTier.TIER_1),
        ("trade_inflow_change", FactorTier.TIER_1),
        # Tier 2 — 强辅助（7项）
        ("large_transactions", FactorTier.TIER_2),
        ("spot_max_inflow", FactorTier.TIER_2),
        ("sector_rank", FactorTier.TIER_2),
        ("coin_sector_rank", FactorTier.TIER_2),
        ("trade_ratio", FactorTier.TIER_2),
        ("alpha", FactorTier.TIER_2),
        ("sentiment_ratio", FactorTier.TIER_2),
        # Tier 3 — 上下文（7项）
        ("balance_price_divergence", FactorTier.TIER_3),
        ("spot_contract_divergence", FactorTier.TIER_3),
        ("spot_fund_snapshot", FactorTier.TIER_3),
        ("address_pnl", FactorTier.TIER_3),
        ("grade", FactorTier.TIER_3),
        ("fomo", FactorTier.TIER_3),
        ("gains_declines", FactorTier.TIER_3),
        # Tier 4 — 验证（5项）
        ("price_market_type", FactorTier.TIER_4),
        ("spot_persistence", FactorTier.TIER_4),
        ("rotation_speed", FactorTier.TIER_4),
        ("address_activity", FactorTier.TIER_4),
        ("trade_count", FactorTier.TIER_4),
        # Tier 5 — 元数据/辅助（5项）
        ("trade_amount", FactorTier.TIER_5),
        ("social_content", FactorTier.TIER_5),
        ("message_types", FactorTier.TIER_5),
        ("holder_labels", FactorTier.TIER_5),
        ("identifiers", FactorTier.TIER_5),
        # ── K线技术面因子（10项）────────────────────────────────
        ("trend_strength", FactorTier.TIER_1),
        ("macd_divergence", FactorTier.TIER_1),
        ("momentum_resonance", FactorTier.TIER_1),
        ("multi_tf_return", FactorTier.TIER_2),
        ("volatility", FactorTier.TIER_2),
        ("volume_price_divergence", FactorTier.TIER_2),
        ("rsi_extreme", FactorTier.TIER_2),
        ("bollinger_breakout", FactorTier.TIER_2),
        ("vwap_deviation", FactorTier.TIER_3),
        ("atr_normalized", FactorTier.TIER_4),
    ], _SPOT_TIER_WEIGHT),
)


# ═══════════════════════════════════════════════════════════════════
# 合约默认排序（31 项）
# 来源：docs/因子分析/核心因子/合约因子.md
# ═══════════════════════════════════════════════════════════════════

CONTRACT_DEFAULT_PROFILE = RankingProfile(
    profile_id="contract_default",
    market_type=MarketType.CONTRACT,
    description="合约交易默认因子排序 — 侧重情绪指标、FOMO、资金博弈加速度",
    factors=_build_factors([
        # Tier 1 — 核心（7项）
        ("contract_consistency", FactorTier.TIER_1),
        ("contract_trade_inflow", FactorTier.TIER_1),
        ("score_and_change", FactorTier.TIER_1),
        ("trade_inflow_change", FactorTier.TIER_1),
        ("fomo", FactorTier.TIER_1),
        ("deviation", FactorTier.TIER_1),
        ("contract_market_cap_ratio", FactorTier.TIER_1),
        # Tier 2 — 强辅助（6项）
        ("sentiment_ratio", FactorTier.TIER_2),
        ("alpha", FactorTier.TIER_2),
        ("contract_max_inflow", FactorTier.TIER_2),
        ("spot_contract_divergence", FactorTier.TIER_2),
        ("sector_rank", FactorTier.TIER_2),
        ("coin_sector_rank", FactorTier.TIER_2),
        # Tier 3 — 上下文（7项）
        ("trade_ratio", FactorTier.TIER_3),
        ("grade", FactorTier.TIER_3),
        ("contract_fund_snapshot", FactorTier.TIER_3),
        ("gains_declines", FactorTier.TIER_3),
        ("rotation_speed", FactorTier.TIER_3),
        ("balance_trend", FactorTier.TIER_3),
        ("large_transactions", FactorTier.TIER_3),
        # Tier 4 — 验证（5项）
        ("contract_persistence", FactorTier.TIER_4),
        ("price_market_type", FactorTier.TIER_4),
        ("address_pnl", FactorTier.TIER_4),
        ("balance_price_divergence", FactorTier.TIER_4),
        ("address_activity", FactorTier.TIER_4),
        # Tier 5 — 元数据/辅助（6项）
        ("trade_count", FactorTier.TIER_5),
        ("trade_amount", FactorTier.TIER_5),
        ("social_content", FactorTier.TIER_5),
        ("message_types", FactorTier.TIER_5),
        ("holder_labels", FactorTier.TIER_5),
        ("identifiers", FactorTier.TIER_5),
        # ── K线技术面因子（13项）────────────────────────────────
        ("momentum_resonance", FactorTier.TIER_1),
        ("funding_rate_zscore", FactorTier.TIER_1),
        ("macd_divergence", FactorTier.TIER_1),
        ("trend_strength", FactorTier.TIER_1),
        ("rsi_extreme", FactorTier.TIER_2),
        ("oi_change_rate", FactorTier.TIER_2),
        ("volatility", FactorTier.TIER_2),
        ("volume_price_divergence", FactorTier.TIER_2),
        ("bollinger_breakout", FactorTier.TIER_2),
        ("multi_tf_return", FactorTier.TIER_2),
        ("long_short_extreme", FactorTier.TIER_3),
        ("vwap_deviation", FactorTier.TIER_3),
        ("atr_normalized", FactorTier.TIER_4),
    ], _CONTRACT_TIER_WEIGHT),
)
