# -*- coding: utf-8 -*-
"""
Runtime — Unified Agent Runtime Layer.

Provides the core abstractions for the agentic conversation loop:
- Protocols (LLMClient, ToolExecutor, PermissionPrompter)
- ConversationRuntime (ReAct loop engine)
- Session + Compaction (with 4-layer priority)
- PermissionResolver (Sprint 6 V2 single-lattice — see runtime.policy.permission)
- HookRunner (Pre/Post tool-use middleware)
- PolicyEngine (declarative rule engine)
- RecoveryEngine (one-shot auto-recovery)
- LaneManager + TaskPacket (parallel execution tracks)
- WorkspaceManager (filesystem isolation)
- SystemPromptBuilder (dynamic prompt assembly)
"""

from vendor_runtime_sdk.runtime.protocols import (
    LLMClient,
    ToolExecutor,
    PermissionPrompter,
    AssistantEvent,
    ToolResult,
    TurnSummary,
    PermissionRequest,
    PermissionDecision,
)

__all__ = [
    # Protocols
    "LLMClient",
    "ToolExecutor",
    "PermissionPrompter",
    "AssistantEvent",
    "ToolResult",
    "TurnSummary",
    "PermissionRequest",
    "PermissionDecision",
    # Modules (import as needed):
    #   runtime.conversation  → ConversationRuntime
    #   runtime.session       → Session, SessionJournal, CompactionResult
    #   runtime.hooks         → HookRunner, PreToolUseHook, PostToolUseHook
    #   runtime.policy        → PermissionResolver + PermissionMode (V2)
    #   runtime.policy_engine → PolicyEngine, PolicyRule, ActionType
    #   runtime.recovery      → RecoveryEngine, RecoveryRecipe, RecoveryResult
    #   runtime.lane          → LaneManager, Lane, LaneState, LaneResult
    #   runtime.task_packet   → TaskPacket, ValidatedPacket, create_simple_packet
    #   runtime.workspace     → WorkspaceManager, WorkspaceInfo,
    #                            get_workspace_manager, set_workspace_manager
    #   runtime.prompt_builder → SystemPromptBuilder, PromptLayer
    #   runtime.session_compaction → compact_session, BlockPriority
]
