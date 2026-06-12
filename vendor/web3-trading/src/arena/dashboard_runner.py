# -*- coding: utf-8 -*-
"""Dashboard controlled Arena runner."""

from __future__ import annotations

import asyncio
import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from arena.agents import normalize_agent_names

_RUN_DIR = Path("data/dashboard_arena")
_task: Optional[asyncio.Task] = None
_stop_event: Optional[asyncio.Event] = None
_state: Dict[str, Any] = {
    "status": "stopped",
    "rounds": 0,
    "latest": None,
    "last_error": "",
}


@contextmanager
def _temporary_env(values: Dict[str, str]):
    old_values = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            os.environ[key] = value
        yield
    finally:
        for key, old_value in old_values.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _symbols(value: Any) -> List[str]:
    if isinstance(value, str):
        items = value.split(",")
    elif isinstance(value, list):
        items = value
    else:
        items = []
    return [str(item).strip().upper().replace("/", "-") for item in items if str(item).strip()]


def _agent_list(value: Any) -> List[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str) and not value.strip():
        return []
    if isinstance(value, list) and not any(str(item).strip() for item in value):
        return []
    return normalize_agent_names(value)


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "y", "on"}


def _env_value(names: str | Iterable[str], default: Any = None) -> Any:
    keys = [names] if isinstance(names, str) else list(names)
    for key in keys:
        value = os.getenv(key)
        if value not in (None, ""):
            return value
    return default


def _config_value(config: Dict[str, Any], key: str, env_names: str | Iterable[str], default: Any = None) -> Any:
    value = config.get(key)
    if value not in (None, "") and value != []:
        return value
    return _env_value(env_names, default)


def _first_config_value(config: Dict[str, Any], keys: Iterable[str], env_names: str | Iterable[str], default: Any = None) -> Any:
    for key in keys:
        value = config.get(key)
        if value not in (None, "") and value != []:
            return value
    return _env_value(env_names, default)


def _config_bool(config: Dict[str, Any], key: str, env_names: str | Iterable[str], default: bool = False) -> bool:
    return _bool(_config_value(config, key, env_names, default), default)


