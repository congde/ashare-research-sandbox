# -*- coding: utf-8 -*-
"""Background runner for LLM futures machine automation."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from web.api.llm_futures_executor import (
    default_max_unrealized_loss_pct,
    run_llm_futures_batch,
)

_RUN_DIR = Path("data/llm_futures_runs")
_task: Optional[asyncio.Task] = None
_stop_event: Optional[asyncio.Event] = None
_state: Dict[str, Any] = {
    "status": "stopped",
    "rounds": 0,
    "latest": None,
    "last_error": "",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "y", "on"}


def _num(value: Any, default: float, min_value: float, max_value: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(min_value, min(max_value, number))


def _int(value: Any, default: int, min_value: int, max_value: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        number = default
    return max(min_value, min(max_value, number))


def _normalize_config(config: Dict[str, Any]) -> Dict[str, Any]:
    machine_auto = _bool(config.get("machineAuto"), True)
    return {
        "symbols": config.get("symbols") or "BTC,ETH,HYPE",
        "accountId": str(config.get("accountId") or "claude").lower(),
        "intervalSeconds": _int(config.get("intervalSeconds"), 60, 60, 86400),
        "maxRounds": _int(config.get("maxRounds"), 0, 0, 100000),
        "machineAuto": machine_auto,
        "autoPositionSize": _bool(config.get("autoPositionSize"), True),
        "positionPctPerSymbol": _num(
            config.get("maxPositionPctPerSymbol") or config.get("positionPctPerSymbol"),
            0.1,
            0.01,
            0.25,
        ),
        "maxPositionPctPerSymbol": _num(
            config.get("maxPositionPctPerSymbol") or config.get("positionPctPerSymbol"),
            0.1,
            0.01,
            0.25,
        ),
        "contracts": _int(config.get("contracts"), 1, 1, 100),
        "leverage": _int(
            config.get("maxLeverage") or config.get("leverage"),
            10,
            1,
            125,
        ),
        "maxLeverage": _int(
            config.get("maxLeverage") or config.get("leverage"),
            10,
            1,
            125,
        ),
        "autoLeverage": _bool(config.get("autoLeverage"), True),
        "maxNotionalUsd": _num(config.get("maxNotionalUsd"), 30.0, 1.0, 500.0),
        "maxMarginUsd": _num(config.get("maxMarginUsd"), 15.0, 1.0, 100.0),
        "minConfidence": _num(config.get("minConfidence"), 55.0, 0.0, 100.0),
        "onlyReady": _bool(config.get("onlyReady"), False),
        "requireFiveSignalAlign": _bool(config.get("requireFiveSignalAlign"), True),
        "stopOnReversal": _bool(config.get("stopOnReversal"), True),
        "stopOnLoss": _bool(config.get("stopOnLoss"), True),
        "maxUnrealizedLossPct": _num(
            config.get("maxUnrealizedLossPct"),
            default_max_unrealized_loss_pct(),
            0.0,
            50.0,
        ),
        "maxUnrealizedLossUsd": _num(config.get("maxUnrealizedLossUsd"), 0.0, 0.0, 10000.0),
        "useTradingAgents": _bool(config.get("useTradingAgents"), False),
        "model": config.get("model"),
        "marginMode": str(config.get("marginMode") or "CROSS").upper(),
        "positionMode": str(config.get("positionMode") or "HEDGE").upper(),
        "confirmLive": "CONFIRM" if machine_auto else str(config.get("confirmLive") or ""),
        "execute": True,
    }


def _append_runner_log(payload: Dict[str, Any]) -> None:
    _RUN_DIR.mkdir(parents=True, exist_ok=True)
    path = _RUN_DIR / f"runs_{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


async def _run_loop(config: Dict[str, Any], stop_event: asyncio.Event) -> None:
    global _state
    interval = int(config["interval_seconds"])
    next_at = time.monotonic()

    _state.update({
        "status": "running",
        "started_at": _now_iso(),
        "stopped_at": "",
        "config": config,
        "rounds": 0,
        "last_error": "",
    })

    while not stop_event.is_set():
        delay = max(0.0, next_at - time.monotonic())
        if delay > 0:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=delay)
                break
            except asyncio.TimeoutError:
                pass

        round_no = int(_state.get("rounds") or 0) + 1
        _state.update({
            "round_status": "running",
            "current_round": round_no,
            "last_started_at": _now_iso(),
            "last_error": "",
        })
        started = time.monotonic()
        try:
            result = await run_llm_futures_batch(config)
            latest = {
                "round": round_no,
                "ts": _now_iso(),
                "latency_ms": round((time.monotonic() - started) * 1000, 2),
                **result,
            }
            _append_runner_log(latest)
            _state.update({
                "round_status": "finished",
                "current_round": round_no,
                "rounds": round_no,
                "latest": latest,
                "last_finished_at": _now_iso(),
                "last_error": "",
            })
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _state.update({
                "round_status": "error",
                "current_round": round_no,
                "rounds": round_no,
                "last_finished_at": _now_iso(),
                "last_error": f"{type(exc).__name__}: {exc}",
            })
            _append_runner_log({"round": round_no, "ts": _now_iso(), "error": _state["last_error"], "config": config})

        if int(config.get("max_rounds") or 0) > 0 and round_no >= int(config["max_rounds"]):
            break
        next_at = max(next_at + interval, time.monotonic())

    _state.update({"status": "stopped", "stopped_at": _now_iso()})


async def start_runner(config: Dict[str, Any]) -> Dict[str, Any]:
    global _task, _stop_event
    from web.api.live_automation_runner import stop_runner as stop_unified

    await stop_unified()
    normalized = _normalize_config(config)
    normalized["interval_seconds"] = int(normalized.pop("intervalSeconds"))
    normalized["max_rounds"] = int(normalized.pop("maxRounds"))
    if _task and not _task.done():
        await stop_runner()
    _stop_event = asyncio.Event()
    _task = asyncio.create_task(_run_loop(normalized, _stop_event), name="llm_futures_runner")
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
