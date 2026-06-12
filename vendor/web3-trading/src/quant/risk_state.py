# -*- coding: utf-8 -*-
"""持久化交易风控状态。"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RiskState:
    current_day: str
    day_start_equity: float = 0.0
    daily_pnl: float = 0.0
    peak_equity: float = 0.0
    last_equity: float = 0.0
    paused: bool = False
    updated_at: str = ""

    @classmethod
    def fresh(cls) -> "RiskState":
        return cls(current_day=_today_utc(), updated_at=_now_utc())


class RiskStateStore:
    """用 JSON 文件保存风控状态，避免每次工具调用都重置日内限制。"""

    def __init__(self, path: str | None = None):
        raw_path = path or os.getenv("QUANT_RISK_STATE_PATH") or "data/quant_risk_state.json"
        self.path = Path(raw_path)
        self.state = self._load()
        self._reset_if_new_day()

    def snapshot(self) -> dict[str, Any]:
        return asdict(self.state)

    def update_equity(self, current_equity: float) -> None:
        self._reset_if_new_day()
        if current_equity <= 0:
            return
        if self.state.day_start_equity <= 0:
            self.state.day_start_equity = current_equity
        if current_equity > self.state.peak_equity:
            self.state.peak_equity = current_equity
        self.state.last_equity = current_equity
        self.state.daily_pnl = current_equity - self.state.day_start_equity
        self.state.updated_at = _now_utc()
        self.save()

    def record_trade_pnl(self, pnl: float) -> None:
        self._reset_if_new_day()
        self.state.daily_pnl += pnl
        if self.state.day_start_equity > 0:
            self.state.last_equity = self.state.day_start_equity + self.state.daily_pnl
        self.state.updated_at = _now_utc()
        self.save()

    def set_paused(self, paused: bool) -> None:
        self.state.paused = paused
        self.state.updated_at = _now_utc()
        self.save()

    def reset_daily(self) -> None:
        last_equity = max(self.state.last_equity, 0.0)
        self.state.current_day = _today_utc()
        self.state.day_start_equity = last_equity
        self.state.daily_pnl = 0.0
        self.state.paused = False
        self.state.updated_at = _now_utc()
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(self.snapshot(), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.path)

    def _load(self) -> RiskState:
        if not self.path.exists():
            return RiskState.fresh()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return RiskState(
                current_day=str(data.get("current_day") or _today_utc()),
                day_start_equity=float(data.get("day_start_equity") or 0),
                daily_pnl=float(data.get("daily_pnl") or 0),
                peak_equity=float(data.get("peak_equity") or 0),
                last_equity=float(data.get("last_equity") or 0),
                paused=bool(data.get("paused") or False),
                updated_at=str(data.get("updated_at") or _now_utc()),
            )
        except Exception:
            return RiskState.fresh()

    def _reset_if_new_day(self) -> None:
        if self.state.current_day != _today_utc():
            self.reset_daily()
