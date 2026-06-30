from __future__ import annotations

from datetime import datetime, timezone

UTC = timezone.utc
from decimal import Decimal

import pytest

from risk import (
    AbnormalCandleRule,
    KillSwitch,
    MaxDrawdownRule,
    MaxPositionRule,
    MaxSlippageRule,
    RiskCheckResult,
    RiskManager,
    RiskThresholdPatchError,
    default_risk_manager,
)
from strategy_engine.backtest.candles import Candle
from strategy_engine.backtest.engine import BacktestEngine, StrategyContext
from strategy_engine.backtest.portfolio import Portfolio
from strategy_engine.backtest.protocol import OrderIntent, OrderSide, OrderType


def _candle(ts: datetime, *, price: float = 100.0) -> Candle:
    close = Decimal(f"{price:.4f}")
    return Candle(
        exchange="test",
        symbol="BTC/USDT",
        timeframe="1m",
        ts=ts,
        open=close,
        high=close * Decimal("1.001"),
        low=close * Decimal("0.999"),
        close=close,
        volume=Decimal("1.0"),
    )


def _intent(*, side: OrderSide = OrderSide.BUY, qty: str = "0.1") -> OrderIntent:
    return OrderIntent(
        symbol="BTC/USDT",
        side=side,
        type=OrderType.MARKET,
        qty=Decimal(qty),
    )


def _ctx_portfolio(initial_cash: str = "1000") -> tuple[StrategyContext, Portfolio]:
    portfolio = Portfolio(initial_cash=Decimal(initial_cash))
    ctx = StrategyContext(symbol="BTC/USDT", timeframe="1m", portfolio=portfolio)
    return ctx, portfolio


def test_allow_singleton_reused() -> None:
    assert RiskCheckResult.allow() is RiskCheckResult.allow()


def test_max_position_blocks_when_post_fill_exceeds() -> None:
    ctx, portfolio = _ctx_portfolio()
    rule = MaxPositionRule(max_notional_usd=Decimal("100"))
    candle = _candle(datetime(2026, 5, 16, tzinfo=UTC), price=100.0)
    result = rule.check(_intent(qty="2.0"), ctx=ctx, portfolio=portfolio, candle=candle)
    assert result.allowed is False
    assert result.rule_id == "MAX_POSITION_PCT"


def test_max_drawdown_blocks_buy_when_drawdown_exceeded() -> None:
    ctx, portfolio = _ctx_portfolio(initial_cash="1000")
    rule = MaxDrawdownRule(max_drawdown_pct=Decimal("0.10"))
    portfolio.apply_buy("BTC/USDT", Decimal("5.0"), Decimal("100"), Decimal("0"))
    rule.check(
        _intent(qty="0.01"),
        ctx=ctx,
        portfolio=portfolio,
        candle=_candle(datetime(2026, 5, 16, tzinfo=UTC), price=100.0),
    )
    result = rule.check(
        _intent(qty="0.01"),
        ctx=ctx,
        portfolio=portfolio,
        candle=_candle(datetime(2026, 5, 16, 0, 2, tzinfo=UTC), price=80.0),
    )
    assert result.allowed is False
    assert result.rule_id == "MAX_DAILY_LOSS_PCT"


def test_kill_switch_blocks_when_tripped() -> None:
    ctx, portfolio = _ctx_portfolio()
    ks = KillSwitch()
    ks.trip("incident")
    candle = _candle(datetime(2026, 5, 16, tzinfo=UTC))
    result = ks.check(_intent(), ctx=ctx, portfolio=portfolio, candle=candle)
    assert result.allowed is False
    assert result.rule_id == "EMERGENCY_HALT"


def test_manager_first_block_wins_short_circuit() -> None:
    ctx, portfolio = _ctx_portfolio()
    candle = _candle(datetime(2026, 5, 16, tzinfo=UTC))
    ks = KillSwitch()
    ks.trip("must short-circuit here")

    class _TripwireRule:
        rule_id = "TRIPWIRE"
        invoked = False

        def check(self, intent, *, ctx, portfolio, candle):
            type(self).invoked = True
            return RiskCheckResult(allowed=False, rule_id="TRIPWIRE", reason="should not run")

    mgr = RiskManager(rules=[ks, _TripwireRule()])
    result = mgr.check(_intent(), ctx=ctx, portfolio=portfolio, candle=candle)
    assert result.rule_id == "EMERGENCY_HALT"
    assert _TripwireRule.invoked is False


