# -*- coding: utf-8 -*-
"""
ReAct Agent Loop

Core orchestration loop that implements the ReAct (Reason + Act) pattern:
    LLM call -> tool_calls -> execute tools -> append results -> repeat

Inspired by nanobot's agent loop architecture but adapted for the 
ai-web3-tradding-agent's SSE streaming pipeline.

Key features:
- Multi-turn tool calling with configurable max_iterations
- Streaming event generation compatible with existing StreamResponse
- Parallel tool execution within a single iteration
- Graceful error handling (never crashes the loop)
- Support for both OpenAI API and BaseLLM interfaces
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Union

from agent.tools.base import ToolResult
from agent.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


# ============================================================
# Event Types for the Agent Loop
# ============================================================

class LoopEventType(str, Enum):
    """Types of events emitted by the AgentLoop."""
    ITERATION_START = "iteration_start"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ITERATION_END = "iteration_end"
    FINAL_RESPONSE = "final_response"
    STREAMING_DELTA = "streaming_delta"
    ERROR = "error"
    MAX_ITERATIONS = "max_iterations"


@dataclass
class ToolCallInfo:
    """Information about a single tool call decision by the LLM."""
    tool_call_id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class ToolResultInfo:
    """Result from a single tool execution."""
    tool_call_id: str
    name: str
    result: ToolResult
    elapsed_ms: int = 0


@dataclass
class LoopEvent:
    """
    Event emitted by the AgentLoop during execution.
    
    These events allow the caller to observe and react to each step
    of the ReAct loop, enabling SSE streaming, logging, etc.
    """
    type: LoopEventType
    iteration: int = 0
    content: Optional[str] = None
    tool_calls: List[ToolCallInfo] = field(default_factory=list)
    tool_results: List[ToolResultInfo] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


# ============================================================
# Agent Loop
# ============================================================

class AgentLoop:
    """
    ReAct Agent Loop - the core orchestration engine.
    
    Implements the ReAct pattern: repeatedly calls the LLM, executes
    any requested tools, appends results, and repeats until the LLM
    produces a final response (no tool calls) or max_iterations is reached.
    
    Designed to be composable:
    - Can be used standalone or embedded in BaseAgent
    - Yields LoopEvent objects that can be converted to StreamResponse
    - Supports both OpenAI AsyncOpenAI client and BaseLLM interfaces
    
    Usage:
        loop = AgentLoop(
            llm=openai_client, 
            model_name="gpt-4",
            tool_registry=registry,
            max_iterations=10,
        )
        
        async for event in loop.run(messages):
            if event.type == LoopEventType.TOOL_CALL:
                # Handle tool call event (e.g. stream to frontend)
                ...
            elif event.type == LoopEventType.FINAL_RESPONSE:
                # Handle final response
                print(event.content)
    """

    def __init__(
        self,
        llm,
        model_name: str,
        tool_registry: ToolRegistry,
        max_iterations: int = 10,
        temperature: float = 0.2,
        max_tokens: int = 800,
        timeout: float = 30.0,
        extra_body: Optional[Dict] = None,
        tool_choice: str = "auto",
        parallel_tool_calls: bool = True,
        on_before_tool_execute: Optional[Callable] = None,
    ):
        """
        Initialize the AgentLoop.
        
        Args:
            llm: OpenAI AsyncOpenAI client instance
            model_name: Model name to use for LLM calls
            tool_registry: Registry of available tools
            max_iterations: Maximum number of LLM-tool cycles
            temperature: LLM temperature
            max_tokens: Max tokens for LLM response
            timeout: LLM API call timeout in seconds
            extra_body: Extra body parameters for LLM API
            tool_choice: Tool choice strategy ("auto", "required", "none")
            parallel_tool_calls: Whether to execute multiple tool calls in parallel
            on_before_tool_execute: Optional callback before each tool execution
        """
        self.llm = llm
        self.model_name = model_name
        self.tool_registry = tool_registry
        self.max_iterations = max_iterations
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.extra_body = extra_body
        self.tool_choice = tool_choice
        self.parallel_tool_calls = parallel_tool_calls
        self.on_before_tool_execute = on_before_tool_execute

        # State tracking
        self._iteration_count = 0
        self._total_tool_calls = 0
        self._accumulated_tool_results: List[ToolResultInfo] = []

    async def run(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
    ) -> AsyncGenerator[LoopEvent, None]:
        """
        Execute the ReAct loop.
        
        Yields LoopEvent objects for each step: tool calls, tool results,
        and the final response.
        
        Args:
            messages: Conversation messages (mutated in-place with tool results)
            system_prompt: Optional system prompt to prepend
            
        Yields:
            LoopEvent objects for each step
        """
        # Prepend system prompt if provided
        if system_prompt and (not messages or messages[0].get("role") != "system"):
            messages.insert(0, {"role": "system", "content": system_prompt})
        elif system_prompt and messages and messages[0].get("role") == "system":
            messages[0]["content"] = system_prompt

        tool_definitions = self.tool_registry.get_definitions()
        if not tool_definitions:
            logger.warning("No tools registered in ToolRegistry, running without tools")

        for iteration in range(self.max_iterations):
            self._iteration_count = iteration + 1
            
            yield LoopEvent(
                type=LoopEventType.ITERATION_START,
                iteration=self._iteration_count,
                metadata={"total_tool_calls": self._total_tool_calls},
            )

            # --- LLM Call ---
            try:
                response = await self._call_llm(messages, tool_definitions)
            except Exception as e:
                error_msg = f"LLM call failed at iteration {self._iteration_count}: {type(e).__name__}: {str(e)}"
                logger.exception(error_msg)
                yield LoopEvent(
                    type=LoopEventType.ERROR,
                    iteration=self._iteration_count,
                    error=error_msg,
                )
                return

            message = response.choices[0].message
            tool_calls = message.tool_calls

            # --- No tool calls: Final response ---
            if not tool_calls:
                content = message.content or ""
                yield LoopEvent(
                    type=LoopEventType.FINAL_RESPONSE,
                    iteration=self._iteration_count,
                    content=content,
                    metadata={
                        "total_iterations": self._iteration_count,
                        "total_tool_calls": self._total_tool_calls,
                        "accumulated_results": [
                            {"name": r.name, "success": r.result.success}
                            for r in self._accumulated_tool_results
                        ],
                    },
                )
                # Append assistant message to history
                messages.append({"role": "assistant", "content": content})
                return

            # --- Tool calls: Execute and continue ---
            # Parse tool calls
            call_infos = []
            for tc in tool_calls:
                try:
                    args = tc.function.arguments
                    if isinstance(args, str):
                        args = json.loads(args)
                except (json.JSONDecodeError, AttributeError):
                    args = {}
                
                call_infos.append(ToolCallInfo(
                    tool_call_id=tc.id,
                    name=tc.function.name,
                    arguments=args,
                ))

            self._total_tool_calls += len(call_infos)

            # Emit tool call event
            yield LoopEvent(
                type=LoopEventType.TOOL_CALL,
                iteration=self._iteration_count,
                tool_calls=call_infos,
            )

            # Append assistant message with tool calls to messages
            messages.append({
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments if isinstance(tc.function.arguments, str) else json.dumps(tc.function.arguments, ensure_ascii=False),
                        },
                    }
                    for tc in tool_calls
                ],
            })

            # Execute tools
            tool_result_infos = await self._execute_tools(call_infos)
            self._accumulated_tool_results.extend(tool_result_infos)

            # Append tool results to messages
            for tri in tool_result_infos:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tri.tool_call_id,
                    "content": tri.result.to_message(),
                })

            # Emit tool result event
            yield LoopEvent(
                type=LoopEventType.TOOL_RESULT,
                iteration=self._iteration_count,
                tool_results=tool_result_infos,
            )

            yield LoopEvent(
                type=LoopEventType.ITERATION_END,
                iteration=self._iteration_count,
            )

        # Max iterations reached
        logger.warning(f"AgentLoop reached max_iterations={self.max_iterations}")
        yield LoopEvent(
            type=LoopEventType.MAX_ITERATIONS,
            iteration=self._iteration_count,
            metadata={
                "total_iterations": self._iteration_count,
                "total_tool_calls": self._total_tool_calls,
            },
            error=f"Reached maximum iterations ({self.max_iterations})",
        )

    async def run_to_completion(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
    ) -> str:
        """
        Run the loop to completion and return the final response content.
        
        Convenience method for cases where streaming events aren't needed
        (e.g., subagent execution).
        
        Args:
            messages: Conversation messages
            system_prompt: Optional system prompt
            
        Returns:
            Final response content string
        """
        final_content = ""
        async for event in self.run(messages, system_prompt):
            if event.type == LoopEventType.FINAL_RESPONSE:
                final_content = event.content or ""
            elif event.type == LoopEventType.ERROR:
                final_content = f"Error: {event.error}"
            elif event.type == LoopEventType.MAX_ITERATIONS:
                # Try to use the last assistant message if available
                for msg in reversed(messages):
                    if msg.get("role") == "assistant" and msg.get("content"):
                        final_content = msg["content"]
                        break
                if not final_content:
                    final_content = "Reached maximum iteration limit."
        return final_content

    async def _call_llm(
        self,
        messages: List[Dict[str, str]],
        tool_definitions: List[Dict],
    ):
        """
        Make a single LLM API call.
        
        Args:
            messages: Current conversation messages
            tool_definitions: OpenAI tool schemas
            
        Returns:
            LLM response object
        """
        kwargs = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "timeout": self.timeout,
        }

        if tool_definitions:
            kwargs["tools"] = tool_definitions
            kwargs["tool_choice"] = self.tool_choice

        if self.extra_body:
            kwargs["extra_body"] = self.extra_body

        response = await self.llm.chat.completions.create(**kwargs)
        return response

    async def _execute_tools(
        self,
        call_infos: List[ToolCallInfo],
    ) -> List[ToolResultInfo]:
        """
        Execute one or more tool calls.
        
        If parallel_tool_calls is True, executes all tools concurrently.
        Otherwise, executes them sequentially.
        
        Args:
            call_infos: List of tool calls to execute
            
        Returns:
            List of ToolResultInfo with results
        """
        if self.parallel_tool_calls and len(call_infos) > 1:
            return await self._execute_tools_parallel(call_infos)
        else:
            return await self._execute_tools_sequential(call_infos)

    async def _execute_tools_sequential(
        self,
        call_infos: List[ToolCallInfo],
    ) -> List[ToolResultInfo]:
        """Execute tool calls one by one."""
        results = []
        for ci in call_infos:
            result_info = await self._execute_single_tool(ci)
            results.append(result_info)
        return results

    async def _execute_tools_parallel(
        self,
        call_infos: List[ToolCallInfo],
    ) -> List[ToolResultInfo]:
        """Execute tool calls concurrently."""
        tasks = [self._execute_single_tool(ci) for ci in call_infos]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        result_infos = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.exception(f"Parallel tool execution failed: {result}")
                result_infos.append(ToolResultInfo(
                    tool_call_id=call_infos[i].tool_call_id,
                    name=call_infos[i].name,
                    result=ToolResult(success=False, error=str(result)),
                ))
            else:
                result_infos.append(result)
        return result_infos

    async def _execute_single_tool(self, call_info: ToolCallInfo) -> ToolResultInfo:
        """Execute a single tool call."""
        if self.on_before_tool_execute:
            try:
                await self.on_before_tool_execute(call_info)
            except Exception as e:
                logger.warning(f"on_before_tool_execute callback failed: {e}")

        start_time = time.time()
        result = await self.tool_registry.execute(call_info.name, call_info.arguments)
        elapsed_ms = int((time.time() - start_time) * 1000)

        return ToolResultInfo(
            tool_call_id=call_info.tool_call_id,
            name=call_info.name,
            result=result,
            elapsed_ms=elapsed_ms,
        )

    @property
    def iteration_count(self) -> int:
        """Number of iterations completed."""
        return self._iteration_count

    @property
    def total_tool_calls(self) -> int:
        """Total number of tool calls made across all iterations."""
        return self._total_tool_calls

    @property
    def accumulated_tool_results(self) -> List[ToolResultInfo]:
        """All tool results accumulated across iterations."""
        return self._accumulated_tool_results
