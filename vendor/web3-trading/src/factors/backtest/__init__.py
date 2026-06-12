# -*- coding: utf-8 -*-
"""因子信号回测框架。

录制阶段::

    from factors import FactorPipeline, PipelineConfig
    from libs.valuescan import ValueScanClient
    from libs.kucoin_openapi import KuCoinClient
    from factors.backtest import DataRecorder

    client = ValueScanClient.from_env()
    kucoin = KuCoinClient.from_env()
    pipeline = FactorPipeline(client, PipelineConfig.for_spot(), kucoin=kucoin)
    recorder = DataRecorder(pipeline, kucoin)
    snap = await recorder.record_snapshot("BTC", "4427")

回测阶段::

    from factors.backtest import BacktestEngine, BacktestConfig
    from libs.kucoin_openapi import KuCoinClient

    kucoin = KuCoinClient.from_env()
    engine = BacktestEngine(kucoin)
    config = BacktestConfig(symbols=["BTC"], lookback_days=30)
    report = await engine.run(config)
"""

from .config import BacktestConfig
from .engine import BacktestEngine, BacktestError
from .models import (
    BacktestReport,
    BacktestTimePoint,
    EvalMetrics,
    FactorSnapshot,
    PriceBar,
    SourceData,
)
from .recorder import DataRecorder
from .reporter import Reporter
from .simulator import Simulator

__all__ = [
    "BacktestEngine",
    "BacktestError",
    "BacktestConfig",
    "BacktestReport",
    "BacktestTimePoint",
    "EvalMetrics",
    "FactorSnapshot",
    "PriceBar",
    "SourceData",
    "DataRecorder",
    "Reporter",
    "Simulator",
]
