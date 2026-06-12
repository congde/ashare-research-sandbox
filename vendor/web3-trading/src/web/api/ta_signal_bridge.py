# -*- coding: utf-8 -*-
"""
TradingAgents ↔ LLM Signal Analyzer bridge.

Runs the TradingAgents multi-agent debate graph and extracts structured
context that the LLM signal analyzer can consume as an additional data
dimension alongside market/kline/onchain/news/valuescan.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _is_available() -> bool:
    """Check if the tradingagents package and integration layer are usable."""
    try:
        from agent.trading_agents.compat import is_trading_agents_available
        return is_trading_agents_available()
    except Exception:
        return False


def _resolve_data_mode() -> str:
    try:
        from web.config import config
        mode = (getattr(config, "trading_agents_data_source", "kucoin") or "kucoin").strip().lower()
        if mode not in ("upstream", "kucoin", "all"):
            return "kucoin"
        return mode
    except Exception:
        return "kucoin"


async def run_trading_agents_for_signal(
    symbol: str,
    trade_date: Optional[date] = None,
    reply_language: str = "Chinese",
    timeout_s: float = 180.0,
    debate_context: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Execute the TradingAgents multi-agent debate graph for *symbol* and return
    a structured dict suitable for injection into the LLM signal context.

    Returns ``None`` when TA is unavailable or execution fails (caller should
    treat it as a soft degradation — signal analysis proceeds without TA).

    Returned dict shape::

        {
            "available": True,
            "symbol": "BTC",
            "dataSource": "kucoin",
            "latencyMs": 12345,
            "marketReport": "...",
            "sentimentReport": "...",
            "newsReport": "...",
            "fundamentalsReport": "...",
            "traderPlan": "...",
            "finalDecision": "...",
            "rawState": { ... },
        }
    """
    if not _is_available():
        logger.info("TradingAgents not available, skipping for signal analysis")
        return None

    from agent.trading_agents.compat import (
        map_symbol_to_yahoo_ticker,
        run_propagate_sync,
        today_trade_date,
    )

    data_mode = _resolve_data_mode()
    if data_mode == "upstream":
        ticker = map_symbol_to_yahoo_ticker(symbol)
    else:
        ticker = symbol.upper().replace("-USDT", "").replace("/USDT", "")

    if trade_date is None:
        trade_date = today_trade_date()

    t0 = time.time()
    try:
        final_state, processed_signal = await asyncio.wait_for(
            asyncio.to_thread(
                run_propagate_sync,
                ticker,
                trade_date,
                False,
                reply_language,
                debate_context,
            ),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "TradingAgents timed out after %.0fs for %s", timeout_s, symbol
        )
        return None
    except Exception as e:
        logger.warning("TradingAgents execution failed for %s: %s", symbol, e)
        return None

    latency_ms = int((time.time() - t0) * 1000)

    # Normalize final_state to dict
    try:
        st = dict(final_state) if not isinstance(final_state, dict) else final_state
    except Exception:
        st = {}

    fundamentals = st.get("fundamentals_report", "")
    if debate_context and str(debate_context).strip() and not fundamentals:
        fundamentals = str(debate_context).strip()

    result: Dict[str, Any] = {
        "available": True,
        "symbol": ticker,
        "dataSource": data_mode,
        "latencyMs": latency_ms,
        "marketReport": st.get("market_report", ""),
        "sentimentReport": st.get("sentiment_report", ""),
        "newsReport": st.get("news_report", ""),
        "fundamentalsReport": fundamentals,
        "traderPlan": st.get("trader_investment_plan") or st.get("investment_plan", ""),
        "finalDecision": st.get("final_trade_decision", ""),
        "rawState": st,
    }

    # Extract bull/bear analyst debate if present
    for key in ("bull_analyst_report", "bear_analyst_report",
                "bull_report", "bear_report",
                "risk_manager_report", "risk_report"):
        val = st.get(key)
        if val:
            result[_camel(key)] = val

    logger.info(
        "TradingAgents completed for %s in %dms (source=%s, keys=%s)",
        symbol, latency_ms, data_mode, list(st.keys())[:10],
    )
    return result


