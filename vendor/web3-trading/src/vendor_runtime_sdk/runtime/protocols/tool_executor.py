"""
Protocol 2: Tool Executor — 工具执行抽象 (§4.2)

Defines the contract for tool execution. Tools always return ToolResult
and never raise exceptions (§2 ToolResult never-throw).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ToolResult:
    """Result of a tool execution — errors returned in .error, never thrown."""

    output: str = ""
    error: str | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def is_error(self) -> bool:
        return self.error is not None


class ToolExecutor(Protocol):
    """Protocol for tool execution — never throws, error in ToolResult."""

    async def execute(self, name: str, args: dict) -> ToolResult: ...