def _int(value: Any, default: int, min_value: int, max_value: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        number = default
    return max(min_value, min(max_value, number))


def _resolve_unified_model(config: Dict[str, Any]) -> str:
    """Single LLM model for five-signal analysis and all Arena LLM agents."""
    for key in ("model", "llmModel", "deepseekModel"):
        value = config.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return str(
        _env_value(
            ("QUANT_ARENA_DEFAULT_MODEL", "QUANT_ARENA_DEEPSEEK_MODEL"),
            "deepseek/deepseek-v4-flash",
        )
    ).strip() or "deepseek/deepseek-v4-flash"


def _normalize_config(config: Dict[str, Any]) -> Dict[str, Any]:
    live_enabled = _config_bool(config, "live", ("QUANT_ARENA_LIVE", "QUANT_ARENA_LIVE_ENABLED"), False)
    agents = normalize_agent_names(_config_value(
        config,
        "agents",
        "QUANT_ARENA_AGENTS",
        "trend_hunter,claude_agent,dashboard_deepseek",
    ))
    agent_mode = str(_config_value(config, "agentMode", "QUANT_ARENA_AGENT_MODE", "llm")).lower()
    if agent_mode not in {"llm", "rule"}:
        agent_mode = "llm"
    raw_execution_agents = _first_config_value(
        config,
        ("executionAgents", "activeAgent"),
        ("QUANT_ARENA_EXECUTION_AGENTS", "QUANT_ARENA_ACTIVE_AGENT", "ACTIVE_AGENT"),
        "",
    )
    execution_agents = _agent_list(raw_execution_agents)
    # active_agent 保留给旧字段兼容；真正进入风控和执行的是 execution_agents。
    active_agent = execution_agents[0] if execution_agents else ""
    for agent_name in execution_agents:
        if agent_name not in agents:
            agents.append(agent_name)
    paper_only = _config_bool(config, "paperOnly", "QUANT_ARENA_PAPER_ONLY", True)
    execute = _config_bool(config, "execute", ("QUANT_ARENA_EXECUTE", "QUANT_SCHEDULER_EXECUTE"), False)
    dry_run = _config_bool(config, "dryRun", ("QUANT_ARENA_DRY_RUN", "QUANT_LIVE_DRY_RUN", "QUANT_SCHEDULER_DRY_RUN"), True)
    confirmation = str(_config_value(config, "confirmation", ("QUANT_ARENA_CONFIRMATION", "QUANT_SCHEDULER_CONFIRMATION"), ""))
    if live_enabled:
        # Arena 实盘只需要 QUANT_ARENA_LIVE=true；下面三个值是兼容旧执行链路的派生状态。
        paper_only = False
        execute = True
        dry_run = False
        confirmation = confirmation or "CONFIRM"
    return {
        "symbols": _symbols(_config_value(config, "symbols", ("QUANT_ARENA_SYMBOLS", "QUANT_SCHEDULER_SYMBOLS"), "BTC")),
        "quote": str(_config_value(config, "quote", "QUANT_ARENA_QUOTE", "USDT")).upper(),
        "agents": agents,
        "active_agent": active_agent,
        "execution_agents": execution_agents,
        "interval_seconds": _int(_config_value(config, "intervalSeconds", ("QUANT_ARENA_INTERVAL_SECONDS", "QUANT_SCHEDULER_INTERVAL_SECONDS"), 3600), 3600, 5, 86400),
        "max_rounds": _int(_config_value(config, "maxRounds", "QUANT_ARENA_MAX_ROUNDS", 0), 0, 0, 100000),
        "agent_mode": agent_mode,
        "live_enabled": live_enabled,
        "paper_only": paper_only,
        "execute": execute,
        "dry_run": dry_run,
        "confirmation": confirmation,
        "include_account": _bool(config.get("includeAccount"), True),
        "include_rag": _bool(config.get("includeRag"), False),
        "rag_size": _int(config.get("ragSize"), 1, 1, 8),
        "include_microstructure": _bool(config.get("includeMicrostructure"), False),
        "include_valuescan_messages": _bool(config.get("includeValuescanMessages"), False),
        "include_signal_evidence": _bool(config.get("includeSignalEvidence"), True),
        "model": _resolve_unified_model(config),
        "deepseek_model": _resolve_unified_model(config),
        "deepseek_fallback_model": str(_config_value(config, "deepseekFallbackModel", "QUANT_ARENA_DEEPSEEK_FALLBACK_MODEL", "")),
        "default_model": _resolve_unified_model(config),
        "agent_models": str(_env_value("QUANT_ARENA_AGENT_MODELS", "")),
        "agent_configs": str(_env_value("QUANT_ARENA_AGENT_CONFIGS", "")),
    }


def _compact_signal(signal: Any) -> Dict[str, Any]:
    row = signal.model_dump(mode="json") if hasattr(signal, "model_dump") else dict(signal)
    return {
        "agent_name": row.get("agent_name"),
        "symbol": row.get("symbol"),
        "action": row.get("action"),
        "execution_action": row.get("execution_action"),
        "direction": row.get("direction"),
        "intent": row.get("intent"),
        "score": row.get("score"),
        "confidence": row.get("confidence"),
        "horizon": row.get("horizon"),
        "regime": row.get("regime"),
        "entry_reason": row.get("entry_reason") or [],
        "risk_flags": row.get("risk_flags") or [],
        "metadata": row.get("metadata") or {},
    }


def _compact_result(result: Any, latency_ms: float, round_no: int) -> Dict[str, Any]:
    data = result.model_dump(mode="json") if hasattr(result, "model_dump") else dict(result)
    signals = [_compact_signal(item) for item in data.get("signals") or []]
    return {
        "round": round_no,
        "ts": _now_iso(),
        "latency_ms": round(latency_ms, 2),
        "symbols": data.get("symbols") or [],
        "agents": data.get("agents") or [],
        "active_agent": data.get("active_agent") or "",
        "execution_agents": data.get("execution_agents") or [],
        "paper_only": data.get("paper_only", True),
        "signals": signals,
        "active_decisions": data.get("active_decisions") or [],
        "risk_results": data.get("risk_results") or [],
        "execution_results": data.get("execution_results") or [],
        "data_quality": data.get("data_quality") or {},
        "log_files": data.get("log_files") or {},
    }


def _append_runner_log(payload: Dict[str, Any]) -> None:
    _RUN_DIR.mkdir(parents=True, exist_ok=True)
    path = _RUN_DIR / f"runs_{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


async def _run_loop(config: Dict[str, Any], stop_event: asyncio.Event) -> None:
    from arena.engine import run_live_arena

    global _state
    interval = int(config["interval_seconds"])

    next_at = time.monotonic()  # 首次立即运行

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
            "status": "running",
            "round_status": "running",
            "current_round": round_no,
            "last_started_at": _now_iso(),
            "last_error": "",
        })
        started = time.monotonic()
        try:
            unified_model = config.get("model") or config.get("deepseek_model") or config.get("default_model")
            temp_env = {
                "QUANT_ARENA_AGENT_MODE": config["agent_mode"],
                "QUANT_ARENA_DEEPSEEK_MODEL": unified_model,
                "QUANT_ARENA_DEFAULT_MODEL": unified_model,
            }
            if config.get("deepseek_fallback_model"):
                temp_env["QUANT_ARENA_DEEPSEEK_FALLBACK_MODEL"] = config["deepseek_fallback_model"]
            if config.get("agent_models"):
                temp_env["QUANT_ARENA_AGENT_MODELS"] = config["agent_models"]
            if config.get("agent_configs"):
                temp_env["QUANT_ARENA_AGENT_CONFIGS"] = config["agent_configs"]
            if config.get("live_enabled"):
                temp_env.update({
                    "QUANT_LIVE_TRADING": "true",
                    "QUANT_LIVE_DRY_RUN": "false",
                    "QUANT_EXCHANGE_SANDBOX": "false",
                })
            with _temporary_env(temp_env):
                result = await run_live_arena(
                    symbols=config["symbols"],
                    quote=config["quote"],
                    agent_names=config["agents"],
                    active_agent=config["active_agent"],
                    execution_agents=config["execution_agents"],
                    paper_only=config["paper_only"],
                    execute=config["execute"],
                    dry_run=config["dry_run"],
                    confirmation=config["confirmation"],
                    include_account=config["include_account"],
                    include_rag=config["include_rag"],
                    rag_size=config["rag_size"],
                    include_microstructure=config["include_microstructure"],
                    include_valuescan_messages=config["include_valuescan_messages"],
                    include_signal_evidence=config["include_signal_evidence"],
                    print_traces=False,
                )
            latest = _compact_result(result, (time.monotonic() - started) * 1000, round_no)
            _append_runner_log(latest)
            _state.update({
                "status": "running",
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
                "status": "running",
                "round_status": "error",
                "current_round": round_no,
                "rounds": round_no,
                "last_finished_at": _now_iso(),
                "last_error": f"{type(exc).__name__}: {exc}",
            })
            _append_runner_log({"round": round_no, "ts": _now_iso(), "error": _state["last_error"], "config": config})
        if int(config.get("max_rounds") or 0) > 0 and round_no >= int(config["max_rounds"]):
            break
        # 更新下一次触发时间
        next_at = max(next_at + interval, time.monotonic())
    _state.update({"status": "stopped", "stopped_at": _now_iso()})


async def start_runner(config: Dict[str, Any]) -> Dict[str, Any]:
    global _task, _stop_event
    from web.api.live_automation_runner import stop_runner as stop_unified

    await stop_unified()
    normalized = _normalize_config(config)
    if not normalized["symbols"]:
        raise ValueError("symbols 不能为空")
    if _task and not _task.done():
        await stop_runner()
    _stop_event = asyncio.Event()
    _task = asyncio.create_task(_run_loop(normalized, _stop_event), name="dashboard_arena_runner")
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
