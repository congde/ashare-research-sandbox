"""BaseFactorComputer 抽象基类 — 所有因子计算器必须实现的契约。

排序元数据（factor_index、factor_tier、default_weight）不再硬编码在
计算器上，而是由管线从 ``RankingProfile`` 动态注入，支持按市场类型、
按代币的动态排序。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import ClassVar, List, Set

from .context import FactorContext
from .enums import FactorCategory, MarketType
from .models import DecisionTrace, EvidenceLink, FactorMeta, FactorResult

logger = logging.getLogger(__name__)


class BaseFactorComputer(ABC):
    """所有因子计算器的抽象基类。

    子类声明类级别元数据并实现 ``compute()`` 方法。
    排序信息（index、tier、weight）由 RankingProfile 从外部注入，
    因此同一个计算器可在不同市场或代币下有不同的排序。

    用法::

        class TradeInflowComputer(BaseFactorComputer):
            factor_name: ClassVar[str] = "spot_trade_inflow"
            category: ClassVar[FactorCategory] = FactorCategory.FUND_FLOW
            display_name: ClassVar[str] = "多粒度资金净流入"
            requires_data: ClassVar[List[str]] = ["realtime_fund"]
            supported_markets: ClassVar[Set[MarketType]] = {MarketType.SPOT}

            async def compute(self, ctx: FactorContext) -> FactorResult:
                ...
    """

    # ------------------------------------------------------------------
    # 类级别元数据（子类中覆写）
    # ------------------------------------------------------------------

    factor_name: ClassVar[str] = ""
    category: ClassVar[FactorCategory] = FactorCategory.META
    display_name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    requires_data: ClassVar[List[str]] = []
    supported_markets: ClassVar[Set[MarketType]] = {MarketType.SPOT, MarketType.CONTRACT}

    # ------------------------------------------------------------------
    # 元数据访问器
    # ------------------------------------------------------------------

    @classmethod
    def meta(cls) -> FactorMeta:
        """以值对象形式返回此计算器的静态元数据。"""
        return FactorMeta(
            factor_name=cls.factor_name,
            category=cls.category,
            display_name=cls.display_name,
            description=cls.description,
            requires_data=list(cls.requires_data),
        )

    # ------------------------------------------------------------------
    # 核心计算（子类实现）
    # ------------------------------------------------------------------

    @abstractmethod
    async def compute(self, ctx: FactorContext) -> FactorResult:
        """根据提供的数据上下文计算此因子。

        返回的 FactorResult 应将 ``factor_index``、``factor_tier`` 和
        ``weight`` 保留为默认值 — 管线会从当前 RankingProfile 注入这些值。
        """
        ...

    # ------------------------------------------------------------------
    # 生命周期钩子
    # ------------------------------------------------------------------

    def check_prerequisites(self, ctx: FactorContext) -> bool:
        """检查所有必需数据键是否存在且非空。

        可覆写以实现自定义逻辑（如最少数据点要求）。
        """
        for key in self.requires_data:
            if key not in ctx.data or ctx.data[key] is None:
                return False
            val = ctx.data[key]
            if isinstance(val, (list, dict)) and len(val) == 0:
                return False
        return True

    async def compute_if_available(self, ctx: FactorContext) -> FactorResult | None:
        """安全计算 — 仅在前提条件满足时执行。

        如果前提条件不满足或计算抛出异常，返回 None。
        """
        if not self.check_prerequisites(ctx):
            logger.debug("Factor %s: prerequisites not met, skipping.", self.factor_name)
            return None
        try:
            return await self.compute(ctx)
        except Exception:
            logger.error(
                "Factor %s: computation failed for %s.",
                self.factor_name,
                ctx.symbol,
                exc_info=True,
            )
            return None

    # ------------------------------------------------------------------
    # 子类辅助工厂方法
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
        """安全除法，分母为零或 NaN 时返回默认值。"""
        if not denominator:
            return default
        result = numerator / denominator
        if result != result:  # NaN 检查
            return default
        return result

    @staticmethod
    def _build_trace(
        factor_name: str,
        raw_inputs: dict,
        evidence_chain: List[EvidenceLink],
        conclusion: str,
        suggested_action: str = "",
        limitations: List[str] | None = None,
        counter_argument: str = "",
    ) -> DecisionTrace:
        """DecisionTrace 工厂方法，提供合理默认值。"""
        return DecisionTrace(
            factor_name=factor_name,
            raw_inputs=raw_inputs,
            evidence_chain=evidence_chain,
            conclusion=conclusion,
            suggested_action=suggested_action,
            limitations=limitations or [],
            counter_argument=counter_argument,
        )

    @staticmethod
    def _evidence(
        data_point: str,
        interpretation: str,
        implication: str,
        confidence: float = 0.7,
    ) -> EvidenceLink:
        """单个 EvidenceLink 的工厂方法。"""
        return EvidenceLink(
            data_point=data_point,
            interpretation=interpretation,
            implication=implication,
            confidence=confidence,
        )
