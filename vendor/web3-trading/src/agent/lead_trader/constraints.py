# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List

from agent.lead_trader.metadata import RiskTier


class ConstraintSeverity(str, Enum):
    BLOCK = "block"
    WARNING = "warning"


@dataclass
class ConstraintViolation:
    constraint_name: str
    message: str
    severity: ConstraintSeverity = ConstraintSeverity.BLOCK


@dataclass
class StrategyConstraints:
    max_position_pct: float = 30.0
    max_leverage: int = 3
    daily_loss_limit_pct: float = 5.0
    blocked_pairs: List[str] = field(default_factory=list)
    allowed_pairs: List[str] = field(default_factory=list)
    block_promise_return: bool = False
    max_confidence_cap: float = 95.0
    stop_loss_pct: float = 5.0

    @classmethod
    def from_risk_tier(cls, risk_tier: RiskTier, **overrides) -> "StrategyConstraints":
        mapping = {
            RiskTier.CONSERVATIVE: dict(max_position_pct=15.0, max_leverage=1, daily_loss_limit_pct=2.0),
            RiskTier.MODERATE: dict(max_position_pct=30.0, max_leverage=3, daily_loss_limit_pct=5.0),
            RiskTier.AGGRESSIVE: dict(max_position_pct=50.0, max_leverage=5, daily_loss_limit_pct=8.0),
        }
        payload = mapping.get(risk_tier, mapping[RiskTier.MODERATE]).copy()
        payload.update(overrides)
        return cls(**payload)


class ConstraintChecker:
    def __init__(self, constraints: StrategyConstraints):
        self.constraints = constraints

    def check_signal(self, signal: Dict) -> List[ConstraintViolation]:
        rows: List[ConstraintViolation] = []
        position_pct = float(signal.get("position_pct") or 0)
        leverage = int(signal.get("leverage") or 0)
        pair = str(signal.get("pair") or "")

        if position_pct > self.constraints.max_position_pct:
            rows.append(ConstraintViolation("max_position_pct", "Position exceeds limit", ConstraintSeverity.BLOCK))

        if leverage > self.constraints.max_leverage:
            rows.append(ConstraintViolation("max_leverage", "Leverage exceeds limit", ConstraintSeverity.BLOCK))

        if pair and pair in set(self.constraints.blocked_pairs or []):
            rows.append(ConstraintViolation("blocked_pair", "Pair is blocked", ConstraintSeverity.BLOCK))

        if self.constraints.allowed_pairs and pair and pair not in set(self.constraints.allowed_pairs):
            rows.append(ConstraintViolation("allowed_pair", "Pair not in allow list", ConstraintSeverity.BLOCK))

        if self.constraints.block_promise_return:
            content = str(signal.get("content") or "")
            keywords = ("保证盈利", "稳赚不赔", "保本", "100%")
            if any(k in content for k in keywords):
                rows.append(ConstraintViolation("block_promise_return", "Promise return wording detected", ConstraintSeverity.BLOCK))

        confidence = signal.get("confidence")
        if confidence is not None and float(confidence) > self.constraints.max_confidence_cap:
            rows.append(ConstraintViolation("max_confidence_cap", "Confidence above cap", ConstraintSeverity.WARNING))

        stop_loss = signal.get("stop_loss_pct")
        if stop_loss is not None and float(stop_loss) > self.constraints.stop_loss_pct * 2:
            rows.append(ConstraintViolation("stop_loss_too_wide", "Stop loss is too wide", ConstraintSeverity.WARNING))

        take_profit = signal.get("take_profit_pct")
        if stop_loss is not None and take_profit is not None and float(take_profit) <= float(stop_loss):
            rows.append(ConstraintViolation("take_profit_below_stop", "Take profit should exceed stop", ConstraintSeverity.WARNING))

        return rows

    def is_signal_publishable(self, signal: Dict) -> bool:
        return all(v.severity != ConstraintSeverity.BLOCK for v in self.check_signal(signal))
