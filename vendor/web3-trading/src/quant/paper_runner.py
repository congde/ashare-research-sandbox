# -*- coding: utf-8 -*-
"""Dashboard controlled strategy paper runner."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

_RUN_DIR = Path("data/paper_arena")
_task: Optional[asyncio.Task] = None
_stop_event: Optional[asyncio.Event] = None
_state: Dict[str, Any] = {"status": "stopped", "rounds": 0, "latest": None, "last_error": ""}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "y", "on"}


def _num(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int, min_value: int, max_value: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        number = default
    return max(min_value, min(max_value, number))


def _normalize_config(config: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "session_id": str(config.get("sessionId") or ""),
        "reset": _bool(config.get("reset"), True),
        "symbol": str(config.get("symbol") or "BTC-USDT").strip().upper(),
        "type": str(config.get("type") or "1hour"),
        "strategies": config.get("strategies") or [],
        "market_type": str(config.get("marketType") or "spot").lower(),
        "allow_short": _bool(config.get("allowShort"), False),
        "initial_cash": max(10.0, _num(config.get("initialCash"), 10000.0)),
        "allocation_pct": max(0.01, min(1.0, _num(config.get("allocationPct"), 1.0))),
        "slippage_pct": max(0.0, min(5.0, _num(config.get("slippagePct"), 0.05))),
        "commission_pct": max(0.0, min(1.0, _num(config.get("commissionPct"), 0.1))),
        "stop_loss": max(0.1, min(50.0, _num(config.get("stopLoss"), 3.0))),
        "take_profit": max(0.1, min(100.0, _num(config.get("takeProfit"), 5.0))),
        "trailing_stop": max(0.0, min(50.0, _num(config.get("trailingStop"), 0.0))),
        "max_hold_bars": _int(config.get("maxHoldBars"), 0, 0, 2000),
        "warmup_limit": _int(config.get("warmupLimit") or config.get("limit"), 300, 80, 1000),
        "interval_seconds": _int(config.get("intervalSeconds"), 20, 5, 3600),
    }


def _append_runner_log(payload: Dict[str, Any]) -> None:
    _RUN_DIR.mkdir(parents=True, exist_ok=True)
    path = _RUN_DIR / f"runner_{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


async def _run_loop(config: Dict[str, Any], stop_event: asyncio.Event) -> None:
    from quant.paper_arena import advance_strategy_paper_session, reset_strategy_paper_session

    global _state
    interval = int(config["interval_seconds"])
    next_at = time.monotonic()
    _state.update({
        "status": "running",
        "started_at": _now_iso(),
        "stopped_at": "",
        "config": config,
        "rounds": 0,
        "latest": None,
        "last_error": "",
    })
    session_id = config.get("session_id") or ""
    while not stop_event.is_set():
        delay = max(0.0, next_at - time.monotonic())
        if delay > 0:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=delay)
                break
            except asyncio.TimeoutError:
                pass
        round_no = int(_state.get("rounds") or 0) + 1
        _state.update({"last_started_at": _now_iso(), "last_error": ""})
        try:
            if round_no == 1 and (config.get("reset") or not session_id):
                result = await reset_strategy_paper_session(
                    symbol=config["symbol"],
                    kline_type=config["type"],
                    strategies=config["strategies"],
                    initial_cash=config["initial_cash"],
                    allocation_pct=config["allocation_pct"],
                    slippage_pct=config["slippage_pct"],
                    commission_pct=config["commission_pct"],
                    stop_loss_pct=config["stop_loss"],
                    take_profit_pct=config["take_profit"],
                    trailing_stop_pct=config["trailing_stop"],
                    max_hold_bars=config["max_hold_bars"],
                    allow_short=config["allow_short"],
                    market_type=config["market_type"],
                    warmup_limit=config["warmup_limit"],
                    process_now=True,
                )
                session_id = str(result.get("session_id") or "")
                config["session_id"] = session_id
            else:
                result = await advance_strategy_paper_session(session_id, warmup_limit=config["warmup_limit"])
            latest = {"round": round_no, "ts": _now_iso(), **result}
            _append_runner_log(latest)
            _state.update({
                "status": "running",
                "rounds": round_no,
                "latest": latest,
                "last_finished_at": _now_iso(),
                "last_error": "",
                "config": config,
            })
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            _state.update({"rounds": round_no, "last_finished_at": _now_iso(), "last_error": error})
            _append_runner_log({"round": round_no, "ts": _now_iso(), "error": error, "config": config})
        next_at = max(next_at + interval, time.monotonic())
    _state.update({"status": "stopped", "stopped_at": _now_iso()})


async def start_runner(config: Dict[str, Any]) -> Dict[str, Any]:
    global _task, _stop_event
    normalized = _normalize_config(config)
    if _task and not _task.done():
        await stop_runner()
    _stop_event = asyncio.Event()
    _task = asyncio.create_task(_run_loop(normalized, _stop_event), name="strategy_paper_runner")
    await asyncio.sleep(0)
    return get_status()


async def stop_runner() -> Dict[str, Any]:
    global _task, _stop_event
    if _stop_event is not None:
        _stop_event.set()
    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            _state.update({"status": "stopped", "stopped_at": _now_iso()})
    _task = None
    _stop_event = None
    return get_status()


def get_status() -> Dict[str, Any]:
    running = bool(_task and not _task.done())
    status = "running" if running else str(_state.get("status") or "stopped")
    return {"running": running, **_state, "status": status}
