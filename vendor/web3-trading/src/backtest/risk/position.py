# -*- coding: utf-8 -*-
"""
Position management — trailing stop, time stop, slippage model.

Extracted from the engine loop into a dedicated module for clean
separation (analogous to Claude Code separating tool execution from
the agent loop — toolExecution.ts vs query.ts).
"""

from __future__ import annotations

from typing import Optional, Tuple

from backtest.models import Trade, BacktestConfig


def check_exit(
    position: Trade,
    price: float,
    sig_score: float,
    bar_idx: int,
    config: BacktestConfig,
) -> Tuple[bool, str, float]:
    """Check all exit conditions for an open position.

    Returns:
        (should_exit, reason, net_pnl_pct)
    """
    entry = position.entry_price
    if position.direction == "LONG":
        pnl = (price - entry) / entry * 100
    else:
        pnl = (entry - price) / entry * 100

    # Apply slippage on exit
    pnl -= config.slippage_pct

    # --- Trailing stop ---
    if config.trailing_stop_pct > 0 and position.peak_price > 0:
        if position.direction == "LONG":
            trail_ref = position.peak_price * (1 - config.trailing_stop_pct / 100)
            if price <= trail_ref:
                net_pnl = pnl - config.commission_pct * 2
                return True, "移动止损", net_pnl
        else:
            # For SHORT, peak_price tracks the lowest price seen
            trail_ref = position.peak_price * (1 + config.trailing_stop_pct / 100)
            if price >= trail_ref:
                net_pnl = pnl - config.commission_pct * 2
                return True, "移动止损", net_pnl

    # --- Fixed stop loss ---
    if pnl <= -config.stop_loss_pct:
        net_pnl = pnl - config.commission_pct * 2
        return True, "止损", net_pnl

    # --- Fixed take profit ---
    if pnl >= config.take_profit_pct:
        net_pnl = pnl - config.commission_pct * 2
        return True, "止盈", net_pnl

    # --- Time stop (max bars held) ---
    bars_held = bar_idx - position.entry_idx
    if config.max_hold_bars > 0 and bars_held >= config.max_hold_bars:
        net_pnl = pnl - config.commission_pct * 2
        return True, "超时平仓", net_pnl

    # --- Signal reversal ---
    exit_threshold = 0.0  # could add to config
    if position.direction == "LONG" and sig_score <= -exit_threshold:
        net_pnl = pnl - config.commission_pct * 2
        return True, "信号反转", net_pnl
    if position.direction == "SHORT" and sig_score >= exit_threshold:
        net_pnl = pnl - config.commission_pct * 2
        return True, "信号反转", net_pnl

    return False, "", 0.0


def update_peak_price(position: Trade, price: float) -> None:
    """Update the peak price for trailing stop tracking."""
    if position.direction == "LONG":
        if price > position.peak_price:
            position.peak_price = price
    else:
        # For SHORT positions, track the lowest price (best for short)
        if position.peak_price == 0 or price < position.peak_price:
            position.peak_price = price


def close_position(
    position: Trade,
    price: float,
    bar_idx: int,
    ts: int,
    reason: str,
    commission_pct: float,
    slippage_pct: float = 0.0,
) -> Trade:
    """Close a position and compute final PnL."""
    entry = position.entry_price
    if position.direction == "LONG":
        pnl = (price - entry) / entry * 100
    else:
        pnl = (entry - price) / entry * 100

    net_pnl = pnl - commission_pct * 2 - slippage_pct
    position.exit_idx = bar_idx
    position.exit_price = price
    position.exit_ts = ts
    position.pnl_pct = net_pnl
    position.exit_reason = reason
    position.bars_held = bar_idx - position.entry_idx
    return position
