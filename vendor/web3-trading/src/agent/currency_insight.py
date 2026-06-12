# -*- coding: utf-8 -*-
"""
币种洞察工作流

使用 LangGraph + Agent + Skills 架构实现币种洞察功能。
- LangGraph: 任务编排框架，负责流程控制
- Agent: 决策中心，负责工具选择和任务规划
- Skills: 原子能力组件，复用 agent/skills/ 目录下的组件

工作流程：
1. Agent 分析任务，决策需要调用的工具
2. Skills 执行工具调用，获取市场数据
3. Agent 汇总数据，生成结构化洞察报告
4. Skills 回调业务方接口

注意：本模块为后台异步任务场景设计，与 BaseAgent 的 SSE 流式场景不同，
因此不继承 BaseAgent，但复用其 LLM 客户端管理方式。
"""
import uuid
import logging
import json_repair as json
from typing import TypedDict, Optional, List, Literal, Dict, Union, Any
from langgraph.graph import StateGraph, END
from pydantic import BaseModel

from agent.skills.tool_call import MCPToolCallSkill
from agent.skills.callback import CallbackSkill
from agent.utils import utc_now_iso
from mcp.mcp_http_client import mcp_client
from llm.llm import llm
from llm.base import create_llm
from web.config import config

logger = logging.getLogger(__name__)

# 模块级 LLM 单例，与 BaseAgent 保持一致


class FinalResponse(BaseModel):
    symbol: str
    updateTime: str = ""
    overview: str = ""
    technicalIndicators: dict = {}
    pricePerformance: List[dict] = []
    marketSentiment: dict = {}
    keyTweets: dict = {}
    opportunitySummary: dict = {}
    keyPoints: List[dict] = []


# ============================================================
# State 定义
# ============================================================

class CurrencyInsightState(TypedDict):
    """币种洞察工作流状态"""
    # 输入
    user_id: str
    symbol: str
    market_type: Literal["spot", "future"]
    callback_url: str
    source: str
    extra: dict
    
    # Agent 决策
    tool_calls: List[dict]
    
    # Skills 执行结果
    tool_results: List[dict]
    
    # 输出
    insight_data: Optional[dict]
    callback_success: bool
    error: Optional[str]
    messages: List[dict] = []
    format_ok: bool = False

    status: str = "Ok"
    reason: str = ""


# ============================================================
# Agent 定义（决策中心）
# ============================================================

AVAILABLE_TOOLS = [
    "get_crypto_investment_outlook",  # 机会分析
    "get_crypto_market_data"          # 指标查询
]


