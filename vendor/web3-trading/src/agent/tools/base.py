# -*- coding: utf-8 -*-
"""
Base Tool Definition

Defines the abstract base class for all tools used in the agent orchestration
system. Inspired by nanobot's tool architecture.

Each tool provides:
- A unique name
- A description for the LLM
- A JSON Schema for parameters
- An async execute method
- An OpenAI function-calling schema generator
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ToolResult:
    """
    Standardized result from tool execution.
    
    Tools should always return a ToolResult instead of raising exceptions.
    Errors are captured in the `error` field.
    """
    success: bool = True
    content: str = ""
    data: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_message(self) -> str:
        """Convert to a string suitable for LLM message content."""
        if self.error:
            return f"Error: {self.error}"
        return self.content


class BaseTool(ABC):
    """
    Abstract base class for all agent tools.
    
    Tools are the atomic execution units in the agent orchestration system.
    They wrap external capabilities (MCP tools, local functions, etc.) into 
    a unified interface that the AgentLoop can invoke.
    
    Subclasses must implement:
    - name: unique identifier
    - description: human-readable description for the LLM
    - parameters: JSON Schema dict defining expected arguments
    - execute(): async method that performs the tool's action
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name identifying this tool."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description for the LLM to understand the tool's purpose."""
        ...

    async def mcp_description(self) -> str:
        from mcp.mcp_http_client import mcp_client
        prompt = await mcp_client.get_prompt(self.name)
        return prompt or self.description

    @property
    @abstractmethod
    def parameters(self) -> Dict[str, Any]:
        """
        JSON Schema object defining expected parameters.
        
        Example:
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"}
                },
                "required": ["query"]
            }
        """
        ...

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """
        Execute the tool with given arguments.
        
        Must NOT raise exceptions - errors should be returned in ToolResult.error.
        
        Args:
            **kwargs: Arguments matching the tool's parameter schema
            
        Returns:
            ToolResult with execution outcome
        """
        ...

    def validate_params(self, params: Dict[str, Any]) -> List[str]:
        """
        Validate parameters against the schema.
        
        Returns a list of error messages. Empty list means valid.
        """
        errors = []
        schema = self.parameters
        required = schema.get("required", [])
        properties = schema.get("properties", {})

        for key in required:
            if key not in params:
                errors.append(f"Missing required parameter: {key}")

        for key in params:
            if key not in properties:
                # Allow extra params but log a warning
                logger.debug(f"Tool '{self.name}' received unexpected parameter: {key}")

        return errors

    def to_openai_schema(self) -> Dict[str, Any]:
        """
        Convert this tool to OpenAI function-calling schema format.
        
        Returns:
            Dict in the format expected by OpenAI's `tools` parameter:
            {
                "type": "function",
                "function": {
                    "name": "...",
                    "description": "...",
                    "parameters": {...}
                }
            }
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        }

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name={self.name})>"


class DirectResponseTool(BaseTool):
    """
    Pseudo-tool for the LLM to signal it wants to respond directly
    without using any external tools.
    
    This replaces the hardcoded `direct_response` tool that was previously
    injected in `_decide_tools_and_actions()`.
    """

    @property
    def name(self) -> str:
        return "direct_response"

    @property
    def description(self) -> str:
        return (
            "This tool is used to directly respond to the user's query when no external "
            "tools are needed. You should provide your intended response content in the "
            "suggested_response parameter to help the system understand your response intent."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "suggested_response": {
                    "type": "string",
                    "description": (
                        "Your intended response content to the user's query. Keep it as "
                        "brief as possible (preferably one sentence or a few key points) "
                        "to express your response intent."
                    ),
                },
                "detect_language": {
                    "type": "string",
                    "description": (
                        "Detect the writing language used in the user's query text. "
                        "If the user explicitly requests a specific language, set this "
                        "to that language."
                    ),
                },
            },
            "required": ["suggested_response", "detect_language"],
        }

    async def execute(self, **kwargs) -> ToolResult:
        """Direct response doesn't execute externally - just passes through."""
        return ToolResult(
            success=True,
            content=kwargs.get("suggested_response", ""),
            data=kwargs,
            metadata={"detect_language": kwargs.get("detect_language", "English")},
        )
