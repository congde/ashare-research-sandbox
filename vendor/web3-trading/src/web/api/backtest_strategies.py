# -*- coding: utf-8 -*-
"""
Backtest strategies — backward-compatibility re-exports.

The actual strategy implementations live under src/backtest/strategies/.
"""

from backtest.models import Signal, WalkForwardResult
from backtest.optimization.walk_forward import walk_forward_optimize
from backtest.registry import STRATEGY_REGISTRY, get_strategy, list_strategies
from backtest.strategies.base import Strategy
from backtest.strategies.bollinger_squeeze import BollingerSqueezeStrategy
from backtest.strategies.buy_and_hold import BuyAndHoldStrategy
from backtest.strategies.ensemble import EnsembleStrategy
from backtest.strategies.foundation_model import FoundationModelStrategy
from backtest.strategies.ma_crossover import MACrossoverStrategy
from backtest.strategies.macd import MACDStrategy
from backtest.strategies.rsi_mean_reversion import RSIMeanReversionStrategy
from backtest.strategies.technical_signal import TechnicalSignalStrategy
