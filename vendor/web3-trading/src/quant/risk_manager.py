# -*- coding: utf-8 -*-
"""交易风险管理模块。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from quant.risk_state import RiskStateStore


def _config_value(name: str, default):
    env_value = os.getenv(name)
    if env_value not in (None, ""):
        return env_value
    try:
        from web import config as web_config

        cfg = web_config.config
        if cfg is not None:
            return getattr(cfg, name.lower(), default)
    except Exception:
        pass
    return default


def _config_float(name: str, default: float) -> float:
    try:
        return float(_config_value(name, default))
    except (TypeError, ValueError):
        return default


@dataclass
class RiskLimits:
    """可通过环境变量覆盖的交易风险阈值。"""

    max_position_risk: float = 0.02       # 单笔最大风险占总权益比例
    max_total_exposure: float = 0.30      # 总仓位市值 / 总权益上限
    max_daily_loss: float = 0.05          # 日内最大亏损比例
    max_drawdown: float = 0.15            # 最大回撤比例
    min_confidence: float = 0.50          # 决策最低置信度
    max_leverage: int = 5                 # 默认更保守，最大杠杆倍数
    max_quantity_usd: float = 5000.0      # 单笔最大交易金额

    @classmethod
    def from_env(cls) -> "RiskLimits":
        return cls(
            max_position_risk=_config_float("QUANT_MAX_POSITION_RISK", 0.02),
            max_total_exposure=_config_float("QUANT_MAX_TOTAL_EXPOSURE", 0.30),
            max_daily_loss=_config_float("QUANT_MAX_DAILY_LOSS", 0.05),
            max_drawdown=_config_float("QUANT_MAX_DRAWDOWN", 0.15),
            min_confidence=_config_float("QUANT_MIN_CONFIDENCE", 0.50),
            max_leverage=int(_config_float("QUANT_MAX_LEVERAGE", 5)),
            max_quantity_usd=_config_float("QUANT_MAX_QUANTITY_USD", 5000.0),
        )


@dataclass
class RiskCheckResult:
    approved: bool
    reason: str
    adjusted_quantity: Optional[float] = None


class RiskManager:
    """统一风控入口：对 LLM/规则策略产生的交易决策做最后闸门。"""

    def __init__(self, limits: Optional[RiskLimits] = None, state_store: Optional[RiskStateStore] = None):
        self.limits = limits or RiskLimits.from_env()
        self._state_store = state_store or RiskStateStore()

    @property
    def _daily_pnl(self) -> float:
        return self._state_store.state.daily_pnl

    @property
    def _peak_equity(self) -> float:
        return self._state_store.state.peak_equity

    @property
    def _paused(self) -> bool:
        return self._state_store.state.paused

    def update_equity(self, current_equity: float) -> None:
        self._state_store.update_equity(current_equity)

    def reset_daily(self) -> None:
        self._state_store.reset_daily()

    def record_trade_pnl(self, pnl: float) -> None:
        self._state_store.record_trade_pnl(pnl)

    def snapshot(self) -> dict:
        return self._state_store.snapshot()

    @property
    def is_paused(self) -> bool:
        return self._paused

    def check_trade(
        self,
        decision: dict,
        cash: float,
        total_position_value: float,
        total_equity: float,
    ) -> RiskCheckResult:
        """Validate a trade decision against risk limits.

        decision 支持两种契约：
        - action: buy | sell | short | cover | hold
        - signal: entry | exit | hold
        """
        if self._paused:
            return RiskCheckResult(False, "Trading paused due to risk circuit breaker")

        action = str(decision.get("action") or "").lower()
        signal = str(decision.get("signal") or "").lower()
        is_entry = action in ("buy", "short") or signal == "entry"
        if not is_entry:
            return RiskCheckResult(True, "Non-entry signal, no risk check needed")

        confidence = float(decision.get("confidence") or 0)
        if confidence < self.limits.min_confidence:
            return RiskCheckResult(False, f"Confidence {confidence:.2f} below minimum {self.limits.min_confidence:.2f}")

        leverage = float(decision.get("leverage") or 1)
        if leverage > self.limits.max_leverage:
            return RiskCheckResult(False, f"Leverage {leverage:g}x exceeds maximum {self.limits.max_leverage}x")

        price = float(decision.get("price") or 0)
        quantity = float(decision.get("quantity") or 0)
        trade_value = abs(price * quantity)
        if trade_value <= 0:
            return RiskCheckResult(False, "Invalid price or quantity")
        if trade_value > self.limits.max_quantity_usd:
            return RiskCheckResult(False, f"Trade value ${trade_value:,.2f} exceeds maximum ${self.limits.max_quantity_usd:,.2f}")
        if action == "buy" and cash <= 0:
            return RiskCheckResult(False, "No cash available for buy order")
        if action == "buy" and trade_value > cash:
            return RiskCheckResult(False, f"Insufficient cash ${cash:,.2f} for order ${trade_value:,.2f}")

        if total_equity > 0:
            new_exposure = (total_position_value + trade_value) / total_equity
            if new_exposure > self.limits.max_total_exposure:
                return RiskCheckResult(False, f"Total exposure {new_exposure:.1%} would exceed limit {self.limits.max_total_exposure:.1%}")

        stop_loss = decision.get("stop_loss") or decision.get("stopLoss")
        risk_usd = float(decision.get("risk_usd") or decision.get("riskUsd") or 0)
        if stop_loss and price and quantity:
            risk_usd = abs(price - float(stop_loss)) * abs(quantity)

        if total_equity > 0 and risk_usd > 0:
            risk_ratio = risk_usd / total_equity
            if risk_ratio > self.limits.max_position_risk:
                max_risk_usd = total_equity * self.limits.max_position_risk
                if stop_loss and price:
                    risk_per_unit = abs(price - float(stop_loss))
                    if risk_per_unit > 0:
                        adjusted_qty = max_risk_usd / risk_per_unit
                        return RiskCheckResult(
                            True,
                            f"Quantity adjusted from {quantity} to {adjusted_qty:.6f} to meet {self.limits.max_position_risk:.1%} risk limit",
                            adjusted_quantity=adjusted_qty,
                        )
                return RiskCheckResult(False, f"Risk ${risk_usd:,.2f} ({risk_ratio:.1%}) exceeds limit {self.limits.max_position_risk:.1%}")

        if self._peak_equity > 0 and total_equity > 0:
            drawdown = (self._peak_equity - total_equity) / self._peak_equity
            if drawdown > self.limits.max_drawdown:
                self._state_store.set_paused(True)
                return RiskCheckResult(False, f"Max drawdown {drawdown:.1%} exceeded limit {self.limits.max_drawdown:.1%}. Trading paused.")

        if total_equity > 0 and self._daily_pnl < 0:
            daily_loss_ratio = -self._daily_pnl / total_equity
            if daily_loss_ratio > self.limits.max_daily_loss:
                self._state_store.set_paused(True)
                return RiskCheckResult(False, f"Daily loss {daily_loss_ratio:.1%} exceeded limit {self.limits.max_daily_loss:.1%}. Trading paused.")

        return RiskCheckResult(True, "Trade approved")
