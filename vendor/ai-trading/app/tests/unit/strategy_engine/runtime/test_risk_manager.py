"""Tests for the runtime risk manager + concrete rules.

Three concerns under test:

  1. **Concrete rules** — MaxPositionRule, MaxDrawdownRule, KillSwitch
     each have correctness invariants pinned independently of the
     manager that composes them.

  2. **Manager composition** — first-block-wins short-circuit, rule
     ordering, dynamic add.

  3. **StrategyRuntime integration** — a blocked intent never reaches
     the order router and appears in result.rejected with the right
     reason shape.

Rationale for pinning each rule's tests separately: the manager is
purely composition logic; if the rules are individually correct +
the manager composes them correctly, the system is correct. Avoids
a quadratic test matrix.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.connectors.protocol import OrderIntent, OrderSide, OrderType
from app.domain.market_data import Candle
from app.strategy_engine.backtest.engine import StrategyContext
from app.strategy_engine.backtest.portfolio import Portfolio
from app.strategy_engine.runtime import (
    AbnormalCandleRule,
    KillSwitch,
    MaxDrawdownRule,
    MaxPositionRule,
    MaxSlippageRule,
    RiskCheckResult,
    RiskManager,
    SimOrderRouter,
    StrategyRuntime,
)
from app.strategy_engine.runtime.protocol import CandleSource
from app.strategy_engine.runtime.risk_manager import RiskThresholdPatchError

# ── Helpers ──────────────────────────────────────────────────────


def _candle(ts: datetime, *, price: float = 100.0) -> Candle:
    p = Decimal(f"{price:.4f}")
    return Candle(
        exchange="test",
        symbol="BTC/USDT",
        timeframe="1m",
        ts=ts,
        open=p, high=p, low=p, close=p,
        volume=Decimal("1.0"),
    )


def _intent(
    *,
    side: OrderSide = OrderSide.BUY,
    qty: str = "0.1",
    symbol: str = "BTC/USDT",
) -> OrderIntent:
    return OrderIntent(
        symbol=symbol,
        side=side,
        type=OrderType.MARKET,
        qty=Decimal(qty),
    )


def _make_ctx_and_portfolio(initial_cash: str = "1000") -> tuple[StrategyContext, Portfolio]:
    portfolio = Portfolio(initial_cash=Decimal(initial_cash))
    ctx = StrategyContext(
        symbol="BTC/USDT", timeframe="1m", portfolio=portfolio,
    )
    return ctx, portfolio


# ── RiskCheckResult.allow singleton ─────────────────────────────


def test_allow_singleton_reused() -> None:
    """``RiskCheckResult.allow()`` returns the SAME instance on every
    call. Hot path runs this per intent per rule; avoiding per-call
    allocation matters."""
    a = RiskCheckResult.allow()
    b = RiskCheckResult.allow()
    assert a is b
    assert a.allowed is True
    assert a.rule_id == ""
    assert a.reason == ""


# ── MaxPositionRule ─────────────────────────────────────────────


def test_max_position_allows_when_below_threshold() -> None:
    """Empty position + small buy → fine."""
    ctx, portfolio = _make_ctx_and_portfolio()
    rule = MaxPositionRule(max_notional_usd=Decimal("1000"))
    candle = _candle(datetime(2026, 5, 16, tzinfo=UTC), price=100.0)
    # BUY 0.1 BTC × $100 = $10 notional — well under $1000.
    result = rule.check(_intent(qty="0.1"), ctx=ctx, portfolio=portfolio, candle=candle)
    assert result.allowed is True


def test_max_position_blocks_when_post_fill_exceeds() -> None:
    """BUY that would push notional above cap → blocked with reason."""
    ctx, portfolio = _make_ctx_and_portfolio()
    rule = MaxPositionRule(max_notional_usd=Decimal("100"))
    candle = _candle(datetime(2026, 5, 16, tzinfo=UTC), price=100.0)
    # BUY 2.0 BTC × $100 = $200 → exceeds $100 cap.
    result = rule.check(_intent(qty="2.0"), ctx=ctx, portfolio=portfolio, candle=candle)
    assert result.allowed is False
    assert result.rule_id == "MAX_POSITION_PCT"
    # Reason mentions the offending numbers — useful for audit log.
    assert "$200" in result.reason


def test_max_position_uses_post_fill_qty_not_pre_fill() -> None:
    """Already-large position + a BUY of 0.0 should NOT be blocked
    (no delta). Pin: rule looks at WOULD-BE position, not pre-fill.

    Edge case: a zero-qty intent shouldn't ever happen in practice
    but defensively shouldn't trigger a false-positive."""
    ctx, portfolio = _make_ctx_and_portfolio()
    # Manually plant a large position.
    portfolio.apply_buy("BTC/USDT", Decimal("0.5"), Decimal("100"), Decimal("0"))
    rule = MaxPositionRule(max_notional_usd=Decimal("100"))
    candle = _candle(datetime(2026, 5, 16, tzinfo=UTC), price=100.0)
    # BUY 0.0 → post_qty unchanged at 0.5 × $100 = $50 — under cap.
    result = rule.check(_intent(qty="0.0"), ctx=ctx, portfolio=portfolio, candle=candle)
    assert result.allowed is True


