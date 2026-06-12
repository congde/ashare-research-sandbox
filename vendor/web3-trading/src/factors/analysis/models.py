# -*- coding: utf-8 -*-
"""P2 因子分析共享模型 — 权重优化、共线性检测、市场状态自适应。"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field

from factors.enums import MarketType
from libs.valuescan.models import VSBaseModel


# ---------------------------------------------------------------------------
# P2.1 权重优化 — 枚举 & 模型
# ---------------------------------------------------------------------------


class OptimizerType(StrEnum):
    IC_WEIGHTED = "ic_weighted"
    RISK_PARITY = "risk_parity"
    MEAN_VARIANCE = "mean_variance"
    EQUAL_WEIGHT = "equal_weight"


class ABTestWinner(StrEnum):
    PROFILE_A = "profile_a"
    PROFILE_B = "profile_b"
    NO_SIGNIFICANT_DIFFERENCE = "no_significant_difference"


class OptimizedWeight(VSBaseModel):
    factor_name: str = Field(..., description="因子名称")
    raw_weight: float = Field(..., description="优化器输出的原始权重")
    normalized_weight: float = Field(0.0, ge=0.0, description="归一化后权重 (总和=1)")
    optimizer_metric: float = Field(default=0.0, description="优化器目标指标值 (IC_IR / 1/sigma / IR)")


class OptimizerResult(VSBaseModel):
    optimizer_type: OptimizerType = Field(..., description="优化器类型")
    profile_id: str = Field(..., description="生成的结果标识，如 ic_weighted_v1")
    market_type: MarketType = Field(..., description="市场类型")
    weights: list[OptimizedWeight] = Field(..., description="优化后权重列表")
    sharpe_estimate: float = Field(default=0.0, description="组合夏普比率估计值")
    equal_weight_sharpe: float = Field(default=0.0, description="等权基线夏普比率")
    sharpe_improvement: float = Field(default=0.0, description="夏普改进百分比")
    notes: str = Field(default="", description="优化备注")


class ABComparisonRow(VSBaseModel):
    factor_name: str = Field(..., description="因子名称")
    weight_a: float = Field(..., description="A 方案权重")
    weight_b: float = Field(..., description="B 方案权重")
    ic_mean_a: float = Field(..., description="A 方案 IC 均值")
    ic_mean_b: float = Field(..., description="B 方案 IC 均值")
    ir_a: float = Field(..., description="A 方案 IR")
    ir_b: float = Field(..., description="B 方案 IR")


class ABTestReport(VSBaseModel):
    id: str = Field(..., description="报告唯一标识")
    profile_a_id: str = Field(..., description="A 方案 profile_id")
    profile_b_id: str = Field(..., description="B 方案 profile_id")
    optimizer_types: list[OptimizerType] = Field(default_factory=list, description="参与对比的优化器类型")
    winner: ABTestWinner = Field(..., description="优胜方案")
    sharpe_a: float = Field(..., description="A 方案夏普")
    sharpe_b: float = Field(..., description="B 方案夏普")
    p_value: float = Field(..., description="统计显著性 p-value")
    per_factor_comparison: list[ABComparisonRow] = Field(default_factory=list, description="逐因子对比明细")
    recommendation: str = Field(default="", description="推荐行动")


# ---------------------------------------------------------------------------
# P2.2 共线性检测 — 枚举 & 模型
# ---------------------------------------------------------------------------


class CollinearitySeverity(StrEnum):
    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"


class DedupAction(StrEnum):
    KEEP_PRIMARY = "keep_primary"
    DOWNWEIGHT = "downweight"
    REMOVE = "remove"


class FactorCorrelationPair(VSBaseModel):
    factor_a: str = Field(..., description="因子 A 名称")
    factor_b: str = Field(..., description="因子 B 名称")
    pearson_r: float = Field(..., description="Pearson 相关系数")
    spearman_rho: float = Field(..., description="Spearman 秩相关系数")
    p_value: float = Field(default=0.0, description="显著性 p-value")


class CollinearityGroup(VSBaseModel):
    group_id: str = Field(..., description="共线性组唯一标识")
    factor_names: list[str] = Field(..., description="该组内因子名称列表")
    avg_correlation: float = Field(..., description="组内平均 Spearman |rho|")
    severity: CollinearitySeverity = Field(..., description="共线性严重程度")
    primary_factor: str = Field(..., description="推荐保留的主因子 (IC 最高)")
    vif_scores: dict[str, float] = Field(default_factory=dict, description="每个因子的 VIF 值")
    recommendation: str = Field(default="", description="去重建议文字")


class CorrelationMatrix(VSBaseModel):
    factor_names: list[str] = Field(..., description="因子名称列表（按矩阵行列顺序）")
    pearson_matrix: list[list[float]] = Field(default_factory=list, description="Pearson 相关矩阵 (N x N)")
    spearman_matrix: list[list[float]] = Field(default_factory=list, description="Spearman 相关矩阵 (N x N)")
    clusters: list[CollinearityGroup] = Field(default_factory=list, description="检测到的共线性组")
    high_correlation_pairs: list[FactorCorrelationPair] = Field(default_factory=list, description="高相关对 (|rho| > 0.7)")


class DedupPlan(VSBaseModel):
    collinearity_cutoff: float = Field(default=0.7, description="共线性检测阈值")
    groups: list[CollinearityGroup] = Field(..., description="共线性分组")
    actions: list[dict[str, Any]] = Field(default_factory=list, description="具体操作列表")
    adjusted_weights: dict[str, float] = Field(default_factory=dict, description="调整后权重映射 {factor_name: adjusted_weight}")


# ---------------------------------------------------------------------------
# P2.3 市场状态自适应 — 枚举 & 模型
# ---------------------------------------------------------------------------


class MarketState(StrEnum):
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    HIGH_VOL = "high_vol"
    LOW_VOL = "low_vol"


class MarketStateResult(VSBaseModel):
    state: MarketState = Field(..., description="当前市场状态")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="状态判断置信度")
    indicators: dict[str, float] = Field(default_factory=dict, description="各判断指标的原始值 (adx, atr_pct, bb_width, ema_ratio)")
    adjacent_states: list[MarketState] = Field(default_factory=list, description="相邻状态 (用于平滑插值)")
    adjacent_weights: list[float] = Field(default_factory=list, description="相邻状态混合权重")


class StateWeightBias(VSBaseModel):
    factor_name: str = Field(..., description="因子名称")
    base_weight: float = Field(..., description="基线权重（来自默认 profile）")
    bias_multiplier: float = Field(default=1.0, ge=0.0, description="该状态下的权重乘数")
    reason: str = Field(default="", description="为何此状态上调/下调该因子")


class StateProfile(VSBaseModel):
    state: MarketState = Field(..., description="市场状态")
    profile_id: str = Field(..., description="配置文件 ID")
    market_type: MarketType = Field(..., description="适用市场类型")
    biases: list[StateWeightBias] = Field(..., description="各因子的权重偏置列表")
