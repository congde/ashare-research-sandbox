# -*- coding: utf-8 -*-
"""交易决策引擎：多源上下文 → LLM 推理 → 风控前置结构化决策。"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

logger = logging.getLogger(__name__)

from pydantic import BaseModel, Field


class TradingDecision(BaseModel):
    symbol: str
    market: str = "crypto"
    action: Literal["buy", "sell", "short", "cover", "hold"] = "hold"
    quantity: float = 0.0
    price: float = 0.0
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    leverage: float = 1.0
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    risk_usd: float = 0.0
    rationale: str = ""
    invalidation: str = ""
    evidence_for: List[str] = Field(default_factory=list)
    evidence_against: List[str] = Field(default_factory=list)
    data_sources: List[str] = Field(default_factory=list)


class TradingDecisionSet(BaseModel):
    summary: str = ""
    risk_state: Literal["normal", "caution", "paused"] = "caution"
    should_execute: bool = False
    decisions: List[TradingDecision] = Field(default_factory=list)


_SYSTEM_PROMPT_PATH = Path(__file__).parent / "prompts" / "trading_system.md"


def load_trading_system_prompt() -> str:
    return _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def build_trading_user_prompt(context: Dict[str, Any]) -> str:
    """构造单条动态 user prompt：任务说明 + 本次 JSON 数据上下文。"""
    return (
        "请基于下面 JSON 数据上下文进行交易解读、推理和决策。\n"
        "必须按系统提示词的顺序完成：市场结构 -> 多信号一致性 -> 持仓/账户状态 -> 方向与置信度。\n"
        "只输出 TradingDecisionSet JSON，不要输出 Markdown 或额外解释。\n"
        "如果数据源不可用、过期或冲突，请在 evidence_against 和 rationale 中明确体现，并保守处理。\n"
        "不要把缺失数据、错误响应或过期事件当作有效入场证据。\n\n"
        "本次动态数据上下文：\n"
        f"```json\n{json.dumps(context, ensure_ascii=False, indent=2, default=str)}\n```"
    )


def _debug_enabled() -> bool:
    raw = os.getenv("QUANT_DEBUG_CONTEXT", "")
    return raw.lower() in ("1", "true", "yes", "y")


async def make_trading_decision(context: Dict[str, Any]) -> TradingDecisionSet:
    """调用项目统一 LLM 生成结构化交易决策。

    调试日志（终端可见）：
    - 系统提示词路径：始终打印
    - LLM 完整输入 context：QUANT_DEBUG_CONTEXT=true 时打印
    - LLM 原始输出 decision：QUANT_DEBUG_CONTEXT=true 时打印
    """
    from llm.llm import llm

    system_prompt = load_trading_system_prompt()
    user_prompt = build_trading_user_prompt(context)

    debug = _debug_enabled()
    logger.info("[QUANT] 系统提示词文件: %s", _SYSTEM_PROMPT_PATH)

    if debug:
        logger.info(
            "[QUANT][INPUT] 系统提示词:\n%s",
            system_prompt,
        )
        logger.info(
            "[QUANT][INPUT] LLM 用户 prompt（动态上下文）:\n%s",
            user_prompt,
        )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    result: TradingDecisionSet = await llm.ainvoke(
        messages=messages,
        temperature=0.2,
        response_format=TradingDecisionSet,
        timeout=60,
    )

    if debug:
        logger.info(
            "[QUANT][OUTPUT] LLM 决策结果:\n%s",
            json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2),
        )
    else:
        # 始终打印摘要，方便快速确认决策
        decisions_summary = [
            f"{d.symbol} -> {d.action} confidence={d.confidence:.2f}"
            for d in result.decisions
        ]
        logger.info(
            "[QUANT] 决策摘要 risk_state=%s should_execute=%s decisions=%s",
            result.risk_state,
            result.should_execute,
            decisions_summary,
        )

    return result
