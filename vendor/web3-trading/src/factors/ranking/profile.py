"""RankingProfile — 因子排序配置文件，由外层动态传入。"""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import Field

from libs.valuescan.models import VSBaseModel

from ..enums import FactorTier, MarketType


class FactorEntry(VSBaseModel):
    """排序配置文件中的单个因子条目。"""

    factor_name: str = Field(..., description="因子唯一标识名，如 'spot_trade_inflow'")
    rank: int = Field(..., ge=1, description="排序位置，1=最重要")
    weight: float = Field(..., ge=0.0, description="聚合时的贡献权重")
    tier: FactorTier = Field(..., description="因子层级")


class RankingProfile(VSBaseModel):
    """因子排序配置文件。

    由外层业务逻辑构造并传入 PipelineConfig。不同的市场类型、
    不同的代币可以使用不同的排序配置，实现因子重要性的动态调整。

    用法::

        profile = SPOT_DEFAULT_PROFILE
        weight = profile.get_weight("spot_trade_inflow")  # 3.0
        rank = profile.get_rank("spot_trade_inflow")       # 2
    """

    profile_id: str = Field(..., description="配置文件唯一标识")
    market_type: MarketType = Field(..., description="适用的市场类型")
    description: str = Field("", description="配置文件说明")
    factors: List[FactorEntry] = Field(
        default_factory=list, description="按 rank 升序排列的因子列表"
    )

    # ------------------------------------------------------------------
    # 查询接口
    # ------------------------------------------------------------------

    def get_entry(self, factor_name: str) -> Optional[FactorEntry]:
        """按名称获取因子条目。"""
        for f in self.factors:
            if f.factor_name == factor_name:
                return f
        return None

    def get_weight(self, factor_name: str) -> float:
        """获取因子权重，未找到返回 0.0。"""
        entry = self.get_entry(factor_name)
        return entry.weight if entry else 0.0

    def get_rank(self, factor_name: str) -> int:
        """获取因子排序位置，未找到返回 999。"""
        entry = self.get_entry(factor_name)
        return entry.rank if entry else 999

    def get_tier(self, factor_name: str) -> Optional[FactorTier]:
        """获取因子层级。"""
        entry = self.get_entry(factor_name)
        return entry.tier if entry else None

    def active_factors(self) -> List[str]:
        """返回 weight > 0 的因子名列表。"""
        return [f.factor_name for f in self.factors if f.weight > 0]

    def top_n(self, n: int) -> List[str]:
        """返回排名前 N 的因子名列表。"""
        sorted_factors = sorted(self.factors, key=lambda f: f.rank)
        return [f.factor_name for f in sorted_factors[:n]]

    def factor_names(self) -> List[str]:
        """返回所有因子名（按 rank 排序）。"""
        return [f.factor_name for f in sorted(self.factors, key=lambda f: f.rank)]

    def as_weight_map(self) -> Dict[str, float]:
        """返回 {factor_name: weight} 映射。"""
        return {f.factor_name: f.weight for f in self.factors}
