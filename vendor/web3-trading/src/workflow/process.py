# -*- coding: utf-8 -*-
import time
import uuid
import logging
import json_repair
import json
import importlib
from enum import StrEnum
from typing import TypedDict, Optional, List, Literal, Dict, Union, Any
from langgraph.graph import StateGraph, END
from pydantic import BaseModel

from agent.skills.tool_call import ToolCallSkill
from agent.skills.callback import WorkFlowCallbackSkill
from agent.utils import utc_now_iso
from mcp.mcp_http_client import mcp_client
from llm.llm import llm
from llm.base import create_llm
from web.config import config
from agent.tools.base import BaseTool, ToolResult
from libs.load_prompt import get_prompt
from libs.callback import execute_callback, get_func
from memory.mem0 import Mem0Memory

logger = logging.getLogger(__name__)


class Tool(BaseModel):
    name: str
    parameters: Dict[str, Any]
    description: str = ""
    result: Optional[ToolResult] = None
    tool_call_id: Optional[str] = "call_" + uuid.uuid4().hex[:24]
    status: bool = False

    def to_tool_call(self):
        """Convert to the format for messages"""
        return {
            "id": self.tool_call_id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": self.parameters,
            }
        }


class State(TypedDict):
    """工作流状态"""
    # 输入
    start_time: float = time.time()
    user_id: str
    query: str
    extra_query: dict = {}
    callback_url: str
    skill_config: dict = {}
    
    # Agent 决策
    messages: List[dict] = []
    tools: List[Tool] = []
    
    # 输出
    result: Any = None
    extra_body: dict = {}
    status: str = "Failed"  # Ok, Failed
    reason: str = ""  # 失败原因
    memory: str = ""  # 长期记忆（按 query 召回）


