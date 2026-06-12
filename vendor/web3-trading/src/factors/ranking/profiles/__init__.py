# -*- coding: utf-8 -*-
"""市场状态自适应权重预设。

每种市场状态下，各因子有一个 bias_multiplier（权重乘数）：
- TRENDING: 技术面因子更有效，×1.5
- RANGING: 资金流/AI 合成因子更有效，×1.3/×1.2
- HIGH_VOL: 恐慌/FOMO 类因子权重提升，全局降权 ×0.8
- LOW_VOL: 突破类因子权重提升，×1.3
"""

from __future__ import annotations

from factors.analysis.models import MarketState, StateProfile, StateWeightBias
from factors.enums import FactorCategory, MarketType
from factors.ranking.profile import RankingProfile
from factors.ranking.presets import CONTRACT_DEFAULT_PROFILE, SPOT_DEFAULT_PROFILE

# ── 因子分类 → 状态偏置映射 ───────────────────────────────────────────

_STATE_CATEGORY_BIASES: dict[MarketState, list[tuple[FactorCategory, float]]] = {
    MarketState.TRENDING_UP: [
        (FactorCategory.TECHNICAL, 1.5),
    ],
    MarketState.TRENDING_DOWN: [
        (FactorCategory.TECHNICAL, 1.5),
    ],
    MarketState.RANGING: [
        (FactorCategory.FUND_FLOW, 1.3),
        (FactorCategory.AI_COMPOSITE, 1.2),
        (FactorCategory.SOCIAL, 1.2),
    ],
    MarketState.HIGH_VOL: [
        (FactorCategory.AI_COMPOSITE, 1.5),
        (FactorCategory.SOCIAL, 1.5),
        (FactorCategory.FUND_FLOW, 0.8),
        (FactorCategory.TECHNICAL, 0.8),
    ],
    MarketState.LOW_VOL: [
        (FactorCategory.TECHNICAL, 1.3),
        (FactorCategory.FUND_FLOW, 1.1),
    ],
}

# ── 因子名称 → 分类推断 ──────────────────────────────────────────────

_TECHNICAL_NAMES = {
    "trend_strength", "macd_divergence", "momentum_resonance",
    "multi_tf_return", "volatility", "volume_price_divergence",
    "rsi_extreme", "bollinger_breakout", "vwap_deviation", "atr_normalized",
}

_FUND_FLOW_NAMES = {
    "spot_consistency", "spot_trade_inflow", "spot_market_cap_ratio",
    "spot_max_inflow", "spot_persistence", "spot_fund_snapshot",
    "contract_consistency", "contract_trade_inflow", "contract_market_cap_ratio",
    "contract_max_inflow", "contract_persistence", "contract_fund_snapshot",
    "trade_inflow_change", "trade_ratio", "trade_amount",
    "spot_contract_divergence",
}

_AI_NAMES = {"alpha", "fomo", "grade", "gains_declines", "score_and_change", "message_types"}
_ONCHAIN_NAMES = {
    "deviation", "balance_trend", "balance_price_divergence",
    "large_transactions", "address_pnl", "address_activity", "trade_count",
}
_SOCIAL_NAMES = {"sentiment_ratio", "social_content"}
_DERIVATIVES_NAMES = {"funding_rate_zscore", "long_short_extreme", "oi_change_rate"}
_SECTOR_NAMES = {"sector_rank", "coin_sector_rank", "rotation_speed"}
_MARKET_NAMES = {"price_market_type"}


def _factor_name_to_category(factor_name: str) -> FactorCategory:
    if factor_name in _TECHNICAL_NAMES:
        return FactorCategory.TECHNICAL
    if factor_name in _FUND_FLOW_NAMES:
        return FactorCategory.FUND_FLOW
    if factor_name in _AI_NAMES:
        return FactorCategory.AI_COMPOSITE
    if factor_name in _ONCHAIN_NAMES:
        return FactorCategory.ONCHAIN
    if factor_name in _SOCIAL_NAMES:
        return FactorCategory.SOCIAL
    if factor_name in _DERIVATIVES_NAMES:
        return FactorCategory.DERIVATIVES
    if factor_name in _SECTOR_NAMES:
        return FactorCategory.SECTOR
    if factor_name in _MARKET_NAMES:
        return FactorCategory.MARKET_STRUCTURE
    return FactorCategory.META


def _get_base_profile(market_type: MarketType) -> RankingProfile:
    if market_type == MarketType.CONTRACT:
        return CONTRACT_DEFAULT_PROFILE
    return SPOT_DEFAULT_PROFILE


def build_state_profile(state: MarketState, market_type: MarketType = MarketType.SPOT) -> StateProfile:
    """为给定市场状态和类型构建 StateProfile。

    从默认 RankingProfile 中读取因子列表和基线权重，
    按状态规则应用 category-level 的 bias_multiplier。
    """
    base = _get_base_profile(market_type)
    category_biases = dict(_STATE_CATEGORY_BIASES.get(state, []))

    reason_map = {
        MarketState.TRENDING_UP: "趋势市场中技术面因子信噪比更高",
        MarketState.TRENDING_DOWN: "下跌趋势中技术面因子更有效",
        MarketState.RANGING: "横盘市场中资金流向更准确反映主力意图",
        MarketState.HIGH_VOL: "高波动市场中情绪类因子信号增强，全局信号降权",
        MarketState.LOW_VOL: "低波动市场中突破类因子提前发现行情启动",
    }

    biases: list[StateWeightBias] = []
    for entry in base.factors:
        cat = _factor_name_to_category(entry.factor_name)
        multiplier = category_biases.get(cat, 1.0)
        biases.append(StateWeightBias(
            factor_name=entry.factor_name,
            base_weight=entry.weight,
            bias_multiplier=multiplier,
            reason=reason_map.get(state, ""),
        ))

    return StateProfile(
        state=state,
        profile_id=f"{state.value}_{market_type.value}_v1",
        market_type=market_type,
        biases=biases,
    )
