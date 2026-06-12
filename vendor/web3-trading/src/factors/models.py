"""编码推理链的核心 Pydantic 模型。

关键设计：每个 FactorResult 携带一个 DecisionTrace，
内含有序的 EvidenceLink 对象，使信号可直接被下游 LLM Agent 解读，
无需额外 prompt 工程。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from libs.valuescan.models import VSBaseModel

from .context import FactorContext
from .enums import DataGranularity, FactorCategory, FactorTier, SignalDirection


# ---------------------------------------------------------------------------
# K-line / 衍生品数据模型
# ---------------------------------------------------------------------------


class KlineFrame(BaseModel):
    """单周期 K 线 OHLCV 数组。"""
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    close: np.ndarray = Field(description="收盘价序列")
    high: np.ndarray = Field(description="最高价序列")
    low: np.ndarray = Field(description="最低价序列")
    volume: np.ndarray = Field(description="成交量序列")


class KlineSnapshot(BaseModel):
    """多周期 K 线数据快照。

    因子计算器通过属性访问，如 snapshot.tf_1h.close。
    """
    model_config = ConfigDict(frozen=True)

    tf_15m: Optional[KlineFrame] = Field(default=None, description="15分钟K线")
    tf_1h: Optional[KlineFrame] = Field(default=None, description="1小时K线")
    tf_4h: Optional[KlineFrame] = Field(default=None, description="4小时K线")
    tf_1d: Optional[KlineFrame] = Field(default=None, description="1日K线")

    @property
    def is_empty(self) -> bool:
        return self.tf_15m is None and self.tf_1h is None and self.tf_4h is None and self.tf_1d is None


class FundingRateData(BaseModel):
    """资金费率数据。"""
    model_config = ConfigDict(frozen=True)

    values: List[float] = Field(default_factory=list, description="资金费率历史序列")

    @property
    def current(self) -> Optional[float]:
        return self.values[-1] if self.values else None


class OpenInterestData(BaseModel):
    """持仓量数据。"""
    model_config = ConfigDict(frozen=True)

    values: List[float] = Field(default_factory=list, description="持仓量序列")

    @property
    def current(self) -> Optional[float]:
        return self.values[-1] if self.values else None


class DerivativesSnapshot(BaseModel):
    """合约衍生品数据快照。"""
    model_config = ConfigDict(frozen=True)

    funding_rate: Optional[FundingRateData] = Field(default=None, description="资金费率数据")
    open_interest: Optional[OpenInterestData] = Field(default=None, description="持仓量数据")

    @property
    def is_empty(self) -> bool:
        return self.funding_rate is None and self.open_interest is None


# ---------------------------------------------------------------------------
# 推理链模型
# ---------------------------------------------------------------------------


class EvidenceLink(VSBaseModel):
    """推理链中的单步：数据 → 解读 → 推论。"""

    data_point: str = Field(
        ...,
        description="原始观测数据，如 '24H净流入: -1.2M USD'",
    )
    interpretation: str = Field(
        ...,
        description="数据在交易层面的含义，如 '净流出表示代币离开交易所，暗示囤币行为'",
    )
    implication: str = Field(
        ...,
        description="对价格方向的推论，如 '持续净流出通常在3-7天后价格上涨'",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="该推理环的置信度，基于数据质量和历史可靠性 (0-1)",
    )


class DecisionTrace(VSBaseModel):
    """单次因子计算的完整端到端推理链。

    使因子信号可直接被下游 LLM Agent 消费的结构。
    每个因子计算器都必须生成此追溯链。
    """

    factor_name: str = Field(..., description="因子标识，如 'trade_inflow_multi_granular'")

    raw_inputs: Dict[str, Any] = Field(
        default_factory=dict,
        description="该因子消耗的原始数据快照（已脱敏）",
    )

    evidence_chain: List[EvidenceLink] = Field(
        default_factory=list,
        description="从原始数据到结论的有序推理步骤",
    )

    conclusion: str = Field(
        ...,
        description="汇总全部证据链后的综合结论",
    )

    suggested_action: str = Field(
        "",
        description="基于该因子单独给出的交易操作建议",
    )

    limitations: List[str] = Field(
        default_factory=list,
        description="已知的局限性及数据质量注意事项",
    )

    counter_argument: str = Field(
        "",
        description="最有力的反向论点，强制平衡推理",
    )


# ---------------------------------------------------------------------------
# 因子结果模型
# ---------------------------------------------------------------------------


class GranularityValue(VSBaseModel):
    """多粒度因子中，某个时间粒度下的单点数值。"""

    granularity: DataGranularity = Field(..., description="时间粒度，如 5m/15m/1h/24h")
    value: float = Field(..., description="该粒度下的原始数值")
    weight: float = Field(1.0, ge=0.0, le=1.0, description="聚合时该粒度的权重 (0-1)")


class FactorResult(VSBaseModel):
    """单次因子计算的输出——核心产出契约。

    每个因子计算器都返回此结构体，包含信号方向、置信度、
    元数据和完整推理链。
    """

    # 身份标识
    factor_name: str = Field(..., description="唯一因子标识，如 'trade_inflow_multi_granular'")
    factor_index: int = Field(0, ge=0, le=99, description="排序列表中的因子编号 (0=未注入, >=1=已由 profile 注入)")
    factor_tier: FactorTier = Field(..., description="因子所属层级 (Tier 1~5)")
    category: FactorCategory = Field(..., description="数据来源分类，如 fund_flow / whale_cost / social")
    display_name: str = Field("", description="UI/日志可读的中文展示名")

    # 信号
    signal_direction: SignalDirection = Field(..., description="信号方向，如 bullish / bearish / neutral")
    normalized_score: float = Field(
        ...,
        ge=-1.0,
        le=1.0,
        description="归一化得分：符号=方向（+看涨，-看跌），绝对值=强度",
    )
    raw_value: float = Field(
        0.0,
        description="归一化前的原始计算值，保留以供透明度审计",
    )

    # 质量
    confidence: float = Field(..., ge=0.0, le=1.0, description="该信号的置信度 (0-1)")
    data_freshness_ms: int = Field(
        0,
        description="源数据最大存活时长（毫秒），0=实时数据",
    )
    data_completeness: float = Field(
        1.0,
        ge=0.0,
        le=1.0,
        description="期望数据的可用比例，1.0=全部可用",
    )

    # 权重
    weight: float = Field(
        1.0,
        ge=0.0,
        description="聚合为综合得分时的贡献权重",
    )

    # 推理
    trace: DecisionTrace = Field(..., description="完整端到端推理链")

    # 可选的多粒度明细
    granularity_breakdown: Optional[List[GranularityValue]] = Field(
        None,
        description="跨时间窗口聚合因子的各粒度逐项数值",
    )


class FactorMeta(VSBaseModel):
    """因子的静态元数据——声明在 Computer 类上。

    排序相关字段（factor_index, factor_tier, weight）已移至
    RankingProfile，由外层动态注入。
    """

    factor_name: str = Field(..., description="因子唯一标识名")
    category: FactorCategory = Field(..., description="数据来源分类")
    display_name: str = Field("", description="中文展示名称")
    description: str = Field("", description="因子功能简述")
    requires_data: List[str] = Field(default_factory=list, description="该因子依赖的 context 数据键列表")


# ---------------------------------------------------------------------------
# 交叉因子结果
# ---------------------------------------------------------------------------


class CrossFactorResult(VSBaseModel):
    """两个或多个因子组合成的高阶信号结果。"""

    cross_name: str = Field(..., description="交叉因子名，如 'deviation_x_trade_inflow'")
    parent_factors: List[str] = Field(..., description="源因子名列表")
    formula: str = Field("", description="人类可读的组合公式")

    signal_direction: SignalDirection = Field(..., description="组合信号方向")
    normalized_score: float = Field(..., ge=-1.0, le=1.0, description="归一化得分 (-1~1)")
    confidence: float = Field(..., ge=0.0, le=1.0, description="组合信号置信度 (0-1)")
    trace: DecisionTrace = Field(..., description="交叉因子的推理链")


# ---------------------------------------------------------------------------
# 聚合结果包
# ---------------------------------------------------------------------------


class FactorBundle(VSBaseModel):
    """单一代币在单个时间点的全部因子计算结果。

    结果按层级分区存储，便于按粒度筛选。
    包含交叉因子组合和质量指标。

    继承自 VSBaseModel 的 frozen=True —— 使用 model_copy(update={...})
    生成更新后的副本，而非原地修改。
    """

    quality_report_id: str = Field("", description="关联的本地质量报告 ID")
    vs_token_id: str = Field(..., description="ValueScan 代币 ID")
    symbol: str = Field("", description="代币符号，如 BTC、ETH")
    coin_key: str = Field("", description="链+合约地址标识")
    computed_at_ms: int = Field(0, description="计算时间（毫秒时间戳）")

    tier1_results: List[FactorResult] = Field(default_factory=list, description="Tier 1 核心因子结果")
    tier2_results: List[FactorResult] = Field(default_factory=list, description="Tier 2 强辅助因子结果")
    tier3_results: List[FactorResult] = Field(default_factory=list, description="Tier 3 上下文因子结果")
    tier4_results: List[FactorResult] = Field(default_factory=list, description="Tier 4 验证因子结果")
    tier5_results: List[FactorResult] = Field(default_factory=list, description="Tier 5 元数据因子结果")

    context: Optional[FactorContext] = Field(default=None, description="本次计算的原始数据上下文")

    cross_factors: List[CrossFactorResult] = Field(default_factory=list, description="交叉因子组合结果")

    overall_completeness: float = Field(
        0.0, ge=0.0, le=1.0, description="期望因子成功计算的比例 (0-1)"
    )
    errors: List[str] = Field(default_factory=list, description="计算过程中收集的错误信息")

    @property
    def all_results(self) -> List[FactorResult]:
        """跨所有层级的结果平坦列表。"""
        return (
            self.tier1_results
            + self.tier2_results
            + self.tier3_results
            + self.tier4_results
            + self.tier5_results
        )

    @property
    def aggregate_score(self) -> float:
        """所有成功计算因子的加权聚合得分。

        交叉因子结果以 TIER_1 权重计入。
        """
        signals: List[tuple[float, float]] = []  # (得分, 权重)

        for r in self.all_results:
            if r.confidence > 0.0:
                signals.append((r.normalized_score, r.weight))

        for cr in self.cross_factors:
            if cr.confidence > 0.0:
                signals.append((cr.normalized_score, 1.5))

        if not signals:
            return 0.0

        total_weight = sum(w for _, w in signals)
        if total_weight == 0:
            return 0.0

        return sum(s * w for s, w in signals) / total_weight
