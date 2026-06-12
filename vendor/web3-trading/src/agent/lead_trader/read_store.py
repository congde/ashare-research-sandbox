# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional
import time
import uuid


@dataclass
class BacktestResultRecord:
    result_id: str
    trader_id: str
    strategy_version_id: str
    strategy_id: str
    symbol: str
    pair: str
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    total_trades: int = 0
    win_rate: float = 0.0
    signal_hit_rate: float = 0.0
    gate_passed: bool = False
    gate_details: Dict = field(default_factory=dict)
    created_at: int = field(default_factory=lambda: int(time.time()))

    def __post_init__(self) -> None:
        if not self.result_id:
            self.result_id = f"bt-{uuid.uuid4().hex[:10]}"

    def check_gate(self) -> bool:
        failures: List[str] = []
        if self.sharpe_ratio < 1.0:
            failures.append("sharpe_too_low")
        if self.max_drawdown_pct > 40.0:
            failures.append("drawdown_too_high")
        if self.total_trades < 20:
            failures.append("insufficient_trades")
        if self.win_rate < 0.45:
            failures.append("win_rate_too_low")
        self.gate_passed = len(failures) == 0
        self.gate_details = {"failures": failures}
        return self.gate_passed


@dataclass
class LeaderboardEntry:
    rank: int
    trader_id: str
    trader_name: str
    strategy_version_id: str
    risk_tier: str
    total_return_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    win_rate: float = 0.0
    signal_hit_rate: float = 0.0
    composite_score: float = 0.0

    def compute_composite_score(self) -> float:
        score = (
            max(0.0, min(100.0, self.total_return_pct)) * 0.15
            + max(0.0, min(3.0, self.sharpe_ratio)) / 3.0 * 30.0
            + max(0.0, min(4.0, self.sortino_ratio)) / 4.0 * 20.0
            + max(0.0, min(1.0, self.win_rate)) * 15.0
            + max(0.0, min(1.0, self.signal_hit_rate)) * 15.0
            + max(0.0, (40.0 - min(40.0, self.max_drawdown_pct)) / 40.0) * 5.0
        )
        self.composite_score = round(max(0.0, min(100.0, score)), 2)
        return self.composite_score


class SignalBacktestReadStore:
    def __init__(self):
        self._records: Dict[str, BacktestResultRecord] = {}

    async def save_backtest_result(self, record: BacktestResultRecord) -> None:
        if record.result_id in self._records:
            raise ValueError(f"result_id {record.result_id} already exists")
        self._records[record.result_id] = record

    async def get_backtest_result(self, result_id: str) -> Optional[Dict]:
        record = self._records.get(result_id)
        return asdict(record) if record else None

    async def query_backtest_results(
        self,
        trader_id: str = "",
        gate_passed_only: bool = False,
    ) -> List[Dict]:
        rows = list(self._records.values())
        if trader_id:
            rows = [r for r in rows if r.trader_id == trader_id]
        if gate_passed_only:
            rows = [r for r in rows if r.gate_passed]
        return [asdict(r) for r in rows]

    async def get_leaderboard(self, top_k: int = 10) -> List[LeaderboardEntry]:
        entries: List[LeaderboardEntry] = []
        for idx, rec in enumerate(self._records.values(), start=1):
            entry = LeaderboardEntry(
                rank=idx,
                trader_id=rec.trader_id,
                trader_name=rec.trader_id,
                strategy_version_id=rec.strategy_version_id,
                risk_tier="moderate",
                total_return_pct=rec.total_return_pct,
                sharpe_ratio=rec.sharpe_ratio,
                sortino_ratio=rec.sortino_ratio,
                max_drawdown_pct=rec.max_drawdown_pct,
                win_rate=rec.win_rate,
                signal_hit_rate=rec.signal_hit_rate,
            )
            entry.compute_composite_score()
            entries.append(entry)
        entries.sort(key=lambda x: x.composite_score, reverse=True)
        for i, e in enumerate(entries, start=1):
            e.rank = i
        return entries[: max(0, int(top_k))]


_read_store: Optional[SignalBacktestReadStore] = None


def get_read_store() -> SignalBacktestReadStore:
    global _read_store
    if _read_store is None:
        _read_store = SignalBacktestReadStore()
    return _read_store