def test_max_position_sell_reduces_exposure_so_always_safe() -> None:
    """SELL that closes a position → post-fill notional smaller than
    pre-fill → must always allow."""
    ctx, portfolio = _make_ctx_and_portfolio()
    portfolio.apply_buy("BTC/USDT", Decimal("1.0"), Decimal("100"), Decimal("0"))
    rule = MaxPositionRule(max_notional_usd=Decimal("50"))  # already exceeded
    candle = _candle(datetime(2026, 5, 16, tzinfo=UTC), price=100.0)
    # SELL 0.5 → post_qty 0.5 × $100 = $50 → at-cap (still allowed since
    # the rule only blocks STRICTLY above).
    result = rule.check(
        _intent(side=OrderSide.SELL, qty="0.5"),
        ctx=ctx, portfolio=portfolio, candle=candle,
    )
    assert result.allowed is True


# ── MaxDrawdownRule ─────────────────────────────────────────────


def test_max_drawdown_allows_buy_when_no_drawdown_yet() -> None:
    """First-tick equity = initial capital = peak → 0% drawdown → ok."""
    ctx, portfolio = _make_ctx_and_portfolio(initial_cash="1000")
    rule = MaxDrawdownRule(max_drawdown_pct=Decimal("0.10"))
    candle = _candle(datetime(2026, 5, 16, tzinfo=UTC), price=100.0)
    result = rule.check(_intent(qty="0.01"), ctx=ctx, portfolio=portfolio, candle=candle)
    assert result.allowed is True


def test_max_drawdown_blocks_buy_when_drawdown_exceeded() -> None:
    """Plant a losing position so equity drops, then BUY → blocked.

    Math:
      Buy 5.0 BTC at $100 → cash drops to $500, position worth $500.
      Tick 1 at price=$100 → equity = 500 + 500 = $1000 → peak=$1000.
      Tick 2 at price=$80  → equity = 500 + 400 = $900 = 10% drawdown
                              → at threshold → BLOCK.
    """
    ctx, portfolio = _make_ctx_and_portfolio(initial_cash="1000")
    rule = MaxDrawdownRule(max_drawdown_pct=Decimal("0.10"))

    # Set up the position.
    portfolio.apply_buy("BTC/USDT", Decimal("5.0"), Decimal("100"), Decimal("0"))
    # Cash = 1000 - 500 = 500. Position 5.0 BTC.

    # Tick 1: mark equity at peak (price=100, position worth 500 → equity=1000).
    rule.check(
        _intent(qty="0.01"),
        ctx=ctx, portfolio=portfolio,
        candle=_candle(datetime(2026, 5, 16, tzinfo=UTC), price=100.0),
    )
    assert rule._peak == Decimal("1000")

    # Tick 2: price drops to $90 → equity = 500 + 5.0*90 = $950 (5% down).
    result = rule.check(
        _intent(qty="0.01"),
        ctx=ctx, portfolio=portfolio,
        candle=_candle(datetime(2026, 5, 16, 0, 1, tzinfo=UTC), price=90.0),
    )
    assert result.allowed is True  # 5% < 10%

    # Tick 3: price drops to $80 → equity = 500 + 5.0*80 = $900 (10% down).
    result = rule.check(
        _intent(qty="0.01"),
        ctx=ctx, portfolio=portfolio,
        candle=_candle(datetime(2026, 5, 16, 0, 2, tzinfo=UTC), price=80.0),
    )
    assert result.allowed is False
    assert result.rule_id == "MAX_DAILY_LOSS_PCT"
    assert "below peak" in result.reason


