# -*- coding: utf-8 -*-
"""
Backtest API — endpoints for strategy backtesting on the dashboard.

Auto-registered by web.router.auto_import (BaseRouter subclass).
"""

import json
import logging
from dataclasses import asdict

from fastapi import Request
from fastapi.responses import JSONResponse

from web.router import BaseRouter
from web.api.backtest_service import execute_backtest
from web.api.backtest_strategies import list_strategies, get_strategy
from web.api.llm_signal_analyzer import LLMModel, _get_llm

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Backtest LLM analysis prompt
# ---------------------------------------------------------------------------
_BT_RECOMMEND_PROMPT = """你是一位资深加密货币交易顾问。用户运行了一份策略回测后，希望结合当前实时行情数据获取买入建议。

你会收到：
1. 回测结果摘要（策略表现、胜率、夏普比率等）
2. 当前最新 K 线的技术分析（RSI、布林带、趋势、突破信号等）
3. 当前策略信号（策略对最新行情给出的信号方向和分数）
4. 最近新闻摘要（如有）
5. 市场情绪/恐惧贪婪指数（如有）

请输出以下内容（用中文，Markdown 格式）：

## 当前信号判断
- 方向：看多 / 看空 / 观望
- 信心度：1-10 分
- 理由：结合技术面和策略信号说明

## 关键价位
- 支撑位 / 阻力位

## 买入建议
- 是否建议入场
- 建议入场价区间
- 止损价位
- 止盈目标
- 建议仓位比例（占总资金 %）

## 消息面研判
- 近期利好/利空因素

## 风险提示
- 列出 2-3 条当前主要风险

## 时效性
- 本建议的有效时间窗口

请确保建议具体、可操作，给出明确的数字（价格、百分比），不要只给模糊描述。"""

_BT_SYSTEM_PROMPT = """你是一位专业的量化策略分析师。用户会给你一份策略回测报告的关键指标和交易记录。

请对回测结果进行深入分析，输出以下内容：
1. **总体评价**：一句话总结策略表现（优秀/良好/一般/较差），并给出信心度评分(1-10)
2. **核心指标解读**：对胜率、盈亏比、夏普比率、最大回撤的解读，是否达到实盘标准
3. **策略优势**：列出 2-3 个优势
4. **策略风险与不足**：列出 2-3 个风险点
5. **改进建议**：提出 2-3 条具体可执行的优化建议（如调参、增加过滤条件、换周期等）
6. **实盘建议**：是否推荐投入实盘，推荐仓位比例，额外注意事项

请用中文回答，结构清晰，每个部分用 Markdown 标题。"""