def _camel(snake: str) -> str:
    """Convert snake_case to camelCase."""
    parts = snake.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def format_ta_for_llm_context(ta_data: Dict[str, Any]) -> str:
    """
    Format TradingAgents output into a concise text block for the LLM signal
    system prompt context section.
    """
    if not ta_data or not ta_data.get("available"):
        return ""

    sections: List[str] = []

    sections.append(
        f"数据来源: TradingAgents 多智能体辩论图 (source={ta_data.get('dataSource', '?')}, "
        f"latency={ta_data.get('latencyMs', '?')}ms)"
    )

    for key, label in (
        ("marketReport", "市场/技术面分析 (Market Analyst)"),
        ("sentimentReport", "情绪/社交面分析 (Sentiment Analyst)"),
        ("newsReport", "消息面分析 (News Analyst)"),
        ("fundamentalsReport", "基本面分析 (Fundamentals Analyst)"),
    ):
        val = ta_data.get(key, "")
        if val and str(val).strip():
            sections.append(f"[{label}]\n{str(val).strip()}")

    # Bull/bear debate
    bull = ta_data.get("bullAnalystReport") or ta_data.get("bullReport") or ""
    bear = ta_data.get("bearAnalystReport") or ta_data.get("bearReport") or ""
    if bull:
        sections.append(f"[多头分析师 (Bull Analyst)]\n{str(bull).strip()}")
    if bear:
        sections.append(f"[空头分析师 (Bear Analyst)]\n{str(bear).strip()}")

    # Risk manager
    risk = ta_data.get("riskManagerReport") or ta_data.get("riskReport") or ""
    if risk:
        sections.append(f"[风控经理 (Risk Manager)]\n{str(risk).strip()}")

    # Trader plan & final decision
    plan = ta_data.get("traderPlan", "")
    if plan:
        sections.append(f"[交易员投资计划 (Trader Plan)]\n{str(plan).strip()}")

    decision = ta_data.get("finalDecision", "")
    if decision:
        sections.append(f"[最终交易决策 (Final Decision)]\n{str(decision).strip()}")

    if len(sections) <= 1:
        return ""

    return "\n\n".join(sections)


def extract_ta_signal_hints(ta_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract high-level signal hints from TA output to help enrichment.

    Returns a dict with optional keys:
        - bias: "bullish" | "bearish" | "neutral"
        - confidence_adj: float adjustment to confidence
        - reasons: list of additional reasons
    """
    if not ta_data or not ta_data.get("available"):
        return {}

    hints: Dict[str, Any] = {}
    decision = str(ta_data.get("finalDecision", "")).lower()

    # Try to infer bias from the final decision text
    buy_keywords = ["buy", "long", "bullish", "accumulate", "做多", "买入", "看多"]
    sell_keywords = ["sell", "short", "bearish", "reduce", "做空", "卖出", "看空"]
    hold_keywords = ["hold", "neutral", "wait", "观望", "持有", "中性"]

    buy_count = sum(1 for kw in buy_keywords if kw in decision)
    sell_count = sum(1 for kw in sell_keywords if kw in decision)
    hold_count = sum(1 for kw in hold_keywords if kw in decision)

    if buy_count > sell_count and buy_count > hold_count:
        hints["bias"] = "bullish"
    elif sell_count > buy_count and sell_count > hold_count:
        hints["bias"] = "bearish"
    elif hold_count > 0:
        hints["bias"] = "neutral"

    # Extract reasons from the decision
    reasons = []
    if ta_data.get("traderPlan"):
        reasons.append(f"TradingAgents 交易员计划: {str(ta_data['traderPlan'])[:200]}")
    if ta_data.get("finalDecision"):
        reasons.append(f"TradingAgents 最终决策: {str(ta_data['finalDecision'])[:200]}")
    hints["reasons"] = reasons

    return hints