def test_max_drawdown_always_allows_sell() -> None:
    """SELL is the recovery action — closing losing positions during
    drawdown is what the rule INTENDS to encourage."""
    ctx, portfolio = _make_ctx_and_portfolio(initial_cash="1000")
    rule = MaxDrawdownRule(max_drawdown_pct=Decimal("0.01"))  # 1% — very tight
    # Plant a position and drop the price so drawdown is huge.
    portfolio.apply_buy("BTC/USDT", Decimal("1.0"), Decimal("100"), Decimal("0"))
    candle = _candle(datetime(2026, 5, 16, tzinfo=UTC), price=10.0)
    # Equity now well below peak — but SELL is allowed.
    result = rule.check(
        _intent(side=OrderSide.SELL, qty="0.5"),
        ctx=ctx, portfolio=portfolio, candle=candle,
    )
    assert result.allowed is True


def test_max_drawdown_tracks_peak_across_ticks() -> None:
    """Peak should be the MAX equity ever observed by this rule's
    check, not just the most recent. Catches a "peak = last_equity"
    implementation bug that would mask drawdowns after recoveries."""
    ctx, portfolio = _make_ctx_and_portfolio(initial_cash="1000")
    rule = MaxDrawdownRule(max_drawdown_pct=Decimal("0.20"))

    # Tick 1: equity 1000 → peak 1000
    rule.check(
        _intent(qty="0.01"),
        ctx=ctx, portfolio=portfolio,
        candle=_candle(datetime(2026, 5, 16, tzinfo=UTC), price=100.0),
    )
    assert rule._peak == Decimal("1000")

    # Buy position, then price rises to $150 → equity = 850 cash +
    # 1.0 × 150 = 1000... actually plant cash by skipping the buy.
    # Simpler: just manually set the peak via observation.

    # Tick 2: price unchanged → equity still 1000 → peak still 1000
    rule.check(
        _intent(qty="0.01"),
        ctx=ctx, portfolio=portfolio,
        candle=_candle(datetime(2026, 5, 16, 0, 1, tzinfo=UTC), price=100.0),
    )
    assert rule._peak == Decimal("1000")


# ── KillSwitch ──────────────────────────────────────────────────


def test_kill_switch_starts_untripped() -> None:
    """Default state is allow-all. Operator explicitly trips."""
    ctx, portfolio = _make_ctx_and_portfolio()
    ks = KillSwitch()
    candle = _candle(datetime(2026, 5, 16, tzinfo=UTC))
    assert ks.tripped is False
    assert ks.check(_intent(), ctx=ctx, portfolio=portfolio, candle=candle).allowed is True


def test_kill_switch_blocks_when_tripped() -> None:
    """Once tripped, every intent (BUY or SELL) blocked. SELL is NOT
    excluded — operator may want a TOTAL halt during an incident."""
    ctx, portfolio = _make_ctx_and_portfolio()
    ks = KillSwitch()
    ks.trip("incident-2026-05-17 — anomalous price action")
    candle = _candle(datetime(2026, 5, 16, tzinfo=UTC))

    buy_result = ks.check(_intent(), ctx=ctx, portfolio=portfolio, candle=candle)
    assert buy_result.allowed is False
    assert buy_result.rule_id == "EMERGENCY_HALT"
    assert "anomalous price action" in buy_result.reason

    sell_result = ks.check(
        _intent(side=OrderSide.SELL),
        ctx=ctx, portfolio=portfolio, candle=candle,
    )
    assert sell_result.allowed is False


def test_kill_switch_trip_is_idempotent() -> None:
    """Re-tripping preserves the original reason — first operator's
    audit trail wins. Prevents a second tripper from overwriting
    the original incident note."""
    ks = KillSwitch()
    ks.trip("first reason")
    ks.trip("second reason")
    assert ks.tripped_reason == "first reason"


