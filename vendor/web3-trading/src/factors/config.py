"""管线配置 — 排序档案、超时、并发控制。"""

from __future__ import annotations

from pydantic import Field

from libs.valuescan.models import VSBaseModel

from .ranking import CONTRACT_DEFAULT_PROFILE, SPOT_DEFAULT_PROFILE, RankingProfile


class PipelineConfig(VSBaseModel):
    """因子计算管线的配置。

    ``ranking_profile`` 是核心配置 — 决定哪些因子处于活跃状态、
    它们的权重和排序。超时和并发设置是正交的调优参数。

    继承自 VSBaseModel 的 frozen=True — 使用 model_copy(update={...})
    生成更新后的副本，而非原地修改。
    """

    # 排序 — 核心配置入口
    ranking_profile: RankingProfile = Field(
        default_factory=lambda: SPOT_DEFAULT_PROFILE,
        description="因子排序、权重和层级。隐式决定市场类型。",
    )

    # 超时
    compute_timeout_s: float = Field(
        30.0, ge=1.0, description="每个代币的管线超时时间（秒）。"
    )
    single_factor_timeout_s: float = Field(
        10.0, ge=0.5, description="单个因子计算的超时时间（秒）。"
    )

    # 自适应
    adaptive_weighting_enabled: bool = Field(
        True, description="是否启用市场状态自适应权重。"
    )

    # 并发
    max_concurrent_factors: int = Field(
        20, ge=1, description="每个代币同时计算的最大因子数。"
    )
    max_concurrent_tokens: int = Field(
        10, ge=1, description="批量模式下同时处理的最大代币数。"
    )

    # 归一化参数
    inflow_normalization_scale: float = Field(
        10_000_000.0, ge=1.0, description="资金流入 normalize_to_bipolar 的 USD 缩放因子。"
    )
    deviation_normalization_scale: float = Field(
        100.0, ge=1.0, description="成本偏离度的百分比缩放因子。"
    )

    # ------------------------------------------------------------------
    # 便捷属性
    # ------------------------------------------------------------------

    @property
    def market_type(self):
        """快捷访问 profile 的市场类型。"""
        return self.ranking_profile.market_type

    # ------------------------------------------------------------------
    # 工厂方法
    # ------------------------------------------------------------------

    @classmethod
    def for_spot(cls) -> PipelineConfig:
        """现货市场默认 profile（31 个因子，现货排序）。"""
        return cls(ranking_profile=SPOT_DEFAULT_PROFILE)

    @classmethod
    def for_contract(cls) -> PipelineConfig:
        """合约市场默认 profile（31 个因子，合约排序）。"""
        return cls(ranking_profile=CONTRACT_DEFAULT_PROFILE)

    @classmethod
    def mvp(cls) -> PipelineConfig:
        """最小可行管线：仅 tier 1-2 的活跃因子。"""
        from .ranking import SPOT_DEFAULT_PROFILE as spot
        active = [f for f in spot.factors if f.weight > 1.0]
        profile = spot.model_copy(update={"factors": active, "description": "MVP (Tier 1-2 only)"})
        return cls(ranking_profile=profile)

    @classmethod
    def standard(cls) -> PipelineConfig:
        """标准管线：现货默认中所有权重大于零的因子。"""
        return cls.for_spot()

    @classmethod
    def full(cls) -> PipelineConfig:
        """完整管线：包含零权重的元数据因子在内的所有因子。"""
        return cls.for_spot()

    @classmethod
    def custom(cls, profile: RankingProfile) -> PipelineConfig:
        """使用用户提供的 RankingProfile 构建自定义管线。"""
        return cls(ranking_profile=profile)
