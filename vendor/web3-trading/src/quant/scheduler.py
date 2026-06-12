# -*- coding: utf-8 -*-
"""定时交易决策任务。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_task: Optional[asyncio.Task] = None


def _config_value(name: str, default=""):
    env_value = os.getenv(name)
    if env_value not in (None, ""):
        return env_value
    try:
        from web import config as web_config

        cfg = web_config.config
        if cfg is not None:
            return getattr(cfg, name.lower(), default)
    except Exception:
        pass
    return default


def _bool_config(name: str, default: bool) -> bool:
    raw = _config_value(name, default)
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return default
    return str(raw).lower() in ("1", "true", "yes", "y")


def _int_config(name: str, default: int) -> int:
    try:
        return int(float(_config_value(name, default)))
    except (TypeError, ValueError):
        return default


def _float_config(name: str, default: float) -> float:
    try:
        return float(_config_value(name, default))
    except (TypeError, ValueError):
        return default


def _optional_bool_config(name: str) -> Optional[bool]:
    raw = _config_value(name, None)
    if raw in (None, ""):
        return None
    if isinstance(raw, bool):
        return raw
    return str(raw).lower() in ("1", "true", "yes", "y")


def _first_config(names: tuple[str, ...], default=""):
    for name in names:
        value = _config_value(name, None)
        if value not in (None, ""):
            return value
    return default


def _bool_first_config(names: tuple[str, ...], default: bool) -> bool:
    raw = _first_config(names, default)
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return default
    return str(raw).lower() in ("1", "true", "yes", "y")


def _optional_agent_names(value) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str) and not value.strip():
        return []
    if isinstance(value, list) and not any(str(item).strip() for item in value):
        return []
    from arena.agents import normalize_agent_names

    return normalize_agent_names(value)


def _symbols_config() -> list[str]:
    raw = _config_value("QUANT_SCHEDULER_SYMBOLS", "BTC,ETH")
    if isinstance(raw, list):
        return [str(item).strip().upper() for item in raw if str(item).strip()]
    return [item.strip().upper() for item in str(raw).split(",") if item.strip()]


def _write_decision_log(payload: dict) -> None:
    log_dir = Path("data/quant_scheduler")
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"decisions_{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


async def _run_once() -> None:
    mode = str(_config_value("QUANT_SCHEDULER_MODE", "tool")).lower().strip()
    if mode == "arena":
        await _run_once_arena()
        return
    await _run_once_tool()


async def _run_once_tool() -> None:
    from agent.tools.trading_decision import TradingDecisionTool

    tool = TradingDecisionTool()
    symbols = _symbols_config()
    result = await tool.execute(
        symbols=symbols,
        execute=_bool_config("QUANT_SCHEDULER_EXECUTE", False),
        dry_run=_bool_config("QUANT_SCHEDULER_DRY_RUN", True),
        confirmation=str(_config_value("QUANT_SCHEDULER_CONFIRMATION", "")),
        include_account=_bool_config("QUANT_SCHEDULER_INCLUDE_ACCOUNT", True),
        include_rag=_bool_config("QUANT_SCHEDULER_INCLUDE_RAG", True),
        rag_size=_int_config("QUANT_SCHEDULER_RAG_SIZE", 4),
        include_microstructure=_bool_config("QUANT_SCHEDULER_INCLUDE_MICROSTRUCTURE", False),
        include_valuescan_messages=_bool_config("QUANT_SCHEDULER_INCLUDE_VALUESCAN_MESSAGES", False),
        include_signal_evidence=_bool_config("QUANT_SCHEDULER_INCLUDE_SIGNAL_EVIDENCE", True),
        include_trading_agents=_optional_bool_config("QUANT_SCHEDULER_INCLUDE_TRADING_AGENTS"),
        trading_agents_timeout_s=_float_config("QUANT_SCHEDULER_TRADING_AGENTS_TIMEOUT_S", 90.0),
    )
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "symbols": symbols,
        "success": result.success,
        "error": result.error,
        "data": result.data,
    }
    _write_decision_log(payload)
    logger.info("quant scheduler finished: success=%s symbols=%s", result.success, symbols)


async def _run_once_arena() -> None:
    from arena.engine import run_live_arena

    symbols = _symbols_config()
    live_enabled = _bool_config("QUANT_ARENA_LIVE", False) or _bool_config("QUANT_ARENA_LIVE_ENABLED", False)
    paper_only = _bool_first_config(("QUANT_ARENA_PAPER_ONLY",), True)
    execute = _bool_first_config(("QUANT_ARENA_EXECUTE", "QUANT_SCHEDULER_EXECUTE"), False)
    dry_run = _bool_first_config(("QUANT_ARENA_DRY_RUN", "QUANT_LIVE_DRY_RUN", "QUANT_SCHEDULER_DRY_RUN"), True)
    confirmation = str(_first_config(("QUANT_ARENA_CONFIRMATION", "QUANT_SCHEDULER_CONFIRMATION"), ""))
    if live_enabled:
        paper_only = False
        execute = True
        dry_run = False
        confirmation = confirmation or "CONFIRM"
    result = await run_live_arena(
        symbols=symbols,
        quote=str(_first_config(("QUANT_ARENA_QUOTE",), "USDT")).upper(),
        agent_names=_optional_agent_names(_first_config(("QUANT_ARENA_AGENTS",), "claude_agent")) or ["claude_agent"],
        active_agent=str(_first_config(("QUANT_ARENA_ACTIVE_AGENT", "ACTIVE_AGENT"), "")),
        execution_agents=_optional_agent_names(_first_config(("QUANT_ARENA_EXECUTION_AGENTS", "QUANT_ARENA_ACTIVE_AGENT", "ACTIVE_AGENT"), "")),
        paper_only=paper_only,
        execute=execute,
        dry_run=dry_run,
        confirmation=confirmation,
        include_account=_bool_config("QUANT_SCHEDULER_INCLUDE_ACCOUNT", True),
        include_rag=_bool_config("QUANT_SCHEDULER_INCLUDE_RAG", True),
        rag_size=_int_config("QUANT_SCHEDULER_RAG_SIZE", 4),
        include_microstructure=_bool_config("QUANT_SCHEDULER_INCLUDE_MICROSTRUCTURE", False),
        include_valuescan_messages=_bool_config("QUANT_SCHEDULER_INCLUDE_VALUESCAN_MESSAGES", False),
        include_signal_evidence=_bool_config("QUANT_SCHEDULER_INCLUDE_SIGNAL_EVIDENCE", True),
    )
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "mode": "arena",
        "symbols": symbols,
        "data": result.model_dump(mode="json") if hasattr(result, "model_dump") else result,
    }
    _write_decision_log(payload)
    logger.info("quant scheduler arena finished: symbols=%s active_agent=%s", symbols, payload["data"].get("active_agent") if isinstance(payload["data"], dict) else "")


async def _loop() -> None:
    server_env = str(_config_value("serverEnv", os.getenv("serverEnv", ""))).lower()
    default_min_interval = 10 if server_env == "local" else 60
    min_interval = max(_int_config("QUANT_SCHEDULER_MIN_INTERVAL_SECONDS", default_min_interval), 1)
    interval = max(_int_config("QUANT_SCHEDULER_INTERVAL_SECONDS", 900), min_interval)
    logger.info("quant scheduler started, interval=%ss", interval)
    while True:
        try:
            await _run_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("quant scheduler run failed: %s", exc)
        await asyncio.sleep(interval)


def start_quant_scheduler() -> None:
    global _task
    if not _bool_config("QUANT_SCHEDULER_ENABLED", False):
        logger.info("quant scheduler disabled")
        return
    if _task and not _task.done():
        return
    _task = asyncio.create_task(_loop(), name="quant_scheduler")


async def stop_quant_scheduler() -> None:
    global _task
    if not _task:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    _task = None
    logger.info("quant scheduler stopped")