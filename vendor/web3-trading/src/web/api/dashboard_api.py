# -*- coding: utf-8 -*-
"""
Dashboard API — thin controller layer for the 投顾 (investment advisor) page.

All heavy lifting (data fetching, signal computation) lives in:
- dashboard_service.py  — external data access (MCP, KuCoin, fallbacks)
- signal_analyzer.py    — composable signal scoring pipeline
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import Request
from fastapi.responses import JSONResponse

from web.router import BaseRouter
from web.api.dashboard_service import (
    kucoin_get,
    build_skills_modules,
    fetch_news,
    fetch_onchain,
    fetch_onchain_metrics,
    fetch_kline_signals,
    fetch_market_stats,
    fetch_derivatives_snapshot,
    fetch_orderbook_snapshot,
    fetch_recent_trades,
    fetch_valuescan_signal_data,
    normalize_tickers,
    normalize_candle,
    to_contract_symbol,
    analyze_candles,
    SIGNAL_NEWS_HOURS,
    SIGNAL_NEWS_LIMIT,
)
from web.api.signal_analyzer import compute_signal
from web.api.llm_signal_analyzer import compute_signal_with_llm, LLMModel
from web.api.ta_signal_bridge import run_trading_agents_for_signal
from web.api.signal_backtest_context import (
    format_backtest_debate_context,
    resolve_signal_backtest_options,
    run_all_strategy_backtests,
)
from web.api.opportunity_scanner import scan_opportunities
from web.api.realtime_market_bridge import enrich_signal_data, fetch_signal_kline_signals
from dao.local.signal_task_store import (
    create_task,
    get_task,
    update_task_running,
    update_task_done,
    update_task_failed,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure helpers (formatting / local analysis — no I/O)
# ---------------------------------------------------------------------------
def _signed_pct(value: float) -> str:
    pct = value * 100
    return f"{'+' if pct >= 0 else ''}{pct:.2f}%"


def _level_from_quant(score: float) -> str:
    if score >= 75:
        return "A"
    if score >= 60:
        return "B"
    if score >= 45:
        return "C"
    return "D"


def _build_local_skills_analysis(
    symbols: List[str],
    market_stats_list: List[Dict],
    quant_snapshot_list: List[Dict],
    module_snapshot: Optional[Dict] = None,
    reason: str = "",
) -> str:
    quant_by = {
        str(q["symbol"]).upper(): q
        for q in (quant_snapshot_list or [])
        if isinstance(q, dict) and q.get("symbol")
    }
    market_by = {
        str(m.get("symbol", "")).upper(): m
        for m in (market_stats_list or [])
        if isinstance(m, dict) and m.get("symbol")
    }

    ranked = []
    for sym in symbols:
        upper = (sym or "").upper()
        quant = quant_by.get(upper, {})
        market = market_by.get(upper, {})
        score = float(quant.get("quantScore") or 0)
        change_rate = float(market.get("changeRate") if "changeRate" in market else quant.get("changeRate") or 0)
        vol_value = float(market.get("volValue") if "volValue" in market else quant.get("volValue") or 0)
        ranked.append({
            "symbol": upper, "score": score,
            "changeRate": change_rate, "volValue": vol_value,
            "opportunityLevel": quant.get("opportunityLevel") or _level_from_quant(score),
            "last": float(market.get("last") if "last" in market else quant.get("last") or 0),
            "high": float(market.get("high") or 0),
            "low": float(market.get("low") or 0),
        })
    ranked.sort(key=lambda x: (x["score"], x["volValue"]), reverse=True)

    top = ranked[0] if ranked else None
    top_text = (
        f"{top['symbol']}(评分 {top['score']:.1f}，24h {_signed_pct(top['changeRate'])})"
        if top else "暂无高置信标的"
    )
    module_meta = "无"
    if module_snapshot and isinstance(module_snapshot, dict):
        mods = module_snapshot.get("modules") or []
        module_meta = f"{module_snapshot.get('symbol', '-')} / {len(mods)} 个模块"

    entry_lines = []
    for i, item in enumerate(ranked):
        last = item["last"]
        rng = f"{last * 0.992:.4f} ~ {last * 1.004:.4f}" if last > 0 else "等待盘口确认"
        stop = f"{last * 0.988:.4f}" if last > 0 else "-"
        target = f"{last * 1.018:.4f}" if last > 0 else "-"
        pos = "20%" if item["opportunityLevel"] == "A" else "12%" if item["opportunityLevel"] == "B" else "8%"
        entry_lines.append(
            f"{i + 1}. {item['symbol']}\n"
            f"   - 优先级: {'高' if i == 0 else '中' if i == 1 else '低'}\n"
            f"   - 入场区间: {rng}\n"
            f"   - 止损位: {stop}\n"
            f"   - 第一目标位: {target}\n"
            f"   - 仓位建议: {pos}\n"
            f"   - 失效条件: 跌破止损且 1h 成交量放大"
        )

    return (
        f"结论\n- 当前优先关注: {top_text}\n"
        f"- 依据: 量化评分、24h 变动、成交额与可用模块快照。\n\n"
        f"机会\n"
        + "\n".join(
            f"- {x['symbol']}: 机会等级 {x['opportunityLevel']}，24h {_signed_pct(x['changeRate'])}，成交额 {x['volValue']:.2f}"
            for x in ranked
        )
        + "\n\n风险\n- 若 BTC 出现放量反向波动，山寨币相关策略需同步降杠杆。\n"
        "- 低流动性标的滑点风险高，市价单需谨慎。\n\n"
        f"观察指标\n- 1h/4h 收盘形态、MA20 斜率、成交量变化。\n- 模块样本: {module_meta}\n"
        + (f"- 触发兜底原因: {reason}\n" if reason else "")
        + "\n交易计划\n"
        + ("\n".join(entry_lines) if entry_lines else "- 暂无可执行计划（缺少有效行情数据）。")
    )


# ---------------------------------------------------------------------------
# K-line single-timeframe verdict
# ---------------------------------------------------------------------------
def _kline_verdict(analysis: Dict) -> Dict[str, Any]:
    """Derive a directional verdict from a single-timeframe analysis dict."""
    if not analysis:
        return {"action": "WAIT", "actionLabel": "等待", "direction": "neutral", "score": 0, "reasons": ["数据不足"]}

    score = 0.0
    reasons: List[str] = []
    trend = analysis.get("trend", "")
    rsi = analysis.get("rsi")
    bb_pct_b = analysis.get("bbPctB")
    bb_width = analysis.get("bbWidth")
    regime = analysis.get("regime", "unknown")
    breakout = analysis.get("breakout", "none")
    vol_ratio = analysis.get("volRatio", 1.0)
    range_pos = analysis.get("rangePos", 50)

    trend_map = {
        "bullish": (20, "均线多头排列，趋势向上"),
        "weak_bullish": (10, "短线偏多，价格站上 MA20"),
        "bearish": (-20, "均线空头排列，趋势向下"),
        "weak_bearish": (-10, "短线偏空，价格跌破 MA20"),
    }
    if trend in trend_map:
        delta, reason = trend_map[trend]
        score += delta
        reasons.append(reason)

    if rsi is not None:
        if rsi >= 80:
            score -= 12
            reasons.append(f"RSI {rsi:.1f} 严重超买，回调风险极高")
        elif rsi >= 70:
            score -= 7
            reasons.append(f"RSI {rsi:.1f} 超买，注意回调")
        elif rsi <= 20:
            score += 12
            reasons.append(f"RSI {rsi:.1f} 严重超卖，反弹概率高")
        elif rsi <= 30:
            score += 7
            reasons.append(f"RSI {rsi:.1f} 超卖，关注反弹")

    if bb_pct_b is not None:
        if bb_pct_b >= 100:
            score -= 6
            reasons.append("价格突破布林上轨，短期超买")
        elif bb_pct_b <= 0:
            score += 6
            reasons.append("价格跌破布林下轨，短期超卖")

    if bb_width is not None and bb_width < 2.0:
        reasons.append(f"布林带极度收窄（{bb_width:.1f}%），变盘在即")

    if breakout == "bullish":
        bonus = 15 if vol_ratio >= 1.5 else 8
        score += bonus
        reasons.append(f"向上突破前期高点，量比 {vol_ratio:.1f}x")
    elif breakout == "bearish":
        bonus = 15 if vol_ratio >= 1.5 else 8
        score -= bonus
        reasons.append(f"向下跌破前期低点，量比 {vol_ratio:.1f}x")

    if regime == "trending":
        if "bullish" in trend:
            score += 5
        elif "bearish" in trend:
            score -= 5
    elif regime == "ranging":
        if range_pos >= 80:
            score -= 4
            reasons.append("震荡行情中接近区间顶部，逢高减仓")
        elif range_pos <= 20:
            score += 4
            reasons.append("震荡行情中接近区间底部，逢低布局")

    score = max(-100, min(100, score))

    if score >= 25:
        action, label, direction = "LONG", "做多", "bullish"
    elif score >= 10:
        action, label, direction = "WEAK_LONG", "偏多观望", "bullish"
    elif score <= -25:
        action, label, direction = "SHORT", "做空", "bearish"
    elif score <= -10:
        action, label, direction = "WEAK_SHORT", "偏空观望", "bearish"
    else:
        action, label, direction = "WAIT", "观望等待", "neutral"

    return {
        "action": action,
        "actionLabel": label,
        "direction": direction,
        "score": round(score, 1),
        "confidence": min(95, round(abs(score), 1)),
        "reasons": reasons,
    }


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
class DashboardApi(BaseRouter):
    """Thin API controller — delegates to service + analyzer layers."""

    def __init__(self):
        super().__init__()

        # ---- Market tickers ----
        @self._router.get("/market/tickers")
        async def market_tickers(request: Request, quote: str = "USDT", search: str = "", limit: int = 300):
            try:
                data = await kucoin_get("/api/v1/market/allTickers")
                tickers = normalize_tickers(
                    (data.get("data") or {}).get("ticker") or [],
                    quote=quote, search=search, limit=min(limit, 300),
                )
                return JSONResponse({"ok": True, "quote": quote.upper(), "count": len(tickers), "tickers": tickers})
            except Exception as e:
                logger.exception("market/tickers error")
                return JSONResponse({"ok": False, "message": str(e), "error": "market_tickers_failed"}, status_code=500)

        # ---- K-line analysis ----
        @self._router.get("/market/kline-analysis")
        async def kline_analysis(
            request: Request,
            symbol: str = "BTC-USDT",
            type: str = "1hour",
            limit: int = 120,
            realtime: bool = True,
        ):
            symbol = (symbol or "BTC-USDT").strip().upper()
            kline_type = {"15min": "15min", "1hour": "1hour", "4hour": "4hour", "1day": "1day"}.get(type, "1hour")
            limit = max(20, min(300, limit))
            if not symbol or "-" not in symbol:
                return JSONResponse({"ok": False, "error": "invalid_symbol", "message": "symbol 格式应为 BTC-USDT"}, status_code=400)
            try:
                data = await kucoin_get(f"/api/v1/market/candles?symbol={symbol}&type={kline_type}")
                raw = (data.get("data") or [])[:limit]
                candles = sorted(
                    [c for c in (normalize_candle(r) for r in raw) if c],
                    key=lambda x: x["tsSec"],
                )
                if len(candles) < 20:
                    return JSONResponse({"ok": False, "error": "insufficient_candles", "message": f"K线数量不足: {len(candles)}"}, status_code=422)

                live_price = None
                if realtime:
                    try:
                        from quant.market_analysis import merge_live_price_into_candles
                        from web.api.dashboard_service import fetch_orderbook_level1

                        level1 = await fetch_orderbook_level1(symbol)
                        live_price = float(level1.get("price") or 0)
                        if live_price > 0:
                            merge_live_price_into_candles(candles, live_price)
                    except Exception as live_err:
                        logger.warning("kline-analysis realtime merge error for %s: %s", symbol, live_err)

                analysis = analyze_candles(candles)
                closes = [c["close"] for c in candles]
                latest = candles[-1]
                prev = candles[-2] if len(candles) >= 2 else latest
                change_pct = ((latest["close"] - prev["close"]) / prev["close"] * 100) if prev["close"] else 0
                ranges = [c["high"] - c["low"] for c in candles]
                vol_pct = (sum(ranges) / len(ranges) / latest["close"] * 100) if latest["close"] else 0

                trend_map = {"bullish": "多头趋势", "bearish": "空头趋势", "weak_bullish": "短线偏多", "weak_bearish": "短线偏空"}
                trend_label = trend_map.get(analysis["trend"], "数据不足") if analysis else "数据不足"

                regime_map = {"trending": "趋势行情", "ranging": "震荡行情", "transitional": "过渡阶段"}
                verdict = _kline_verdict(analysis)

                return JSONResponse({
                    "ok": True, "symbol": symbol, "type": kline_type, "limit": len(candles),
                    "realtime": bool(realtime),
                    "livePrice": live_price,
                    "trend": trend_label,
                    "verdict": verdict,
                    "metrics": {
                        "latestClose": latest["close"], "latestOpen": latest["open"],
                        "latestHigh": latest["high"], "latestLow": latest["low"],
                        "latestVolume": latest["volume"], "candleChangeRatePct": change_pct,
                        "sma20": analysis["sma20"] if analysis else None,
                        "sma60": analysis["sma60"] if analysis else None,
                        "support20": analysis["support"] if analysis else latest["low"],
                        "resistance20": analysis["resistance"] if analysis else latest["high"],
                        "volatilityPct": vol_pct,
                        "rangePositionPct": analysis["rangePos"] if analysis else 50,
                        "rsi": analysis.get("rsi") if analysis else None,
                        "bbUpper": analysis.get("bbUpper") if analysis else None,
                        "bbLower": analysis.get("bbLower") if analysis else None,
                        "bbWidth": analysis.get("bbWidth") if analysis else None,
                        "bbPctB": analysis.get("bbPctB") if analysis else None,
                        "atr": analysis.get("atr") if analysis else None,
                        "atrPct": analysis.get("atrPct") if analysis else None,
                        "regime": regime_map.get(analysis.get("regime", ""), "未知") if analysis else "未知",
                        "breakout": analysis.get("breakout") if analysis else "none",
                    },
                    "candles": candles,
                })
            except Exception as e:
                logger.exception("kline-analysis error")
                return JSONResponse({"ok": False, "message": str(e), "error": "kline_analysis_failed"}, status_code=500)

        # ---- Skills analyze ----
        @self._router.post("/skills/analyze")
        async def skills_analyze(request: Request):
            try:
                body = await request.json()
            except Exception:
                body = {}
            symbols = [s for s in (str(s).strip().upper() for s in (body.get("symbols") or []) if isinstance(s, str) and s.strip()) if "-" in s][:10]
            if not symbols:
                return JSONResponse({"ok": False, "error": "symbols_required", "message": "symbols 必填"}, status_code=400)

            market_stats_list = []
            for sym in symbols:
                try:
                    data = await kucoin_get(f"/api/v1/market/stats?symbol={sym}")
                    market_stats_list.append({"symbol": sym, **(data.get("data") or {})})
                except Exception:
                    market_stats_list.append({"symbol": sym})

            content = _build_local_skills_analysis(
                symbols=symbols,
                market_stats_list=market_stats_list,
                quant_snapshot_list=body.get("quantSnapshot") if isinstance(body.get("quantSnapshot"), list) else [],
                module_snapshot=body.get("moduleSnapshot"),
            )
            return JSONResponse({"ok": True, "symbols": symbols, "content": content})

        # ---- Skills modules ----
        @self._router.get("/skills/modules")
        async def skills_modules(request: Request, symbol: str = "BTC-USDT"):
            symbol = (symbol or "BTC-USDT").strip().upper()
            futures_symbol = to_contract_symbol(symbol)
            modules = await build_skills_modules(symbol)
            return JSONResponse({"ok": True, "symbol": symbol, "futuresSymbol": futures_symbol, "modules": modules})

        # ---- News (消息面) ----
        @self._router.get("/dashboard/news")
        async def dashboard_news(request: Request, symbol: str = "BTC", limit: int = 20):
            limit = max(1, min(50, limit))
            news_list, source = await fetch_news(symbol, limit=limit, hours=24)
            msg = "" if news_list else (
                "消息面暂时不可用（KuCoin 公告、行业 RSS、Medium/Reddit、MCP 等均未返回数据；"
                "CryptoCompare/CoinGecko Pro/LunarCrush 需配置 API Key，请检查网络后刷新）。"
            )
            return JSONResponse({"ok": True, "count": len(news_list), "news": news_list, "source": source, "message": msg or None})

        # ---- Signal analysis (综合信号) ----
        @self._router.get("/dashboard/signal-analysis")
        async def dashboard_signal_analysis(request: Request, symbol: str = "BTC"):
            sym = (symbol or "BTC").strip().upper()
            pair = f"{sym}-USDT"

            news_task = fetch_news(sym, limit=SIGNAL_NEWS_LIMIT, hours=SIGNAL_NEWS_HOURS)
            onchain_task = fetch_onchain(sym)
            onchain_metrics_task = fetch_onchain_metrics(sym)
            kline_task = fetch_signal_kline_signals(pair)
            vs_task = fetch_valuescan_signal_data(sym)

            news_result, onchain, onchain_metrics, kline, vs_data = await asyncio.gather(
                news_task, onchain_task, onchain_metrics_task, kline_task, vs_task,
                return_exceptions=True,
            )

            if isinstance(news_result, Exception):
                logger.warning("signal-analysis news error: %s", news_result)
                news_list: list = []
            else:
                news_list = news_result[0] if isinstance(news_result, tuple) else []

            if isinstance(onchain, Exception):
                logger.warning("signal-analysis onchain error: %s", onchain)
                onchain = {"summary": "", "extra": {}}
            if isinstance(onchain_metrics, Exception):
                logger.warning("signal-analysis onchain_metrics error: %s", onchain_metrics)
                onchain_metrics = {}
            if isinstance(kline, Exception):
                logger.warning("signal-analysis kline error: %s", kline)
                kline = {}
            if isinstance(vs_data, Exception):
                logger.warning("signal-analysis vs error: %s", vs_data)
                vs_data = {}

            try:
                market = await fetch_market_stats(pair)
            except Exception as e:
                logger.warning("signal-analysis market error: %s", e)
                market = {}

            vs_payload = vs_data if isinstance(vs_data, dict) else {}
            from web.api.valuescan_service import valuescan_chain_snapshot

            aggregated: Dict[str, Any] = {
                "symbol": sym, "pair": pair,
                "news": news_list, "newsCount": len(news_list),
                "onchain": {"summary": onchain.get("summary", "") if isinstance(onchain, dict) else "", "extra": onchain.get("extra", {}) if isinstance(onchain, dict) else {}},
                "onchainMetrics": onchain_metrics if isinstance(onchain_metrics, dict) else {},
                "kline": kline if isinstance(kline, dict) else {},
                "market": market,
                "valuescan": vs_payload,
                "valuescanChain": valuescan_chain_snapshot(vs_payload),
            }
            await enrich_signal_data(aggregated, pair)

            result = compute_signal(aggregated)

            return JSONResponse({
                "ok": True, **aggregated,
                "signal": result.signal, "signalLabel": result.label,
                "confidence": result.confidence, "score": result.score,
                "reasons": result.reasons, "summary": result.summary,
                "tradePlan": result.trade_plan,
            })

        # ---- LLM Signal analysis (大模型综合信号 — 异步任务模式) ----

        async def _run_llm_signal_task(
            task_id: str,
            sym: str,
            pair: str,
            model: LLMModel,
            use_trading_agents: bool = True,
        ):
            """Background coroutine: fetch data (+ optional TradingAgents) → call LLM → save result to MongoDB."""
            try:
                await update_task_running(task_id)

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
                            logger.info(
                                "llm-signal task %s: backtests %s/%s ok (%dms)",
                                task_id,
                                backtest_bundle.get("successCount", 0),
                                backtest_bundle.get("totalCount", 0),
                                backtest_bundle.get("latencyMs", 0),
                            )
                    except Exception as bt_exc:
                        logger.warning(
                            "llm-signal task %s backtest bundle failed: %s", task_id, bt_exc
                        )
                        backtest_bundle = {"available": False, "error": str(bt_exc)}

                news_task = fetch_news(sym, limit=SIGNAL_NEWS_LIMIT, hours=SIGNAL_NEWS_HOURS)
                onchain_task = fetch_onchain(sym)
                onchain_metrics_task = fetch_onchain_metrics(sym)
                kline_task = fetch_signal_kline_signals(pair)
                vs_task = fetch_valuescan_signal_data(sym)
                derivatives_task = fetch_derivatives_snapshot(pair)
                orderbook_task = fetch_orderbook_snapshot(pair)
                trades_task = fetch_recent_trades(pair)

                # Optionally run TradingAgents debate graph in parallel
                async def _noop_ta():
                    return None

                ta_task = (
                    run_trading_agents_for_signal(
                        sym,
                        reply_language="Chinese",
                        debate_context=debate_context or None,
                    )
                    if use_trading_agents
                    else _noop_ta()
                )

                news_result, onchain, onchain_metrics, kline, vs_data, derivatives, orderbook, recent_trades, ta_data = await asyncio.gather(
                    news_task,
                    onchain_task,
                    onchain_metrics_task,
                    kline_task,
                    vs_task,
                    derivatives_task,
                    orderbook_task,
                    trades_task,
                    ta_task,
                    return_exceptions=True,
                )

                if isinstance(news_result, Exception):
                    logger.warning("llm-signal task %s news error: %s", task_id, news_result)
                    news_list: list = []
                else:
                    news_list = news_result[0] if isinstance(news_result, tuple) else []

                if isinstance(onchain, Exception):
                    logger.warning("llm-signal task %s onchain error: %s", task_id, onchain)
                    onchain = {"summary": "", "extra": {}}
                if isinstance(onchain_metrics, Exception):
                    logger.warning("llm-signal task %s onchain_metrics error: %s", task_id, onchain_metrics)
                    onchain_metrics = {}
                if isinstance(kline, Exception):
                    logger.warning("llm-signal task %s kline error: %s", task_id, kline)
                    kline = {}
                if isinstance(vs_data, Exception):
                    logger.warning("llm-signal task %s vs error: %s", task_id, vs_data)
                    vs_data = {}
                if isinstance(derivatives, Exception):
                    logger.warning("llm-signal task %s derivatives error: %s", task_id, derivatives)
                    derivatives = {}
                if isinstance(orderbook, Exception):
                    logger.warning("llm-signal task %s orderbook error: %s", task_id, orderbook)
                    orderbook = {}
                if isinstance(recent_trades, Exception):
                    logger.warning("llm-signal task %s recent_trades error: %s", task_id, recent_trades)
                    recent_trades = {}

                # Handle TradingAgents result
                if isinstance(ta_data, Exception):
                    logger.warning("llm-signal task %s TradingAgents error: %s", task_id, ta_data)
                    ta_data = None

                try:
                    market = await fetch_market_stats(pair)
                except Exception as e:
                    logger.warning("llm-signal task %s market error: %s", task_id, e)
                    market = {}

                vs_payload = vs_data if isinstance(vs_data, dict) else {}
                from web.api.valuescan_service import valuescan_chain_snapshot
                from web.api.news_freshness import apply_news_freshness_to_aggregated

                aggregated: Dict[str, Any] = {
                    "symbol": sym, "pair": pair,
                    "strategyBacktests": backtest_bundle if backtest_bundle else {},
                    "news": news_list, "newsCount": len(news_list),
                    "onchain": {"summary": onchain.get("summary", "") if isinstance(onchain, dict) else "", "extra": onchain.get("extra", {}) if isinstance(onchain, dict) else {}},
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
                await enrich_signal_data(aggregated, pair)

                # Inject TradingAgents data if available
                if ta_data and isinstance(ta_data, dict) and ta_data.get("available"):
                    aggregated["tradingAgents"] = ta_data
                    logger.info(
                        "llm-signal task %s: TradingAgents injected (source=%s, latency=%dms)",
                        task_id,
                        ta_data.get("dataSource", "?"),
                        ta_data.get("latencyMs", 0),
                    )

                try:
                    mark = float((market or {}).get("last") or 0)
                except (TypeError, ValueError):
                    mark = 0.0
                from web.api.valuescan_signal_digest import build_valuescan_digest

                aggregated["valuescanDigest"] = build_valuescan_digest(
                    aggregated.get("valuescan") or {}, mark
                )
                apply_news_freshness_to_aggregated(aggregated)

                from web.api.quant_factors_bridge import (
                    fetch_quant_factors_for_symbol,
                    resolve_quant_factors_options,
                )

                q_opts = resolve_quant_factors_options()
                if q_opts["enabled"]:
                    aggregated["quantFactors"] = await fetch_quant_factors_for_symbol(
                        sym,
                        market=q_opts["market"],
                        timeout_s=q_opts["timeout_s"],
                        min_aggregate=q_opts["min_aggregate"],
                    )
                else:
                    aggregated["quantFactors"] = {"available": False, "reason": "disabled"}

                result = await compute_signal_with_llm(aggregated, model=model)
                from web.api.entry_gate import evaluate_entry_gate_alignment

                alignment = evaluate_entry_gate_alignment(
                    result,
                    market_data=aggregated,
                    news_meta=aggregated.get("newsMeta"),
                    quant_factors=aggregated.get("quantFactors"),
                    quant_min_aggregate=q_opts["min_aggregate"],
                    require_quant_in_gate=bool(q_opts["enabled"]),
                )
                from web.api.five_signal_view import (
                    analysis_view_from_signal_result,
                    build_five_signals_list,
                    format_alignment_dimensions_cn,
                )

                view = analysis_view_from_signal_result(result, aggregated, alignment)
                five_signals = build_five_signals_list(view)

                result_payload = {
                    "ok": True, **aggregated,
                    "signal": result.signal, "signalLabel": result.label,
                    "confidence": result.confidence, "score": result.score,
                    "reasons": result.reasons, "summary": result.summary,
                    "tradePlan": result.tradePlan.model_dump() if result.tradePlan else {},
                    "valuescanInsights": result.valuescanInsights or aggregated.get("valuescanDigest") or {},
                    "fiveSignalAlignment": alignment,
                    "fiveSignalAlignmentLabel": format_alignment_dimensions_cn(alignment),
                    "fiveSignals": five_signals,
                    "quantFactors": aggregated.get("quantFactors") or {},
                    "analysis": result.analysis.model_dump(),
                    "factors": result.factors.model_dump(),
                    "risks": [item.model_dump() for item in result.risks],
                    "scenarios": [item.model_dump() for item in result.scenarios],
                    "dataQuality": result.dataQuality.model_dump(),
                    "tradingAgentsDebate": result.tradingAgentsDebate.model_dump(),
                    "debug": result.debug.model_dump(),
                    "engineMeta": result.engineMeta.model_dump(),
                    "engine": "llm",
                }
                # Remove large rawState from response to keep payload manageable
                if "tradingAgents" in result_payload:
                    ta_resp = result_payload["tradingAgents"]
                    if isinstance(ta_resp, dict):
                        ta_resp.pop("rawState", None)

                await update_task_done(task_id, result_payload)
                logger.info("llm-signal task %s done for %s", task_id, sym)

            except Exception as exc:
                logger.exception("llm-signal task %s failed: %s", task_id, exc)
                await update_task_failed(task_id, str(exc))

        @self._router.get("/dashboard/llm-signal-analysis")
        async def dashboard_llm_signal_analysis(
            request: Request,
            symbol: str = "BTC",
            model: LLMModel = LLMModel.DEEPSEEK_V4_PRO,
            use_trading_agents: bool = True,
        ):
            """Submit an async LLM signal analysis task. Returns taskId immediately.

            When ``use_trading_agents=true`` (default), the background task will
            concurrently run the TradingAgents multi-agent debate graph and
            inject its output into the LLM signal context, producing a richer
            analysis with bull/bear debate, risk-manager assessment, and
            trader-plan cross-validation.
            """
            sym = (symbol or "BTC").strip().upper()
            pair = f"{sym}-USDT"
            task_id = await create_task(sym, model.value)
            asyncio.create_task(
                _run_llm_signal_task(task_id, sym, pair, model, use_trading_agents=use_trading_agents)
            )
            return JSONResponse({"ok": True, "taskId": task_id, "status": "pending"})

        @self._router.get("/dashboard/llm-signal-analysis/poll")
        async def dashboard_llm_signal_poll(request: Request, taskId: str = ""):
            """Poll for the result of a submitted LLM signal analysis task."""
            if not taskId:
                return JSONResponse({"ok": False, "message": "taskId is required"}, status_code=400)
            task = await get_task(taskId)
            if not task:
                return JSONResponse({"ok": False, "message": "task not found"}, status_code=404)
            status = task.get("status", "pending")
            if status == "done":
                return JSONResponse({"ok": True, "status": "done", "data": task.get("result", {})})
            if status == "failed":
                return JSONResponse({"ok": False, "status": "failed", "message": task.get("error", "unknown error")})
            return JSONResponse({"ok": True, "status": status})

        # ---- On-chain data (链上数据) ----
        @self._router.get("/dashboard/onchain")
        async def dashboard_onchain(request: Request, symbol: str = "BTC", limit: int = 10):
            """筹码/资金（ValueScan §3 链上）+ 公网恐贪（展示在技术/情绪区）."""
            limit = max(1, min(20, limit))
            from web.api.valuescan_service import fetch_full_token_data, valuescan_chain_snapshot

            mcp_onchain, metrics, vs_full = await asyncio.gather(
                fetch_onchain(symbol, limit=limit),
                fetch_onchain_metrics(symbol),
                fetch_full_token_data(symbol),
                return_exceptions=True,
            )
            if isinstance(mcp_onchain, Exception):
                mcp_onchain = {"summary": "", "extra": {}}
            if isinstance(metrics, Exception):
                metrics = {}
            if isinstance(vs_full, Exception):
                vs_full = {}

            chain = valuescan_chain_snapshot(vs_full if isinstance(vs_full, dict) else {})
            return JSONResponse({
                "ok": True,
                "symbol": (symbol or "BTC").strip().upper(),
                "source": "valuescan",
                "valuescanChain": chain,
                "mcp": mcp_onchain if isinstance(mcp_onchain, dict) else {},
                "marketSentiment": {
                    "fearGreed": (metrics or {}).get("fearGreed") if isinstance(metrics, dict) else {},
                },
                "publicBtcMetrics": metrics if isinstance(metrics, dict) else {},
            })

        # ---- Opportunity scan (币种机会信号扫描) ----
        @self._router.post("/dashboard/opportunity-scan")
        async def dashboard_opportunity_scan(request: Request):
            """
            Scan multiple symbols for trading opportunities.

            POST body (all fields optional):
            {
                "symbols": ["BTC", "ETH", "SOL"],  // omit to auto-discover top tickers
                "topK": 10,
                "minVolume24h": 100000,
                "useValueScan": true,
                "maxSymbols": 50
            }
            """
            try:
                body = await request.json()
            except Exception:
                body = {}

            symbols = body.get("symbols")
            if isinstance(symbols, list):
                symbols = [str(s).strip().upper() for s in symbols if isinstance(s, str) and s.strip()]
                if not symbols:
                    symbols = None
            else:
                symbols = None

            top_k = min(max(1, int(body.get("topK", 10))), 50)
            min_vol = max(0, float(body.get("minVolume24h", 100000)))
            use_vs = bool(body.get("useValueScan", True))
            max_sym = min(max(5, int(body.get("maxSymbols", 50))), 100)

            try:
                result = await scan_opportunities(
                    symbols=symbols,
                    top_k=top_k,
                    min_volume=min_vol,
                    use_valuescan=use_vs,
                    max_symbols=max_sym,
                )
                return JSONResponse({
                    "ok": True,
                    **result.model_dump(),
                })
            except Exception as e:
                logger.exception("opportunity-scan error")
                return JSONResponse(
                    {"ok": False, "message": str(e), "error": "opportunity_scan_failed"},
                    status_code=500,
                )

        @self._router.get("/dashboard/opportunity-scan")
        async def dashboard_opportunity_scan_get(
            request: Request,
            topK: int = 10,
            minVolume24h: float = 100000,
            useValueScan: bool = True,
            maxSymbols: int = 50,
        ):
            """GET version — auto-discovers top tickers by volume."""
            top_k = min(max(1, topK), 50)
            min_vol = max(0, minVolume24h)
            max_sym = min(max(5, maxSymbols), 100)

            try:
                result = await scan_opportunities(
                    symbols=None,
                    top_k=top_k,
                    min_volume=min_vol,
                    use_valuescan=useValueScan,
                    max_symbols=max_sym,
                )
                return JSONResponse({
                    "ok": True,
                    **result.model_dump(),
                })
            except Exception as e:
                logger.exception("opportunity-scan GET error")
                return JSONResponse(
                    {"ok": False, "message": str(e), "error": "opportunity_scan_failed"},
                    status_code=500,
                )

        # ValueScan endpoints → see vs_routes.py (auto-registered by router.auto_import)
