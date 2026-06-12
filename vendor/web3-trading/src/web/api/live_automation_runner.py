# -*- coding: utf-8 -*-
"""Background runner for unified live automation."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from web.api.live_automation import normalize_automation_config, run_live_automation_round

_RUN_DIR = Path("data/live_automation")
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


async def _stop_peer_runners() -> None:
    from arena.dashboard_runner import stop_runner as stop_arena
    from web.api.llm_futures_runner import stop_runner as stop_llm

    await stop_llm()
    await stop_arena()


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
            result = await run_live_automation_round(config)
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
    await _stop_peer_runners()
    normalized = normalize_automation_config(config)
    if not _normalize_symbols_list(normalized.get("symbols")):
        raise ValueError("symbols 不能为空")
    if _task and not _task.done():
        await stop_runner()
    _stop_event = asyncio.Event()
    _task = asyncio.create_task(_run_loop(normalized, _stop_event), name="live_automation_runner")
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


def _normalize_symbols_list(value: Any) -> list[str]:
    if isinstance(value, str):
        items = [part.strip() for part in value.replace(";", ",").split(",")]
    elif isinstance(value, list):
        items = [str(part).strip() for part in value]
    else:
        items = []
    return [item for item in items if item]


def get_status() -> Dict[str, Any]:
    running = bool(_task and not _task.done())
    status = "running" if running else str(_state.get("status") or "stopped")
    return {"running": running, **_state, "status": status}
