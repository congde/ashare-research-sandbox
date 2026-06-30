"""Runtime risk manager adapted from ai-trading strategy_engine/runtime/risk_manager.py."""

from __future__ import annotations

import logging
from dataclasses import FrozenInstanceError, dataclass, replace
from decimal import Decimal
from typing import Protocol

from strategy_engine.backtest.candles import Candle
from strategy_engine.backtest.engine import StrategyContext
from strategy_engine.backtest.portfolio import Portfolio
from strategy_engine.backtest.protocol import OrderIntent, OrderSide

logger = logging.getLogger("risk_manager")


@dataclass(frozen=True, slots=True)
class RiskCheckResult:
    allowed: bool
    rule_id: str = ""
    reason: str = ""

    @classmethod
    def allow(cls) -> RiskCheckResult:
        return _ALLOW_SINGLETON


_ALLOW_SINGLETON = RiskCheckResult(allowed=True)


class RiskRule(Protocol):
    rule_id: str

    def check(
        self,
        intent: OrderIntent,
        *,
        ctx: StrategyContext,
        portfolio: Portfolio,
        candle: Candle,
    ) -> RiskCheckResult: ...


@dataclass(frozen=True, slots=True)
class MaxPositionRule:
    max_notional_usd: Decimal
    rule_id: str = "MAX_POSITION_PCT"

    def check(
        self,
        intent: OrderIntent,
        *,
        ctx: StrategyContext,
        portfolio: Portfolio,
        candle: Candle,
    ) -> RiskCheckResult:
        position = portfolio.position(intent.symbol)
        delta = intent.qty if intent.side == OrderSide.BUY else -intent.qty
        post_qty = position.qty + delta
        notional = abs(post_qty) * candle.close
        if notional > self.max_notional_usd:
            return RiskCheckResult(
                allowed=False,
                rule_id=self.rule_id,
                reason=(
                    f"post-fill notional ${notional} would exceed "
                    f"max ${self.max_notional_usd} "
                    f"({position.qty} + {delta} = {post_qty} × {candle.close})"
                ),
            )
        return RiskCheckResult.allow()


@dataclass(slots=True)
class MaxDrawdownRule:
    max_drawdown_pct: Decimal
    rule_id: str = "MAX_DAILY_LOSS_PCT"
    _peak: Decimal = Decimal("0")

    def check(
        self,
        intent: OrderIntent,
        *,
        ctx: StrategyContext,
        portfolio: Portfolio,
        candle: Candle,
    ) -> RiskCheckResult:
        if intent.side == OrderSide.SELL:
            return RiskCheckResult.allow()

        equity = portfolio.equity({intent.symbol: candle.close})
        if equity > self._peak:
            self._peak = equity

        if self._peak <= 0:
            return RiskCheckResult.allow()

        drawdown = (self._peak - equity) / self._peak
        if drawdown >= self.max_drawdown_pct:
            return RiskCheckResult(
                allowed=False,
                rule_id=self.rule_id,
                reason=(
                    f"equity ${equity} is {float(drawdown * 100):.2f}% "
                    f"below peak ${self._peak}; max allowed drawdown "
                    f"{float(self.max_drawdown_pct * 100):.2f}%"
                ),
            )
        return RiskCheckResult.allow()


@dataclass(slots=True)
class MaxSlippageRule:
    max_spread_pct: Decimal
    rule_id: str = "MAX_SLIPPAGE_PCT"

    def check(
        self,
        intent: OrderIntent,
        *,
        ctx: StrategyContext,
        portfolio: Portfolio,
        candle: Candle,
    ) -> RiskCheckResult:
        if candle.close <= 0:
            return RiskCheckResult.allow()

        spread = (candle.high - candle.low) / candle.close
        if spread > self.max_spread_pct:
            return RiskCheckResult(
                allowed=False,
                rule_id=self.rule_id,
                reason=(
                    f"intra-bar spread "
                    f"{float(spread * 100):.2f}% exceeds max "
                    f"{float(self.max_spread_pct * 100):.2f}% "
                    f"(H={candle.high} L={candle.low} C={candle.close})"
                ),
            )
        return RiskCheckResult.allow()


