# -*- coding: utf-8 -*-
"""
Strategy registry — analogous to Claude Code's tools.ts.

Handles strategy registration, discovery, and pool assembly.
Strategies are auto-discovered from backtest.strategies.* modules.
"""

from __future__ import annotations

import logging
from typing import Dict, List

from backtest.strategies.base import Strategy

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Registry (singleton dict)
# ---------------------------------------------------------------------------
STRATEGY_REGISTRY: Dict[str, Strategy] = {}


def register(cls: type) -> type:
    """Register a Strategy subclass in the global registry."""
    instance = cls()
    STRATEGY_REGISTRY[instance.name] = instance
    return cls


def get_strategy(name: str) -> Strategy:
    """Lookup strategy by name, fallback to technical_signal."""
    _ensure_loaded()
    return STRATEGY_REGISTRY.get(name, STRATEGY_REGISTRY.get("technical_signal"))


def list_strategies() -> List[Dict[str, str]]:
    """Return list of available strategies for frontend."""
    _ensure_loaded()
    return [
        {"name": s.name, "displayName": s.display_name}
        for s in STRATEGY_REGISTRY.values()
    ]


# ---------------------------------------------------------------------------
# Auto-import all strategy modules (like Claude Code's getAllBaseTools)
# ---------------------------------------------------------------------------
_loaded = False


def _ensure_loaded():
    """Lazily import all strategy modules to populate the registry."""
    global _loaded
    if _loaded:
        return
    _loaded = True

    from backtest.strategies.technical_signal import TechnicalSignalStrategy
    from backtest.strategies.ma_crossover import MACrossoverStrategy
    from backtest.strategies.rsi_mean_reversion import RSIMeanReversionStrategy
    from backtest.strategies.macd import MACDStrategy
    from backtest.strategies.bollinger_squeeze import BollingerSqueezeStrategy
    from backtest.strategies.foundation_model import FoundationModelStrategy
    from backtest.strategies.ensemble import EnsembleStrategy
    from backtest.strategies.buy_and_hold import BuyAndHoldStrategy
    from backtest.strategies.vwap import VWAPStrategy
    from backtest.strategies.funding_rate import FundingRateStrategy

    for cls in [
        TechnicalSignalStrategy,
        MACrossoverStrategy,
        RSIMeanReversionStrategy,
        MACDStrategy,
        BollingerSqueezeStrategy,
        FoundationModelStrategy,
        EnsembleStrategy,
        BuyAndHoldStrategy,
        VWAPStrategy,
        FundingRateStrategy,
    ]:
        register(cls)

    logger.info("Backtest registry loaded: %d strategies", len(STRATEGY_REGISTRY))
