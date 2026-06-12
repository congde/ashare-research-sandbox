# -*- coding: utf-8 -*-
"""Unified live automation: LLM five-signal futures, Arena, or hybrid gate + Arena + futures."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from arena.dashboard_runner import _normalize_config as _normalize_arena_config
from arena.engine import arena_signal_matches_llm_gate
from web.api.llm_futures_executor import (
    _resolve_entry_side,
    analyze_symbol_for_futures,
    default_max_unrealized_loss_pct,
    run_llm_futures_batch,
)
from web.api.llm_signal_analyzer import LLMModel

logger = logging.getLogger(__name__)

PIPELINE_LLM_FUTURES = "llm_futures"
PIPELINE_ARENA = "arena"
PIPELINE_HYBRID = "hybrid"
VALID_PIPELINES = {PIPELINE_LLM_FUTURES, PIPELINE_ARENA, PIPELINE_HYBRID}


def _pipeline(config: Dict[str, Any]) -> str:
    raw = str(config.get("pipeline") or config.get("pipelineMode") or PIPELINE_HYBRID).strip().lower()
    return raw if raw in VALID_PIPELINES else PIPELINE_HYBRID


def _normalize_symbols(value: Any) -> List[str]:
    if isinstance(value, str):
        items = [part.strip() for part in value.replace(";", ",").split(",")]
    elif isinstance(value, list):
        items = [str(part).strip() for part in value]
    else:
        items = []
    return [item.upper().split("-")[0].split("/")[0] for item in items if item]


def _base_symbol(symbol: str) -> str:
    return str(symbol or "").upper().replace("/", "-").split("-")[0]


def _default_use_trading_agents() -> bool:
    try:
        from web.config import config

        return bool(getattr(config, "use_trading_agents", False))
    except Exception:
        return False


def _resolve_model(value: Any) -> LLMModel:
    from web.api.llm_futures_executor import _resolve_model as resolve

    return resolve(value)


def _llm_batch_body(config: Dict[str, Any], *, execute: bool) -> Dict[str, Any]:
    auto_live = bool(config.get("auto_live", config.get("autoLive")))
    machine_auto = bool(config.get("machine_auto", config.get("machineAuto", auto_live)))
    if execute and (auto_live or machine_auto):
        machine_auto = True
    return {
        "symbols": config.get("symbols") or "BTC,ETH,HYPE",
        "accountId": config.get("account_id") or config.get("accountId") or "claude",
        "model": config.get("model"),
        "execute": execute,
        "autoLive": auto_live or machine_auto,
        "machineAuto": machine_auto,
        "autoPositionSize": config.get("auto_position_size", config.get("autoPositionSize", machine_auto)),
        "positionPctPerSymbol": config.get(
            "position_pct_per_symbol",
            config.get("positionPctPerSymbol", config.get("max_position_pct_per_symbol", 0.1)),
        ),
        "maxPositionPctPerSymbol": config.get(
            "max_position_pct_per_symbol",
            config.get("maxPositionPctPerSymbol", config.get("position_pct_per_symbol", 0.1)),
        ),
        "contracts": config.get("contracts", 1),
        "leverage": config.get("leverage", config.get("max_leverage", 10)),
        "maxLeverage": config.get("max_leverage", config.get("maxLeverage", config.get("leverage", 10))),
        "autoLeverage": config.get("auto_leverage", config.get("autoLeverage", machine_auto)),
        "maxNotionalUsd": config.get("max_notional_usd", config.get("maxNotionalUsd", 30)),
        "maxMarginUsd": config.get("max_margin_usd", config.get("maxMarginUsd", 15)),
        "minConfidence": config.get("min_confidence", config.get("minConfidence", 55)),
        "onlyReady": config.get("only_ready", config.get("onlyReady", False)),
        "requireFiveSignalAlign": config.get(
            "require_five_signal_align",
            config.get("requireFiveSignalAlign", True),
        ),
        "requireQuantAlign": config.get(
            "require_quant_align",
            config.get("requireQuantAlign", False),
        ),
        "quantMinAggregate": config.get(
            "quant_min_aggregate",
            config.get("quantMinAggregate", 0.12),
        ),
        "stopOnReversal": config.get("stop_on_reversal", config.get("stopOnReversal", True)),
        "stopOnLoss": config.get("stop_on_loss", config.get("stopOnLoss", True)),
        "maxUnrealizedLossPct": config.get(
            "max_unrealized_loss_pct",
            config.get("maxUnrealizedLossPct", default_max_unrealized_loss_pct()),
        ),
        "maxUnrealizedLossUsd": config.get(
            "max_unrealized_loss_usd",
            config.get("maxUnrealizedLossUsd", 0.0),
        ),
        "useTradingAgents": config.get("use_trading_agents", config.get("useTradingAgents", False)),
        "tradePlanStrict": config.get("trade_plan_strict", config.get("tradePlanStrict", True)),
        "enforceTradePlanStop": config.get(
            "enforce_trade_plan_stop",
            config.get("enforceTradePlanStop", True),
        ),
        "enforceTradePlanTargets": config.get(
            "enforce_trade_plan_targets",
            config.get("enforceTradePlanTargets", False),
        ),
        "marginMode": config.get("margin_mode", config.get("marginMode", "CROSS")),
        "positionMode": config.get("position_mode", config.get("positionMode", "HEDGE")),
        "confirmLive": "CONFIRM" if machine_auto else str(config.get("confirm_live") or config.get("confirmLive") or ""),
        "hybridArenaMatchMode": config.get(
            "hybridArenaMatchMode",
            config.get("hybrid_arena_match_mode", "gate_only"),
        ),
    }


from web.api.five_signal_view import build_five_signals_list


def _compact_llm_row(analysis: Dict[str, Any], *, side: Optional[str], gate_reason: str) -> Dict[str, Any]:
    alignment = analysis.get("fiveSignalAlignment") or {}
    quant = analysis.get("quantFactors") or {}
    quant_summary = None
    if quant.get("available"):
        quant_summary = {
            "aggregateScore": quant.get("aggregateScore"),
            "side": quant.get("side"),
            "topFactors": (quant.get("topFactors") or [])[:4],
        }
    return {
        "symbol": analysis.get("symbol"),
        "signal": analysis.get("signal"),
        "confidence": analysis.get("confidence"),
        "executionReadiness": analysis.get("executionReadiness"),
        "fiveSignalAlignment": alignment,
        "fiveSignals": build_five_signals_list(analysis),
        "factors": analysis.get("factors") or {},
        "consensus": analysis.get("consensus") or {},
        "dataQuality": analysis.get("dataQuality") or {},
        "newsCount": analysis.get("newsCount"),
        "onchain": analysis.get("onchain"),
        "onchainMetrics": analysis.get("onchainMetrics"),
        "quantFactors": quant_summary,
        "tradePlan": analysis.get("tradePlan") or {},
        "valuescanInsights": analysis.get("valuescanInsights") or {},
        "realtime": analysis.get("realtime") or {},
        "gateSide": side,
        "gateReason": gate_reason,
        "summary": analysis.get("summary"),
    }


async def _build_llm_gate(
    config: Dict[str, Any],
) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    from web.api.quant_factors_bridge import resolve_quant_factors_options

    symbols = _normalize_symbols(config.get("symbols"))
    model = _resolve_model(config.get("model"))
    use_trading_agents = bool(
        config.get(
            "use_trading_agents",
            config.get("useTradingAgents", _default_use_trading_agents()),
        )
    )
    min_confidence = float(config.get("min_confidence", config.get("minConfidence", 55)) or 55)
    only_ready = bool(config.get("only_ready", config.get("onlyReady", False)))
    require_align = bool(
        config.get("require_five_signal_align", config.get("requireFiveSignalAlign", True))
    )
    quant_opts = resolve_quant_factors_options()
    require_quant_align = bool(
        config.get("require_quant_align", config.get("requireQuantAlign", quant_opts["require_align"]))
    )
    quant_min_aggregate = float(
        config.get("quant_min_aggregate", config.get("quantMinAggregate", quant_opts["min_aggregate"]))
    )

    analyses = await asyncio.gather(
        *[
            analyze_symbol_for_futures(symbol, model=model, use_trading_agents=use_trading_agents)
            for symbol in symbols
        ],
        return_exceptions=True,
    )

    gate_by_symbol: Dict[str, Dict[str, Any]] = {}
    analyses_by_symbol: Dict[str, Dict[str, Any]] = {}
    rows: List[Dict[str, Any]] = []
    for symbol, analysis in zip(symbols, analyses):
        sym = symbol.upper()
        if isinstance(analysis, Exception):
            rows.append({
                "symbol": sym,
                "gateSide": None,
                "gateReason": f"{type(analysis).__name__}: {analysis}",
            })
            continue
        analyses_by_symbol[sym] = dict(analysis)
        side, reason = _resolve_entry_side(
            analysis,
            min_confidence=min_confidence,
            only_ready=only_ready,
            require_five_signal_align=require_align,
            require_quant_align=require_quant_align,
            quant_min_aggregate=quant_min_aggregate,
        )
        row = _compact_llm_row(analysis, side=side, gate_reason=reason)
        rows.append(row)
        if side:
            gate_by_symbol[sym] = {"side": side, "reason": reason, "analysis": row}

    return gate_by_symbol, rows, analyses_by_symbol


def _arena_approved_symbols(
    arena_result: Dict[str, Any],
    gate_by_symbol: Dict[str, Dict[str, Any]],
    execution_agents: List[str],
    *,
    match_mode: str = "direction",
) -> List[str]:
    """Symbols where at least one execution agent agrees with the LLM gate direction."""
    if not gate_by_symbol:
        return []
    mode = str(match_mode or "direction").strip().lower()
    if mode in {"off", "none", "gate_only"}:
        return sorted(gate_by_symbol.keys())

    execution_set = {str(name).strip() for name in execution_agents if str(name).strip()}
    if not execution_set:
        return list(gate_by_symbol.keys())

    approved: Set[str] = set()
    for signal in arena_result.get("signals") or []:
        agent_name = str(signal.get("agent_name") or "")
        if agent_name not in execution_set:
            continue
        base = _base_symbol(signal.get("symbol") or "")
        gate = gate_by_symbol.get(base)
        if not gate:
            continue
        if arena_signal_matches_llm_gate(signal, str(gate.get("side") or ""), match_mode=mode):
            approved.add(base)
    return sorted(approved)


def normalize_automation_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Merge dashboard payloads into one runner config."""
    pipeline = _pipeline(config)
    unified_model = str(config.get("model") or config.get("llmModel") or config.get("deepseekModel") or "").strip()
    arena = _normalize_arena_config({**config, "model": unified_model} if unified_model else config)
    auto_live = bool(
        config.get("autoLive")
        or config.get("auto_live")
        or config.get("machineAuto")
        or config.get("machine_auto")
        or arena.get("live_enabled")
    )
    machine_auto = auto_live
    model = unified_model or arena.get("model") or arena.get("deepseek_model")
    return {
        "pipeline": pipeline,
        "symbols": config.get("symbols") or ",".join(arena.get("symbols") or ["BTC"]),
        "interval_seconds": max(
            60,
            min(
                86400,
                int(
                    config.get("intervalSeconds")
                    or config.get("interval_seconds")
                    or arena.get("interval_seconds")
                    or 60
                ),
            ),
        ),
        "max_rounds": int(config.get("maxRounds") or config.get("max_rounds") or arena.get("max_rounds") or 0),
        "model": model,
        "account_id": str(config.get("accountId") or config.get("account_id") or "claude").lower(),
        "auto_live": auto_live,
        "machine_auto": machine_auto,
        "auto_position_size": bool(config.get("autoPositionSize", config.get("auto_position_size", machine_auto))),
        "position_pct_per_symbol": float(
            config.get("maxPositionPctPerSymbol")
            or config.get("max_position_pct_per_symbol")
            or config.get("positionPctPerSymbol")
            or config.get("position_pct_per_symbol")
            or 0.1
        ),
        "max_position_pct_per_symbol": float(
            config.get("maxPositionPctPerSymbol")
            or config.get("max_position_pct_per_symbol")
            or config.get("position_pct_per_symbol")
            or 0.1
        ),
        "contracts": config.get("contracts", 1),
        "leverage": config.get("leverage", config.get("max_leverage", 10)),
        "max_leverage": int(
            config.get("maxLeverage")
            or config.get("max_leverage")
            or config.get("leverage")
            or 10
        ),
        "auto_leverage": bool(
            config.get("autoLeverage", config.get("auto_leverage", machine_auto))
        ),
        "max_notional_usd": config.get("maxNotionalUsd", config.get("max_notional_usd", 30)),
        "max_margin_usd": config.get("maxMarginUsd", config.get("max_margin_usd", 15)),
        "min_confidence": config.get("minConfidence", config.get("min_confidence", 55)),
        "only_ready": bool(config.get("onlyReady", config.get("only_ready", False))),
        "require_five_signal_align": bool(
            config.get("requireFiveSignalAlign", config.get("require_five_signal_align", True))
        ),
        "stop_on_reversal": bool(config.get("stopOnReversal", config.get("stop_on_reversal", True))),
        "stop_on_loss": bool(config.get("stopOnLoss", config.get("stop_on_loss", True))),
        "max_unrealized_loss_pct": config.get(
            "maxUnrealizedLossPct",
            config.get("max_unrealized_loss_pct", default_max_unrealized_loss_pct()),
        ),
        "max_unrealized_loss_usd": config.get(
            "maxUnrealizedLossUsd",
            config.get("max_unrealized_loss_usd", 0.0),
        ),
        "use_trading_agents": bool(
            config.get(
                "useTradingAgents",
                config.get(
                    "use_trading_agents",
                    _default_use_trading_agents(),
                ),
            )
        ),
        "require_quant_align": bool(
            config.get("requireQuantAlign", config.get("require_quant_align", False))
        ),
        "quant_min_aggregate": config.get(
            "quantMinAggregate",
            config.get("quant_min_aggregate", 0.12),
        ),
        "margin_mode": str(config.get("marginMode") or config.get("margin_mode") or "CROSS").upper(),
        "position_mode": str(config.get("positionMode") or config.get("position_mode") or "HEDGE").upper(),
        "confirm_live": "CONFIRM" if machine_auto else str(config.get("confirmLive") or config.get("confirm_live") or ""),
        "hybrid_arena_match_mode": str(
            config.get("hybridArenaMatchMode")
            or config.get("hybrid_arena_match_mode")
            or "gate_only"
        ).strip().lower()
        or "gate_only",
        "arena": arena,
    }