class WorkFLowAgent:
    @staticmethod
    def _is_memory_enabled(state: State) -> bool:
        """Whether long-term memory is enabled for current workflow."""
        skill_config = state.get("skill_config") or {}
        # Default enabled for backward compatibility.
        return bool(skill_config.get("enable_memory", False))

    @staticmethod
    def _format_user_memory(memory: List[dict]) -> str:
        """Format recalled memory into compact text for prompt injection."""
        if not memory or not isinstance(memory, list):
            return ""
        lines: List[str] = []
        for item in memory:
            content = item.get("memory", "")
            if not content:
                continue
            score = item.get("score", 0)
            relevance = f"{score * 100:.1f}%" if score else "0%"
            lines.append(f"- ({relevance}) {content}")
        return "\n".join(lines)

    async def _recall_memory(self, state: State) -> str:
        """Recall long-term memory for async bot workflows."""
        user_id = state.get("user_id")
        query = state.get("query", "")
        if not user_id or not query:
            return ""
        try:
            memory_client = Mem0Memory(user_id=user_id)
            memory = await memory_client.recall(query)
            memory_text = self._format_user_memory(memory)
            if memory_text:
                logger.info(f"Workflow memory recalled: user_id={user_id}, lines={len(memory_text.splitlines())}")
            return memory_text
        except Exception as e:
            logger.warning(f"Workflow recall memory failed: {e}")
            return ""

    @staticmethod
    async def _persist_memory(state: State):
        """Persist user query + assistant result to long-term memory."""
        user_id = state.get("user_id")
        query = state.get("query", "")
        result = state.get("result")
        if not user_id or not query or result is None:
            return
        try:
            memory_client = Mem0Memory(user_id=user_id)
            await memory_client.add(
                [
                    {"role": "user", "content": str(query)},
                    {"role": "assistant", "content": str(result)[:4000]},
                ],
                sync=False,
            )
            logger.info(f"Workflow memory persisted: user_id={user_id}")
        except Exception as e:
            logger.warning(f"Workflow persist memory failed: {e}")

    @staticmethod
    def _merge_memory_to_prompt(system_prompt: str, memory_text: str) -> str:
        """Append memory section to system prompt without changing prompt API."""
        if not memory_text:
            return system_prompt
        return (
            f"{system_prompt}\n\n"
            "[User Long-term Memory]\n"
            f"{memory_text}\n"
            "[Use memory only when relevant to current task.]"
        )

    async def _execute_llm_with_callbacks(
        self,
        state: State,
        prompt_key: str,
        messages: List[dict],
        llm_kwargs: Optional[Dict[str, Any]] = None,
        extra_callback_kwargs: Optional[Dict[str, Any]] = None
    ) -> Any:
        """
        统一的LLM调用函数，支持前后回调

        Args:
            state: 工作流状态
            prompt_key: prompt配置键，如 "query_parse_prompt", "plan_prompt", "synthesize_prompt"
            messages: 发送给LLM的消息列表
            llm_kwargs: LLM调用的额外参数，如 temperature, timeout, tools等
            extra_callback_kwargs: 传递给回调的额外参数，如 tools

        Returns:
            LLM响应对象
        """
        try:
            skill_config = state.get("skill_config", {})
            prompt_config = skill_config.get(prompt_key, {})
            before_callback = prompt_config.get("before_callback")
            after_callback = prompt_config.get("after_callback")

            # 准备回调参数
            callback_kwargs = {"state": state}
            if extra_callback_kwargs:
                callback_kwargs.update(extra_callback_kwargs)

            if before_callback:
                await execute_callback(before_callback, **callback_kwargs)

            # 调用LLM
            llm_params = {"messages": messages}
            if llm_kwargs:
                llm_params.update(llm_kwargs)

            response = await llm.ainvoke(**llm_params)

            if after_callback:
                await execute_callback(after_callback, **callback_kwargs, response=response)

            return response

        except Exception as e:
            logger.exception(f"LLM execution failed for {prompt_key}", exc_info=e)
            raise

    async def _handle_workflow_error(self, state: State, stage: str, error: Exception) -> State:
        """统一的工作流错误处理"""
        logger.exception(f"Workflow {stage} failed", exc_info=error)
        state.update({
            "status": "Failed",
            "reason": f"Workflow {stage} failed: {str(error)}"
        })
        return state
    
    def _get_query(self, state: State) -> str:
        """获取查询内容，包含用户输入和额外查询信息"""
        content = state["query"]
        if state.get("extra_query"):
            content += "\n\n" + json.dumps(state["extra_query"], ensure_ascii=False)
        return content

    async def query_pasrse(self, state: State) -> State:
        """查询解析阶段：解析用户输入，提取关键信息，进行必要的预处理"""
        try:
            skill_config = state.get("skill_config") or {}
            query_parse_prompt = skill_config.get("query_parse_prompt") or {}
            if not query_parse_prompt.get("name"):
                return state

            # 构建消息
            message = [
                {
                    "role": "system",
                    "content": await get_prompt(query_parse_prompt)
                },
                {
                    "role": "user",
                    "content": self._get_query(state)
                }
            ]

            # 使用统一的LLM调用函数
            response = await self._execute_llm_with_callbacks(
                state=state,
                prompt_key="query_parse_prompt",
                messages=message,
                llm_kwargs={"temperature": 0.01, "timeout": 30}
            )

            state["query"] = response.content.strip()
            logger.info(f"Query parsed: {state['query']}")

        except Exception as e:
            state = await self._handle_workflow_error(state, "query parsing", e)

        return state
    
    async def plan(self, state: State) -> State:
        """规划阶段：决定需要调用哪些工具"""
        try:
            skill_config = state.get("skill_config") or {}
            if self._is_memory_enabled(state):
                state["memory"] = await self._recall_memory(state)
            if skill_config.get("query_parse_prompt", {}).get("name"):
                state = await self.query_pasrse(state)
                state["messages"].append({
                    "role": "user",
                    "content": state["query"]
                })
            else:
                state["messages"].append({
                    "role": "user",
                    "content": self._get_query(state)
                })

            if not skill_config.get("enable_tools", False):
                return state

            if not skill_config.get("plan_prompt"):
                return state

            system_prompt = await get_prompt(skill_config.get("plan_prompt", {}))
            system_prompt = self._merge_memory_to_prompt(system_prompt, state.get("memory", ""))
            if system_prompt:
                state["messages"] = [{"role": "system", "content": system_prompt}, *[m for m in state["messages"] if m.get("role") != "system"]]

            # 获取可用的工具列表
            available_tools = skill_config.get("available_tools") or []
            tools = await mcp_client.list_openai_tools(available_tools)

            # 使用统一的LLM调用函数，传递tools给回调
            response = await self._execute_llm_with_callbacks(
                state=state,
                prompt_key="plan_prompt",
                messages=state["messages"],
                llm_kwargs={"tools": tools, "temperature": 0.3, "timeout": 60},
                extra_callback_kwargs={"tools": tools}
            )
            if not response.tool_calls:
                logger.info("Agent did not decide to use any tools.")
                state["tools"] = []
                return state

            # 处理工具调用结果
            tool_calls = []
            tool_names = []
            for tool_call in response.tool_calls:
                tool_dict = tool_call.function.model_dump()
                tool_dict["tool_call_id"] = tool_call.id
                tool_calls.append(tool_dict)
                tool_names.append(tool_dict["name"])

            logger.info(f"Agent decided tools: {tool_names}")

            # 更新状态中的工具列表
            workflow_tools = state.get("tools", [])
            for tool in tool_calls:
                workflow_tools.append(Tool(
                    name=tool["name"],
                    parameters=tool["arguments"],
                    tool_call_id=tool["tool_call_id"]
                ))
            state["tools"] = workflow_tools

            # 更新消息
            state["messages"].extend([
                {
                    "role": "assistant",
                    "content": f"I will use the tools {set(tool_names)} to analyze the query.",
                    "tool_calls": [
                        tool.to_tool_call()
                        for tool in workflow_tools
                    ]
                }
            ])
        except Exception as e:
            state = await self._handle_workflow_error(state, "planning", e)
        return state
    
    async def synthesize(self, state: State) -> State:
        """综合阶段：汇总结果，生成结构化报告"""
        try:
            skill_config = state.get("skill_config", {})
            system_prompt = await get_prompt(
                skill_config.get("synthesize_prompt", {}),
                data={
                    "current_time": utc_now_iso(),
                    **(state.get("extra_query") or {})
                }
            )
            system_prompt = self._merge_memory_to_prompt(system_prompt, state.get("memory", ""))
            if system_prompt:
                state["messages"] = [{"role": "system", "content": system_prompt}, *[m for m in state["messages"] if m.get("role") != "system"]]

            # 使用统一的LLM调用函数
            llm_kwargs = {"temperature": 0.3, "timeout": 60}
            response_format = skill_config.get("synthesize_prompt", {}).get("response_format")
            if response_format:
                llm_kwargs["response_format"] = get_func(response_format)
            response = await self._execute_llm_with_callbacks(
                state=state,
                prompt_key="synthesize_prompt",
                messages=state["messages"],
                llm_kwargs=llm_kwargs
            )
            if response_format and issubclass(get_func(response_format), BaseModel):
                result = response.model_dump_json()
            else:
                try:
                    result = json_repair.loads(response.content) or response.content
                    if not isinstance(result, str):
                        result = json.dumps(result, ensure_ascii=False)
                except:
                    result = response.content

            state["result"] = result
            logger.info(f"Agent synthesized: result={state.get('result')}")
            if self._is_memory_enabled(state):
                await self._persist_memory(state)

        except Exception as e:
            state = await self._handle_workflow_error(state, "synthesis", e)

        return state


def create_default_workflow() -> StateGraph:
    """
    创建工作流
    流程：plan -> execute_tools -> synthesize -> callback
    """
    workflow_agent = WorkFLowAgent()
    tool_skill = ToolCallSkill()
    callback_skill = WorkFlowCallbackSkill()
    workflow = StateGraph(State)
    
    # 添加节点
    workflow.add_node("plan", workflow_agent.plan)
    workflow.add_node("execute_tools", tool_skill.execute)
    workflow.add_node("synthesize", workflow_agent.synthesize)
    workflow.add_node("callback", callback_skill.execute)
    
    # 定义边
    workflow.set_entry_point("plan")
    workflow.add_edge("plan", "execute_tools")
    workflow.add_edge("execute_tools", "synthesize")
    workflow.add_edge("synthesize", "callback")
    workflow.add_edge("callback", END)
    
    return workflow.compile()


_AGENT_MAP = {
    "": create_default_workflow()
}
def create_workflow(skill_name: str) -> StateGraph:
    return _AGENT_MAP.get(skill_name, create_default_workflow())


__all__ = [
    "create_workflow"
]
