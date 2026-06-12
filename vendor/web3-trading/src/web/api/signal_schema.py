# -*- coding: utf-8 -*-
"""
Pydantic output schema for LLM signal analysis.

Kept in a separate module so llm_signal_analyzer.py and any future
consumers can import without pulling in the full LLM runtime.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Trade plan
# ---------------------------------------------------------------------------
class TradePlan(BaseModel):
    support: float = Field(0, description="支撑价位")
    resistance: float = Field(0, description="阻力价位")
    entryLow: float = Field(0, description="建议入场下限")
    entryHigh: float = Field(0, description="建议入场上限")
    stop: float = Field(0, description="止损价位")
    target1: float = Field(0, description="第一目标价")
    target2: float = Field(0, description="第二目标价")


# ---------------------------------------------------------------------------
# Sub-blocks
# ---------------------------------------------------------------------------
class EngineMeta(BaseModel):
    model: str = Field("", description="实际使用模型")
    analysisVersion: str = Field("v2", description="分析协议版本")
    fallbackUsed: bool = Field(False, description="是否回退到规则引擎")


class SignalConflict(BaseModel):
    """Detected conflict between two analysis dimensions."""
    dimensionA: str = Field("", description="冲突维度A (e.g. technical)")
    dimensionB: str = Field("", description="冲突维度B (e.g. onchain)")
    directionA: str = Field("neutral", description="维度A方向判断")
    directionB: str = Field("neutral", description="维度B方向判断")
    severity: str = Field("medium", description="low | medium | high")
    description: str = Field("", description="冲突描述")
    confidenceImpact: float = Field(0, description="对总置信度的负向影响 (0~30)")


class DimensionWeight(BaseModel):
    """Adaptive weight for each analysis dimension."""
    dimension: str = Field("", description="维度名称")
    baseWeight: float = Field(0.25, description="基础权重")
    adaptiveWeight: float = Field(0.25, description="自适应权重")
    recentAccuracy: float = Field(0, description="近期准确率 0~1")
    sampleSize: int = Field(0, description="统计样本量")


class ConsensusBlock(BaseModel):
    direction: str = Field("neutral", description="多源一致性方向")
    agreementScore: float = Field(0, description="0~1 一致性分数")
    strength: str = Field("weak", description="weak | medium | strong")
    conflicts: List[str] = Field(default_factory=list, description="主要冲突点")
    detectedConflicts: List[SignalConflict] = Field(
        default_factory=list, description="结构化冲突检测结果"
    )
    dimensionWeights: List[DimensionWeight] = Field(
        default_factory=list, description="各维度自适应权重"
    )


class ScoreBreakdown(BaseModel):
    technical: float = Field(0, description="技术面得分")
    onchain: float = Field(0, description="链上面得分")
    news: float = Field(0, description="消息面得分")
    positioning: float = Field(0, description="仓位/筹码面得分")
    riskPenalty: float = Field(0, description="风险扣分")


class KeyLevels(BaseModel):
    supports: List[float] = Field(default_factory=list, description="关键支撑位")
    resistances: List[float] = Field(default_factory=list, description="关键阻力位")
    invalidation: float = Field(0, description="观点失效位")


class ExecutionPlan(BaseModel):
    timeHorizon: str = Field("", description="执行周期，例如 4h-24h")
    positionSize: str = Field("", description="仓位建议，例如 small / medium")
    riskReward1: float = Field(0, description="到目标1的盈亏比（与确认方向一致）")
    riskReward2: float = Field(0, description="到目标2的盈亏比（与确认方向一致）")
    longRiskReward1: float = Field(0, description="做多到目标1盈亏比")
    longRiskReward2: float = Field(0, description="做多到目标2盈亏比")
    shortRiskReward1: float = Field(0, description="做空到目标1盈亏比")
    shortRiskReward2: float = Field(0, description="做空到目标2盈亏比")
    action: str = Field("", description="执行建议")


class AnalysisBlock(BaseModel):
    bias: str = Field("neutral", description="bullish | neutral | bearish")
    marketState: str = Field("uncertain", description="市场状态")
    horizon: str = Field("intraday", description="分析周期")
    executionReadiness: str = Field("wait", description="ready | watch_pullback | wait_breakout | avoid")
    consensus: ConsensusBlock = Field(default_factory=ConsensusBlock)
    scoreBreakdown: ScoreBreakdown = Field(default_factory=ScoreBreakdown)
    keyLevels: KeyLevels = Field(default_factory=KeyLevels)
    execution: ExecutionPlan = Field(default_factory=ExecutionPlan)
    catalysts: List[str] = Field(default_factory=list, description="关键催化条件")


class FactorBlock(BaseModel):
    direction: str = Field("neutral", description="方向判断")
    score: float = Field(0, description="分项得分")
    confidence: float = Field(0, description="0~1 分项置信度")
    highlights: List[str] = Field(default_factory=list, description="关键证据")


class FactorsBlock(BaseModel):
    technical: FactorBlock = Field(default_factory=FactorBlock)
    onchain: FactorBlock = Field(default_factory=FactorBlock)
    news: FactorBlock = Field(default_factory=FactorBlock)
    positioning: FactorBlock = Field(default_factory=FactorBlock)


class RiskItem(BaseModel):
    type: str = Field("", description="风险类型")
    severity: str = Field("medium", description="low | medium | high")
    evidence: str = Field("", description="风险证据")
    trigger: str = Field("", description="风险触发条件")
    mitigation: str = Field("", description="应对建议")


class ScenarioItem(BaseModel):
    name: str = Field("base", description="bull | base | bear")
    probability: float = Field(0, description="0~1 概率")
    trigger: str = Field("", description="触发条件")
    action: str = Field("", description="对应操作")
    target: List[float] = Field(default_factory=list, description="目标位")


class DataQuality(BaseModel):
    coverageScore: float = Field(0, description="0~1 数据覆盖得分")
    sourceStatus: Dict[str, str] = Field(default_factory=dict, description="各源状态")
    missingFields: List[str] = Field(default_factory=list, description="缺失字段")
    conflictFlags: List[str] = Field(default_factory=list, description="数据冲突标记")
    limitations: List[str] = Field(default_factory=list, description="数据局限")


class CalibrationBlock(BaseModel):
    ruleSignal: str = Field("", description="规则引擎信号")
    ruleScore: float = Field(0, description="规则引擎得分")
    llmRuleGap: float = Field(0, description="LLM 与规则引擎得分差")


class TradingAgentsDebateBlock(BaseModel):
    """TradingAgents multi-agent debate summary injected into signal output."""
    available: bool = Field(False, description="TradingAgents 是否已执行")
    dataSource: str = Field("", description="数据来源模式: kucoin | all | upstream")
    latencyMs: int = Field(0, description="TA 图执行耗时 ms")
    marketSummary: str = Field("", description="市场分析师摘要")
    sentimentSummary: str = Field("", description="情绪分析师摘要")
    newsSummary: str = Field("", description="新闻分析师摘要")
    fundamentalsSummary: str = Field("", description="基本面分析师摘要")
    bullArgument: str = Field("", description="多头分析师论点")
    bearArgument: str = Field("", description="空头分析师论点")
    devilsAdvocate: str = Field("", description="Devil's Advocate 反方论点")
    riskAssessment: str = Field("", description="风控经理评估")
    traderPlan: str = Field("", description="交易员投资计划")
    finalDecision: str = Field("", description="最终交易决策")
    debateRounds: int = Field(0, description="辩论轮次")
    consensusReached: bool = Field(False, description="是否达成共识")


class DebugBlock(BaseModel):
    calibration: CalibrationBlock = Field(default_factory=CalibrationBlock)
    sourceRefs: Dict[str, Any] = Field(default_factory=dict, description="来源标记")


# ---------------------------------------------------------------------------
# Top-level output
# ---------------------------------------------------------------------------
class SignalOutput(BaseModel):
    signal: str = Field("NEUTRAL", description="BUY | WEAK_BUY | NEUTRAL | WEAK_SELL | SELL")
    label: str = Field("中性观望", description="中文信号标签")
    score: float = Field(0, description="-100 ~ 100, 正=多头 负=空头")
    confidence: float = Field(0, description="0 ~ 95 置信度")
    reasons: List[str] = Field(default_factory=list, description="分析依据列表")
    summary: str = Field("", description="200~500字综合分析摘要")
    tradePlan: Optional[TradePlan] = Field(None, description="交易计划")
    analysis: AnalysisBlock = Field(default_factory=AnalysisBlock)
    factors: FactorsBlock = Field(default_factory=FactorsBlock)
    risks: List[RiskItem] = Field(default_factory=list)
    scenarios: List[ScenarioItem] = Field(default_factory=list)
    dataQuality: DataQuality = Field(default_factory=DataQuality)
    tradingAgentsDebate: TradingAgentsDebateBlock = Field(
        default_factory=TradingAgentsDebateBlock,
        description="TradingAgents 多智能体辩论结果（可选）",
    )
    debug: DebugBlock = Field(default_factory=DebugBlock)
    valuescanInsights: Dict[str, Any] = Field(
        default_factory=dict,
        description="ValueScan 归一化摘要：大盘情绪、追踪告警、建议价位",
    )
    engineMeta: EngineMeta = Field(default_factory=EngineMeta)


# ---------------------------------------------------------------------------
# Opportunity Scanner output
# ---------------------------------------------------------------------------
class OpportunityItem(BaseModel):
    """Single coin opportunity entry in a multi-coin scan."""
    rank: int = Field(0, description="排名")
    symbol: str = Field("", description="币种符号")
    pair: str = Field("", description="交易对，如 BTC-USDT")
    signal: str = Field("NEUTRAL", description="BUY | WEAK_BUY | NEUTRAL | WEAK_SELL | SELL")
    label: str = Field("中性观望", description="中文信号标签")
    score: float = Field(0, description="-100 ~ 100")
    confidence: float = Field(0, description="0 ~ 95")
    change24h: float = Field(0, description="24h 涨跌幅")
    volume24h: float = Field(0, description="24h 成交额 USDT")
    last: float = Field(0, description="最新价格")
    keyReasons: List[str] = Field(default_factory=list, description="关键理由（前3条）")
    tradePlan: Optional[TradePlan] = Field(None, description="交易计划")
    riskLevel: str = Field("medium", description="low | medium | high")
    bias: str = Field("neutral", description="bullish | neutral | bearish")
    marketState: str = Field("uncertain", description="市场状态")
    taDecision: str = Field("", description="TradingAgents 最终决策（若有）")


class OpportunityScanResult(BaseModel):
    """Result of a multi-coin opportunity scan."""
    scanTime: str = Field("", description="扫描时间 ISO-8601")
    totalScanned: int = Field(0, description="扫描币种总数")
    topK: int = Field(0, description="返回前 N 个机会")
    opportunities: List[OpportunityItem] = Field(default_factory=list, description="机会列表（按得分排序）")
    marketOverview: str = Field("", description="市场整体概览摘要")
    scanDurationMs: int = Field(0, description="扫描耗时 ms")
    engine: str = Field("rule", description="rule | llm | hybrid")
    errors: List[str] = Field(default_factory=list, description="扫描过程中的错误")


# ---------------------------------------------------------------------------
# Supported LLM models
# ---------------------------------------------------------------------------
class LLMModel(str, Enum):
    """Supported model identifiers — format: provider/model_name.

    DeepSeek: official Chat Completions model names are ``deepseek-v4-pro`` and
    ``deepseek-v4-flash`` (base_url unchanged). See DeepSeek API docs.
    """
    DEEPSEEK_V4_FLASH = "deepseek/deepseek-v4-flash"
    DEEPSEEK_V4_PRO = "deepseek/deepseek-v4-pro"
    DEEPSEEK_REASONER = "deepseek/deepseek-reasoner"
    QWEN3_5_27B = "qwen/Qwen3.5-27B"
