# -*- coding: utf-8 -*-
"""
TradingAgents 依赖检测、配置合并、Yahoo 标的符号与结果格式化。
"""

import logging
import os
import re
from datetime import date, datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from web.config import config

logger = logging.getLogger(__name__)

_ta_module_checked = False
_ta_graph_cls = None


def is_trading_agents_available() -> bool:
    """是否已安装并可导入 TauricResearch `tradingagents` 包。"""
    global _ta_module_checked, _ta_graph_cls
    if _ta_module_checked:
        return _ta_graph_cls is not None
    _ta_module_checked = True
    try:
        from tradingagents.graph.trading_graph import (  # type: ignore[import-not-found]
            TradingAgentsGraph,
        )

        _ta_graph_cls = TradingAgentsGraph
    except Exception as e:
        logger.warning("tradingagents package not available: %s", e)
        _ta_graph_cls = None
    return _ta_graph_cls is not None


def get_trading_agents_graph_class():
    if not is_trading_agents_available():
        return None
    return _ta_graph_cls


def get_resolved_trading_graph_class():
    """
    `kucoin` / `all`：子类图，工具走 ValueScan/KuCoin 注册表（`all` 在工具内拉更全的 ValueScan 维度）；`upstream`：上游 yfinance 图。
    """
    if not is_trading_agents_available():
        return None
    mode = (getattr(config, "trading_agents_data_source", "kucoin") or "kucoin").strip().lower()
    if mode in ("kucoin", "all"):
        from agent.trading_agents.crypto_graph import get_kucoin_trading_agents_graph_class

        kcls = get_kucoin_trading_agents_graph_class()
        if kcls is not None:
            return kcls
    return _ta_graph_cls


def _backend_url() -> str:
    base = (getattr(config, "openai_api_base", None) or os.getenv("OPENAI_API_BASE", "")).strip()
    if not base:
        return "https://api.openai.com/v1"
    if base.rstrip("/").endswith("/v1"):
        return base.rstrip("/")
    return base.rstrip("/") + "/v1"


def _ensure_openai_key_for_ta() -> None:
    """TradingAgents 的 OpenAI 兼容客户端读 OPENAI_API_KEY（或我们注入）。"""
    if os.getenv("OPENAI_API_KEY"):
        return
    k = getattr(config, "openai_api_key", None) or os.getenv("OPENAI_API_KEY", "")
    if k:
        os.environ["OPENAI_API_KEY"] = str(k)


def _ensure_azure_env_for_ta() -> None:
    """为 tradingagents 的 AzureOpenAIClient 同步常见环境变量。"""
    k = getattr(config, "openai_api_key", None)
    if k and not os.getenv("AZURE_OPENAI_API_KEY"):
        os.environ["AZURE_OPENAI_API_KEY"] = str(k)
    base = (getattr(config, "openai_api_base", None) or "").strip()
    if base and "openai.azure.com" in base.lower() and not os.getenv("AZURE_OPENAI_ENDPOINT"):
        u = base.rstrip("/")
        if not u.endswith("/openai/v1") and not u.endswith("/v1"):
            u = u + "/"
        os.environ["AZURE_OPENAI_ENDPOINT"] = u
    dep = getattr(config, "llm_model_name", None)
    if dep and not os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME"):
        os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"] = str(dep)
    os.environ.setdefault("OPENAI_API_VERSION", "2024-12-01-preview")


def build_ta_config(reply_language: str) -> dict:
    from tradingagents.default_config import (  # type: ignore[import-not-found]
        DEFAULT_CONFIG,
    )

    ta = DEFAULT_CONFIG.copy()
    use_azure = bool(getattr(config, "use_azure_openai", False))
    if use_azure:
        _ensure_azure_env_for_ta()
        ta["llm_provider"] = "azure"
    else:
        ta["llm_provider"] = "openai"
        ta["backend_url"] = _backend_url()
    model = getattr(config, "llm_model_name", None) or os.getenv("LLM_MODEL_NAME", "gpt-4.1")
    ta["deep_think_llm"] = model
    ta["quick_think_llm"] = model
    # 用户可见报告语言（与 TradingAgents 一致：辩论内部仍偏英语）
    ta["output_language"] = reply_language or "English"
    # 资源目录防写系统路径失败时，落在项目下
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    ta["data_cache_dir"] = os.path.join(root, "data", "trading_agents_cache")
    ta["results_dir"] = os.path.join(root, "data", "trading_agents_results")
    os.makedirs(ta["data_cache_dir"], exist_ok=True)
    os.makedirs(ta["results_dir"], exist_ok=True)
    # 轮次上限（可由 Apollo 覆盖）
    mdr = getattr(config, "trading_agents_max_debate_rounds", None)
    if mdr is not None:
        try:
            ta["max_debate_rounds"] = int(mdr)
        except (TypeError, ValueError):
            pass
    mrr = getattr(config, "trading_agents_max_risk_discuss_rounds", None)
    if mrr is not None:
        try:
            ta["max_risk_discuss_rounds"] = int(mrr)
        except (TypeError, ValueError):
            pass
    return ta


def _selected_analysts_from_config() -> List[str]:
    raw = getattr(config, "trading_agents_selected_analysts", None)
    if isinstance(raw, list) and raw:
        return [str(x) for x in raw]
    return ["market", "social", "news"]


