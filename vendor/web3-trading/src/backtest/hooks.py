# -*- coding: utf-8 -*-
"""
Lifecycle hooks — analogous to Claude Code's hooks system (src/utils/hooks/).

Provides pre/post trade hooks and other lifecycle events that allow
custom logic to be injected into the backtest engine without modifying
the core loop.  Hooks can be registered globally or per-run.

Hook events:
  - PreTradeEntry(trade, candle, signal)   → can block entry
  - PostTradeEntry(trade, candle)
  - PreTradeExit(trade, candle, reason)    → can override exit
  - PostTradeExit(trade, candle, pnl)
  - OnEngineStart(config, candles)
  - OnEngineDone(result)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from backtest.models import Signal, Trade, BacktestConfig

logger = logging.getLogger(__name__)


class HookEvent(str, Enum):
    PRE_TRADE_ENTRY = "pre_trade_entry"
    POST_TRADE_ENTRY = "post_trade_entry"
    PRE_TRADE_EXIT = "pre_trade_exit"
    POST_TRADE_EXIT = "post_trade_exit"
    ON_ENGINE_START = "on_engine_start"
    ON_ENGINE_DONE = "on_engine_done"


@dataclass
class HookContext:
    """Mutable context passed to hooks — hooks can modify fields to alter behavior."""
    event: HookEvent
    candle: Optional[Dict[str, Any]] = None
    trade: Optional[Trade] = None
    signal: Optional[Signal] = None
    config: Optional[BacktestConfig] = None
    reason: str = ""
    pnl_pct: float = 0.0
    # Hook can set this to True to block the action
    block: bool = False
    # Extra data hooks can attach
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


# Callback signature: (context: HookContext) -> None
HookCallback = Callable[[HookContext], None]


class HookManager:
    """Manages hook registrations and dispatches events.

    Analogous to Claude Code's hook pipeline — hooks run sequentially,
    and any hook can set context.block=True to prevent the action.
    """

    def __init__(self):
        self._hooks: Dict[HookEvent, List[HookCallback]] = {e: [] for e in HookEvent}

    def register(self, event: HookEvent, callback: HookCallback) -> None:
        self._hooks[event].append(callback)

    def fire(self, context: HookContext) -> HookContext:
        """Fire all hooks for the given event. Returns the (possibly modified) context."""
        for callback in self._hooks.get(context.event, []):
            try:
                callback(context)
            except Exception as e:
                logger.warning("Hook %s error: %s", context.event, e)
        return context

    def clear(self, event: Optional[HookEvent] = None) -> None:
        """Clear hooks for a specific event or all events."""
        if event:
            self._hooks[event] = []
        else:
            for e in HookEvent:
                self._hooks[e] = []


# ---------------------------------------------------------------------------
# Built-in hooks (can be enabled via BacktestConfig)
# ---------------------------------------------------------------------------

def max_concurrent_loss_hook(max_consecutive: int = 3) -> HookCallback:
    """Block new entries after N consecutive losses (risk management)."""
    state = {"consecutive_losses": 0}

    def hook(ctx: HookContext):
        if ctx.event == HookEvent.POST_TRADE_EXIT:
            if ctx.pnl_pct <= 0:
                state["consecutive_losses"] += 1
            else:
                state["consecutive_losses"] = 0
        elif ctx.event == HookEvent.PRE_TRADE_ENTRY:
            if state["consecutive_losses"] >= max_consecutive:
                ctx.block = True
                logger.debug("Entry blocked: %d consecutive losses", state["consecutive_losses"])

    return hook


def regime_filter_hook() -> HookCallback:
    """Only allow entries when market regime matches signal direction."""
    def hook(ctx: HookContext):
        if ctx.event != HookEvent.PRE_TRADE_ENTRY:
            return
        signal = ctx.signal
        metadata = ctx.metadata or {}
        regime = metadata.get("regime", "unknown")
        if signal and signal.action in ("LONG", "SHORT") and regime == "ranging":
            # In ranging markets, reduce conviction
            if abs(signal.score) < 35:
                ctx.block = True
    return hook