async def run_live_automation_round(config: Dict[str, Any]) -> Dict[str, Any]:
    normalized = normalize_automation_config(config)
    pipeline = normalized["pipeline"]

    if pipeline == PIPELINE_LLM_FUTURES:
        result = await run_llm_futures_batch(_llm_batch_body(normalized, execute=True))
        return {"ok": bool(result.get("ok", True)), "pipeline": pipeline, "llmFutures": result}

    if pipeline == PIPELINE_ARENA:
        arena_result = await _run_arena_round(normalized["arena"])
        return {"ok": True, "pipeline": pipeline, "arena": arena_result}

    gate_by_symbol, llm_rows, analyses_by_symbol = await _build_llm_gate(normalized)
    gated_symbols = list(gate_by_symbol.keys())
    if not gated_symbols:
        return {
            "ok": True,
            "pipeline": PIPELINE_HYBRID,
            "llmGate": llm_rows,
            "gatedSymbols": [],
            "arenaApprovedSymbols": [],
            "arena": None,
            "llmFutures": None,
            "message": "入场门禁未通过，本轮跳过合约执行",
        }

    arena_cfg = dict(normalized["arena"])
    arena_cfg["symbols"] = gated_symbols
    # Hybrid: Arena 仅做多 Agent 共识，不下现货单
    arena_cfg["paper_only"] = True
    arena_cfg["execute"] = False
    arena_cfg["dry_run"] = True
    arena_result = await _run_arena_round(arena_cfg)
    approved = _arena_approved_symbols(
        arena_result,
        gate_by_symbol,
        arena_cfg.get("execution_agents") or [],
        match_mode=normalized.get("hybrid_arena_match_mode") or "direction",
    )
    hybrid_note = ""
    if gated_symbols and not approved:
        hybrid_note = (
            "入场门禁已通过，但 Arena 执行 Agent 未共识；可将 hybridArenaMatchMode 设为 gate_only（默认）跳过 Arena 拦单"
        )

    execute_futures = bool(
        normalized.get("machine_auto")
        or normalized.get("auto_live")
        or arena_cfg.get("live_enabled")
    )
    futures_body = _llm_batch_body(normalized, execute=execute_futures)
    futures_body["precomputedAnalyses"] = analyses_by_symbol
    futures_body["arenaApprovedSymbols"] = approved
    futures_result = await run_llm_futures_batch(futures_body)

    payload: Dict[str, Any] = {
        "ok": bool(futures_result.get("ok", True)),
        "pipeline": PIPELINE_HYBRID,
        "llmGate": llm_rows,
        "gatedSymbols": gated_symbols,
        "arenaApprovedSymbols": approved,
        "arena": arena_result,
        "llmFutures": futures_result,
        "executeFutures": execute_futures,
        "hybridArenaMatchMode": normalized.get("hybrid_arena_match_mode") or "direction",
    }
    if hybrid_note:
        payload["message"] = hybrid_note
    return payload


