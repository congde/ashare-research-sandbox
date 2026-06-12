"""
Protocol 1: LLM Client — LLM 调用抽象 (§4.2)

Defines the contract for LLM interaction. All ConversationRuntime
modules depend on this Protocol, never on concrete implementations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, Literal, Protocol


@dataclass
class AssistantEvent:
    """Single event emitted during LLM streaming."""

    type: Literal["text_delta", "tool_use", "stop", "usage"]
    text: str | None = None
    tool_name: str | None = None
    tool_args: dict | None = None
    call_id: str | None = None
    usage: dict | None = None  # {prompt_tokens, completion_tokens, cache_*}


@dataclass
class TurnSummary:
    """Summary of a completed turn."""

    text: str
    tool_calls: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)  # {input_tokens, output_tokens, total_tokens}
    iterations: int = 0


class LLMClient(Protocol):
    """Protocol for LLM interaction — stream a single turn."""

    async def stream_turn(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> AsyncIterator[AssistantEvent]: ...