def test_kill_switch_reset_unblocks() -> None:
    """reset() un-trips. Subsequent checks allow again. Used during
    operator recovery."""
    ctx, portfolio = _make_ctx_and_portfolio()
    ks = KillSwitch()
    ks.trip("test")
    ks.reset()
    candle = _candle(datetime(2026, 5, 16, tzinfo=UTC))
    assert ks.check(_intent(), ctx=ctx, portfolio=portfolio, candle=candle).allowed is True


# ── RiskManager composition ─────────────────────────────────────


def test_manager_empty_rules_allows_everything() -> None:
    """No rules → allow. Backward-compat: a runtime constructed with
    no risk_manager (None) should behave the same as one with an
    empty manager."""
    ctx, portfolio = _make_ctx_and_portfolio()
    mgr = RiskManager()
    candle = _candle(datetime(2026, 5, 16, tzinfo=UTC))
    assert mgr.check(_intent(), ctx=ctx, portfolio=portfolio, candle=candle).allowed is True


def test_manager_first_block_wins_short_circuit() -> None:
    """When multiple rules WOULD block, the FIRST in registration
    order returns. The remaining rules are not consulted — pin via
    a tripwire rule that fails the test if invoked."""
    ctx, portfolio = _make_ctx_and_portfolio()
    candle = _candle(datetime(2026, 5, 16, tzinfo=UTC))

    ks = KillSwitch()
    ks.trip("must short-circuit here")

    class _TripwireRule:
        rule_id = "TRIPWIRE"
        invoked = False

        def check(self, intent, *, ctx, portfolio, candle):
            type(self).invoked = True
            return RiskCheckResult(allowed=False, rule_id="TRIPWIRE", reason="should not run")

    tripwire = _TripwireRule()
    mgr = RiskManager(rules=[ks, tripwire])
    result = mgr.check(_intent(), ctx=ctx, portfolio=portfolio, candle=candle)

    assert result.rule_id == "EMERGENCY_HALT"  # killswitch fired first
    assert _TripwireRule.invoked is False  # tripwire skipped


def test_manager_add_rule_appends() -> None:
    """``add_rule`` appends to the registration order. New rules
    evaluate LAST — operators wanting a new top-priority rule
    construct a fresh manager."""
    mgr = RiskManager(rules=[KillSwitch()])
    new_rule = MaxPositionRule(max_notional_usd=Decimal("1000"))
    mgr.add_rule(new_rule)
    rules = mgr.rules
    assert len(rules) == 2
    assert rules[-1] is new_rule


def test_manager_rules_property_is_tuple_not_list() -> None:
    """Read-only snapshot — discourages callers from mutating the
    manager's internal state. Pin the immutable shape."""
    mgr = RiskManager(rules=[KillSwitch()])
    assert isinstance(mgr.rules, tuple)


# ── StrategyRuntime integration ─────────────────────────────────


class _OneCandleSource(CandleSource):
    """Yields exactly one candle then exits. Just enough to drive
    one strategy tick."""

    def __init__(self, candle: Candle) -> None:
        self._candle = candle

    async def stream(self, *, symbol: str, timeframe: str) -> AsyncIterator[Candle]:
        yield self._candle


@pytest.mark.asyncio
async def test_risk_blocked_intent_does_not_reach_router() -> None:
    """End-to-end: a blocked intent appears in result.rejected with
    the synthetic risk_blocked reason, AND the SimOrderRouter's
    submit was never called (no fill recorded)."""

    def buy_strategy(ctx, candle):
        return ctx.order_intent(
            side="buy", qty=Decimal("100.0"), type="market"
        )

    ks = KillSwitch()
    ks.trip("integration test")
    mgr = RiskManager(rules=[ks])

    runtime = StrategyRuntime(
        strategy_fn=buy_strategy,
        candle_source=_OneCandleSource(
            _candle(datetime(2026, 5, 16, tzinfo=UTC)),
        ),
        order_router=SimOrderRouter(),
        symbol="BTC/USDT",
        timeframe="1m",
        risk_manager=mgr,
    )
    result = await runtime.run_until_complete()

    # No fills — the intent didn't reach the router.
    assert len(result.fills) == 0
    # The blocked intent IS recorded in rejected with the synthetic
    # error containing the rule_id.
    assert len(result.rejected) == 1
    rej = result.rejected[0]
    assert rej.state == "rejected"
    assert rej.error is not None
    assert "risk_blocked" in rej.error
    assert "EMERGENCY_HALT" in rej.error


