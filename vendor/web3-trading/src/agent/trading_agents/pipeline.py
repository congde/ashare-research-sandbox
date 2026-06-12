# -*- coding: utf-8 -*-
"""
在 DeepThink 中执行 TradingAgents 多智能体图并产出 SSE 事件流。
"""

import asyncio
import logging
from datetime import date
from typing import Any, AsyncIterator, Set

from agent.schema import StepType, StreamResponse, StreamStatusType
from libs.language import get_localized_message, ENGLISH_NAME_TO_CODE_MAP
from web.config import config

from agent.trading_agents.compat import (
    format_ta_result_markdown,
    is_trading_agents_available,
    map_symbol_to_yahoo_ticker,
    resolve_ticker_from_query,
    run_propagate_sync,
    today_trade_date,
)

logger = logging.getLogger(__name__)


async def stream_trading_agents_analysis(
    agent: Any,
    user_query: str,
    reply_language: str,
    _plan: Any = None,  # noqa: ARG001 — 预留与 route 联动的过滤
) -> AsyncIterator[str]:
    """
    当配置 `use_trading_agents: true` 且能解析到标的、依赖可用时，运行 TradingAgents
    并流式返回 StreamResponse JSON 行。

    成功时设置:
      - agent.cache["trading_agents_completed"] = True
      - agent.cache["full_response"] = 最终 Markdown

    失败或跳过时不设置 `trading_agents_completed`（由调用方回退到 DAG）。
    """
    if False:  # pragma: no cover — 保持本函数为 async generator，避免仅有 return 时变成 coroutine
        yield ""
    if not getattr(config, "use_trading_agents", False):
        return
    if not is_trading_agents_available():
        logger.warning("use_trading_agents enabled but package missing; skip")
        return

    symbol = resolve_ticker_from_query(user_query)
    if not symbol:
        logger.info("TradingAgents: no symbol resolved, fallback to DAG")
        return

    allowed = getattr(config, "trading_agents_allowed_intents", None) or []
    if allowed:
        try:
            catalog = await agent._init_catalog()
            history = agent.history or []
            _, primary = await agent._select_tools(user_query, history, catalog)
            allow_set: Set[str] = {str(x) for x in allowed}
            if not primary:
                logger.info("TradingAgents: no primary_intent for allowlist, skip")
                return
            if primary not in allow_set:
                logger.info(
                    "TradingAgents: primary_intent=%r not in allowed %s, skip",
                    primary,
                    allow_set,
                )
                return
        except Exception as e:
            logger.warning("TradingAgents: intent allowlist check failed, skip: %s", e)
            return

    data_mode = (getattr(config, "trading_agents_data_source", None) or "kucoin").strip().lower()
    if data_mode not in ("upstream", "kucoin", "all"):
        data_mode = "kucoin"
    if data_mode == "upstream":
        ticker_for_graph = map_symbol_to_yahoo_ticker(symbol)
    else:
        ticker_for_graph = symbol

    trade_d: date = today_trade_date()

    session_id = agent.session.id if agent.session else ""
    qa_id = agent.qa.id if agent.qa else ""
    reply_code = ENGLISH_NAME_TO_CODE_MAP.get(reply_language, "en")

    # 与 DAG 一样：在 TOOL_EXECUTION 中展示
    yield StreamResponse(
        sessionId=session_id, qaId=qa_id, status=StreamStatusType.START, type=StepType.TOOL_EXECUTION
    ).model_dump_json(exclude={"save", "deliver"})

    title = get_localized_message("calling_tools_start", reply_code)
    yield StreamResponse(
        sessionId=session_id, qaId=qa_id, status=StreamStatusType.PENDING, type=StepType.TITLE, content=title
    ).model_dump_json(exclude={"save", "deliver"})

    sub = f"**TradingAgents** (source={data_mode}, symbol=`{ticker_for_graph}`, {trade_d})\n\n"
    yield StreamResponse(
        sessionId=session_id,
        qaId=qa_id,
        status=StreamStatusType.PENDING,
        type=StepType.CONTENT,
        content=sub,
        checkSensitive=False,
    ).model_dump_json(exclude={"save", "deliver"})

    try:
        final_state, signal = await asyncio.to_thread(
            run_propagate_sync, ticker_for_graph, trade_d, False, reply_language
        )
    except Exception as e:
        logger.exception("TradingAgents propagate failed: %s", e)
        err = f"\n\n(TradingAgents run failed, falling back: `{e!s}`)\n"
        yield StreamResponse(
            sessionId=session_id, qaId=qa_id, status=StreamStatusType.PENDING, type=StepType.CONTENT, content=err, checkSensitive=False
        ).model_dump_json(exclude={"save", "deliver"})
        yield StreamResponse(
            sessionId=session_id, qaId=qa_id, status=StreamStatusType.END, type=StepType.TOOL_EXECUTION
        ).model_dump_json(exclude={"save", "deliver"})
        return

    # LangGraph 终态可能是类 dict 的映射
    try:
        st = dict(final_state) if not isinstance(final_state, dict) else final_state
    except Exception:
        st = {}

    text = format_ta_result_markdown(st, signal)
    agent.cache["full_response"] = text
    agent.cache["trading_agents_completed"] = True
    # 与 DAG 终局一致，避免下游缺字段
    agent.cache.setdefault("last_tool_summary", f"trading_agents:{data_mode}:{ticker_for_graph}")

    # 深度思考正文块（复用与 DAG 后类似的 CONTENT 流式拼接风格：此处一次性输出）
    yield StreamResponse(
        sessionId=session_id, qaId=qa_id, status=StreamStatusType.PENDING, type=StepType.CONTENT, content=text + "\n", checkSensitive=False
    ).model_dump_json(exclude={"save", "deliver"})

    yield StreamResponse(
        sessionId=session_id, qaId=qa_id, status=StreamStatusType.END, type=StepType.TOOL_EXECUTION
    ).model_dump_json(exclude={"save", "deliver"})
