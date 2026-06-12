# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class RiskTier(str, Enum):
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


class StrategyStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class LeadTraderType(str, Enum):
    AI = "ai"
    HUMAN = "human"


@dataclass
class StrategyVersion:
    version_id: str
    strategy_id: str
    version_number: int
    status: StrategyStatus = StrategyStatus.DRAFT
    max_position_pct: float = 30.0
    max_leverage: int = 3
    daily_loss_limit_pct: float = 5.0
    backtest_sharpe: float = 0.0
    backtest_max_drawdown: float = 100.0


@dataclass
class LeadTraderProfile:
    trader_id: str
    name: str
    trader_type: LeadTraderType
    risk_tier: RiskTier
    is_active: bool = True
    strategy_versions: List[StrategyVersion] = field(default_factory=list)
    active_strategy_version: str = ""

    @property
    def active_version(self) -> Optional[StrategyVersion]:
        if not self.active_strategy_version:
            return None
        for version in self.strategy_versions:
            if version.version_id == self.active_strategy_version:
                return version
        return None

    @staticmethod
    def _check_backtest_gate(version: StrategyVersion) -> bool:
        return (version.backtest_sharpe >= 1.0) and (version.backtest_max_drawdown <= 40.0)

    def publish_version(self, version_id: str) -> bool:
        candidate = None
        for version in self.strategy_versions:
            if version.version_id == version_id:
                candidate = version
                break
        if candidate is None:
            return False
        if not self._check_backtest_gate(candidate):
            return False
        candidate.status = StrategyStatus.PUBLISHED
        self.active_strategy_version = candidate.version_id
        return True


@dataclass
class LeadTraderRegistry:
    _profiles: Dict[str, LeadTraderProfile] = field(default_factory=dict)

    def register(self, profile: LeadTraderProfile) -> None:
        self._profiles[profile.trader_id] = profile

    def get(self, trader_id: str) -> Optional[LeadTraderProfile]:
        return self._profiles.get(trader_id)

    def list_traders(self, risk_tier: Optional[RiskTier] = None) -> List[LeadTraderProfile]:
        rows = list(self._profiles.values())
        if risk_tier is None:
            return rows
        return [p for p in rows if p.risk_tier == risk_tier]


_registry: Optional[LeadTraderRegistry] = None


def get_registry() -> LeadTraderRegistry:
    global _registry
    if _registry is None:
        _registry = LeadTraderRegistry()
    return _registry