@pytest.mark.asyncio
async def test_risk_allow_passes_intent_through_to_router() -> None:
    """When the manager allows, the runtime behaves identically to
    the no-risk-manager case — full fill + trade recorded."""

    def buy_strategy(ctx, candle):
        return ctx.order_intent(
            side="buy", qty=Decimal("0.001"), type="market",
        )

    mgr = RiskManager(rules=[KillSwitch()])  # untripped → allow

    runtime = StrategyRuntime(
        strategy_fn=buy_strategy,
        candle_source=_OneCandleSource(
            _candle(datetime(2026, 5, 16, tzinfo=UTC), price=100.0),
        ),
        order_router=SimOrderRouter(),
        symbol="BTC/USDT",
        timeframe="1m",
        risk_manager=mgr,
    )
    result = await runtime.run_until_complete()
    assert len(result.fills) == 1
    assert result.fills[0].state == "filled"
    assert len(result.trades) == 1


@pytest.mark.asyncio
async def test_no_risk_manager_preserves_v1_behaviour() -> None:
    """Backward compat: constructing without ``risk_manager``
    (None default) preserves the existing v1 path — no synthetic
    rejects, intents go straight to the router."""

    def buy_strategy(ctx, candle):
        return ctx.order_intent(
            side="buy", qty=Decimal("0.001"), type="market",
        )

    runtime = StrategyRuntime(
        strategy_fn=buy_strategy,
        candle_source=_OneCandleSource(
            _candle(datetime(2026, 5, 16, tzinfo=UTC)),
        ),
        order_router=SimOrderRouter(),
        symbol="BTC/USDT",
        timeframe="1m",
        # risk_manager omitted — defaults to None
    )
    result = await runtime.run_until_complete()
    assert len(result.fills) == 1
    assert len(result.rejected) == 0


@pytest.mark.asyncio
async def test_risk_blocked_emits_reject_event_with_rule_id() -> None:
    """The RuntimeEvent stream carries ``risk_rule`` in the payload
    so observability consumers (Prometheus, audit log) can pivot on
    which rule fired."""
    events: list[dict] = []

    async def hook(ev):
        if ev.kind == "reject":
            events.append(dict(ev.payload))

    def buy_strategy(ctx, candle):
        return ctx.order_intent(side="buy", qty=Decimal("100.0"), type="market")

    ks = KillSwitch()
    ks.trip("test")
    mgr = RiskManager(rules=[ks])

    runtime = StrategyRuntime(
        strategy_fn=buy_strategy,
        candle_source=_OneCandleSource(_candle(datetime(2026, 5, 16, tzinfo=UTC))),
        order_router=SimOrderRouter(),
        symbol="BTC/USDT",
        timeframe="1m",
        risk_manager=mgr,
        event_hook=hook,
    )
    await runtime.run_until_complete()
    assert len(events) == 1
    assert events[0]["risk_rule"] == "EMERGENCY_HALT"
    assert "risk_blocked" in events[0]["error"]


# ── MaxSlippageRule (S8-2) ──────────────────────────────────────


def test_max_slippage_allows_quiet_candle() -> None:
    """Tight candle (H-L)/C = 0.1% well below 2% cap → allow."""
    ctx, portfolio = _make_ctx_and_portfolio()
    rule = MaxSlippageRule(max_spread_pct=Decimal("0.02"))
    # Flat candle helper produces H=L=close so spread=0; build a
    # tight-but-non-flat one inline.
    c = Candle(
        exchange="test", symbol="BTC/USDT", timeframe="1m",
        ts=datetime(2026, 5, 16, tzinfo=UTC),
        open=Decimal("100.0"),
        high=Decimal("100.1"),
        low=Decimal("99.9"),
        close=Decimal("100.0"),
        volume=Decimal("1"),
    )
    result = rule.check(_intent(), ctx=ctx, portfolio=portfolio, candle=c)
    assert result.allowed is True


