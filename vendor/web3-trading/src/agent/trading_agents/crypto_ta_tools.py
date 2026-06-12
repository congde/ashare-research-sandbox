# -*- coding: utf-8 -*-
"""
LangChain 工具：供 KucoinTradingAgentsGraph 的 ToolNode 使用，底层走
default_registry（ValueScan、KuCoin 公共 API），不经过 yfinance。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode

logger = logging.getLogger(__name__)

_OUT_CAP = 20000


def _is_full_datasource() -> bool:
    """`trading_agents_data_source: all` 时拉全 ValueScan + 本侧 KuCoin 公共面；`kucoin` 为精简子集。"""
    from web.config import config

    s = (getattr(config, "trading_agents_data_source", "kucoin") or "kucoin").strip().lower()
    return s == "all"


def _clip(text: str, cap: int = _OUT_CAP) -> str:
    t = (text or "").strip()
    if len(t) <= cap:
        return t
    return t[: cap - 3] + "..."


def _normalize_base_symbol(ticker: str) -> str:
    s = (ticker or "").strip().upper()
    # Remove common quote suffixes first; order matters for strings like ETH-USDT.
    if s.endswith("-USDT"):
        s = s[: -len("-USDT")]
    elif s.endswith("/USDT"):
        s = s[: -len("/USDT")]
    elif s.endswith("-USD"):
        s = s[: -len("-USD")]
    s = s.replace(".US", "")
    s = re.sub(r"[^A-Z0-9]", "", s) if s else "BTC"
    if len(s) > 12:
        s = s[:12]
    return s or "BTC"


def _run_tool_sync(name: str, arguments: Dict[str, Any], timeout: float = 90.0) -> str:
    """
    在同步上下文中（TradingAgents 图线程内）跑异步 registry.execute。
    """
    from agent.tools.registry import default_registry

    async def _run() -> str:
        result = await default_registry.execute(name, arguments)
        if not result.success:
            return f"[{name}] error: {result.error or 'unknown'}"
        if result.content:
            return result.content
        try:
            return json.dumps(result.data, ensure_ascii=False)[:20000]
        except Exception:
            return str(result.data)[:20000]

    return asyncio.run(asyncio.wait_for(_run(), timeout=timeout))


def _vs(operation: str, symbol: str, **extras: Any) -> str:
    payload: Dict[str, Any] = {
        "query": "trading_agents_kucoin_bridge",
        "operation": operation,
        "symbol": symbol,
    }
    if extras:
        payload["extras"] = extras
    return _run_tool_sync("valueScan_api", payload)


def _kucoin(endpoint: str, query_params: Optional[Dict[str, Any]] = None) -> str:
    p = (endpoint or "").split("?")[0]
    return _run_tool_sync(
        "kucoin_openapi_public",
        {
            "query": "trading_agents",
            "endpoint": p,
            "market_type": "spot",
            "query_params": query_params or {},
        },
    )


@tool
def kucoin_get_crypto_ohlc_and_ticker(ticker: str) -> str:
    """Current spot-style snapshot for a cryptocurrency. Pass base symbol e.g. BTC, ETH.
    Returns KuCoin/ValueScan market context (not stocks)."""
    sym = _normalize_base_symbol(ticker)
    parts = [f"## token_detail ({sym})\n", _vs("token_detail", sym)]
    parts.append(
        f"\n## price_indicators ({sym})\n"
        + _vs("price_indicators", sym, days=14)
    )
    parts.append(
        f"\n## spot best bid/ask ({sym}-USDT)\n"
        + _kucoin(
            "/api/v1/market/orderbook/level1",
            {"symbol": f"{sym}-USDT"},
        )
    )
    if _is_full_datasource():
        parts.append(f"\n## support_resistance ({sym})\n" + _vs("support_resistance", sym, days=7))
        parts.append(f"\n## kline ({sym}, 1h / 7d)\n" + _vs("kline", sym, bucket="1h", days=7))
        parts.append(f"\n## whale_cost ({sym}, 30d)\n" + _vs("whale_cost", sym, days=30))
    return _clip("\n".join(parts))


@tool
def kucoin_get_technical_bundle(ticker: str) -> str:
    """RSI / MACD-style bundle from ValueScan for crypto symbol (e.g. BTC)."""
    sym = _normalize_base_symbol(ticker)
    base = _vs("price_indicators", sym, days=30)
    if not _is_full_datasource():
        return _clip(base)
    extra = f"\n## support_resistance ({sym})\n" + _vs("support_resistance", sym, days=30)
    return _clip(base + extra)


@tool
def kucoin_social_and_sentiment(ticker: str) -> str:
    """Social and sentiment data for a crypto (whale, flows, social sentiment)."""
    sym = _normalize_base_symbol(ticker)
    a = _vs("social_sentiment", sym)
    b = _vs("realtime_fund", sym)
    return f"## social_sentiment\n{a}\n\n## realtime_fund\n{b}"[:20000]


@tool
def kucoin_news_and_narrative(ticker: str) -> str:
    """AI/ narrative messages and sector-style context for a crypto (not global equity news)."""
    sym = _normalize_base_symbol(ticker)
    a = _vs("ai_messages", sym, msg_type="chance", trade_type=1)
    b = _vs("fund_snapshot", sym)
    parts = [f"## ai_messages (chance)\n{a}\n", f"\n## fund_snapshot\n{b}"]
    if _is_full_datasource():
        parts.append(f"\n## ai_messages (risk)\n" + _vs("ai_messages", sym, msg_type="risk", trade_type=1))
        parts.append(f"\n## ai_messages (funds)\n" + _vs("ai_messages", sym, msg_type="funds", trade_type=1))
    return _clip("".join(parts))


@tool
def kucoin_fundamental_crypto_context(ticker: str) -> str:
    """
    'Fundamentals' analogue for tokens: top holders, fund ratios, on-chain/flow context.
    Not a replacement for equity 10-K statements.
    """
    sym = _normalize_base_symbol(ticker)
    a = _vs("holder_list", sym)
    b = _vs("fund_market_cap_ratio", sym)
    c = _vs("token_flow", sym)
    parts = [f"## holder_list\n{a}\n", f"\n## fund_market_cap_ratio\n{b}\n", f"\n## token_flow\n{c}"]
    if _is_full_datasource():
        parts.append(
            f"\n## large_transactions (page1)\n"
            + _vs("large_transactions", sym, page=1, page_size=20)
        )
    return _clip("".join(parts))


def build_kucoin_tool_nodes() -> Dict[str, ToolNode]:
    """与 TradingAgentsGraph 相同的键：market, social, news, fundamentals — 工具为 KuCoin/ValueScan 系。"""
    return {
        "market": ToolNode(
            [kucoin_get_crypto_ohlc_and_ticker, kucoin_get_technical_bundle],
        ),
        "social": ToolNode([kucoin_social_and_sentiment]),
        "news": ToolNode([kucoin_news_and_narrative]),
        "fundamentals": ToolNode([kucoin_fundamental_crypto_context]),
    }
