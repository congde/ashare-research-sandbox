# -*- coding: utf-8 -*-
"""
Agent Skills Module

This module contains reusable skill components for agent workflows.
Skills are atomic capabilities that can be composed in different workflows.
"""

# Use lazy imports to avoid circular dependencies
def __getattr__(name):
    if name == "BaseSkill":
        from agent.skills.base import BaseSkill
        return BaseSkill
    elif name == "MCPToolCallSkill":
        from agent.skills.tool_call import MCPToolCallSkill
        return MCPToolCallSkill
    elif name == "LLMGenerateSkill":
        from agent.skills.llm_generate import LLMGenerateSkill
        return LLMGenerateSkill
    elif name == "CallbackSkill":
        from agent.skills.callback import CallbackSkill
        return CallbackSkill
    elif name == "SkillRegistry":
        from agent.skills.registry import SkillRegistry
        return SkillRegistry
    elif name == "BaseWorkflowState":
        from agent.skills.workflow import BaseWorkflowState
        return BaseWorkflowState
    elif name == "WorkflowBuilder":
        from agent.skills.workflow import WorkflowBuilder
        return WorkflowBuilder
    elif name == "WorkflowRunner":
        from agent.skills.workflow import WorkflowRunner
        return WorkflowRunner
    elif name == "create_plan_execute_synthesize_workflow":
        from agent.skills.workflow import create_plan_execute_synthesize_workflow
        return create_plan_execute_synthesize_workflow
    elif name == "create_conditional_workflow":
        from agent.skills.workflow import create_conditional_workflow
        return create_conditional_workflow
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "BaseSkill",
    "MCPToolCallSkill",
    "LLMGenerateSkill",
    "CallbackSkill",
    "SkillRegistry",
    "BaseWorkflowState",
    "WorkflowBuilder",
    "WorkflowRunner",
    "create_plan_execute_synthesize_workflow",
    "create_conditional_workflow",
]
