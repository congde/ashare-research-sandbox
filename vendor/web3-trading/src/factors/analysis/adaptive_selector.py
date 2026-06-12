# -*- coding: utf-8 -*-
"""自适应 Profile 选择与合成 — 按市场状态调整因子权重。"""

from __future__ import annotations

from factors.analysis.models import MarketState, MarketStateResult, StateProfile
from factors.ranking.profile import FactorEntry, RankingProfile
from factors.ranking.profiles import build_state_profile


class AdaptiveProfileSelector:
    """根据市场状态选择对应的权重配置文件。"""

    def __init__(
        self,
        base_profile: RankingProfile,
    ) -> None:
        self._base_profile = base_profile
        self._cache: dict[MarketState, StateProfile] = {}

    def get_state_profile(self, state: MarketState) -> StateProfile:
        """获取指定状态的 StateProfile（有缓存）。"""
        if state not in self._cache:
            self._cache[state] = build_state_profile(state, self._base_profile.market_type)
        return self._cache[state]

    def select(self, state_result: MarketStateResult) -> StateProfile:
        """选择主要状态对应的 StateProfile。"""
        return self.get_state_profile(state_result.state)

    def get_all_relevant_profiles(
        self, state_result: MarketStateResult,
    ) -> dict[MarketState, StateProfile]:
        """获取主状态及所有相邻状态的 profiles。"""
        states = {state_result.state}
        states.update(state_result.adjacent_states)
        return {s: self.get_state_profile(s) for s in states}


class ProfileComposer:
    """将多个状态的权重配置合成为连续过渡的加权 profile。

    算法：对每个因子 f
        final_weight = base_weight × Σ(state_weight[s] × bias_multiplier[s, f])

    归一化使活跃因子权重总和与原始 profile 保持一致。
    """

    @staticmethod
    def compose(
        base_profile: RankingProfile,
        state_result: MarketStateResult,
        state_profiles: dict[MarketState, StateProfile],
    ) -> RankingProfile:
        """平滑插值合成最终 RankingProfile。

        Args:
            base_profile: 基线 profile（如 SPOT_DEFAULT_PROFILE）
            state_result: 市场状态结果（含 adjacent_states + adjacent_weights）
            state_profiles: {state: StateProfile} 字典，包含所有相关状态的偏置

        Returns:
            合成后的新 RankingProfile（frozen，纯函数）
        """
        # 构建主状态 + 相邻状态的权重分配
        state_weights: dict[MarketState, float] = {state_result.state: 1.0}
        for adj_state, adj_w in zip(state_result.adjacent_states, state_result.adjacent_weights):
            state_weights[state_result.state] -= adj_w
            state_weights[adj_state] = adj_w

        # 确保主状态权重至少为 0.5
        if state_weights.get(state_result.state, 0) < 0.5:
            s = sum(state_weights.values())
            if s > 0:
                state_weights = {k: v / s for k, v in state_weights.items()}

        # 合并各状态的 bias_multiplier
        combined_bias: dict[str, float] = {}
        for state, sw in state_weights.items():
            profile = state_profiles.get(state)
            if profile is None:
                continue
            for bias in profile.biases:
                existing = combined_bias.get(bias.factor_name, 0.0)
                combined_bias[bias.factor_name] = existing + sw * bias.bias_multiplier

        # 生成新的 FactorEntry 列表
        base_total = sum(e.weight for e in base_profile.factors)
        new_entries: list[FactorEntry] = []
        raw_total = 0.0
        for entry in base_profile.factors:
            multiplier = combined_bias.get(entry.factor_name, 1.0)
            new_weight = entry.weight * multiplier
            raw_total += new_weight
            new_entries.append(FactorEntry(
                factor_name=entry.factor_name,
                rank=entry.rank,
                weight=round(new_weight, 4),
                tier=entry.tier,
            ))

        # 归一化保持总权重不变
        if raw_total > 0 and base_total > 0:
            scale = base_total / raw_total
            new_entries = [
                FactorEntry(
                    factor_name=e.factor_name,
                    rank=e.rank,
                    weight=round(e.weight * scale, 4),
                    tier=e.tier,
                )
                for e in new_entries
            ]

        return RankingProfile(
            profile_id=f"{base_profile.profile_id}_adaptive",
            market_type=base_profile.market_type,
            description=f"自适应合成: {state_result.state.value}",
            factors=new_entries,
        )
