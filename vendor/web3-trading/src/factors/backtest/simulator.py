# -*- coding: utf-8 -*-
"""回放模拟器 — 从本地 JSONL 读取历史快照并构建时间点序列。"""

import time
from typing import Any

from factors.backtest.config import BacktestConfig
from factors.local_store import query_factor_snapshots
from factors.backtest.models import BacktestTimePoint


class Simulator:
    """从 factor_snapshots 回放历史时间点。"""

    async def _query_snapshots(
        self, symbols: list[str], cutoff_ms: int
    ) -> list[dict[str, Any]]:
        """查询 factor_snapshots 集合（可被子类或 mock 覆盖）。"""
        return await query_factor_snapshots(
            {
                "symbol": {"$in": symbols},
                "computed_at_ms": {"$gte": cutoff_ms},
            },
            sort=[("computed_at_ms", 1)],
        )

    async def replay(self, config: BacktestConfig) -> list[BacktestTimePoint]:
        """读取指定币种在回看窗口内的所有快照，返回按时间排序的时间点列表。"""
        cutoff_ms = int((time.time() - config.lookback_days * 86400) * 1000)

        docs = await self._query_snapshots(config.symbols, cutoff_ms)

        timepoints: list[BacktestTimePoint] = []
        for doc in docs:
            timepoints.append(
                BacktestTimePoint(
                    timestamp_ms=doc["computed_at_ms"],
                    symbol=doc["symbol"],
                    aggregate_score=doc.get("aggregate_score", 0.0),
                    factor_scores={
                        r["factor_name"]: r.get("normalized_score", 0.0)
                        for r in doc.get("factor_results", [])
                    },
                    factor_confidences={
                        r["factor_name"]: r.get("confidence", 0.0)
                        for r in doc.get("factor_results", [])
                    },
                )
            )
        return timepoints
