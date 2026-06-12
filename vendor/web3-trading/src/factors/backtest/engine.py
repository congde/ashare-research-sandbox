# -*- coding: utf-8 -*-
"""回测引擎 — 串联 Simulator → Evaluator → Reporter 完整流程。"""

from factors.backtest.config import BacktestConfig
from factors.local_store import save_backtest_report
from factors.backtest.evaluator import Evaluator
from factors.backtest.models import BacktestReport
from factors.backtest.reporter import Reporter
from factors.backtest.simulator import Simulator


class BacktestError(Exception):
    """回测过程中出现的业务错误。"""


class BacktestEngine:
    """回测引擎，串联整个回测流程。"""

    def __init__(self, kucoin=None) -> None:
        self._simulator = Simulator()
        self._evaluator = Evaluator(kucoin)
        self._reporter = Reporter()

    async def run(self, config: BacktestConfig) -> BacktestReport:
        """执行完整的回测流程：回放 → 评估 → 报告 → 存储。

        Raises:
            BacktestError: 快照数不足时抛出。
        """
        timepoints = await self._simulator.replay(config)
        if len(timepoints) < config.min_snapshots:
            raise BacktestError(
                f"快照数不足: {len(timepoints)} < {config.min_snapshots}. "
                f"请延长 lookback_days 或等待更多数据积累。"
            )

        report = await self._evaluator.evaluate(timepoints, config)
        self._reporter.generate(report)

        await save_backtest_report(report.model_dump())

        return report
