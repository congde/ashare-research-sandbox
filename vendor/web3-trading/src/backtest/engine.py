# -*- coding: utf-8 -*-
"""
Backtest Engine — async generator core loop.

This is the heart of the system, directly inspired by Claude Code's Agent Loop
(src/query.ts queryLoop).  Key architectural decisions:

1. **Async Generator**: The engine is an `async def` function that yields
   EngineEvent progress events and returns a BacktestResult.  This allows
   the caller (API layer or UI) to consume real-time progress without
   blocking.

2. **Immutable state snapshots**: Each iteration reads from a frozen config
   and mutates only local position/equity state, just like queryLoop's
   state = { ...newState } pattern.

3. **Pre-computed indicators**: compute_all_indicators() runs once before the
   loop (like Claude Code's prefetch pattern), giving O(1) lookups per candle.

4. **Hook lifecycle**: pre/post trade hooks fire at each entry/exit decision
   point (like Claude Code's runPreToolUseHooks / runPostToolUseHooks).

5. **Position management delegation**: check_exit() in risk/position.py
   handles all exit logic (like Claude Code's toolExecution.ts separated
   from query.ts).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from backtest.models import (
    BacktestConfig,
    BacktestResult,
    EngineEvent,
    EventType,
    Signal,
    Trade,
    WalkForwardResult,
)
from backtest.indicators import IndicatorSeries, compute_all_indicators
from backtest.metrics import compute_metrics
from backtest.hooks import HookContext, HookEvent, HookManager
from backtest.risk.position import check_exit, close_position, update_peak_price
from backtest.registry import get_strategy
from backtest.strategies.base import Strategy
from backtest.cache import cache_get, cache_put

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dynamic slippage model — Phase 2.4
# ---------------------------------------------------------------------------

def _compute_dynamic_slippage(
    candle: Dict,
    config: BacktestConfig,
    direction: str,
) -> float:
    """Compute volume-based dynamic slippage percentage.

    Model: slippage = base_slippage + factor * (1 / relative_volume)
    When volume is low, slippage increases (thin order book).
    When volume is high, slippage decreases (deep order book).

    Returns slippage as a percentage (e.g. 0.15 means 0.15%).
    """
    if not config.dynamic_slippage:
        return config.slippage_pct

    volume = float(candle.get("volume", 0))
    turnover = float(candle.get("turnover", 0))
    close = float(candle.get("close", 1))

    if volume <= 0 or close <= 0:
        return config.slippage_pct

    # Estimate trade size impact: assume we trade ~1% of candle volume
    # Slippage increases when volume is thin
    # Base: config.slippage_pct, amplified by volume impact
    vol_ratio = turnover / close if turnover > 0 else volume
    if vol_ratio <= 0:
        return config.slippage_pct

    # Square-root market impact model (Almgren-Chriss inspired)
    # Impact ∝ sqrt(trade_size / daily_volume) * factor
    import math
    trade_fraction = 0.01  # assume 1% of candle volume
    impact = math.sqrt(trade_fraction) * config.dynamic_slippage_factor

    # Spread component from high-low range
    high = float(candle.get("high", close))
    low = float(candle.get("low", close))
    if high > low > 0:
        spread_pct = (high - low) / close * 100 * 0.1  # 10% of candle range
    else:
        spread_pct = 0.0

    total_slippage = max(config.slippage_pct, impact + spread_pct)
    return min(total_slippage, 2.0)  # cap at 2%


def _compute_funding_cost(
    position: Trade,
    bars_held: int,
    config: BacktestConfig,
) -> float:
    """Compute cumulative funding rate cost for perpetual contracts.

    Funding is charged every 8 hours. Returns cost as percentage.
    A positive funding rate means longs pay shorts.
    """
    if config.funding_rate_pct == 0:
        return 0.0

    # Determine how many funding periods have passed
    kline_hours = {
        "15min": 0.25, "1hour": 1, "4hour": 4, "1day": 24,
    }
    hours_per_bar = kline_hours.get(config.kline_type, 1)
    total_hours = bars_held * hours_per_bar
    funding_periods = total_hours / 8.0  # funding every 8 hours

    # Longs pay positive funding, shorts receive it (and vice versa)
    if position.direction == "LONG":
        cost = funding_periods * config.funding_rate_pct
    else:
        cost = -funding_periods * config.funding_rate_pct

    return cost


# ---------------------------------------------------------------------------
# Core engine: synchronous generator (yields EngineEvent)
# ---------------------------------------------------------------------------

def run_backtest(
    candles: List[Dict],
    strategy: Strategy,
    params: Dict[str, Any],
    config: BacktestConfig,
    hook_manager: Optional[HookManager] = None,
) -> Tuple[List[Trade], List[Dict], List[Dict]]:
    """Run a rolling-window backtest.

    This is the synchronous version for direct use.
    Returns (trades, equity_curve, candle_signals).
    """
    trades: List[Trade] = []
    equity_curve: List[Dict] = []
    candle_signals: List[Dict] = []

    for event in _engine_loop(candles, strategy, params, config, hook_manager):
        if event.type == EventType.ENGINE_DONE and event.data:
            trades = event.data.get("trades", [])
            equity_curve = event.data.get("equity_curve", [])
            candle_signals = event.data.get("candle_signals", [])

    return trades, equity_curve, candle_signals


def _engine_loop(
    candles: List[Dict],
    strategy: Strategy,
    params: Dict[str, Any],
    config: BacktestConfig,
    hook_manager: Optional[HookManager] = None,
):
    """Generator-based engine loop — yields EngineEvent on each step.

    Architecture mirrors Claude Code's queryLoop (src/query.ts:307):
    - 1. Initialize state (indicators, config snapshot)
    - 2. Main loop over candles (like the while(true) in queryLoop)
    - 3. Check exit conditions (like tool execution completion)
    - 4. Check entry conditions (like new tool_use blocks)
    - 5. Yield progress events (like Claude Code's yield StreamEvent)
    - 6. Produce final result
    """
    hooks = hook_manager or HookManager()

    # --- Phase 1: Pre-compute indicators (prefetch pattern) ---
    indicators = compute_all_indicators(candles)

    # --- Fire engine start hook ---
    hooks.fire(HookContext(event=HookEvent.ON_ENGINE_START, config=config))

    yield EngineEvent(type=EventType.ENGINE_START, data={"total_candles": len(candles)})

    # Let strategy do its own pre-computation (e.g., foundation model)
    strategy.prepare(candles, params)

    # --- Phase 2: State initialization ---
    entry_threshold = params.get("entry_threshold", 25)
    equity = 100.0
    peak_equity = 100.0
    position: Optional[Trade] = None
    effective_start = max(config.min_context, config.start_from)

    trades: List[Trade] = []
    equity_curve: List[Dict] = []
    candle_signals: List[Dict] = []

    # --- Phase 3: Main loop (candle by candle, like queryLoop iterations) ---
    for i in range(config.min_context, len(candles)):
        c = candles[i]

        # Generate signal (O(1) lookup for incremental strategies)
        signal = strategy.generate_signal(candles, i, params, indicators)
        action = signal.action
        sig_score = signal.score

        if i >= effective_start:
            candle_signals.append({
                "idx": i,
                "ts": c["tsSec"],
                "close": c["close"],
                "action": action,
                "score": sig_score,
            })

        # --- Exit check (delegated to risk/position.py) ---
        if position is not None:
            price = c["close"]

            # Update trailing stop tracker
            update_peak_price(position, price)

            should_exit, reason, net_pnl = check_exit(
                position, price, sig_score, i, config,
            )

            if should_exit:
                # Fire pre-exit hook
                exit_ctx = hooks.fire(HookContext(
                    event=HookEvent.PRE_TRADE_EXIT,
                    trade=position, candle=c, reason=reason, pnl_pct=net_pnl,
                ))

                position = close_position(
                    position, price, i, c["tsSec"], reason,
                    config.commission_pct, config.slippage_pct,
                )

                if i >= effective_start:
                    trades.append(position)

                # Fire post-exit hook
                hooks.fire(HookContext(
                    event=HookEvent.POST_TRADE_EXIT,
                    trade=position, candle=c, pnl_pct=position.pnl_pct,
                ))

                # Apply funding rate cost for perpetual contracts
                funding_cost = _compute_funding_cost(
                    position, position.bars_held, config,
                )
                adjusted_pnl = position.pnl_pct - funding_cost

                equity *= (1 + adjusted_pnl / 100)
                position = None

                yield EngineEvent(type=EventType.TRADE_CLOSED, idx=i)

        # --- Entry check ---
        if position is None:
            should_enter = False
            direction = ""

            if action == "LONG" and sig_score >= entry_threshold:
                should_enter = True
                direction = "LONG"
            elif action == "SHORT" and sig_score <= -entry_threshold:
                should_enter = True
                direction = "SHORT"

            if should_enter:
                # Fire pre-entry hook (can block)
                entry_ctx = hooks.fire(HookContext(
                    event=HookEvent.PRE_TRADE_ENTRY,
                    signal=signal, candle=c,
                    metadata={"regime": indicators.regime[i] if i < len(indicators.regime) else "unknown"},
                ))

                if not entry_ctx.block:
                    entry_price = c["close"]
                    # Apply slippage on entry (dynamic or fixed)
                    slip_pct = _compute_dynamic_slippage(c, config, direction)
                    if slip_pct > 0:
                        if direction == "LONG":
                            entry_price *= (1 + slip_pct / 100)
                        else:
                            entry_price *= (1 - slip_pct / 100)

                    position = Trade(
                        entry_idx=i,
                        entry_price=entry_price,
                        entry_ts=c["tsSec"],
                        direction=direction,
                        peak_price=entry_price,
                    )

                    # Fire post-entry hook
                    hooks.fire(HookContext(
                        event=HookEvent.POST_TRADE_ENTRY,
                        trade=position, candle=c,
                    ))

                    yield EngineEvent(type=EventType.TRADE_OPENED, idx=i)

        # --- Record equity curve ---
        if i >= effective_start:
            peak_equity = max(peak_equity, equity)
            drawdown = (peak_equity - equity) / peak_equity * 100 if peak_equity > 0 else 0
            equity_curve.append({
                "idx": i,
                "ts": c["tsSec"],
                "close": c["close"],
                "equity": round(equity, 4),
                "drawdown": round(drawdown, 2),
                "inPosition": position is not None,
            })

        yield EngineEvent(type=EventType.CANDLE_PROCESSED, idx=i)

    # --- Close any open position at last candle ---
    if position is not None and candles:
        last = candles[-1]
        position = close_position(
            position, last["close"], len(candles) - 1, last["tsSec"],
            "回测结束", config.commission_pct, config.slippage_pct,
        )
        trades.append(position)
        equity *= (1 + position.pnl_pct / 100)
        if equity_curve:
            equity_curve[-1]["equity"] = round(equity, 4)

    # --- Fire engine done hook ---
    hooks.fire(HookContext(event=HookEvent.ON_ENGINE_DONE))

    yield EngineEvent(
        type=EventType.ENGINE_DONE,
        data={
            "trades": trades,
            "equity_curve": equity_curve,
            "candle_signals": candle_signals,
        },
    )


# ---------------------------------------------------------------------------
# High-level entry point: fetch data + run engine + return result
# ---------------------------------------------------------------------------

async def execute_backtest(
    symbol: str,
    kline_type: str = "1hour",
    limit: int = 300,
    stop_loss_pct: float = 3.0,
    take_profit_pct: float = 5.0,
    trailing_stop_pct: float = 0.0,
    max_hold_bars: int = 0,
    strategy_name: str = "technical_signal",
    optimize: bool = False,
) -> BacktestResult:
    """Fetch K-line data and run a full backtest.

    This is the top-level async entry point, analogous to backtest_service.execute_backtest
    but using the new engine architecture.
    """
    from web.api.dashboard_service import kucoin_get, normalize_candle

    data = await kucoin_get(f"/api/v1/market/candles?symbol={symbol}&type={kline_type}")
    raw = (data.get("data") or [])[:limit]
    candles = sorted(
        [c for c in (normalize_candle(r) for r in raw) if c],
        key=lambda x: x["tsSec"],
    )

    if len(candles) < 60:
        raise ValueError(f"K线数据不足: 需要至少60根, 仅获取 {len(candles)} 根")

    strategy = get_strategy(strategy_name)
    params = dict(strategy.default_params())

    cached = cache_get(
        symbol=symbol,
        kline_type=kline_type,
        limit=limit,
        strategy_name=strategy_name,
        params=params,
        stop_loss=stop_loss_pct,
        take_profit=take_profit_pct,
    )
    if cached is not None and not optimize:
        return cached

    config = BacktestConfig(
        min_context=60,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        trailing_stop_pct=trailing_stop_pct,
        max_hold_bars=max_hold_bars,
        kline_type=kline_type,
    )

    # --- Optional: Walk-forward optimization ---
    wf_result = None
    if optimize and strategy.param_grid():
        from backtest.optimization.walk_forward import walk_forward_optimize
        wf_result = walk_forward_optimize(
            candles, strategy,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            kline_type=kline_type,
        )
        params = wf_result.best_params
        logger.info("[Backtest] Walk-forward optimized params: %s", params)

    # --- Run engine ---
    trades, equity_curve, candle_signals = run_backtest(
        candles, strategy, params, config,
    )

    # --- Compute metrics ---
    result = compute_metrics(
        trades=trades,
        equity_curve=equity_curve,
        candles=candles,
        symbol=symbol,
        kline_type=kline_type,
        strategy_name=strategy.display_name,
    )
    result.candle_signals = candle_signals

    # --- Attach walk-forward metadata ---
    if wf_result:
        from dataclasses import asdict as _asdict
        result.walk_forward = _asdict(wf_result)

    cache_put(
        symbol=symbol,
        kline_type=kline_type,
        limit=limit,
        strategy_name=strategy_name,
        params=params,
        stop_loss=stop_loss_pct,
        take_profit=take_profit_pct,
        result=result,
    )

    return result
