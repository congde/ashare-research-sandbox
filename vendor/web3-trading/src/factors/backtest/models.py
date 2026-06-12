# -*- coding: utf-8 -*-
"""回测数据模型。"""

import uuid
import time
from typing import Any

from pydantic import BaseModel, Field

from factors.enums import MarketType


# ── 本地 JSONL: source_data ───────────────────────────────────────────────

class SourceData(BaseModel):
    """原始数据快照，存储管线拉取的全部 API 原始数据。

    与 factor_snapshots 一对一关联：factor_snapshots.source_data_id → source_data.id。
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, description="主键 UUID")
    symbol: str = Field(description="代币符号，如 BTC")
    vs_token_id: str = Field(description="ValueScan 内部 token ID")
    market_type: MarketType = Field(default=MarketType.SPOT, description="市场类型")
    fetched_at_ms: int = Field(default=0, description="数据获取时间戳（毫秒）")
    data: dict[str, Any] = Field(default_factory=dict, description="FactorContext.data 完整副本（已 sanitized）")


# ── 本地 JSONL: factor_snapshots ────────────────────────────────────────────

class FactorSnapshot(BaseModel):
    """单次因子计算快照 — 三表关联的中心节点。

    通过 quality_report_id → data/data_quality_reports/quality_*.jsonl 关联质量报告。
    通过 source_data_id → source_data.id 关联原始数据。
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, description="主键 UUID")
    symbol: str = Field(description="代币符号，如 BTC")
    vs_token_id: str = Field(description="ValueScan 内部 token ID")
    market_type: MarketType = Field(default=MarketType.SPOT, description="市场类型")
    computed_at_ms: int = Field(default=0, description="计算时间戳（毫秒）")
    quality_report_id: str = Field(default="", description="关联的本地质量报告 ID")
    source_data_id: str = Field(default="", description="关联的 source_data.id")
    factor_results: list[dict[str, Any]] = Field(default_factory=list, description="FactorResult 序列化列表")
    cross_factors: list[dict[str, Any]] = Field(default_factory=list, description="CrossFactorResult 序列化列表")
    aggregate_score: float = Field(default=0.0, description="加权综合得分")
    overall_completeness: float = Field(default=0.0, description="因子计算完整度")
    errors: list[str] = Field(default_factory=list, description="计算错误信息")
    pipeline_duration_ms: int = Field(default=0, description="管线耗时（毫秒）")


# ── MongoDB 集合: price_bars ────────────────────────────────────────────────

class PriceBar(BaseModel):
    """单根 K 线价格数据。"""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, description="主键 UUID")
    symbol: str = Field(description="交易对，如 BTC-USDT")
    timeframe: str = Field(description="K线周期，1h/4h/1d")
    open_time_ms: int = Field(description="开盘时间戳（毫秒）")
    open: float = Field(default=0.0, description="开盘价")
    high: float = Field(default=0.0, description="最高价")
    low: float = Field(default=0.0, description="最低价")
    close: float = Field(default=0.0, description="收盘价")
    volume: float = Field(default=0.0, description="成交量")


# ── 内存模型（不持久化）────────────────────────────────────────────────────

class BacktestTimePoint(BaseModel):
    """回放过程中的单个时间点快照，不持久化。"""

    timestamp_ms: int = Field(description="快照时间戳（毫秒）")
    symbol: str = Field(description="代币符号")
    aggregate_score: float = Field(default=0.0, description="综合信号得分")
    factor_scores: dict[str, float] = Field(default_factory=dict, description="{factor_name: normalized_score}")
    factor_confidences: dict[str, float] = Field(default_factory=dict, description="{factor_name: confidence}")


# ── 评估结果模型 ────────────────────────────────────────────────────────────

class EvalMetrics(BaseModel):
    """单个因子在特定持仓周期下的评估指标。"""

    factor_name: str = Field(description="因子名称")
    category: str = Field(default="", description="因子分类")
    horizon: str = Field(description="评估持仓周期，如 1h/4h/1d/3d")
    ic_mean: float = Field(default=0.0, description="Spearman rank correlation 均值")
    ic_std: float = Field(default=0.0, description="IC 标准差")
    ir: float = Field(default=0.0, description="信息比率 IC Mean / IC Std")
    hit_rate: float = Field(default=0.0, description="方向正确率")
    sample_count: int = Field(default=0, description="有效样本数")
    signal_distribution: dict[str, int] = Field(default_factory=dict, description="bullish/neutral/bearish 计数")


# ── 本地 JSON: backtest_reports ─────────────────────────────────────────────

class BacktestReport(BaseModel):
    """完整回测报告。"""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, description="主键 UUID")
    created_at_ms: int = Field(default_factory=lambda: int(time.time() * 1000), description="生成时间戳（毫秒）")
    config_snapshot: dict[str, Any] = Field(default_factory=dict, description="回测配置快照")
    per_factor: list[EvalMetrics] = Field(default_factory=list, description="每个因子的评估指标")
    per_category: list[dict[str, Any]] = Field(default_factory=list, description="分类别汇总")
    per_tier: list[dict[str, Any]] = Field(default_factory=list, description="分 Tier 汇总")
    aggregate_summary: dict[str, Any] = Field(default_factory=dict, description="整体统计摘要")
    top_factors_by_ic: list[str] = Field(default_factory=list, description="IC 排名（降序）")
    top_factors_by_ir: list[str] = Field(default_factory=list, description="IR 排名（降序）")
