# -*- coding: utf-8 -*-
"""BacktestEngine 单元测试。"""

import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

# 在导入 engine 前注入 mock 依赖，避免缺失 motor/pymongo 导致 ImportError
sys.modules.setdefault("motor", MagicMock())
sys.modules.setdefault("motor.motor_asyncio", MagicMock())
sys.modules.setdefault("pymongo", MagicMock())


class TestBacktestEngine:
    @pytest.mark.asyncio
    async def test_run_raises_on_insufficient_snapshots(self) -> None:
        """快照不足时抛出 BacktestError。"""
        from factors.backtest.config import BacktestConfig
        from factors.backtest.engine import BacktestEngine, BacktestError

        engine = BacktestEngine(kucoin=None)

        with pytest.MonkeyPatch.context() as mp:
            mock_replay = AsyncMock(return_value=[])
            mp.setattr(engine._simulator, "replay", mock_replay)
            with pytest.raises(BacktestError, match="快照数不足"):
                await engine.run(BacktestConfig(symbols=["BTC"], min_snapshots=10))

    @pytest.mark.asyncio
    async def test_run_returns_report_on_success(self) -> None:
        """正常流程返回 BacktestReport。"""
        from factors.backtest.config import BacktestConfig
        from factors.backtest.engine import BacktestEngine
        from factors.backtest.models import BacktestReport, BacktestTimePoint

        tp = BacktestTimePoint(
            timestamp_ms=1000, symbol="BTC",
            factor_scores={"alpha": 0.5}, factor_confidences={"alpha": 0.8},
        )
        engine = BacktestEngine(kucoin=None)

        with pytest.MonkeyPatch.context() as mp:
            mock_replay = AsyncMock(return_value=[tp] * 25)
            mp.setattr(engine._simulator, "replay", mock_replay)
            mock_eval = AsyncMock(return_value=BacktestReport())
            mp.setattr(engine._evaluator, "evaluate", mock_eval)

            mock_save = AsyncMock()
            mp.setattr("factors.backtest.engine.save_backtest_report", mock_save)

            report = await engine.run(BacktestConfig(symbols=["BTC"]))
            mock_save.assert_called_once()

            assert isinstance(report, BacktestReport)
            mock_eval.assert_called_once()