@dataclass(slots=True)
class AbnormalCandleRule:
    max_price_jump_pct: Decimal
    rule_id: str = "ABNORMAL_ORDERBOOK"

    def check(
        self,
        intent: OrderIntent,
        *,
        ctx: StrategyContext,
        portfolio: Portfolio,
        candle: Candle,
    ) -> RiskCheckResult:
        if candle.volume <= 0 and candle.high != candle.low:
            return RiskCheckResult(
                allowed=False,
                rule_id=self.rule_id,
                reason=(
                    f"candle has zero volume but non-flat price "
                    f"(H={candle.high} L={candle.low}) — feed "
                    "may be corrupted or symbol halted"
                ),
            )

        if candle.high == candle.low and candle.volume > 0:
            return RiskCheckResult(
                allowed=False,
                rule_id=self.rule_id,
                reason=(
                    f"candle has zero range (H==L=={candle.high}) "
                    f"but volume {candle.volume} — likely stale feed"
                ),
            )

        if len(ctx.history) >= 2:
            prev_close = ctx.history[-2].close
            if prev_close > 0:
                jump = abs(candle.close - prev_close) / prev_close
                if jump > self.max_price_jump_pct:
                    return RiskCheckResult(
                        allowed=False,
                        rule_id=self.rule_id,
                        reason=(
                            f"bar-to-bar price jump "
                            f"{float(jump * 100):.2f}% exceeds max "
                            f"{float(self.max_price_jump_pct * 100):.2f}% "
                            f"({prev_close} → {candle.close})"
                        ),
                    )

        return RiskCheckResult.allow()


@dataclass(slots=True)
class KillSwitch:
    rule_id: str = "EMERGENCY_HALT"
    tripped: bool = False
    tripped_reason: str = ""

    def trip(self, reason: str) -> None:
        if not self.tripped:
            self.tripped = True
            self.tripped_reason = reason
            logger.warning("KillSwitch tripped: %s", reason)

    def reset(self) -> None:
        self.tripped = False
        self.tripped_reason = ""

    def check(
        self,
        intent: OrderIntent,
        *,
        ctx: StrategyContext,
        portfolio: Portfolio,
        candle: Candle,
    ) -> RiskCheckResult:
        if self.tripped:
            return RiskCheckResult(
                allowed=False,
                rule_id=self.rule_id,
                reason=f"kill switch tripped: {self.tripped_reason}",
            )
        return RiskCheckResult.allow()


class RiskThresholdPatchError(ValueError):
    """Unknown rule, non-patchable field, or invalid threshold value."""


_PATCHABLE_FIELDS: dict[str, frozenset[str]] = {
    "MAX_POSITION_PCT": frozenset({"max_notional_usd"}),
    "MAX_DAILY_LOSS_PCT": frozenset({"max_drawdown_pct"}),
    "MAX_SLIPPAGE_PCT": frozenset({"max_spread_pct"}),
    "ABNORMAL_ORDERBOOK": frozenset({"max_price_jump_pct"}),
}


class RiskManager:
    def __init__(self, rules: list[RiskRule] | None = None) -> None:
        self._rules: list[RiskRule] = list(rules) if rules else []

    def add_rule(self, rule: RiskRule) -> None:
        self._rules.append(rule)

    def patch_threshold(self, rule_id: str, field: str, value: Decimal) -> RiskRule:
        allowed = _PATCHABLE_FIELDS.get(rule_id)
        if allowed is None:
            raise RiskThresholdPatchError(
                f"rule {rule_id!r} has no patchable thresholds; "
                f"patchable rules: {sorted(_PATCHABLE_FIELDS)}"
            )
        if field not in allowed:
            raise RiskThresholdPatchError(
                f"field {field!r} is not patchable on {rule_id!r}; allowed: {sorted(allowed)}"
            )
        if not isinstance(value, Decimal):
            value = Decimal(str(value))
        if value <= 0:
            raise RiskThresholdPatchError(f"threshold {field!r} must be positive, got {value}")

        for index, rule in enumerate(self._rules):
            if getattr(rule, "rule_id", None) != rule_id:
                continue
            try:
                setattr(rule, field, value)
            except FrozenInstanceError:
                self._rules[index] = replace(rule, **{field: value})  # type: ignore[type-var]
            logger.warning("RiskManager.patch_threshold: %s.%s set to %s", rule_id, field, value)
            return self._rules[index]

        raise RiskThresholdPatchError(f"no active rule with id {rule_id!r} in this manager")

    @property
    def rules(self) -> tuple[RiskRule, ...]:
        return tuple(self._rules)

    def check(
        self,
        intent: OrderIntent,
        *,
        ctx: StrategyContext,
        portfolio: Portfolio,
        candle: Candle,
    ) -> RiskCheckResult:
        for rule in self._rules:
            result = rule.check(intent, ctx=ctx, portfolio=portfolio, candle=candle)
            if not result.allowed:
                logger.info(
                    "RiskManager blocked intent: %s (%s)",
                    result.rule_id,
                    result.reason,
                )
                return result
        return RiskCheckResult.allow()
