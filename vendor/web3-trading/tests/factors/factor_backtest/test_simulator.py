# -*- coding: utf-8 -*-
"""Simulator 单元测试。"""

import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

# 在导入 Simulator 前注入 motor mock，避免缺失 motor 依赖导致 ImportError
sys.modules.setdefault("motor", MagicMock())
sys.modules.setdefault("motor.motor_asyncio", MagicMock())


class TestSimulator:
    @pytest.mark.asyncio
    async def test_replay_empty_returns_empty_list(self) -> None:
        """无快照时返回空列表。"""
        from factors.backtest.config import BacktestConfig
        from factors.backtest.simulator import Simulator

        sim = Simulator()
        with pytest.MonkeyPatch.context() as mp:
            mock_query = AsyncMock(return_value=[])
            mp.setattr(
                sim,
                "_query_snapshots",
                mock_query,
            )
            timepoints = await sim.replay(BacktestConfig(symbols=["BTC"]))

        assert timepoints == []

    @pytest.mark.asyncio
    async def test_replay_builds_timepoints_correctly(self) -> None:
        """验证快照 doc → BacktestTimePoint 转换正确。"""
        from factors.backtest.config import BacktestConfig
        from factors.backtest.simulator import Simulator

        docs = [
            {
                "computed_at_ms": 1000,
                "symbol": "BTC",
                "aggregate_score": 0.75,
                "factor_results": [
                    {"factor_name": "alpha", "normalized_score": 0.5, "confidence": 0.8},
                    {"factor_name": "fomo", "normalized_score": -0.3, "confidence": 0.6},
                ],
            },
            {
                "computed_at_ms": 2000,
                "symbol": "BTC",
                "aggregate_score": 0.60,
                "factor_results": [
                    {"factor_name": "alpha", "normalized_score": 0.2, "confidence": 0.7},
                ],
            },
        ]

        sim = Simulator()
        with pytest.MonkeyPatch.context() as mp:
            mock_query = AsyncMock(return_value=docs)
            mp.setattr(sim, "_query_snapshots", mock_query)
            timepoints = await sim.replay(BacktestConfig(symbols=["BTC"]))

        assert len(timepoints) == 2
        assert timepoints[0].timestamp_ms == 1000
        assert timepoints[0].aggregate_score == 0.75
        assert timepoints[0].factor_scores == {"alpha": 0.5, "fomo": -0.3}
        assert timepoints[0].factor_confidences == {"alpha": 0.8, "fomo": 0.6}

    @pytest.mark.asyncio
    async def test_replay_respects_lookback_days(self) -> None:
        """验证回看窗口过滤。"""
        from factors.backtest.config import BacktestConfig
        from factors.backtest.simulator import Simulator

        sim = Simulator()
        with pytest.MonkeyPatch.context() as mp:
            mock_query = AsyncMock(return_value=[])
            mp.setattr(sim, "_query_snapshots", mock_query)
            await sim.replay(BacktestConfig(symbols=["BTC"], lookback_days=7))

        # _query_snapshots 接收 (symbols, cutoff_ms) 两个位置参数
        assert mock_query.call_args is not None
        args = mock_query.call_args.args
        assert args[0] == ["BTC"]
        # cutoff_ms 应为 now - 7 days 的毫秒时间戳，验证其为合理整数
        import time
        now_ms = int(time.time() * 1000)
        expected_cutoff = int((time.time() - 7 * 86400) * 1000)
        assert isinstance(args[1], int)
        assert args[1] <= now_ms
        # 允许 1 秒偏差
        assert abs(args[1] - expected_cutoff) < 2000