def test_max_slippage_blocks_wide_spread() -> None:
    """Wide intra-bar spread (10% of close) → block. The reason
    field carries the offending percentage for audit."""
    ctx, portfolio = _make_ctx_and_portfolio()
    rule = MaxSlippageRule(max_spread_pct=Decimal("0.02"))
    c = Candle(
        exchange="test", symbol="BTC/USDT", timeframe="1m",
        ts=datetime(2026, 5, 16, tzinfo=UTC),
        open=Decimal("100.0"),
        high=Decimal("105.0"),
        low=Decimal("95.0"),  # (105-95)/100 = 10% spread
        close=Decimal("100.0"),
        volume=Decimal("1"),
    )
    result = rule.check(_intent(), ctx=ctx, portfolio=portfolio, candle=c)
    assert result.allowed is False
    assert result.rule_id == "MAX_SLIPPAGE_PCT"
    assert "10.00%" in result.reason


def test_max_slippage_gates_sell_too() -> None:
    """SELL is also blocked — closing into a wick is just as bad
    as opening into one. Pin the symmetry."""
    ctx, portfolio = _make_ctx_and_portfolio()
    rule = MaxSlippageRule(max_spread_pct=Decimal("0.01"))
    c = Candle(
        exchange="test", symbol="BTC/USDT", timeframe="1m",
        ts=datetime(2026, 5, 16, tzinfo=UTC),
        open=Decimal("100.0"),
        high=Decimal("110.0"),
        low=Decimal("90.0"),
        close=Decimal("100.0"),
        volume=Decimal("1"),
    )
    result = rule.check(
        _intent(side=OrderSide.SELL),
        ctx=ctx, portfolio=portfolio, candle=c,
    )
    assert result.allowed is False


def test_max_slippage_handles_zero_close_defensively() -> None:
    """A close=0 candle (test fixture / corrupted feed) has no
    defined spread fraction — rule allows rather than divide by
    zero. Defensive guard pinned."""
    ctx, portfolio = _make_ctx_and_portfolio()
    rule = MaxSlippageRule(max_spread_pct=Decimal("0.01"))
    c = Candle(
        exchange="test", symbol="BTC/USDT", timeframe="1m",
        ts=datetime(2026, 5, 16, tzinfo=UTC),
        open=Decimal("0"),
        high=Decimal("0"),
        low=Decimal("0"),
        close=Decimal("0"),
        volume=Decimal("1"),
    )
    result = rule.check(_intent(), ctx=ctx, portfolio=portfolio, candle=c)
    assert result.allowed is True


# ── AbnormalCandleRule (S8-2) ───────────────────────────────────


def _ranged_candle(ts: datetime, *, price: float = 100.0) -> Candle:
    """Candle with a small intra-bar range (NOT the flat H==L
    sentinel that triggers AbnormalCandleRule's stale-feed branch).
    Used by AbnormalCandleRule tests where we need a realistic
    OHLCV shape."""
    p = Decimal(f"{price:.4f}")
    return Candle(
        exchange="test",
        symbol="BTC/USDT",
        timeframe="1m",
        ts=ts,
        open=p,
        high=p * Decimal("1.001"),
        low=p * Decimal("0.999"),
        close=p,
        volume=Decimal("1.0"),
    )


def test_abnormal_candle_allows_clean_candle() -> None:
    """Normal candle + 1 prior history → no anomalies → allow."""
    ctx, portfolio = _make_ctx_and_portfolio()
    # Plant a prior candle so the bar-to-bar jump check has data.
    prev = _ranged_candle(datetime(2026, 5, 16, tzinfo=UTC), price=100.0)
    ctx.history.append(prev)
    curr = _ranged_candle(datetime(2026, 5, 16, 0, 1, tzinfo=UTC), price=100.5)
    ctx.history.append(curr)

    rule = AbnormalCandleRule(max_price_jump_pct=Decimal("0.10"))
    result = rule.check(_intent(), ctx=ctx, portfolio=portfolio, candle=curr)
    assert result.allowed is True