class CurrencyInsightAgent:
    """
    币种洞察 Agent - 决策中心
    
    职责：
    1. plan: 分析任务，决定需要调用哪些工具
    2. synthesize: 汇总工具结果，生成结构化洞察报告
    
    注意：复用模块级 LLM 单例，避免每次实例化创建新客户端
    """
    
    async def plan(self, state: CurrencyInsightState) -> CurrencyInsightState:
        """规划阶段：决定需要调用哪些工具"""
        symbol = state.get("symbol", "")
        market_type = state.get("market_type", "spot")
        logger.info(f"Agent planning for {symbol} ({market_type})")
        system_prompt = await mcp_client.get_prompt("currency_insight_plan_prompt")
        state["messages"] = [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": f"Please analyze the performance of {symbol} in the {market_type} market. Call relevant tools to obtain market data, technical indicators, investment opportunities and other information to generate a detailed currency insight report for me."
            }
        ]
            
        tools = await mcp_client.list_openai_tools(AVAILABLE_TOOLS)
        response = await llm.ainvoke(
            messages=state["messages"],
            tools=tools,
            temperature=0.3,
        )
        tool_calls = [{"tool_call_id": tool_call.id} | tool_call.function.model_dump() for tool_call in response.tool_calls]
        logger.info(f"Agent decided tools: {[tc['name'] for tc in tool_calls]}")

        if not tool_calls:
            tool_calls = [
                {
                    "tool_call_id": f"call_{uuid.uuid4().hex[:24]}",
                    "name": "get_crypto_investment_outlook",
                    "arguments": {'symbol': symbol, 'market_type': market_type, 'query': f'Analyze {symbol} ({market_type})','detect_language': 'English'}
                },
                {
                    "tool_call_id": f"call_{uuid.uuid4().hex[:24]}",
                    "name": "get_crypto_market_data",
                    "arguments": {'symbol': f'{symbol}-USDT', 'indicator': 'PRICE', 'market_type': market_type, 'query': f'Get the current price for {symbol}-USDT', 'detect_language': 'English'}
                }
            ]
        state["tool_calls"] = tool_calls
        state["messages"].extend([
            {
                "role": "assistant",
                "content": f"I will use the tools {set([tool['name'] for tool in tool_calls])} to obtain market insights for {symbol}."
            }
        ])
        return state
    
    async def synthesize(self, state: CurrencyInsightState) -> CurrencyInsightState:
        """综合阶段：汇总结果，生成结构化报告"""
        symbol = state.get("symbol", "")
        success = False
        for tool_result in state.get("tool_results", []):
            status = tool_result.get("success", False)
            if status:
                success = True
                break

        if not success:
            fallback = FinalResponse(symbol=symbol).model_dump(mode="json")
            fallback["updateTime"] = utc_now_iso()
            state.update({
                "format_ok": False,
                "insight_data": fallback,
                "status": "Failed",
                "reason": "All tool calls failed, unable to generate insight report"
            })
            return state

        
        logger.info(f"Agent synthesizing for {symbol}")
        
        system_prompt = await mcp_client.get_prompt("currency_insight_synthesis_prompt", data={"symbol": symbol, "date": utc_now_iso()[:10]})
        if system_prompt:
            state["messages"] = [{"role": "system", "content": system_prompt}, *[m for m in state["messages"] if m.get("role") != "system"]]
        
        try:
            response = await llm.ainvoke(
                messages=state["messages"],
                model="Qwen3.5-27B",
                temperature=0.3,
                response_format=FinalResponse,
                timeout=30
            )
            result = response.model_dump(mode="json")
            result["updateTime"] = utc_now_iso()
            state.update({
                "format_ok": True,
                "insight_data": result,
            })
        except:
            logger.exception(f"Failed to synthesize insight data for {symbol}")
            fallback = FinalResponse(symbol=symbol).model_dump(mode="json")
            fallback["updateTime"] = utc_now_iso()
            state.update({
                "format_ok": False,
                "insight_data": fallback,
                "status": "Failed",
                "reason": "LLM synthesis failed or format not correct"
            })

        logger.info(f"Agent synthesized insight data for {symbol}: format_ok={state.get('format_ok')}")
        return state
    

# ============================================================
# LangGraph 工作流编排
# ============================================================

def create_currency_insight_workflow():
    """
    创建币种洞察工作流
    
    流程：plan -> execute_tools -> synthesize -> callback
    """
    # 复用 skills/ 目录下的组件
    agent = CurrencyInsightAgent()
    tool_skill = MCPToolCallSkill()  # 批量模式
    callback_skill = CallbackSkill()
    
    workflow = StateGraph(CurrencyInsightState)
    
    # 添加节点
    workflow.add_node("plan", agent.plan)
    workflow.add_node("execute_tools", tool_skill.execute)
    workflow.add_node("synthesize", agent.synthesize)
    workflow.add_node("callback", callback_skill.execute)
    
    # 定义边
    workflow.set_entry_point("plan")
    workflow.add_edge("plan", "execute_tools")
    workflow.add_edge("execute_tools", "synthesize")
    workflow.add_edge("synthesize", "callback")
    workflow.add_edge("callback", END)
    
    return workflow.compile()


async def run_currency_insight(
    user_id: str,
    symbol: str,
    market_type: str,
    callback_url: str,
    source: str
) -> CurrencyInsightState:
    """执行币种洞察工作流"""
    logger.info(f"Starting currency insight: symbol={symbol}, market_type={market_type}")
    
    workflow = create_currency_insight_workflow()
    
    initial_state: CurrencyInsightState = {
        "user_id": user_id,
        "symbol": symbol,
        "market_type": market_type,
        "callback_url": callback_url,
        "source": source,
        "tool_calls": [],
        "tool_results": [],
        "insight_data": None,
        "callback_success": False,
        "error": None
    }
    
    try:
        result = await workflow.ainvoke(initial_state)
        logger.info(f"Currency insight completed: symbol={symbol}, success={result.get('callback_success')}")
        return result
    except Exception as e:
        logger.exception(f"Currency insight failed: {e}")
        return {**initial_state, "error": str(e)}


__all__ = [
    "CurrencyInsightState",
    "CurrencyInsightAgent", 
    "create_currency_insight_workflow",
    "run_currency_insight",
]