def test_default_risk_manager_registers_five_mvp_rules() -> None:
    mgr = default_risk_manager(initial_capital=Decimal("10000"))
    assert {rule.rule_id for rule in mgr.rules} == {
        "EMERGENCY_HALT",
        "MAX_POSITION_PCT",
        "MAX_DAILY_LOSS_PCT",
        "MAX_SLIPPAGE_PCT",
        "ABNORMAL_ORDERBOOK",
    }


def test_patch_threshold_mutates_drawdown_rule_in_place() -> None:
    rule = MaxDrawdownRule(max_drawdown_pct=Decimal("0.10"))
    rule._peak = Decimal("5000")
    mgr = RiskManager([rule])
    mgr.patch_threshold("MAX_DAILY_LOSS_PCT", "max_drawdown_pct", Decimal("0.25"))
    patched = next(item for item in mgr.rules if item.rule_id == "MAX_DAILY_LOSS_PCT")
    assert patched.max_drawdown_pct == Decimal("0.25")
    assert patched._peak == Decimal("5000")


def test_patch_threshold_rejects_unknown_rule_id() -> None:
    mgr = RiskManager([MaxDrawdownRule(max_drawdown_pct=Decimal("0.10"))])
    with pytest.raises(RiskThresholdPatchError, match="patchable"):
        mgr.patch_threshold("NOPE", "max_drawdown_pct", Decimal("0.2"))


def test_backtest_engine_records_risk_rejection() -> None:
    candles = [_candle(datetime(2026, 5, 16, tzinfo=UTC), price=100.0)]

    def always_buy(ctx: StrategyContext, candle: Candle) -> OrderIntent:
        return ctx.order_intent("buy", Decimal("0.01"), type="market")

    ks = KillSwitch()
    ks.trip("integration test")
    engine = BacktestEngine(
        strategy_fn=always_buy,
        risk_manager=RiskManager(rules=[ks]),
    )
    result = engine.run(candles, symbol="BTC/USDT", timeframe="1m")
    assert len(result.trades) == 0
    assert len(result.risk_rejections) == 1
    assert result.risk_rejections[0].rule_id == "EMERGENCY_HALT"


def test_abnormal_candle_blocks_zero_range_with_volume() -> None:
    ctx, portfolio = _ctx_portfolio()
    candle = Candle(
        exchange="test",
        symbol="BTC/USDT",
        timeframe="1m",
        ts=datetime(2026, 5, 16, tzinfo=UTC),
        open=Decimal("100.0"),
        high=Decimal("100.0"),
        low=Decimal("100.0"),
        close=Decimal("100.0"),
        volume=Decimal("50.0"),
    )
    ctx.history.append(candle)
    rule = AbnormalCandleRule(max_price_jump_pct=Decimal("0.10"))
    result = rule.check(_intent(), ctx=ctx, portfolio=portfolio, candle=candle)
    assert result.allowed is False
    assert "stale feed" in result.reason


def test_max_slippage_blocks_wide_spread() -> None:
    ctx, portfolio = _ctx_portfolio()
    rule = MaxSlippageRule(max_spread_pct=Decimal("0.02"))
    candle = Candle(
        exchange="test",
        symbol="BTC/USDT",
        timeframe="1m",
        ts=datetime(2026, 5, 16, tzinfo=UTC),
        open=Decimal("100.0"),
        high=Decimal("105.0"),
        low=Decimal("95.0"),
        close=Decimal("100.0"),
        volume=Decimal("1"),
    )
    result = rule.check(_intent(), ctx=ctx, portfolio=portfolio, candle=candle)
    assert result.allowed is False
    assert result.rule_id == "MAX_SLIPPAGE_PCT"
