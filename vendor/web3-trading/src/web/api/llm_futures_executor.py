# -*- coding: utf-8 -*-
"""Execute KuCoin futures orders from dashboard LLM signal analysis."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from web.api.dashboard_service import (
    SIGNAL_NEWS_HOURS,
    SIGNAL_NEWS_LIMIT,
    fetch_derivatives_snapshot,
    fetch_market_stats,
    fetch_news,
    fetch_onchain,
    fetch_onchain_metrics,
    fetch_orderbook_snapshot,
    fetch_recent_trades,
    fetch_valuescan_signal_data,
)
from web.api.llm_signal_analyzer import (
    LLMModel,
    compute_signal_with_llm,
    evaluate_five_signal_alignment,
    resolve_futures_auto_exit,
)
from web.api.quant_factors_bridge import (
    evaluate_quant_alignment,
    fetch_quant_factors_for_symbol,
    resolve_quant_factors_options,
)
from web.api.trade_plan_executor import (
    evaluate_trade_plan_entry,
    normalize_trade_plan,
    resolve_trade_plan_options,
)
from web.api.trade_plan_store import (
    clear_entry_trade_plan,
    reconcile_stored_plans,
    resolve_position_trade_plan,
    save_entry_trade_plan,
)
from web.api.signal_backtest_context import (
    format_backtest_debate_context,
    resolve_signal_backtest_options,
    run_all_strategy_backtests,
)
from web.api.realtime_market_bridge import enrich_signal_data, fetch_signal_kline_signals
from web.api.ta_signal_bridge import run_trading_agents_for_signal
from web.api.executable_gate import is_execution_ready as _is_execution_ready

logger = logging.getLogger(__name__)

_DEFAULT_SYMBOLS = ("BTC", "ETH", "HYPE")
_DEFAULT_MAX_UNREALIZED_LOSS_PCT = 30.0


def default_max_unrealized_loss_pct() -> float:
    """默认最大浮亏%（conf/default.yaml: live_max_unrealized_loss_pct）。"""
    try:
        from web.config import config as app_config

        if app_config is not None:
            raw = getattr(app_config, "live_max_unrealized_loss_pct", None)
            if raw is not None:
                return max(0.0, min(50.0, float(raw)))
    except Exception:
        pass
    return _DEFAULT_MAX_UNREALIZED_LOSS_PCT


def _parse_leverage_controls(body: Dict[str, Any], *, machine_auto: bool) -> tuple[bool, int, int]:
    """返回 (auto_leverage, max_leverage_cap, fixed_leverage)。"""
    auto = body.get("autoLeverage")
    if auto is None:
        auto = body.get("auto_leverage")
    if auto is None:
        auto = machine_auto
    auto_leverage = bool(auto)

    cap_raw = body.get("maxLeverage")
    if cap_raw is None:
        cap_raw = body.get("max_leverage")
    if cap_raw is None:
        cap_raw = body.get("leverage")
    max_cap = max(1, int(_num(cap_raw, 10 if machine_auto else 5)))
    env_cap = int(_num(os.getenv("QUANT_MAX_LEVERAGE"), 0))
    if env_cap > 0:
        max_cap = min(max_cap, env_cap)
    fixed = max(1, min(max_cap, int(_num(body.get("leverage"), max_cap))))
    return auto_leverage, max_cap, fixed


def _signal_strength_ratio(analysis: Dict[str, Any]) -> Tuple[float, float, bool]:
    """与自动杠杆共用：置信度档位 × ready 折扣。"""
    confidence = _num(analysis.get("confidence"), 0.0)
    ready = _is_execution_ready(analysis.get("executionReadiness"))
    if confidence >= 78:
        ratio = 1.0
    elif confidence >= 68:
        ratio = 0.75
    elif confidence >= 58:
        ratio = 0.5
    else:
        ratio = 0.35
    if not ready:
        ratio *= 0.5
    return confidence, ratio, ready


def resolve_order_leverage(
    analysis: Dict[str, Any],
    *,
    auto_leverage: bool,
    max_leverage: int,
    fixed_leverage: int,
) -> Tuple[int, Dict[str, Any]]:
    """按用户杠杆上限自动选杠杆；关闭自动时使用固定值（不超过上限）。"""
    cap = max(1, min(125, int(max_leverage)))
    fixed = max(1, min(cap, int(fixed_leverage)))

    if not auto_leverage:
        return fixed, {"mode": "fixed", "leverage": fixed, "maxLeverage": cap}

    confidence, ratio, ready = _signal_strength_ratio(analysis)
    leverage = max(1, min(cap, int(round(cap * ratio)) or 1))
    return leverage, {
        "mode": "auto",
        "leverage": leverage,
        "maxLeverage": cap,
        "confidence": round(confidence, 2),
        "ready": ready,
        "ratio": round(ratio, 3),
    }


def _parse_position_controls(body: Dict[str, Any], *, machine_auto: bool) -> tuple[bool, float, float]:
    """返回 (auto_position_size, max_position_pct, fixed_position_pct)。"""
    auto = body.get("autoPositionSize")
    if auto is None:
        auto = body.get("auto_position_size")
    if auto is None:
        auto = machine_auto
    auto_position = bool(auto)

    pct_raw = body.get("maxPositionPctPerSymbol")
    if pct_raw is None:
        pct_raw = body.get("max_position_pct_per_symbol")
    if pct_raw is None:
        pct_raw = body.get("positionPctPerSymbol")
    if pct_raw is None:
        pct_raw = body.get("position_pct_per_symbol")
    max_pct = max(0.01, min(0.25, _num(pct_raw, 0.1 if machine_auto else 0.05)))
    fixed = max_pct
    return auto_position, max_pct, fixed


def resolve_position_pct(
    analysis: Dict[str, Any],
    *,
    auto_position_size: bool,
    max_position_pct: float,
    fixed_position_pct: float,
) -> Tuple[float, Dict[str, Any]]:
    """按用户仓位上限与信号强度选用保证金占比。"""
    cap = max(0.01, min(0.25, float(max_position_pct)))
    fixed = max(0.01, min(cap, float(fixed_position_pct)))

    if not auto_position_size:
        return fixed, {
            "mode": "fixed",
            "positionPct": round(fixed, 4),
            "maxPositionPct": round(cap, 4),
        }

    confidence, ratio, ready = _signal_strength_ratio(analysis)
    pct = max(0.01, min(cap, cap * ratio))
    return pct, {
        "mode": "auto",
        "positionPct": round(pct, 4),
        "maxPositionPct": round(cap, 4),
        "confidence": round(confidence, 2),
        "ready": ready,
        "ratio": round(ratio, 3),
    }


def _num(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        if number != number:
            return default
        return number
    except (TypeError, ValueError):
        return default


def _normalize_symbols(value: Any) -> List[str]:
    if isinstance(value, str):
        items = [part.strip() for part in value.replace(";", ",").split(",")]
    elif isinstance(value, list):
        items = [str(part).strip() for part in value]
    else:
        items = []
    symbols = [item.upper().split("-")[0].split("/")[0] for item in items if item]
    return symbols or list(_DEFAULT_SYMBOLS)


def _resolve_model(value: Any) -> LLMModel:
    raw = str(value or "").strip()
    if not raw:
        return LLMModel.DEEPSEEK_V4_PRO
    try:
        return LLMModel(raw)
    except ValueError:
        pass
    lowered = raw.lower()
    for item in LLMModel:
        if lowered in {item.value.lower(), item.name.lower()}:
            return item
        if lowered in item.value.lower():
            return item
    return LLMModel.DEEPSEEK_V4_PRO


def _futures_symbol(base: str) -> str:
    return f"{base.upper()}/USDT:USDT"


def _base_from_market_symbol(symbol: str) -> str:
    raw = str(symbol or "").upper().replace("-", "/")
    pair = raw.split(":", 1)[0]
    return pair.split("/", 1)[0]


async def _aggregate_signal_data(
    symbol: str,
    *,
    use_trading_agents: bool = False,
) -> Dict[str, Any]:
    sym = symbol.upper()
    pair = f"{sym}-USDT"

    bt_opts = resolve_signal_backtest_options()
    backtest_bundle: Dict[str, Any] = {}
    debate_context = ""
    if bt_opts.get("enabled"):
        try:
            backtest_bundle = await run_all_strategy_backtests(
                pair,
                kline_type=bt_opts["kline_type"],
                limit=bt_opts["limit"],
                stop_loss_pct=bt_opts["stop_loss_pct"],
                take_profit_pct=bt_opts["take_profit_pct"],
                trailing_stop_pct=bt_opts["trailing_stop_pct"],
                max_hold_bars=bt_opts["max_hold_bars"],
            )
            if backtest_bundle.get("available"):
                debate_context = format_backtest_debate_context(backtest_bundle)
        except Exception as exc:
            logger.warning("llm-futures backtest bundle failed for %s: %s", sym, exc)
            backtest_bundle = {"available": False, "error": str(exc)}

    news_task = fetch_news(sym, limit=SIGNAL_NEWS_LIMIT, hours=SIGNAL_NEWS_HOURS)
    onchain_task = fetch_onchain(sym)
    onchain_metrics_task = fetch_onchain_metrics(sym)
    kline_task = fetch_signal_kline_signals(pair)
    vs_task = fetch_valuescan_signal_data(sym)
    derivatives_task = fetch_derivatives_snapshot(pair)
    orderbook_task = fetch_orderbook_snapshot(pair)
    trades_task = fetch_recent_trades(pair)
    ta_task = (
        run_trading_agents_for_signal(
            sym,
            reply_language="Chinese",
            debate_context=debate_context or None,
        )
        if use_trading_agents
        else asyncio.sleep(0, result=None)
    )
    quant_opts = resolve_quant_factors_options()
    quant_task = (
        fetch_quant_factors_for_symbol(sym, market=quant_opts["market"])
        if quant_opts["enabled"]
        else asyncio.sleep(0, result={"available": False, "reason": "disabled"})
    )

    (
        news_result,
        onchain,
        onchain_metrics,
        kline,
        vs_data,
        derivatives,
        orderbook,
        recent_trades,
        ta_data,
        quant_factors,
    ) = await asyncio.gather(
        news_task,
        onchain_task,
        onchain_metrics_task,
        kline_task,
        vs_task,
        derivatives_task,
        orderbook_task,
        trades_task,
        ta_task,
        quant_task,
        return_exceptions=True,
    )

    if isinstance(news_result, Exception):
        logger.warning("llm-futures news error for %s: %s", sym, news_result)
        news_list: list = []
    else:
        news_list = news_result[0] if isinstance(news_result, tuple) else []

    if isinstance(onchain, Exception):
        onchain = {"summary": "", "extra": {}}
    if isinstance(onchain_metrics, Exception):
        onchain_metrics = {}
    if isinstance(kline, Exception):
        kline = {}
    if isinstance(vs_data, Exception):
        vs_data = {}
    if isinstance(derivatives, Exception):
        derivatives = {}
    if isinstance(orderbook, Exception):
        orderbook = {}
    if isinstance(recent_trades, Exception):
        recent_trades = {}
    if isinstance(ta_data, Exception):
        ta_data = None
    if isinstance(quant_factors, Exception):
        logger.warning("llm-futures quant factors error for %s: %s", sym, quant_factors)
        quant_factors = {"available": False, "reason": str(quant_factors)}
    if not isinstance(quant_factors, dict):
        quant_factors = {"available": False, "reason": "invalid_payload"}

    try:
        market = await fetch_market_stats(pair)
    except Exception as exc:
        logger.warning("llm-futures market error for %s: %s", sym, exc)
        market = {}

    vs_payload = vs_data if isinstance(vs_data, dict) else {}
    from web.api.valuescan_service import valuescan_chain_snapshot
    from web.api.news_freshness import apply_news_freshness_to_aggregated

    aggregated: Dict[str, Any] = {
        "symbol": sym,
        "pair": pair,
        "strategyBacktests": backtest_bundle if backtest_bundle else {},
        "news": news_list,
        "newsCount": len(news_list),
        "onchain": {
            "summary": onchain.get("summary", "") if isinstance(onchain, dict) else "",
            "extra": onchain.get("extra", {}) if isinstance(onchain, dict) else {},
        },
        "onchainMetrics": onchain_metrics if isinstance(onchain_metrics, dict) else {},
        "kline": kline if isinstance(kline, dict) else {},
        "market": market,
        "valuescan": vs_payload,
        "valuescanChain": valuescan_chain_snapshot(vs_payload),
        "derivatives": derivatives if isinstance(derivatives, dict) else {},
        "microstructure": {
            "orderbook": orderbook if isinstance(orderbook, dict) else {},
            "recentTrades": recent_trades if isinstance(recent_trades, dict) else {},
        },
    }
    if ta_data and isinstance(ta_data, dict) and ta_data.get("available"):
        aggregated["tradingAgents"] = ta_data
    aggregated["quantFactors"] = quant_factors
    apply_news_freshness_to_aggregated(aggregated)
    await enrich_signal_data(aggregated, pair)
    return aggregated


def _resolve_entry_side(
    analysis: Dict[str, Any],
    *,
    min_confidence: float,
    only_ready: bool,
    require_five_signal_align: bool,
    require_quant_align: bool = False,
    quant_min_aggregate: float = 0.12,
) -> tuple[Optional[str], str]:
    from web.api.entry_gate import resolve_entry_gate_options

    alignment = analysis.get("fiveSignalAlignment") or analysis.get("entryGateAlignment") or {}
    gate_opts = resolve_entry_gate_options()
    eff_min_conf = float(min_confidence) if min_confidence > 0 else gate_opts["min_confidence"]
    confidence = _num(analysis.get("confidence"), 0.0)
    readiness = str(analysis.get("executionReadiness") or "wait").lower()

    if confidence < eff_min_conf:
        return None, f"置信度 {confidence} 低于门槛 {eff_min_conf}"

    side: Optional[str] = None
    reason = ""

    if require_five_signal_align:
        if not alignment.get("aligned"):
            return None, alignment.get("reason") or "入场门禁未通过"
        side = alignment.get("side")
        reason = alignment.get("reason") or "入场门禁通过"
    else:
        signal = str(analysis.get("signal") or "NEUTRAL").upper()
        if signal == "BUY":
            side, reason = "buy", f"综合信号 {signal}"
        elif signal == "SELL":
            side, reason = "sell", f"综合信号 {signal}"
        else:
            return None, f"综合信号 {signal} 不可执行"

    if only_ready and not _is_execution_ready(readiness):
        return None, f"执行准备度 {analysis.get('executionReadiness')} 非 ready（门禁已含可执行维时通常已满足）"

    if require_quant_align and side:
        quant = analysis.get("quantFactors") or {}
        ok, msg = evaluate_quant_alignment(
            side,
            quant,
            require_align=True,
            min_aggregate=quant_min_aggregate,
        )
        if not ok:
            return None, msg

    return side, reason


async def analyze_symbol_for_futures(
    symbol: str,
    *,
    model: LLMModel = LLMModel.DEEPSEEK_V4_PRO,
    use_trading_agents: bool = False,
) -> Dict[str, Any]:
    sym = symbol.upper()
    data = await _aggregate_signal_data(sym, use_trading_agents=use_trading_agents)
    result = await compute_signal_with_llm(data, model=model)
    analysis = result.analysis.model_dump() if result.analysis else {}
    q_opts = resolve_quant_factors_options()
    from web.api.entry_gate import evaluate_entry_gate_alignment, resolve_entry_gate_options

    gate_opts = resolve_entry_gate_options()
    alignment = evaluate_entry_gate_alignment(
        result,
        market_data=data,
        news_meta=data.get("newsMeta"),
        quant_factors=data.get("quantFactors"),
        quant_min_aggregate=q_opts["min_aggregate"],
        require_quant_in_gate=bool(q_opts["enabled"]),
    )
    from web.api.five_signal_view import analysis_view_from_signal_result, build_five_signals_list

    view = analysis_view_from_signal_result(result, data, alignment)
    five_signals = build_five_signals_list(view)
    return {
        "symbol": sym,
        "pair": data.get("pair") or f"{sym}-USDT",
        "futuresSymbol": _futures_symbol(sym),
        "signal": result.signal,
        "label": result.label,
        "score": result.score,
        "confidence": result.confidence,
        "summary": result.summary,
        "reasons": result.reasons,
        "executionReadiness": analysis.get("executionReadiness") or "wait",
        "bias": analysis.get("bias") or "neutral",
        "consensus": analysis.get("consensus") or {},
        "factors": result.factors.model_dump() if result.factors else {},
        "quantFactors": data.get("quantFactors") or {},
        "fiveSignalAlignment": alignment,
        "fiveSignals": five_signals,
        "dataQuality": result.dataQuality.model_dump() if result.dataQuality else {},
        "newsCount": len(data.get("news") or []),
        "newsMeta": data.get("newsMeta") or {},
        "onchain": data.get("onchain") or {},
        "onchainMetrics": data.get("onchainMetrics") or {},
        "tradePlan": result.tradePlan.model_dump() if result.tradePlan else {},
        "valuescanInsights": result.valuescanInsights or data.get("valuescanDigest") or {},
        "realtime": data.get("realtime") or {},
        "engineMeta": result.engineMeta.model_dump() if result.engineMeta else {},
        "dataQuality": result.dataQuality.model_dump() if result.dataQuality else {},
        "_result": result,
    }


async def _fetch_available_usdt(account_id: str) -> float:
    from quant.kucoin_native import KuCoinNativeClient
    from web.api.live_trading_routes import _native_order_ok

    native = KuCoinNativeClient("futures", account_id=account_id)
    response = await native.futures_account_overview("USDT")
    if _native_order_ok(response):
        data = response.get("data") or {}
        return _num(data.get("availableBalance") or data.get("availableMargin"))
    return 0.0


async def _resolve_entry_contracts(
    account_id: str,
    futures_symbol: str,
    leverage: int,
    *,
    requested_contracts: int,
    max_margin_usd: float,
    max_notional_usd: float,
    position_pct: float,
    available_usdt: float,
    auto_size: bool,
) -> tuple[int, Dict[str, Any]]:
    from web.api.dashboard_service import fetch_futures_contract_meta, fetch_futures_mark_price

    if not auto_size:
        return max(1, requested_contracts), {
            "mode": "manual",
            "contracts": max(1, requested_contracts),
            "availableUsdt": round(available_usdt, 4),
        }

    margin_budget = min(max_margin_usd, available_usdt * max(position_pct, 0.01))
    if margin_budget <= 1:
        return 0, {
            "mode": "auto",
            "contracts": 0,
            "availableUsdt": round(available_usdt, 4),
            "marginBudget": round(margin_budget, 4),
            "reason": "可用保证金不足，跳过开仓",
        }

    pair = futures_symbol.split(":")[0].replace("/", "-")
    mark = await fetch_futures_mark_price(pair)
    meta = await fetch_futures_contract_meta(pair)
    price = _num(mark.get("markPrice") or mark.get("price") or mark.get("last"))
    contract_size = max(_num(meta.get("multiplier") or meta.get("contractSize"), 1.0), 1e-12)

    if price <= 0:
        return 0, {"mode": "auto", "contracts": 0, "reason": "无法读取合约价格"}

    notional_budget = min(max_notional_usd, margin_budget * leverage)
    contracts = max(1, int(notional_budget / (price * contract_size)))
    while contracts > 1:
        est_margin = (contracts * contract_size * price) / leverage
        if est_margin <= margin_budget:
            break
        contracts -= 1

    est_margin = (contracts * contract_size * price) / leverage
    est_notional = contracts * contract_size * price
    return contracts, {
        "mode": "auto",
        "contracts": contracts,
        "availableUsdt": round(available_usdt, 4),
        "marginBudget": round(margin_budget, 4),
        "estimatedMarginUsd": round(est_margin, 4),
        "estimatedNotionalUsd": round(est_notional, 4),
        "price": round(price, 8),
        "contractSize": contract_size,
        "positionPct": position_pct,
    }


def _resolve_live_confirm(body: Dict[str, Any]) -> tuple[str, bool]:
    confirm_live = str(body.get("confirmLive") or body.get("confirm_live") or "").strip()
    if confirm_live == "CONFIRM":
        return "CONFIRM", True
    auto_live = bool(body.get("autoLive", body.get("auto_live")))
    machine_auto = bool(body.get("machineAuto", body.get("machine_auto")))
    if auto_live or machine_auto:
        return "CONFIRM", True
    return confirm_live, False


async def _fetch_open_futures_positions(account_id: str, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    from quant.kucoin_native import KuCoinNativeClient
    from web.api.live_trading_routes import _native_order_ok

    targets = {symbol.upper() for symbol in symbols}
    positions_by_base: Dict[str, Dict[str, Any]] = {}
    native = KuCoinNativeClient("futures", account_id=account_id)
    response = await native.futures_positions("USDT")
    if not _native_order_ok(response):
        return positions_by_base

    for row in response.get("data") or []:
        contracts = abs(_num(row.get("currentQty") or row.get("size") or row.get("qty") or 0))
        if contracts <= 0:
            continue
        native_symbol = str(row.get("symbol") or "")
        base = native_symbol.replace("USDTM", "").replace("USDT", "")
        if base == "XBT":
            base = "BTC"
        if base not in targets:
            continue
        side = "long" if _num(row.get("currentQty") or row.get("size") or row.get("qty")) > 0 else "short"
        entry_price = _num(row.get("avgEntryPrice") or row.get("entryPrice"))
        mark_price = _num(row.get("markPrice") or row.get("markValue"))
        unrealised_pnl = _num(row.get("unrealisedPnl") or row.get("unrealizedPnl"))
        unrealised_roe = _num(row.get("unrealisedRoe") or row.get("unrealizedRoe"))
        pos_margin = _num(row.get("posMargin") or row.get("maintMargin") or row.get("maintainMargin"))
        unrealized_margin_pct = 0.0
        if pos_margin > 0 and unrealised_pnl < 0:
            unrealized_margin_pct = unrealised_pnl / pos_margin * 100.0
        unrealized_pnl_pct = 0.0
        if entry_price > 0 and mark_price > 0:
            if side == "long":
                unrealized_pnl_pct = (mark_price - entry_price) / entry_price * 100.0
            else:
                unrealized_pnl_pct = (entry_price - mark_price) / entry_price * 100.0
        positions_by_base[base] = {
            "symbol": _futures_symbol(base),
            "futuresSymbol": _futures_symbol(base),
            "nativeSymbol": native_symbol,
            "side": side,
            "contracts": int(max(1, round(contracts))),
            "notional": _num(row.get("markValue") or row.get("posCost")),
            "entryPrice": entry_price,
            "markPrice": mark_price,
            "unrealisedPnl": unrealised_pnl,
            "unrealisedRoe": unrealised_roe,
            "unrealizedPnlPct": unrealized_pnl_pct,
            "unrealizedMarginPct": unrealized_margin_pct,
        }
    return positions_by_base


def _order_payload(
    *,
    account_id: str,
    analysis: Dict[str, Any],
    side: str,
    contracts: int,
    leverage: int,
    max_notional_usd: float,
    max_margin_usd: float,
    confirm_live: str,
    body: Dict[str, Any],
    reduce_only: bool,
    order_type: str = "market",
    limit_price: Optional[float] = None,
) -> Dict[str, Any]:
    payload = {
        "accountId": account_id,
        "symbol": analysis.get("futuresSymbol") or _futures_symbol(str(analysis.get("symbol") or "BTC")),
        "side": side,
        "contracts": contracts,
        "leverage": leverage,
        "marginMode": str(body.get("marginMode") or "CROSS").upper(),
        "positionMode": str(body.get("positionMode") or "HEDGE").upper(),
        "reduceOnly": reduce_only,
        "maxNotionalUsd": max_notional_usd,
        "maxMarginUsd": max_margin_usd,
        "confirmLive": confirm_live,
        "orderType": order_type,
    }
    if limit_price and limit_price > 0:
        payload["price"] = limit_price
    trade_plan = analysis.get("tradePlan") or {}
    if trade_plan.get("stop"):
        payload["tradePlanStop"] = trade_plan.get("stop")
    return payload


async def run_llm_futures_batch(body: Dict[str, Any]) -> Dict[str, Any]:
    from web.api.live_trading_routes import _resolve_live_futures_account_id, _run_futures_order

    symbols = _normalize_symbols(body.get("symbols"))
    execute = bool(body.get("execute", True))
    confirm_live, confirm_ok = _resolve_live_confirm(body)
    if execute and not confirm_ok:
        return {"ok": False, "message": "真实合约下单需开启「自动实盘」，或在手动下单区输入 CONFIRM"}

    model = _resolve_model(body.get("model"))
    use_trading_agents = bool(body.get("useTradingAgents"))
    min_confidence = _num(body.get("minConfidence"), 55.0)
    only_ready = bool(body.get("onlyReady", False))
    require_five_signal_align = bool(body.get("requireFiveSignalAlign", True))
    quant_opts = resolve_quant_factors_options()
    require_quant_align = bool(
        body.get("requireQuantAlign", body.get("require_quant_align", quant_opts["require_align"]))
    )
    quant_min_aggregate = float(
        body.get("quantMinAggregate", body.get("quant_min_aggregate", quant_opts["min_aggregate"]))
    )
    plan_opts = resolve_trade_plan_options()
    trade_plan_strict = bool(
        body.get("tradePlanStrict", body.get("trade_plan_strict", plan_opts["strict"]))
    )
    trade_plan_tolerance = float(
        body.get(
            "tradePlanEntryTolerancePct",
            body.get("trade_plan_entry_tolerance_pct", plan_opts["entry_tolerance_pct"]),
        )
    )
    enforce_plan_stop = bool(
        body.get("enforceTradePlanStop", body.get("enforce_trade_plan_stop", plan_opts["enforce_stop"]))
    )
    enforce_plan_targets = bool(
        body.get(
            "enforceTradePlanTargets",
            body.get("enforce_trade_plan_targets", plan_opts["enforce_targets"]),
        )
    )
    stop_on_reversal = bool(body.get("stopOnReversal", True))
    stop_on_loss = bool(body.get("stopOnLoss", True))
    max_unrealized_loss_pct = max(
        0.0, _num(body.get("maxUnrealizedLossPct"), default_max_unrealized_loss_pct())
    )
    max_unrealized_loss_usd = max(0.0, _num(body.get("maxUnrealizedLossUsd"), 0.0))
    machine_auto = bool(body.get("machineAuto"))
    auto_position_size, max_position_pct, fixed_position_pct = _parse_position_controls(
        body,
        machine_auto=machine_auto,
    )
    requested_contracts = max(1, int(_num(body.get("contracts"), 1)))
    auto_leverage, max_leverage_cap, fixed_leverage = _parse_leverage_controls(body, machine_auto=machine_auto)
    max_notional_usd = _num(body.get("maxNotionalUsd"), 30.0 if machine_auto else 100.0)
    max_margin_usd = _num(body.get("maxMarginUsd"), 15.0 if machine_auto else 50.0)
    account_id = _resolve_live_futures_account_id(body)

    available_usdt = await _fetch_available_usdt(account_id) if execute else 0.0
    open_positions = await _fetch_open_futures_positions(account_id, symbols) if execute else {}
    if execute:
        stale = reconcile_stored_plans(account_id, set(open_positions.keys()))
        if stale:
            logger.info(
                "cleared stale trade plans for %s (no open position): %s",
                account_id,
                ", ".join(stale),
            )

    precomputed_raw = body.get("precomputedAnalyses") or body.get("precomputed_analyses") or {}
    arena_approved_raw = body.get("arenaApprovedSymbols")
    if arena_approved_raw is None:
        arena_approved_raw = body.get("arena_approved_symbols")
    arena_approved: Optional[set[str]] = None
    if arena_approved_raw is not None:
        arena_approved = {
            str(item).upper().split("-")[0].split("/")[0]
            for item in (arena_approved_raw if isinstance(arena_approved_raw, list) else [])
        }

    analyses: List[Any] = []
    for symbol in symbols:
        sym = symbol.upper()
        cached = precomputed_raw.get(sym) if isinstance(precomputed_raw, dict) else None
        if cached and not isinstance(cached, Exception):
            analyses.append(dict(cached))
            continue
        try:
            analyses.append(
                await analyze_symbol_for_futures(symbol, model=model, use_trading_agents=use_trading_agents)
            )
        except Exception as exc:
            analyses.append(exc)

    results: List[Dict[str, Any]] = []
    closed = 0
    opened = 0

    for symbol, analysis in zip(symbols, analyses):
        sym = symbol.upper()
        if isinstance(analysis, Exception):
            results.append({
                "symbol": sym,
                "status": "failed",
                "action": "analyze",
                "reason": f"{type(analysis).__name__}: {analysis}",
            })
            continue

        result_obj = analysis.pop("_result", None)
        row: Dict[str, Any] = {
            **{key: value for key, value in analysis.items() if key != "_result"},
            "side": None,
            "status": "skipped",
            "action": "hold",
            "reason": "",
        }

        existing = open_positions.get(sym)
        order_leverage, leverage_meta = resolve_order_leverage(
            row,
            auto_leverage=auto_leverage,
            max_leverage=max_leverage_cap,
            fixed_leverage=fixed_leverage,
        )
        row["leverage"] = order_leverage
        row["leverageMeta"] = leverage_meta
        order_position_pct, position_meta = resolve_position_pct(
            row,
            auto_position_size=auto_position_size,
            max_position_pct=max_position_pct,
            fixed_position_pct=fixed_position_pct,
        )
        row["positionPct"] = order_position_pct
        row["positionMeta"] = position_meta

        plan_exit_enabled = enforce_plan_stop or enforce_plan_targets
        auto_exit_enabled = stop_on_reversal or stop_on_loss or plan_exit_enabled
        if execute and auto_exit_enabled and existing:
            close_leverage = max(1, int(_num(existing.get("leverage"), order_leverage)))
            position_plan = resolve_position_trade_plan(
                account_id,
                sym,
                fallback=row.get("tradePlan"),
            )
            should_close, exit_reason, exit_action = resolve_futures_auto_exit(
                existing,
                result_obj,
                row.get("fiveSignalAlignment") or {},
                stop_on_reversal=stop_on_reversal,
                stop_on_loss=stop_on_loss,
                max_loss_pct=max_unrealized_loss_pct,
                max_loss_usd=max_unrealized_loss_usd,
                trade_plan=position_plan,
                enforce_plan_stop=enforce_plan_stop,
                enforce_plan_targets=enforce_plan_targets,
                analysis=row if result_obj is None else None,
            )
            if should_close:
                close_side = "sell" if existing.get("side") == "long" else "buy"
                close_contracts = int(existing.get("contracts") or requested_contracts)
                order_body = _order_payload(
                    account_id=account_id,
                    analysis=row,
                    side=close_side,
                    contracts=close_contracts,
                    leverage=close_leverage,
                    max_notional_usd=max_notional_usd,
                    max_margin_usd=max_margin_usd,
                    confirm_live=confirm_live,
                    body=body,
                    reduce_only=True,
                )
                try:
                    order_result = await _run_futures_order(order_body)
                except Exception as exc:
                    row["status"] = "failed"
                    row["action"] = exit_action
                    row["reason"] = str(exc)
                    results.append(row)
                    continue

                row["exitOrder"] = order_result
                row["stopLossOrder"] = order_result
                row["action"] = exit_action
                row["unrealizedPnlPct"] = existing.get("unrealizedPnlPct")
                row["unrealisedPnl"] = existing.get("unrealisedPnl")
                if order_result.get("ok"):
                    row["status"] = "stopped"
                    row["reason"] = exit_reason
                    closed += 1
                    open_positions.pop(sym, None)
                    clear_entry_trade_plan(account_id, sym)
                else:
                    row["status"] = "failed"
                    row["reason"] = order_result.get("message") or order_result.get("reason") or exit_reason
                results.append(row)
                continue

        side, reason = _resolve_entry_side(
            row,
            min_confidence=min_confidence,
            only_ready=only_ready,
            require_five_signal_align=require_five_signal_align,
            require_quant_align=require_quant_align,
            quant_min_aggregate=quant_min_aggregate,
        )
        row["side"] = side
        row["reason"] = reason

        if not side:
            row["status"] = "skipped"
            row["action"] = "hold"
            results.append(row)
            continue

        if arena_approved is not None and sym not in arena_approved:
            row["status"] = "skipped"
            row["action"] = "hold"
            row["reason"] = (
                "Arena 执行 Agent 未与入场门禁一致"
                "（WEAK_* 仅方向一致时请将 hybridArenaMatchMode=direction，或改用 llm_futures 管线）"
            )
            results.append(row)
            continue

        if existing:
            existing_side = str(existing.get("side") or "").lower()
            if (existing_side == "long" and side == "buy") or (existing_side == "short" and side == "sell"):
                row["status"] = "skipped"
                row["action"] = "hold"
                row["reason"] = f"已有同向持仓 ({existing_side})，不再加仓"
                results.append(row)
                continue
            if (existing_side == "long" and side == "sell") or (existing_side == "short" and side == "buy"):
                row["status"] = "skipped"
                row["action"] = "hold"
                row["reason"] = (
                    f"已有 {existing_side} 仓，信号为反向 {side}；"
                    "未触发自动平仓时不叠反向仓（避免 HEDGE 双向持仓）"
                )
                results.append(row)
                continue

        if not execute:
            row["status"] = "analyzed"
            row["action"] = "entry"
            row["reason"] = (
                f"入场门禁建议 {side}，杠杆 {order_leverage}x（上限 {max_leverage_cap}x），"
                f"仓位 {order_position_pct * 100:.1f}%（上限 {max_position_pct * 100:.1f}%），未执行下单"
            )
            results.append(row)
            continue

        order_contracts, sizing = await _resolve_entry_contracts(
            account_id,
            row.get("futuresSymbol") or _futures_symbol(sym),
            order_leverage,
            requested_contracts=requested_contracts,
            max_margin_usd=max_margin_usd,
            max_notional_usd=max_notional_usd,
            position_pct=order_position_pct,
            available_usdt=available_usdt,
            auto_size=auto_position_size,
        )
        row["positionSizing"] = sizing
        if order_contracts <= 0:
            row["status"] = "skipped"
            row["action"] = "hold"
            row["reason"] = sizing.get("reason") or "仓位控制后无可下单张数"
            results.append(row)
            continue

        plan = normalize_trade_plan(row.get("tradePlan"))
        order_type = "market"
        limit_price: Optional[float] = None
        if trade_plan_strict:
            if not plan:
                row["status"] = "skipped"
                row["action"] = "hold"
                row["reason"] = "交易计划缺失，严格模式下禁止开仓"
                results.append(row)
                continue
            from web.api.dashboard_service import fetch_futures_mark_price

            pair = str(row.get("pair") or f"{sym}-USDT")
            try:
                mark_data = await fetch_futures_mark_price(pair)
            except Exception as exc:
                logger.warning("trade plan mark price fetch failed for %s: %s", sym, exc)
                mark_data = {}
            mark_price = _num(
                mark_data.get("markPrice") or mark_data.get("price") or mark_data.get("value")
            )
            allowed, plan_reason, plan_meta = evaluate_trade_plan_entry(
                plan,
                side,
                mark_price,
                tolerance_pct=trade_plan_tolerance,
            )
            row["tradePlanCheck"] = {"allowed": allowed, "reason": plan_reason, **plan_meta}
            if not allowed:
                row["status"] = "skipped"
                row["action"] = "hold"
                row["reason"] = plan_reason
                results.append(row)
                continue
            order_type = str(plan_meta.get("orderType") or "market")
            limit_price = None
            if order_type == "limit":
                limit_price = _num(plan_meta.get("limitPrice"))

        order_body = _order_payload(
            account_id=account_id,
            analysis=row,
            side=side,
            contracts=order_contracts,
            leverage=order_leverage,
            max_notional_usd=max_notional_usd,
            max_margin_usd=max_margin_usd,
            confirm_live=confirm_live,
            body=body,
            reduce_only=False,
            order_type=order_type,
            limit_price=limit_price,
        )
        try:
            order_result = await _run_futures_order(order_body)
        except Exception as exc:
            row["status"] = "failed"
            row["action"] = "entry"
            row["reason"] = str(exc)
            results.append(row)
            continue

        row["order"] = order_result
        row["action"] = "entry"
        if order_result.get("ok"):
            row["status"] = "executed"
            plan_note = ""
            if plan.get("stop"):
                plan_note = f" · 止损 {plan['stop']:.4g}"
            entry_px = _num(
                (order_result.get("preflight") or {}).get("price")
                or (row.get("tradePlanCheck") or {}).get("markPrice")
            )
            if plan:
                save_entry_trade_plan(
                    account_id,
                    sym,
                    plan,
                    side=side,
                    entry_price=entry_px,
                )
            row["reason"] = (
                f"交易计划执行：{order_type} {side}（{order_leverage}x · 仓位 {order_position_pct * 100:.1f}%）{plan_note}"
            )
            opened += 1
        else:
            row["status"] = "failed"
            row["reason"] = order_result.get("message") or order_result.get("reason") or "下单失败"
        results.append(row)

    executed = sum(1 for item in results if item.get("status") == "executed")
    skipped = sum(1 for item in results if item.get("status") == "skipped")
    failed = sum(1 for item in results if item.get("status") == "failed")
    stopped = sum(1 for item in results if item.get("status") == "stopped")
    loss_cut = sum(1 for item in results if item.get("action") == "loss_cut" and item.get("status") == "stopped")
    signal_exit = sum(
        1
        for item in results
        if item.get("action") in {"stop_loss", "plan_stop", "plan_target"}
        and item.get("status") == "stopped"
    )
    return {
        "ok": True,
        "account_id": account_id,
        "symbols": symbols,
        "execute": execute,
        "machineAuto": machine_auto,
        "autoPositionSize": auto_position_size,
        "maxPositionPctPerSymbol": max_position_pct,
        "autoLeverage": auto_leverage,
        "maxLeverage": max_leverage_cap,
        "availableUsdt": round(available_usdt, 4),
        "requireFiveSignalAlign": require_five_signal_align,
        "requireQuantAlign": require_quant_align,
        "quantMinAggregate": quant_min_aggregate,
        "tradePlanStrict": trade_plan_strict,
        "enforceTradePlanStop": enforce_plan_stop,
        "enforceTradePlanTargets": enforce_plan_targets,
        "stopOnReversal": stop_on_reversal,
        "stopOnLoss": stop_on_loss,
        "maxUnrealizedLossPct": max_unrealized_loss_pct,
        "maxUnrealizedLossUsd": max_unrealized_loss_usd,
        "arenaApprovedSymbols": sorted(arena_approved) if arena_approved is not None else None,
        "executed": executed,
        "opened": opened,
        "stopped": stopped,
        "signalExit": signal_exit,
        "lossCut": loss_cut,
        "skipped": skipped,
        "failed": failed,
        "results": results,
    }
