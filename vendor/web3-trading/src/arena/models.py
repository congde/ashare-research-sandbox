# -*- coding: utf-8 -*-
"""Arena 数据模型。"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


AgentAction = Literal["LONG", "SHORT", "WEAK_LONG", "WEAK_SHORT", "WAIT", "buy", "sell", "short", "cover", "hold"]
AgentDirection = Literal["long", "short", "neutral", "LONG", "SHORT", "WAIT"]
AgentIntent = Literal["open", "close", "reduce", "wait"]
ExecutionAction = Literal["buy", "sell", "short", "cover", "hold"]
AgentHorizon = Literal["scalp", "intraday", "swing", "position"]


class AgentRiskBoundary(BaseModel):
    """单个 Arena Agent 的策略级风险边界。"""

    max_position_risk_pct: float = Field(0.01, ge=0.0, le=1.0)
    max_gross_exposure_pct: float = Field(0.10, ge=0.0, le=1.0)
    min_confidence_to_trade: float = Field(0.5, ge=0.0, le=1.0)
    max_leverage: float = Field(1.0, ge=1.0, le=5.0)
    stop_loss_pct_range: List[float] = Field(default_factory=lambda: [1.0, 8.0])
    paper_only_until_review: bool = True
    notes: List[str] = Field(default_factory=list)


class AgentProfile(BaseModel):
    """Arena Agent 的角色、权限、提示词和适用边界。"""

    name: str
    display_name: str
    role: str
    strategy: str
    prompt: str
    prompt_path: str = ""
    account_id: str = "default"
    allowed_data_apis: List[str] = Field(default_factory=list)
    output_schema: str = "AgentSignal"
    suitable_market_regimes: List[str] = Field(default_factory=list)
    risk_boundary: AgentRiskBoundary = Field(default_factory=AgentRiskBoundary)


class AgentSignal(BaseModel):
    """单个交易/决策 Agent 的独立输出。"""

    agent_name: str
    symbol: str
    action: AgentAction = "WAIT"
    direction: Optional[AgentDirection] = None
    intent: AgentIntent = "wait"
    execution_action: Optional[ExecutionAction] = None
    score: float = Field(0.0)
    confidence: float = Field(0.0)

    @field_validator("score", mode="before")
    @classmethod
    def _clamp_score(cls, v: Any) -> float:
        """LLM 可能输出负数表示方向，取绝对值保留强度，方向由 action 字段决定。"""
        try:
            return max(0.0, min(100.0, abs(float(v))))
        except (TypeError, ValueError):
            return 0.0

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence(cls, v: Any) -> float:
        """自动 clamp 到 [0, 1]。"""
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return 0.0
    horizon: AgentHorizon = "intraday"
    regime: str = "unknown"
    entry_reason: List[str] = Field(default_factory=list)
    invalidation: str = ""
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None
    data_sources: List[str] = Field(default_factory=list)
    risk_flags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AgentSignalSet(BaseModel):
    """单个 Arena Agent 的 LLM 结构化输出。"""

    summary: str = ""
    signals: List[AgentSignal] = Field(default_factory=list)


class AgentRunTrace(BaseModel):
    """单个 Agent 一次运行的完整输入、提示词和输出。"""

    agent_name: str
    display_name: str
    symbols: List[str] = Field(default_factory=list)
    profile: AgentProfile
    prompt: str
    input_context: Dict[str, Any] = Field(default_factory=dict)
    output_signals: List[AgentSignal] = Field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
    latency_ms: float = 0.0
    error: Optional[str] = None


class AgentPerformanceRecord(BaseModel):
    """Agent paper/live 表现流水，后续可用行情回放补 PnL。"""

    ts: str
    agent_name: str
    symbol: str
    mode: Literal["paper", "live_candidate", "live"] = "paper"
    action: AgentAction = "WAIT"
    execution_action: Optional[ExecutionAction] = None
    score: float = 0.0
    confidence: float = 0.0
    price: Optional[float] = None
    paper_only: bool = True
    active_agent: str = ""
    risk_approved: Optional[bool] = None
    risk_reason: str = ""
    execution_status: str = "not_executed"
    evaluation_status: str = "pending_price_outcome"
    signal: Dict[str, Any] = Field(default_factory=dict)


class ArenaRunResult(BaseModel):
    """一次 Arena 运行结果。"""

    mode: str = "arena"
    symbols: List[str] = Field(default_factory=list)
    agents: List[str] = Field(default_factory=list)
    active_agent: str = ""
    execution_agents: List[str] = Field(default_factory=list)
    paper_only: bool = True
    agent_profiles: List[AgentProfile] = Field(default_factory=list)
    signals: List[AgentSignal] = Field(default_factory=list)
    agent_traces: List[AgentRunTrace] = Field(default_factory=list)
    performance_records: List[AgentPerformanceRecord] = Field(default_factory=list)
    active_decisions: List[Dict[str, Any]] = Field(default_factory=list)
    risk_results: List[Dict[str, Any]] = Field(default_factory=list)
    risk_state: Dict[str, Any] = Field(default_factory=dict)
    execution_results: List[Dict[str, Any]] = Field(default_factory=list)
    data_quality: Dict[str, Any] = Field(default_factory=dict)
    data_context: Dict[str, Any] = Field(default_factory=dict)
    log_files: Dict[str, str] = Field(default_factory=dict)