class BacktestApi(BaseRouter):
    """Backtest endpoints under /api/dashboard/backtest/*."""

    def __init__(self):
        super().__init__()

        @self._router.get("/dashboard/backtest/strategies")
        async def dashboard_backtest_strategies():
            """List available backtest strategies."""
            return JSONResponse({"ok": True, "strategies": list_strategies()})

        @self._router.get("/dashboard/backtest")
        async def dashboard_backtest(
            request: Request,
            symbol: str = "BTC-USDT",
            type: str = "1hour",
            limit: int = 300,
            stopLoss: float = 3.0,
            takeProfit: float = 5.0,
            trailingStop: float = 0.0,
            maxHoldBars: int = 0,
            strategy: str = "technical_signal",
            optimize: str = "false",
        ):
            """Run a rolling-window backtest on historical K-line data."""
            symbol = (symbol or "BTC-USDT").strip().upper()
            if "-" not in symbol:
                return JSONResponse(
                    {"ok": False, "error": "invalid_symbol", "message": "symbol 格式应为 BTC-USDT"},
                    status_code=400,
                )

            kline_type = {"15min": "15min", "1hour": "1hour", "4hour": "4hour", "1day": "1day"}.get(type, "1hour")
            limit = max(60, min(1500, limit))
            stop_loss = max(0.5, min(20.0, stopLoss))
            take_profit = max(0.5, min(50.0, takeProfit))
            trailing_stop = max(0.0, min(20.0, trailingStop))
            max_hold_bars = max(0, min(500, maxHoldBars))
            do_optimize = optimize.lower() in ("true", "1", "yes")

            try:
                result = await execute_backtest(
                    symbol=symbol,
                    kline_type=kline_type,
                    limit=limit,
                    stop_loss_pct=stop_loss,
                    take_profit_pct=take_profit,
                    trailing_stop_pct=trailing_stop,
                    max_hold_bars=max_hold_bars,
                    strategy_name=strategy,
                    optimize=do_optimize,
                )

                payload = asdict(result)
                # Thin out equity curve for frontend (max 500 points)
                eq = payload.get("equity_curve", [])
                if len(eq) > 500:
                    step = max(1, len(eq) // 500)
                    payload["equity_curve"] = eq[::step]
                    if eq[-1] not in payload["equity_curve"]:
                        payload["equity_curve"].append(eq[-1])

                # Thin out candle_signals similarly
                cs = payload.get("candle_signals", [])
                if len(cs) > 500:
                    step = max(1, len(cs) // 500)
                    payload["candle_signals"] = cs[::step]

                payload["stop_loss_pct"] = stop_loss
                payload["take_profit_pct"] = take_profit
                payload["trailing_stop_pct"] = trailing_stop
                payload["max_hold_bars"] = max_hold_bars

                return JSONResponse({"ok": True, **payload})

            except ValueError as ve:
                return JSONResponse(
                    {"ok": False, "error": "insufficient_data", "message": str(ve)},
                    status_code=422,
                )
            except Exception as e:
                logger.exception("backtest error")
                return JSONResponse(
                    {"ok": False, "error": "backtest_failed", "message": str(e)},
                    status_code=500,
                )

        @self._router.post("/dashboard/backtest/recommend")
        async def backtest_recommend(request: Request):
            """Generate buy/sell recommendation based on backtest + live market data."""
            body = await request.json()
            model_str = body.get("model", "deepseek/deepseek-v4-flash")
            symbol = (body.get("symbol") or "BTC-USDT").strip().upper()
            kline_type = body.get("klineType", "1hour")
            strategy_name = body.get("strategy", "technical_signal")
            metrics = body.get("metrics", {})
            params = body.get("params")  # optimized params from walk-forward

            try:
                llm_model = LLMModel(model_str)
            except ValueError:
                llm_model = LLMModel.DEEPSEEK_V4_FLASH

            try:
                from web.api.dashboard_service import (
                    kucoin_get, normalize_candle, analyze_candles,
                    fetch_news, fetch_fear_greed_index,
                )

                # 1. Fetch latest K-lines
                data = await kucoin_get(f"/api/v1/market/candles?symbol={symbol}&type={kline_type}")
                raw = (data.get("data") or [])[:200]
                candles = sorted(
                    [c for c in (normalize_candle(r) for r in raw) if c],
                    key=lambda x: x["tsSec"],
                )
                if not candles:
                    return JSONResponse({"ok": False, "message": "无法获取K线数据"}, status_code=422)

                # 2. Technical analysis on latest candles
                analysis = analyze_candles(candles) or {}

                # 3. Strategy signal on latest candle
                strategy = get_strategy(strategy_name)
                use_params = params if params else strategy.default_params()
                if hasattr(strategy, 'prepare'):
                    strategy.prepare(candles, use_params)
                latest_signal = strategy.generate_signal(candles, len(candles) - 1, use_params)

                # 4. Fetch news (best effort)
                base_sym = symbol.split("-")[0]
                news_items, news_source = [], "none"
                try:
                    news_items, news_source = await fetch_news(base_sym, limit=5, hours=24)
                except Exception as exc:
                    logger.warning("recommend news fetch error: %s", exc)

                # 5. Fear & Greed (best effort)
                fear_greed = {}
                try:
                    fear_greed = await fetch_fear_greed_index()
                except Exception as exc:
                    logger.warning("recommend fear_greed error: %s", exc)

                # 6. Build user message
                latest = candles[-1]
                news_text = ""
                if news_items:
                    news_lines = [f"- {n.get('title', '')}" for n in news_items[:5]]
                    news_text = "\n最近新闻:\n" + "\n".join(news_lines)

                fg_text = ""
                if fear_greed:
                    fg_text = f"\n恐惧贪婪指数: {fear_greed.get('value', 'N/A')} ({fear_greed.get('label', '')})，昨日: {fear_greed.get('yesterday', 'N/A')}"

                user_msg = (
                    f"## 实时行情建议请求 — {symbol}\n\n"
                    f"### 回测表现摘要\n"
                    f"- 策略: {strategy.display_name}\n"
                    f"- 总收益率: {metrics.get('total_return_pct', 'N/A')}%\n"
                    f"- 胜率: {metrics.get('win_rate', 'N/A')}%\n"
                    f"- 夏普比率: {metrics.get('sharpe_ratio', 'N/A')}\n"
                    f"- 盈亏比: {metrics.get('profit_factor', 'N/A')}\n"
                    f"- 最大回撤: {metrics.get('max_drawdown_pct', 'N/A')}%\n\n"
                    f"### 当前策略信号\n"
                    f"- 信号方向: {latest_signal.action}\n"
                    f"- 信号分数: {latest_signal.score:.1f}\n\n"
                    f"### 当前技术面 ({kline_type})\n"
                    f"- 最新价: {latest['close']}\n"
                    f"- 趋势: {analysis.get('trend', 'N/A')}\n"
                    f"- RSI(14): {analysis.get('rsi', 'N/A')}\n"
                    f"- 布林%%B: {analysis.get('bbPctB', 'N/A')}\n"
                    f"- 布林宽度: {analysis.get('bbWidth', 'N/A')}%\n"
                    f"- ATR%%: {analysis.get('atrPct', 'N/A')}%\n"
                    f"- 量比: {analysis.get('volRatio', 'N/A')}\n"
                    f"- 市场状态: {analysis.get('regime', 'N/A')}\n"
                    f"- 突破: {analysis.get('breakout', 'none')}\n"
                    f"- 支撑: {analysis.get('support', 'N/A')}\n"
                    f"- 阻力: {analysis.get('resistance', 'N/A')}\n"
                    f"{news_text}\n"
                    f"{fg_text}\n"
                )

                # 7. Call LLM
                llm, _ = _get_llm(llm_model)
                resp = await llm.ainvoke([
                    {"role": "system", "content": _BT_RECOMMEND_PROMPT},
                    {"role": "user", "content": user_msg},
                ])
                analysis_text = resp.content if hasattr(resp, "content") else str(resp)

                return JSONResponse({
                    "ok": True,
                    "recommendation": analysis_text,
                    "model": llm_model.value,
                    "signal": {"action": latest_signal.action, "score": round(latest_signal.score, 1)},
                    "price": latest["close"],
                    "rsi": analysis.get("rsi"),
                    "trend": analysis.get("trend"),
                    "fearGreed": fear_greed.get("value"),
                })

            except Exception as e:
                logger.exception("recommend error")
                return JSONResponse(
                    {"ok": False, "error": "recommend_failed", "message": str(e)},
                    status_code=500,
                )

        @self._router.post("/dashboard/backtest/analyze")
        async def backtest_llm_analyze(request: Request):
            """Use an LLM to analyze backtest results."""
            body = await request.json()
            model_str = body.get("model", "deepseek/deepseek-v4-flash")
            metrics = body.get("metrics")
            trades = body.get("trades")
            symbol = body.get("symbol", "")

            if not metrics:
                return JSONResponse(
                    {"ok": False, "error": "missing_metrics", "message": "请先运行回测"},
                    status_code=400,
                )

            # Resolve LLM model
            try:
                llm_model = LLMModel(model_str)
            except ValueError:
                llm_model = LLMModel.DEEPSEEK_V4_FLASH

            # Build user message with backtest summary
            trade_summary = ""
            if trades:
                recent = trades[-10:] if len(trades) > 10 else trades
                lines = []
                for t in recent:
                    lines.append(
                        f"  方向={t.get('direction','?')}, 入场价={t.get('entry_price','?')}, "
                        f"出场价={t.get('exit_price','?')}, 收益={t.get('pnl_pct','?')}%, "
                        f"出场原因={t.get('exit_reason','?')}"
                    )
                trade_summary = "\n最近交易记录:\n" + "\n".join(lines)

            user_msg = (
                f"## 回测报告 — {symbol}\n\n"
                f"- 总收益率: {metrics.get('total_return_pct', 'N/A')}%\n"
                f"- 最大回撤: {metrics.get('max_drawdown_pct', 'N/A')}%\n"
                f"- 胜率: {metrics.get('win_rate_pct', 'N/A')}%\n"
                f"- 夏普比率: {metrics.get('sharpe_ratio', 'N/A')}\n"
                f"- 盈亏比(Profit Factor): {metrics.get('profit_factor', 'N/A')}\n"
                f"- 总交易次数: {metrics.get('total_trades', 'N/A')}\n"
                f"- 平均收益: {metrics.get('avg_return_pct', 'N/A')}%\n"
                f"- 止损比例: {metrics.get('stop_loss_pct', 'N/A')}%\n"
                f"- 止盈比例: {metrics.get('take_profit_pct', 'N/A')}%\n"
                f"{trade_summary}"
            )

            try:
                llm, resolved = _get_llm(llm_model)
                messages = [
                    {"role": "system", "content": _BT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ]
                resp = await llm.ainvoke(
                    messages=messages,
                    temperature=0.4,
                    extra_body={"chat_template_kwargs": {"enable_thinking": False}} if resolved.lower().startswith("qwen") else None,
                )
                content = resp.content if hasattr(resp, "content") else str(resp)
                return JSONResponse({"ok": True, "analysis": content, "model": model_str})
            except Exception as e:
                logger.exception("backtest LLM analyze error")
                return JSONResponse(
                    {"ok": False, "error": "llm_error", "message": str(e)},
                    status_code=500,
                )