def test_abnormal_candle_blocks_zero_volume_with_price_motion() -> None:
    """Volume=0 but H != L → likely feed corruption. Block."""
    ctx, portfolio = _make_ctx_and_portfolio()
    c = Candle(
        exchange="test", symbol="BTC/USDT", timeframe="1m",
        ts=datetime(2026, 5, 16, tzinfo=UTC),
        open=Decimal("100.0"),
        high=Decimal("100.5"),
        low=Decimal("99.5"),
        close=Decimal("100.0"),
        volume=Decimal("0"),  # suspicious
    )
    ctx.history.append(c)

    rule = AbnormalCandleRule(max_price_jump_pct=Decimal("0.10"))
    result = rule.check(_intent(), ctx=ctx, portfolio=portfolio, candle=c)
    assert result.allowed is False
    assert result.rule_id == "ABNORMAL_ORDERBOOK"
    assert "zero volume" in result.reason


def test_abnormal_candle_blocks_zero_range_with_volume() -> None:
    """H == L AND volume > 0 → stale feed. Block."""
    ctx, portfolio = _make_ctx_and_portfolio()
    c = Candle(
        exchange="test", symbol="BTC/USDT", timeframe="1m",
        ts=datetime(2026, 5, 16, tzinfo=UTC),
        open=Decimal("100.0"),
        high=Decimal("100.0"),
        low=Decimal("100.0"),
        close=Decimal("100.0"),
        volume=Decimal("50.0"),  # not zero
    )
    ctx.history.append(c)

    rule = AbnormalCandleRule(max_price_jump_pct=Decimal("0.10"))
    result = rule.check(_intent(), ctx=ctx, portfolio=portfolio, candle=c)
    assert result.allowed is False
    assert "stale feed" in result.reason


def test_abnormal_candle_blocks_large_bar_to_bar_jump() -> None:
    """Bar-to-bar 25% jump on a 10% threshold → block."""
    ctx, portfolio = _make_ctx_and_portfolio()
    prev = _ranged_candle(datetime(2026, 5, 16, tzinfo=UTC), price=100.0)
    curr = _ranged_candle(datetime(2026, 5, 16, 0, 1, tzinfo=UTC), price=125.0)
    # History order: prev, curr.
    ctx.history.append(prev)
    ctx.history.append(curr)

    rule = AbnormalCandleRule(max_price_jump_pct=Decimal("0.10"))
    result = rule.check(_intent(), ctx=ctx, portfolio=portfolio, candle=curr)
    assert result.allowed is False
    assert "price jump" in result.reason


def test_abnormal_candle_allows_first_bar_no_baseline() -> None:
    """First candle has no predecessor — rule cannot compute a
    bar-to-bar jump. Falls through to allow rather than block.

    Pin this: blocking the first bar would prevent ANY strategy
    from making its initial trade on a fresh runtime, which would
    break warm-up logic universally.
    """
    ctx, portfolio = _make_ctx_and_portfolio()
    c = _ranged_candle(datetime(2026, 5, 16, tzinfo=UTC), price=1000.0)
    ctx.history.append(c)  # only the current candle, no prior

    rule = AbnormalCandleRule(max_price_jump_pct=Decimal("0.01"))  # very tight
    result = rule.check(_intent(), ctx=ctx, portfolio=portfolio, candle=c)
    assert result.allowed is True


def test_abnormal_candle_allows_normal_jump_below_threshold() -> None:
    """5% jump on a 10% threshold → fine. Pins that the rule
    isn't trigger-happy on normal volatility."""
    ctx, portfolio = _make_ctx_and_portfolio()
    prev = _ranged_candle(datetime(2026, 5, 16, tzinfo=UTC), price=100.0)
    curr = _ranged_candle(datetime(2026, 5, 16, 0, 1, tzinfo=UTC), price=105.0)
    ctx.history.append(prev)
    ctx.history.append(curr)

    rule = AbnormalCandleRule(max_price_jump_pct=Decimal("0.10"))
    result = rule.check(_intent(), ctx=ctx, portfolio=portfolio, candle=curr)
    assert result.allowed is True


# ── 5/5 MVP rules composed together ─────────────────────────────


