# -*- coding: utf-8 -*-
"""
SystemPromptBuilder — Dynamic system prompt assembly for the Runtime.

Layers (assembled top-to-bottom):
  1. Base identity: Role + personality + language directive
  2. Memory injection: File memory (from memory/prompt_builder) + vector recall (Mem0)
  3. Tool descriptions: Available tools summary + policy constraints
  4. Workspace context: Current workspace root + lane info
  5. Dynamic append: Override prompts / persona / skill-specific directives

Design principle:
  - Existing agent/prompt/effective_system.py handles the "effective system" resolution
    (override_system_prompt > custom_system_prompt > MCP template + append)
  - This builder sits ABOVE that, composing the full prompt from structured layers
  - The result is fed into ConversationRuntime as the system_prompt parameter

Integration:
  - Reuses agent/prompt/effective_system.py for prompt resolution
  - Reuses memory/prompt_builder.py for memory injection
  - Adds runtime-specific layers (tools, workspace, lane)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


# ──────────────── Prompt Layer ────────────────


@dataclass
class PromptLayer:
    """A single layer in the system prompt stack"""

    name: str
    content: str
    priority: int = 0  # Higher = appears earlier in the assembled prompt
    separator: str = "\n\n"


# ──────────────── System Prompt Builder ────────────────


class SystemPromptBuilder:
    """
    Dynamic system prompt builder — assembles layers into a coherent system prompt.

    Usage:
        builder = SystemPromptBuilder(base_identity="You are a helpful AI assistant.")
        builder.add_layer(PromptLayer(name="tools", content=tool_summary, priority=10))
        builder.add_layer(PromptLayer(name="memory", content=memory_block, priority=20))
        prompt = builder.build()
    """

    def __init__(
        self,
        base_identity: str = "You are a helpful AI assistant.",
        language_hint: Optional[str] = None,
        memory_block: Optional[str] = None,
        tool_summaries: Optional[List[Dict]] = None,
        workspace_root: Optional[str] = None,
        lane_id: Optional[str] = None,
        append_system_prompt: Optional[str] = None,
    ):
        self._base_identity = base_identity
        self._language_hint = language_hint
        self._memory_block = memory_block
        self._tool_summaries = tool_summaries or []
        self._workspace_root = workspace_root
        self._lane_id = lane_id
        self._append_system_prompt = append_system_prompt
        self._extra_layers: List[PromptLayer] = []

    def add_layer(self, layer: PromptLayer) -> None:
        """Add an additional prompt layer"""
        self._extra_layers.append(layer)

    def remove_layer(self, name: str) -> None:
        """Remove a layer by name"""
        self._extra_layers = [l for l in self._extra_layers if l.name != name]

    def set_base_identity(self, identity: str) -> None:
        """Override the base identity"""
        self._base_identity = identity

    def set_memory_block(self, block: str) -> None:
        """Set the memory injection block"""
        self._memory_block = block

    def set_tool_summaries(self, summaries: List[Dict]) -> None:
        """Set tool descriptions"""
        self._tool_summaries = summaries

    def set_workspace(self, root: str, lane_id: Optional[str] = None) -> None:
        """Set workspace context"""
        self._workspace_root = root
        self._lane_id = lane_id

    def build(self) -> str:
        """
        Assemble all layers into the final system prompt.

        Layer priority ordering (higher priority = earlier):
          - Memory (priority 100): Critical context for continuity
          - Identity (priority 50): Core role definition
          - Tools (priority 30): Tool usage guidelines
          - Workspace (priority 20): Environment context
          - Extra layers: Custom additions
          - Append (priority 0): Always at the end
        """
        layers: List[PromptLayer] = []

        # Layer 1: Base identity (always present)
        identity_content = self._base_identity
        if self._language_hint:
            identity_content += f"\n\n{self._language_hint}"
        layers.append(PromptLayer(name="identity", content=identity_content, priority=50))

        # Layer 2: Memory injection
        if self._memory_block:
            layers.append(PromptLayer(
                name="memory",
                content=self._memory_block,
                priority=100,
            ))

        # Layer 3: Tool descriptions
        if self._tool_summaries:
            tool_content = self._build_tool_section()
            if tool_content:
                layers.append(PromptLayer(name="tools", content=tool_content, priority=30))

        # Layer 4: Workspace context
        if self._workspace_root:
            ws_content = f"Current workspace: {self._workspace_root}"
            if self._lane_id:
                ws_content += f"\nActive lane: {self._lane_id}"
            layers.append(PromptLayer(name="workspace", content=ws_content, priority=20))

        # Layer 5: Extra layers
        layers.extend(self._extra_layers)

        # Layer 6: Append system prompt (always last)
        if self._append_system_prompt:
            layers.append(PromptLayer(
                name="append",
                content=self._append_system_prompt,
                priority=0,
            ))

        # Sort by priority (descending) and assemble
        layers.sort(key=lambda l: -l.priority)

        parts = [l.content for l in layers if l.content.strip()]
        return "\n\n".join(parts)

    def _build_tool_section(self) -> str:
        """Build tool summary section"""
        if not self._tool_summaries:
            return ""

        lines = ["Available tools:"]
        for tool in self._tool_summaries:
            name = tool.get("name", "unknown")
            desc = tool.get("description", "")
            # Truncate description
            if len(desc) > 200:
                desc = desc[:197] + "..."
            lines.append(f"- {name}: {desc}")

        return "\n".join(lines)

    def preview(self) -> str:
        """Preview the assembled prompt structure (for debugging)"""
        layers: List[PromptLayer] = []
        layers.append(PromptLayer(name="identity", content="[identity]", priority=50))
        if self._memory_block:
            layers.append(PromptLayer(name="memory", content=f"[memory: {len(self._memory_block)} chars]", priority=100))
        if self._tool_summaries:
            layers.append(PromptLayer(name="tools", content=f"[tools: {len(self._tool_summaries)} tools]", priority=30))
        if self._workspace_root:
            layers.append(PromptLayer(name="workspace", content=f"[workspace: {self._workspace_root}]", priority=20))
        layers.extend(self._extra_layers)
        if self._append_system_prompt:
            layers.append(PromptLayer(name="append", content="[append]", priority=0))

        layers.sort(key=lambda l: -l.priority)
        return " → ".join(l.name for l in layers)
