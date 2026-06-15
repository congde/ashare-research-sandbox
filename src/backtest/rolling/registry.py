# -*- coding: utf-8 -*-
"""Strategy registry adapted from web3-trading."""
from __future__ import annotations

import logging
from typing import Dict, List

from backtest.rolling.strategies.base import Strategy

logger = logging.getLogger(__name__)
STRATEGY_REGISTRY: Dict[str, Strategy] = {}
_loaded = False


def register(cls: type) -> type:
    instance = cls()
    STRATEGY_REGISTRY[instance.name] = instance
    return cls


def get_strategy(name: str) -> Strategy:
    _ensure_loaded()
    return STRATEGY_REGISTRY.get(name, STRATEGY_REGISTRY["technical_signal"])


def list_strategies() -> List[dict[str, str]]:
    _ensure_loaded()
    return [
        {"name": s.name, "displayName": s.display_name}
        for s in STRATEGY_REGISTRY.values()
    ]


def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    from backtest.rolling.strategies.bollinger_squeeze import BollingerSqueezeStrategy
    from backtest.rolling.strategies.buy_and_hold import BuyAndHoldStrategy
    from backtest.rolling.strategies.ma_crossover import MACrossoverStrategy
    from backtest.rolling.strategies.macd import MACDStrategy
    from backtest.rolling.strategies.rsi_mean_reversion import RSIMeanReversionStrategy
    from backtest.rolling.strategies.technical_signal import TechnicalSignalStrategy

    for cls in [
        TechnicalSignalStrategy,
        MACrossoverStrategy,
        RSIMeanReversionStrategy,
        MACDStrategy,
        BollingerSqueezeStrategy,
        BuyAndHoldStrategy,
    ]:
        register(cls)