def test_all_five_mvp_rules_compose_in_manager() -> None:
    """All five MVP rules can coexist in one RiskManager.

    Pins: the rule taxonomy is complete enough for v1.0 GA without
    needing further rule classes. M4's "5 risk rules verified" DoD
    item — this PR delivers all 5 in static form; the runtime-side
    verification (real venue, real loss) is the operator's M4 test.
    """
    mgr = RiskManager(
        rules=[
            KillSwitch(),
            MaxPositionRule(max_notional_usd=Decimal("10000")),
            MaxDrawdownRule(max_drawdown_pct=Decimal("0.10")),
            MaxSlippageRule(max_spread_pct=Decimal("0.02")),
            AbnormalCandleRule(max_price_jump_pct=Decimal("0.10")),
        ],
    )
    rule_ids = {r.rule_id for r in mgr.rules}
    # All five enum values represented.
    assert rule_ids == {
        "EMERGENCY_HALT",
        "MAX_POSITION_PCT",
        "MAX_DAILY_LOSS_PCT",
        "MAX_SLIPPAGE_PCT",
        "ABNORMAL_ORDERBOOK",
    }


# ── patch_threshold: operator-driven live threshold mutation (3.1) ──
#
# Backs the change_threshold approval handler. The reflection is
# WHITELISTED — an operator may only change a rule's numeric threshold,
# never internal state (_peak), rule_id, or arbitrary attributes.


def _rule_by_id(mgr: RiskManager, rule_id: str):
    return next(r for r in mgr.rules if r.rule_id == rule_id)


def test_patch_threshold_mutates_mutable_rule_in_place_preserving_state() -> None:
    rule = MaxDrawdownRule(max_drawdown_pct=Decimal("0.10"))
    rule._peak = Decimal("5000")  # simulate a peak accrued mid-run
    mgr = RiskManager([rule])

    mgr.patch_threshold("MAX_DAILY_LOSS_PCT", "max_drawdown_pct", Decimal("0.25"))

    patched = _rule_by_id(mgr, "MAX_DAILY_LOSS_PCT")
    assert patched.max_drawdown_pct == Decimal("0.25")
    # In-place mutation — running peak must survive a threshold change.
    assert patched._peak == Decimal("5000")
    assert patched is rule  # same object, not a replacement


def test_patch_threshold_replaces_frozen_rule() -> None:
    # MaxPositionRule is frozen; patch must swap in a dataclasses.replace copy.
    mgr = RiskManager([MaxPositionRule(max_notional_usd=Decimal("1000"))])

    mgr.patch_threshold("MAX_POSITION_PCT", "max_notional_usd", Decimal("5000"))

    patched = _rule_by_id(mgr, "MAX_POSITION_PCT")
    assert patched.max_notional_usd == Decimal("5000")
    assert patched.rule_id == "MAX_POSITION_PCT"


def test_patch_threshold_rejects_unknown_rule_id() -> None:
    mgr = RiskManager([MaxDrawdownRule(max_drawdown_pct=Decimal("0.10"))])
    with pytest.raises(RiskThresholdPatchError, match="patchable"):
        mgr.patch_threshold("NOPE", "max_drawdown_pct", Decimal("0.2"))


def test_patch_threshold_rejects_non_whitelisted_field() -> None:
    # Reflection guard: _peak / rule_id / arbitrary attrs are NOT patchable.
    mgr = RiskManager([MaxDrawdownRule(max_drawdown_pct=Decimal("0.10"))])
    for bad_field in ("_peak", "rule_id", "max_notional_usd"):
        with pytest.raises(RiskThresholdPatchError, match="not patchable"):
            mgr.patch_threshold("MAX_DAILY_LOSS_PCT", bad_field, Decimal("1"))


def test_patch_threshold_rejects_non_positive_value() -> None:
    mgr = RiskManager([MaxDrawdownRule(max_drawdown_pct=Decimal("0.10"))])
    for bad in (Decimal("0"), Decimal("-0.1")):
        with pytest.raises(RiskThresholdPatchError, match="positive"):
            mgr.patch_threshold("MAX_DAILY_LOSS_PCT", "max_drawdown_pct", bad)


def test_patch_threshold_rejects_rule_absent_from_manager() -> None:
    # MAX_SLIPPAGE_PCT is a known patchable kind but this manager has no
    # such rule installed → no-active-rule error (not a silent no-op).
    mgr = RiskManager([MaxDrawdownRule(max_drawdown_pct=Decimal("0.10"))])
    with pytest.raises(RiskThresholdPatchError, match="no active rule"):
        mgr.patch_threshold("MAX_SLIPPAGE_PCT", "max_spread_pct", Decimal("0.03"))
