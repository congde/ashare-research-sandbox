"""Event-driven backtest engine (ADR-0009)."""

from app.strategy_engine.backtest.candles import (
    CandleValidationError,
    resample_candles,
    validate_candles,
)
from app.strategy_engine.backtest.engine import (
    BacktestEngine,
    StrategyContext,
    StrategyFn,
)
from app.strategy_engine.backtest.models import (
    BacktestMetrics,
    BacktestResult,
    BacktestTrade,
    ConstantBpsFee,
    ConstantBpsSlippage,
    FeeModel,
    SlippageModel,
    VolumeAwareSlippage,
    compute_metrics,
)
from app.strategy_engine.backtest.portfolio import EquityPoint, Portfolio, Position
from app.strategy_engine.backtest.result_builder import (
    PublishedResult,
    deserialise_equity,
    deserialise_trades,
    publish_backtest_result,
)
from app.strategy_engine.backtest.walk_forward import (
    FoldResult,
    StrategyFactory,
    WalkForwardReport,
    walk_forward_analysis,
)

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "BacktestMetrics",
    "BacktestTrade",
    "StrategyContext",
    "StrategyFn",
    "ConstantBpsFee",
    "ConstantBpsSlippage",
    "VolumeAwareSlippage",
    "FeeModel",
    "SlippageModel",
    "Portfolio",
    "Position",
    "EquityPoint",
    "PublishedResult",
    "CandleValidationError",
    "FoldResult",
    "StrategyFactory",
    "WalkForwardReport",
    "compute_metrics",
    "deserialise_equity",
    "deserialise_trades",
    "publish_backtest_result",
    "resample_candles",
    "validate_candles",
    "walk_forward_analysis",
]
