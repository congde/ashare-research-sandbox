"""Trial ledger — records every backtest / param search attempt for DSR correction."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paths import DATA_DIR

TRIALS_PATH = DATA_DIR / "backtest_trials.jsonl"


@dataclass
class TrialRecord:
    source: str
    strategy_key: str
    sharpe_ratio: float
    total_return_pct: float
    params: dict[str, Any] = field(default_factory=dict)
    total_trades: int = 0
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TrialLedger:
    def __init__(self) -> None:
        self._records: list[TrialRecord] = []

    def record(
        self,
        *,
        source: str,
        strategy_key: str,
        sharpe_ratio: float,
        total_return_pct: float,
        params: dict[str, Any] | None = None,
        total_trades: int = 0,
        persist: bool = True,
    ) -> TrialRecord:
        item = TrialRecord(
            source=source,
            strategy_key=strategy_key,
            sharpe_ratio=float(sharpe_ratio),
            total_return_pct=float(total_return_pct),
            params=dict(params or {}),
            total_trades=int(total_trades),
        )
        self._records.append(item)
        if persist:
            self._append_disk(item)
        return item

    def count(self, *, source: str | None = None, strategy_key: str | None = None) -> int:
        return len(self.filter(source=source, strategy_key=strategy_key))

    def filter(
        self,
        *,
        source: str | None = None,
        strategy_key: str | None = None,
    ) -> list[TrialRecord]:
        rows = self._records
        if source:
            rows = [row for row in rows if row.source == source]
        if strategy_key:
            rows = [row for row in rows if row.strategy_key == strategy_key]
        return rows

    def summary(self, *, strategy_key: str | None = None) -> dict[str, Any]:
        rows = self.filter(strategy_key=strategy_key)
        if not rows:
            return {
                "num_trials": 0,
                "best_sharpe": 0.0,
                "sharpe_variance": 0.0,
                "sources": {},
            }
        sharpes = [row.sharpe_ratio for row in rows]
        mean = sum(sharpes) / len(sharpes)
        variance = sum((value - mean) ** 2 for value in sharpes) / max(1, len(sharpes) - 1)
        sources: dict[str, int] = {}
        for row in rows:
            sources[row.source] = sources.get(row.source, 0) + 1
        return {
            "num_trials": len(rows),
            "best_sharpe": round(max(sharpes), 4),
            "sharpe_variance": round(variance, 6),
            "sources": sources,
        }

    def load_disk(self) -> int:
        if not TRIALS_PATH.exists():
            return 0
        loaded = 0
        with TRIALS_PATH.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                self._records.append(TrialRecord(**payload))
                loaded += 1
        return loaded

    def _append_disk(self, record: TrialRecord) -> None:
        TRIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with TRIALS_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")


_LEDGER = TrialLedger()


def get_ledger() -> TrialLedger:
    return _LEDGER


def reset_ledger_for_tests() -> None:
    _LEDGER._records.clear()
