# -*- coding: utf-8 -*-
"""Arena 运行引擎。"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from arena.agents import AGENT_REGISTRY, create_agent, normalize_agent_names
from arena.agent_config import account_for_agent, normalize_agent_id
from arena.models import AgentPerformanceRecord, AgentRunTrace, AgentSignal, ArenaRunResult
from arena.storage import append_arena_log, append_arena_performance_records, append_arena_trace_log
from quant.live_trader import LiveTrader
from quant.opensearch_rag import opensearch_rag
from quant.risk_manager import RiskLimits, RiskManager


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_symbols(symbols: Any) -> List[str]:
    if isinstance(symbols, str):
        items = [item.strip() for item in symbols.split(",")]
    elif isinstance(symbols, list):
        items = [str(item).strip() for item in symbols]
    else:
        items = []
    return [item.upper().replace("/", "-") for item in items if item]


def _normalize_execution_agents(value: Iterable[str] | str | None) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str) and not value.strip():
        return []
    if not isinstance(value, str):
        items = [str(item).strip() for item in value]
        if not any(items):
            return []
    return normalize_agent_names(value)


def _spot_pair(symbol: str, quote: str = "USDT") -> str:
    normalized = symbol.upper().replace("/", "-")
    return normalized if "-" in normalized else f"{normalized}-{quote.upper()}"


def _cash_equity(account_snapshot: Dict[str, Any], quote: str) -> tuple[float, float, float]:
    cash = 0.0
    total_equity = 0.0
    total_position_value = 0.0
    try:
        balance = account_snapshot.get("balance") or {}
        total = balance.get("total") or {}
        free = balance.get("free") or {}
        cash = float(free.get(quote.upper()) or free.get(quote) or 0)
        total_equity = float(total.get(quote.upper()) or total.get(quote) or cash or 0)
        for position in account_snapshot.get("positions") or []:
            total_position_value += abs(float(position.get("notional") or position.get("contracts") or 0))
    except Exception:
        pass
    return cash, total_equity, total_position_value


def _current_price(context: Dict[str, Any], symbol: str, quote: str) -> float:
    base = symbol.upper().replace("/", "-").split("-")[0]
    for item in context.get("marketContext") or []:
        if str(item.get("symbol") or "").upper() != base:
            continue
        market = item.get("marketStats") or {}
        return _num(market.get("last") or market.get("price") or 0)
    return 0.0


def _base_symbol(symbol: str) -> str:
    return str(symbol or "").upper().replace("/", "-").split("-")[0]


def _normalize_arena_action_token(action: str) -> str:
    return str(action or "").strip().lower().replace("-", "_")


_BUY_ACTION_TOKENS = frozenset({"buy", "long", "weak_long", "weak_buy"})
_SELL_ACTION_TOKENS = frozenset({"sell", "short", "weak_short", "weak_sell"})


def _action_token_matches_llm_gate(action: str, gate_side: str) -> bool:
    token = _normalize_arena_action_token(action)
    gate_lower = str(gate_side or "").lower()
    if gate_lower == "buy":
        return token in _BUY_ACTION_TOKENS
    if gate_lower == "sell":
        return token in _SELL_ACTION_TOKENS
    return False


def _direction_matches_llm_gate(direction: str, gate_side: str) -> bool:
    gate_lower = str(gate_side or "").lower()
    direction_lower = str(direction or "").lower()
    if gate_lower == "buy":
        return direction_lower in {"long", "bullish"}
    if gate_lower == "sell":
        return direction_lower in {"short", "bearish"}
    return False


def arena_signal_matches_llm_gate(
    signal: Any,
    gate_side: str,
    *,
    match_mode: str = "direction",
) -> bool:
    """Whether an Arena agent signal agrees with the LLM five-signal gate side.

    match_mode:
      - direction: execution_action, raw action (incl. WEAK_*), or direction field
      - execution: only non-hold execution_action
      - off: always True (gate-only hybrid)
    """
    gate_lower = str(gate_side or "").lower()
    if not gate_lower:
        return False
    mode = str(match_mode or "direction").strip().lower()
    if mode in {"off", "none", "gate_only"}:
        return True

    if isinstance(signal, dict):
        execution_action = signal.get("execution_action")
        action = signal.get("action")
        direction = signal.get("direction")
    else:
        execution_action = getattr(signal, "execution_action", None)
        action = getattr(signal, "action", None)
        direction = getattr(signal, "direction", None)

    exec_token = _normalize_arena_action_token(str(execution_action or ""))
    if exec_token not in {"hold", "wait", ""} and _action_token_matches_llm_gate(exec_token, gate_lower):
        return True
    if mode == "execution":
        return False
    if _action_token_matches_llm_gate(str(action or ""), gate_lower):
        return True
    return _direction_matches_llm_gate(str(direction or ""), gate_lower)


def _arena_action_matches_llm_gate(action: str, gate_side: str) -> bool:
    return _action_token_matches_llm_gate(action, gate_side)


def _execution_action(signal: AgentSignal) -> str:
    explicit = getattr(signal, "execution_action", None)
    if explicit:
        return str(explicit).lower()
    raw = str(signal.action or "")
    lower = raw.lower()
    if lower in {"buy", "sell", "short", "cover", "hold"}:
        return lower
    return {
        "LONG": "buy",
        "SHORT": "short",
        "WEAK_LONG": "buy",
        "WEAK_SHORT": "short",
    }.get(raw.upper(), "hold")


def _position_quantity(context: Dict[str, Any], symbol: str, quote: str) -> float:
    pair = _spot_pair(symbol, quote).replace("-", "/")
    base = _base_symbol(symbol)
    account = context.get("account") if isinstance(context.get("account"), dict) else {}
    for position in account.get("positions") or []:
        pos_symbol = str(position.get("symbol") or "").upper().replace("-", "/")
        asset = str(position.get("asset") or "").upper()
        if pos_symbol == pair.upper() or asset == base:
            return abs(_num(position.get("amount") or position.get("contracts") or position.get("free") or 0))
    return 0.0


def _signal_to_decision(signal: AgentSignal, context: Dict[str, Any], quote: str, cash: float, total_equity: float) -> Dict[str, Any]:
    existing = signal.metadata.get("decision") if isinstance(signal.metadata, dict) else None
    if isinstance(existing, dict):
        return existing

    symbol = _spot_pair(signal.symbol, quote).replace("-", "/")
    price = _current_price(context, signal.symbol, quote)
    action = _execution_action(signal)
    if action == "hold" or price <= 0 or total_equity <= 0:
        return {
            "symbol": symbol,
            "market": "crypto",
            "action": "hold",
            "signal": "hold",
            "quantity": 0.0,
            "price": price,
            "confidence": signal.confidence,
            "leverage": 1,
            "stop_loss": None,
            "take_profit": None,
            "risk_usd": 0.0,
            "rationale": "; ".join(signal.entry_reason) or "Arena agent waits",
            "invalidation": signal.invalidation,
            "evidence_for": signal.entry_reason,
            "evidence_against": signal.risk_flags,
            "data_sources": signal.data_sources,
        }

    stop_pct = signal.stop_loss_pct or 2.0
    take_profit_pct = signal.take_profit_pct or max(stop_pct * 1.6, 2.0)
    if action in ("buy", "cover"):
        stop_loss = price * (1 - stop_pct / 100)
        take_profit = price * (1 + take_profit_pct / 100)
    else:
        stop_loss = price * (1 + stop_pct / 100)
        take_profit = price * (1 - take_profit_pct / 100)

    limits = RiskLimits.from_env()
    risk_usd = max(total_equity * limits.max_position_risk, 0.0)
    if action in ("sell", "cover"):
        quantity = _position_quantity(context, signal.symbol, quote)
    else:
        risk_per_unit = abs(price - stop_loss)
        quantity = risk_usd / risk_per_unit if risk_per_unit > 0 else 0.0
        max_quantity_by_order = limits.max_quantity_usd / price if price > 0 else 0.0
        quantity = min(quantity, max_quantity_by_order)
        if action == "buy" and cash > 0:
            quantity = min(quantity, cash / price)
    quantity = max(0.0, quantity)

    return {
        "symbol": symbol,
        "market": "crypto",
        "action": action,
        "signal": "entry" if action in ("buy", "short") else "exit",
        "quantity": quantity,
        "price": price,
        "confidence": signal.confidence,
        "leverage": 1,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "risk_usd": risk_usd,
        "rationale": "; ".join(signal.entry_reason) or f"Arena active agent {signal.agent_name}",
        "invalidation": signal.invalidation,
        "evidence_for": signal.entry_reason,
        "evidence_against": signal.risk_flags,
        "data_sources": signal.data_sources,
    }


async def _run_agent_with_trace(agent_name: str, context: Dict[str, Any], symbols: List[str]) -> tuple[List[AgentSignal], AgentRunTrace]:
    agent = create_agent(agent_name)
    started = datetime.now(timezone.utc)
    input_context: Dict[str, Any] = {}
    prompt = ""
    error: Optional[str] = None
    try:
        input_context = agent.build_input_context(context, symbols)
        prompt = agent.build_prompt(input_context)
        timeout_seconds = max(30.0, float(os.getenv("QUANT_ARENA_AGENT_TIMEOUT_SECONDS", "150")))
        signals = await asyncio.wait_for(agent.generate(input_context, symbols), timeout=timeout_seconds)
    except Exception as exc:
        error = f"{type(exc).__name__}:{exc}"
        signals = [
            AgentSignal(
                agent_name=agent_name,
                symbol=_base_symbol(symbol),
                action="WAIT",
                score=0,
                confidence=0,
                entry_reason=[],
                invalidation="Agent execution failed",
                risk_flags=[f"agent_error:{error}"],
            )
            for symbol in symbols
        ]
    finished = datetime.now(timezone.utc)
    trace = AgentRunTrace(
        agent_name=agent.name,
        display_name=agent.display_name,
        symbols=symbols,
        profile=agent.profile,
        prompt=prompt,
        input_context=input_context,
        output_signals=signals,
        started_at=started.isoformat(),
        finished_at=finished.isoformat(),
        latency_ms=(finished - started).total_seconds() * 1000,
        error=error,
    )
    return signals, trace


async def run_agents_with_traces(context: Dict[str, Any], symbols: Iterable[str], agent_names: Iterable[str] | str | None = None) -> tuple[List[AgentSignal], List[AgentRunTrace]]:
    """并发运行多个交易 Agent，并保留每个 Agent 的完整输入/提示词/输出。"""
    symbol_list = [_base_symbol(symbol) for symbol in symbols]
    names = normalize_agent_names(agent_names)
    results = await asyncio.gather(*[_run_agent_with_trace(name, context, symbol_list) for name in names])
    signals: List[AgentSignal] = []
    traces: List[AgentRunTrace] = []
    for agent_signals, trace in results:
        signals.extend(agent_signals)
        traces.append(trace)
    return signals, traces


async def run_agents(context: Dict[str, Any], symbols: Iterable[str], agent_names: Iterable[str] | str | None = None) -> List[AgentSignal]:
    """并发运行多个交易 Agent。"""
    signals, _ = await run_agents_with_traces(context, symbols, agent_names)
    return signals


async def _build_context(
    symbols: List[str],
    quote: str,
    execute: bool,
    dry_run: bool,
    account_ids: List[str],
    include_account: bool,
    include_rag: bool,
    rag_size: int,
    include_microstructure: bool,
    include_valuescan_messages: bool,
    include_signal_evidence: bool,
    dex_tokens: Optional[List[Dict[str, Any]]],
) -> tuple[Dict[str, Any], Optional[LiveTrader]]:
    from agent.tools.trading_decision import TradingDecisionTool, _safe_call
    from quant.hengan_data import get_social_heat

    tool = TradingDecisionTool()
    market_context = await asyncio.gather(*[
        tool._collect_symbol_context(
            symbol,
            quote,
            include_microstructure=include_microstructure,
            include_valuescan_messages=include_valuescan_messages,
        )
        for symbol in symbols
    ])
    dex_context, social_heat = await asyncio.gather(
        tool._collect_dex_context(dex_tokens),
        _safe_call(get_social_heat({"tokens": dex_tokens}), {}) if dex_tokens else asyncio.sleep(0, result={}),
    )

    account_snapshot: Dict[str, Any] = {"available": False}
    accounts: Dict[str, Any] = {}
    if include_account or execute:
        target_accounts = list(dict.fromkeys(account_ids or ["default"]))
        for account_id in target_accounts:
            account_trader: Optional[LiveTrader] = None
            try:
                account_trader = LiveTrader(dry_run=dry_run, account_id=account_id)
                snapshot = await account_trader.get_account_snapshot([_spot_pair(symbol, quote).replace("-", "/") for symbol in symbols])
                snapshot["available"] = True
                snapshot["account_id"] = account_id
            except Exception as exc:
                snapshot = {"available": False, "account_id": account_id, "error": str(exc)}
            finally:
                if account_trader is not None:
                    try:
                        await account_trader.close()
                    except Exception:
                        pass
            accounts[account_id] = snapshot
        account_snapshot = accounts.get(target_accounts[0]) or {"available": False}

    data_quality = {
        "dexScan": {
            "requested": bool(dex_tokens),
            "available": bool(dex_context),
            "reason": "ok" if dex_context else ("not_requested" if not dex_tokens else "no_valid_data_returned; check DexScan auth/base URL"),
        },
        "socialHeat": {
            "requested": bool(dex_tokens),
            "available": bool(social_heat),
            "reason": "ok" if social_heat else ("not_requested" if not dex_tokens else "no_valid_data_returned; check HengAn social auth/base URL"),
        },
        "account": {
            "requested": bool(include_account or execute),
            "available": bool(accounts) and all(bool(item.get("available")) for item in accounts.values()),
            "reason": "ok" if accounts and all(bool(item.get("available")) for item in accounts.values()) else account_snapshot.get("error") or "not_requested",
        },
    }

    rag_docs: Dict[str, Any] | List[Any] = []
    if include_rag:
        doc_size = max(1, min(int(rag_size or 4), 8))
        market_docs, news_docs = await asyncio.gather(
            opensearch_rag.search_events(symbols, size=doc_size, index=opensearch_rag.index, source_types=["kline", "onchain"]),
            opensearch_rag.search_events(symbols, size=doc_size, index=opensearch_rag.news_index, source_types=["news", "twitter"]),
        )
        rag_docs = {"marketEvents": market_docs, "nonMarketEvents": news_docs}

    evidence = await tool._collect_evidence(
        symbol_list=symbols,
        market_context=market_context,
        dex_context=dex_context,
        quote=quote,
        include_signal_evidence=include_signal_evidence,
        include_trading_agents=False,
        trading_agents_timeout_s=0,
    )

    context = {
        "symbols": symbols,
        "marketContext": market_context,
        "dexContext": dex_context,
        "socialHeat": social_heat,
        "account": account_snapshot,
        "accounts": {"default": account_snapshot, **accounts},
        "ragDocs": rag_docs,
        "evidence": evidence,
        "dataQuality": data_quality,
        "executionRequest": {
            "execute": execute,
            "dry_run": dry_run,
            "mode": "arena",
            "include_microstructure": include_microstructure,
            "include_valuescan_messages": include_valuescan_messages,
            "rag_size": max(1, min(int(rag_size or 4), 8)),
        },
    }
    return context, None


def _build_performance_records(
    ts: str,
    signals: List[AgentSignal],
    active_agent: str,
    execution_agents: List[str],
    paper_only: bool,
    risk_results: List[Dict[str, Any]],
    execution_results: List[Dict[str, Any]],
) -> List[AgentPerformanceRecord]:
    risk_by_key = {
        (str(item.get("agent") or ""), _base_symbol(str(item.get("symbol") or ""))): item
        for item in risk_results
    }
    executed_symbols = {_base_symbol(str(item.get("symbol") or item.get("pair") or "")) for item in execution_results}
    records: List[AgentPerformanceRecord] = []
    execution_set = set(execution_agents)
    for signal in signals:
        key = (signal.agent_name, _base_symbol(signal.symbol))
        risk = risk_by_key.get(key) or {}
        is_active = bool(signal.agent_name in execution_set)
        mode = "paper"
        if is_active and not paper_only:
            mode = "live_candidate"
        execution_status = "paper_signal_recorded"
        if is_active and not paper_only:
            execution_status = "risk_rejected"
            if risk.get("approved"):
                execution_status = "risk_approved_not_executed"
            if _base_symbol(signal.symbol) in executed_symbols:
                execution_status = "submitted_to_live_trader"
        records.append(AgentPerformanceRecord(
            ts=ts,
            agent_name=signal.agent_name,
            symbol=_base_symbol(signal.symbol),
            mode=mode,  # type: ignore[arg-type]
            action=signal.action,
            execution_action=_execution_action(signal),
            score=signal.score,
            confidence=signal.confidence,
            paper_only=paper_only,
            active_agent=active_agent,
            risk_approved=risk.get("approved") if risk else None,
            risk_reason=str(risk.get("reason") or ""),
            execution_status=execution_status,
            signal=signal.model_dump(mode="json"),
        ))
    return records


async def run_live_arena(
    symbols: Any,
    quote: str = "USDT",
    agent_names: Iterable[str] | str | None = None,
    active_agent: str = "",
    execution_agents: Iterable[str] | str | None = None,
    paper_only: bool = True,
    execute: bool = False,
    dry_run: bool = True,
    confirmation: str = "",
    include_account: bool = True,
    include_rag: bool = True,
    rag_size: int = 4,
    include_microstructure: bool = False,
    include_valuescan_messages: bool = False,
    include_signal_evidence: bool = True,
    dex_tokens: Optional[List[Dict[str, Any]]] = None,
    llm_gate_by_symbol: Optional[Dict[str, Dict[str, Any]]] = None,
    print_traces: bool = False,
) -> ArenaRunResult:
    """采集一次实时上下文并运行 Arena。"""
    symbol_list = _normalize_symbols(symbols)
    if not symbol_list:
        raise ValueError("symbols is required")
    if execute and not dry_run and confirmation != "CONFIRM":
        raise ValueError("Live execution requires confirmation='CONFIRM'.")

    names = normalize_agent_names(agent_names)
    normalized_active = normalize_agent_id(active_agent)
    raw_execution_agents = execution_agents if execution_agents is not None else normalized_active
    normalized_execution_agents = _normalize_execution_agents(raw_execution_agents)
    for agent_name in normalized_execution_agents:
        if agent_name not in AGENT_REGISTRY:
            raise ValueError(f"Unknown execution arena agent: {agent_name}")
        if agent_name not in names:
            names.append(agent_name)
    if normalized_active and normalized_active not in normalized_execution_agents:
        normalized_execution_agents.insert(0, normalized_active)

    execution_account_ids = [account_for_agent(agent_name, agent_name) for agent_name in normalized_execution_agents]
    effective_execute = bool(execute and normalized_execution_agents and not paper_only)
    context, trader = await _build_context(
        symbols=symbol_list,
        quote=quote,
        execute=effective_execute,
        dry_run=dry_run,
        account_ids=execution_account_ids or ["default"],
        include_account=include_account,
        include_rag=include_rag,
        rag_size=rag_size,
        include_microstructure=include_microstructure,
        include_valuescan_messages=include_valuescan_messages,
        include_signal_evidence=include_signal_evidence,
        dex_tokens=dex_tokens,
    )

    signals, traces = await run_agents_with_traces(context, symbol_list, names)
    active_decisions: List[Dict[str, Any]] = []
    risk_results: List[Dict[str, Any]] = []
    execution_results: List[Dict[str, Any]] = []

    risk_manager = RiskManager()
    if normalized_execution_agents:
        active_signals = [signal for signal in signals if signal.agent_name in set(normalized_execution_agents)]
        for signal in active_signals:
            account_id = account_for_agent(signal.agent_name, signal.agent_name)
            base = _base_symbol(signal.symbol)
            if llm_gate_by_symbol is not None:
                gate = llm_gate_by_symbol.get(base)
                if not gate:
                    risk_results.append({
                        "symbol": base,
                        "agent": signal.agent_name,
                        "account_id": account_id,
                        "approved": False,
                        "reason": "LLM 入场门禁未通过",
                    })
                    continue
                action = _execution_action(signal)
                gate_side = str(gate.get("side") or "")
                if not arena_signal_matches_llm_gate(signal, gate_side, match_mode="direction"):
                    risk_results.append({
                        "symbol": base,
                        "agent": signal.agent_name,
                        "account_id": account_id,
                        "approved": False,
                        "reason": (
                            f"Arena 信号 (exec={action}, action={signal.action}, dir={signal.direction}) "
                            f"与入场门禁 {gate_side} 不一致"
                        ),
                    })
                    continue
            account_context = (context.get("accounts") or {}).get(account_id) or context.get("account") or {}
            cash, total_equity, total_position_value = _cash_equity(account_context, quote)
            if total_equity > 0:
                risk_manager.update_equity(total_equity)
            decision_context = {**context, "account": account_context}
            decision = _signal_to_decision(signal, decision_context, quote, cash, total_equity)
            result = risk_manager.check_trade(decision, cash, total_position_value, total_equity)
            if result.adjusted_quantity is not None:
                decision["quantity"] = result.adjusted_quantity
            decision["riskApproved"] = result.approved
            decision["riskReason"] = result.reason
            decision["arenaAgent"] = signal.agent_name
            decision["accountId"] = account_id
            decision["source"] = signal.agent_name
            active_decisions.append(decision)
            risk_results.append({"symbol": decision.get("symbol"), "agent": signal.agent_name, "account_id": account_id, "approved": result.approved, "reason": result.reason})

    if effective_execute:
        approved = [decision for decision in active_decisions if decision.get("riskApproved")]
        current_prices = {
            item.get("pair", "").replace("-", "/"): _num((item.get("marketStats") or {}).get("last") or 0)
            for item in context.get("marketContext") or []
        }
        for account_id in list(dict.fromkeys(str(decision.get("accountId") or "default") for decision in approved)):
            account_decisions = [decision for decision in approved if str(decision.get("accountId") or "default") == account_id]
            trader = LiveTrader(dry_run=dry_run, account_id=account_id)
            try:
                execution_results.extend(await trader.execute_decisions(account_decisions, current_prices))
            finally:
                await trader.close()

    ts = datetime.now(timezone.utc).isoformat()
    performance_records = _build_performance_records(
        ts=ts,
        signals=signals,
        active_agent=normalized_active,
        execution_agents=normalized_execution_agents,
        paper_only=paper_only,
        risk_results=risk_results,
        execution_results=execution_results,
    )
    signal_payload = {
        "ts": ts,
        "symbols": symbol_list,
        "agents": names,
        "agentProfiles": [trace.profile.model_dump(mode="json") for trace in traces],
        "activeAgent": normalized_active,
        "executionAgents": normalized_execution_agents,
        "paperOnly": paper_only,
        "signals": [signal.model_dump(mode="json") for signal in signals],
        "activeDecisions": active_decisions,
        "riskResults": risk_results,
        "executionResults": execution_results,
    }
    trace_payload = {
        "ts": ts,
        "symbols": symbol_list,
        "agents": names,
        "traces": [trace.model_dump(mode="json") for trace in traces],
    }
    signals_path = append_arena_log(signal_payload)
    traces_path = append_arena_trace_log(trace_payload)
    performance_path = append_arena_performance_records([record.model_dump(mode="json") for record in performance_records])

    if print_traces:
        print(json.dumps(trace_payload, ensure_ascii=False, indent=2, default=str))

    result = ArenaRunResult(
        symbols=symbol_list,
        agents=names,
        active_agent=normalized_active,
        execution_agents=normalized_execution_agents,
        paper_only=paper_only,
        agent_profiles=[trace.profile for trace in traces],
        signals=signals,
        agent_traces=traces,
        performance_records=performance_records,
        active_decisions=active_decisions,
        risk_results=risk_results,
        risk_state=risk_manager.snapshot(),
        execution_results=execution_results,
        data_quality=context.get("dataQuality") or {},
        data_context=context,
        log_files={
            "signals": str(signals_path),
            "traces": str(traces_path),
            "performance": str(performance_path),
        },
    )
    return result