def _arena_temp_env(arena_config: Dict[str, Any]) -> Dict[str, str]:
    unified_model = (
        arena_config.get("model")
        or arena_config.get("deepseek_model")
        or arena_config.get("default_model")
    )
    temp_env: Dict[str, str] = {
        "QUANT_ARENA_AGENT_MODE": str(arena_config.get("agent_mode") or "llm"),
    }
    if unified_model:
        temp_env["QUANT_ARENA_DEEPSEEK_MODEL"] = str(unified_model)
        temp_env["QUANT_ARENA_DEFAULT_MODEL"] = str(unified_model)
    fallback = arena_config.get("deepseek_fallback_model")
    if fallback:
        temp_env["QUANT_ARENA_DEEPSEEK_FALLBACK_MODEL"] = str(fallback)
    if arena_config.get("agent_models"):
        temp_env["QUANT_ARENA_AGENT_MODELS"] = str(arena_config["agent_models"])
    if arena_config.get("agent_configs"):
        temp_env["QUANT_ARENA_AGENT_CONFIGS"] = str(arena_config["agent_configs"])
    return temp_env


async def _run_arena_round(
    arena_config: Dict[str, Any],
    *,
    llm_gate_by_symbol: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    import time

    from arena.dashboard_runner import _compact_result, _temporary_env
    from arena.engine import run_live_arena

    started = time.monotonic()
    with _temporary_env(_arena_temp_env(arena_config)):
        result = await run_live_arena(
            symbols=arena_config["symbols"],
            quote=arena_config["quote"],
            agent_names=arena_config["agents"],
            active_agent=arena_config["active_agent"],
            execution_agents=arena_config["execution_agents"],
            paper_only=arena_config["paper_only"],
            execute=arena_config["execute"],
            dry_run=arena_config["dry_run"],
            confirmation=arena_config["confirmation"],
            include_account=arena_config["include_account"],
            include_rag=arena_config["include_rag"],
            rag_size=arena_config["rag_size"],
            include_microstructure=arena_config["include_microstructure"],
            include_valuescan_messages=arena_config["include_valuescan_messages"],
            include_signal_evidence=arena_config["include_signal_evidence"],
            llm_gate_by_symbol=llm_gate_by_symbol,
        )
    latency_ms = (time.monotonic() - started) * 1000
    return _compact_result(result, latency_ms, 0)