def map_symbol_to_yahoo_ticker(symbol: str) -> str:
    """
    将用户侧加密货币符号转为 Yahoo Finance 风格（TradingAgents 数据层使用 yfinance）。
    例: BTC -> BTC-USD, PEPE 需链上/交易所时仍按股票数据可用性由上游决定。
    """
    s = (symbol or "").strip().upper()
    s = s.replace("-USDT", "").replace("/USDT", "")
    if not s:
        return "BTC-USD"
    if "-" in s and s.endswith("USD"):
        return s
    return f"{s}-USD"


def resolve_ticker_from_query(user_query: str) -> Optional[str]:
    """
    从问句中解析一个主交易符号（基于 KuCoin 维护的主流列表），无则返回 None。
    """
    if not user_query or not user_query.strip():
        return None
    from libs.crypto_extractor import crypto_extractor

    u = user_query.upper()
    syms = sorted(
        crypto_extractor.crypto_symbols.keys(),
        key=len,
        reverse=True,
    )
    for sym in syms:
        if re.search(rf"(^|[^A-Z0-9]){re.escape(sym)}([^A-Z0-9]|$)", u):
            return sym
    return None


def today_trade_date() -> date:
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz=tz).date()


def build_ta_llm_callbacks():
    """
    传入 TradingAgentsGraph，使 LLM 层输出可观测（链 / LLM 起止日志）。
    """
    try:
        from langchain_core.callbacks import BaseCallbackHandler
    except Exception:
        return None

    class _TATrace(BaseCallbackHandler):
        def on_chain_start(self, serialized, inputs, **kwargs):
            name = (serialized or {}).get("name") or (serialized or {}).get("id") or "chain"
            logger.info("[TradingAgents:chain] start %s", name)

        def on_chain_end(self, outputs, **kwargs):
            logger.info("[TradingAgents:chain] end")

        def on_llm_start(self, serialized, prompts, **kwargs):
            logger.info("[TradingAgents:llm] start")

        def on_llm_end(self, response, **kwargs):
            logger.info("[TradingAgents:llm] end")

    if not getattr(config, "trading_agents_trace_llm", True):
        return None
    return [_TATrace()]


def run_propagate_sync(
    ticker_for_graph: str,
    trade_date: date,
    debug: bool = False,
    reply_language: str = "English",
    debate_context: Optional[str] = None,
) -> Tuple[Any, Any]:
    """
    同步执行 TradingAgentsGraph.propagate（由 asyncio.to_thread 调用）。
    `ticker_for_graph`：Kucoin 模式为 `BTC` 等；upstream 为 Yahoo 类 `BTC-USD`。
    `debate_context`：辩论前注入文本（写入 fundamentals_report，供 Bull/Bear 读取）。
    """
    if not getattr(config, "use_azure_openai", False):
        _ensure_openai_key_for_ta()
    else:
        _ensure_azure_env_for_ta()

    Graph = get_resolved_trading_graph_class()
    if Graph is None:
        raise RuntimeError("TradingAgentsGraph unavailable")

    ta_cfg = build_ta_config(reply_language)
    cb = build_ta_llm_callbacks()
    kwargs: Dict[str, Any] = {
        "selected_analysts": _selected_analysts_from_config(),
        "debug": debug,
        "config": ta_cfg,
    }
    if cb is not None:
        kwargs["callbacks"] = cb
    g = Graph(**kwargs)

    if not (debate_context and str(debate_context).strip()):
        return g.propagate(ticker_for_graph, trade_date)

    init_agent_state = g.propagator.create_initial_state(
        ticker_for_graph, str(trade_date)
    )
    init_agent_state["fundamentals_report"] = str(debate_context).strip()
    args = g.propagator.get_graph_args()
    if cb is not None:
        args.setdefault("config", {})["callbacks"] = cb
    final_state = g.graph.invoke(init_agent_state, **args)
    g.curr_state = final_state
    g._log_state(trade_date, final_state)
    return final_state, g.process_signal(final_state.get("final_trade_decision", ""))


def format_ta_result_markdown(final_state: dict, processed_signal: Any) -> str:
    """将图终态与 process_signal 结果拼成用户可读 Markdown。"""
    parts: List[str] = []
    if not isinstance(final_state, dict):
        return str(processed_signal or final_state)

    for key, label in (
        ("market_report", "##### Market / technical context"),
        ("sentiment_report", "##### Sentiment / social"),
        ("news_report", "##### News"),
        ("fundamentals_report", "##### Fundamentals"),
    ):
        val = final_state.get(key)
        if val:
            parts.append(f"{label}\n\n{val}\n")

    plan = final_state.get("trader_investment_plan") or final_state.get("investment_plan")
    if plan:
        parts.append(f"##### Trader / plan\n\n{plan}\n")

    risk = final_state.get("final_trade_decision")
    if risk:
        parts.append(f"##### Final decision (from graph)\n\n{risk}\n")

    if processed_signal is not None and str(processed_signal).strip():
        parts.append(f"##### Processed signal\n\n{processed_signal}\n")

    if not parts:
        return str(final_state)
    return "\n\n".join(parts).strip()
