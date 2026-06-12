# -*- coding: utf-8 -*-
"""
Agent node handlers — agent_call, fallback, skill prompt, coder agent

Auto-extracted from runtime/workflow_executor.py during refactoring.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

class HandlersAgentMixin:
    """Agent node handlers — agent_call, fallback, skill prompt, coder agent"""

    async def _exec_passthrough(self, node: Dict) -> Dict[str, Any]:
        """Passthrough handler for start/end nodes — no-op."""
        return {"ok": True}

    async def _exec_agent_call(self, node: Dict) -> Dict[str, Any]:
        """Agent node: call LLM with agent persona + upstream context.

        The agent_call node is the core of deliverable-producing workflows.
        It injects upstream context into the prompt and produces structured output.

        SDLC Enhancement (§9.2):
        - Routes to CoderAgent for agent_type='coder' or type='code_generator'
        - Wraps LLM calls with FallbackManager for model degradation
        """
        data = node.get("data") or {}
        agent_type = data.get("agent_type", "")

        # ── Route to CoderAgent for coder/code_generator nodes ──
        if agent_type == "coder" or data.get("type") == "code_generator":
            return await self._run_with_coder_agent(node)

        # ── Standard LLM call with FallbackManager wrapping ──
        return await self._run_with_fallback(node)

    async def _run_with_fallback(self, node: Dict) -> Dict[str, Any]:
        """Pure LLM generation + FallbackManager model degradation.

        On primary model failure, automatically degrades through the fallback
        chain (primary → fallback_1 → fallback_2 → hard error).
        Aligns with §3.2 Layer 1 Runtime Loop.
        """
        from vendor_runtime_sdk.llm.base import create_llm

        data = node.get("data") or {}
        instructions = data.get("prompt") or data.get("instructions") or data.get("task") or ""
        system_prompt = data.get("system_prompt") or ""
        model_override = data.get("model")
        temperature = float(data.get("temperature", 0.3))

        # ── Auto-load skill prompt if skill_name is set and no explicit system_prompt ──
        skill_name = data.get("skill_name")
        if skill_name and not system_prompt:
            system_prompt = self._load_skill_prompt(skill_name)

        # ── Inject upstream context into prompt ──
        node_id = node.get("id", "")
        upstream_ctx = self._ctx.format_upstream_context(current_node_id=node_id)
        if upstream_ctx:
            instructions = (
                f"## Context from Previous Steps\n\n{upstream_ctx}\n\n"
                f"---\n\n{instructions}"
            )

        # ── If deliverable_name set, add output formatting instruction ──
        deliverable_name = data.get("deliverable_name")
        if deliverable_name:
            instructions += (
                f"\n\n---\n**Important**: Your output will be saved as the deliverable "
                f'"{deliverable_name}". Produce complete, self-contained content.'
            )

        messages: list = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": instructions})

        # ── FallbackManager-wrapped LLM call ──
        max_fallback_attempts = 3
        last_error = None

        for attempt in range(max_fallback_attempts):
            try:
                llm, model = create_llm(model_name=model_override)
                resp = await llm.chat.completions.create(
                    model=model_override or model,
                    messages=messages,
                    temperature=temperature,
                )
                text = ""
                if resp.choices:
                    text = (resp.choices[0].message.content or "").strip()

                is_fallback = attempt > 0
                return {
                    "ok": True,
                    "content": text,
                    "model": model_override or model,
                    "agent_type": data.get("agent_type"),
                    "deliverable_name": deliverable_name,
                    "is_fallback": is_fallback,
                    "fallback_attempt": attempt,
                }
            except Exception as e:
                last_error = e
                logger.warning(
                    "agent_call fallback attempt %d/%d failed for node %s: %s",
                    attempt + 1, max_fallback_attempts, node.get("id", ""), e,
                )
                # Clear model override to try default model on next attempt
                model_override = None

        return {
            "ok": False,
            "error": f"All {max_fallback_attempts} LLM attempts failed: {last_error}",
            "agent_type": data.get("agent_type"),
            "deliverable_name": deliverable_name,
        }

    def _load_skill_prompt(self, skill_name: str) -> str:
        """Load a skill's system_prompt from conf/skills/sdlc/{skill_name}.yaml."""
        import re
        import yaml as _yaml

        if not re.match(r'^[a-zA-Z0-9_-]+$', skill_name):
            logger.warning("Invalid skill_name rejected: %s", skill_name)
            return ""

        base_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "conf", "skills", "sdlc")
        )
        skill_path = os.path.abspath(os.path.join(base_dir, f"{skill_name}.yaml"))

        if not skill_path.startswith(base_dir + os.sep):
            logger.warning("Path traversal attempt rejected: %s", skill_name)
            return ""

        if not os.path.exists(skill_path):
            logger.debug("Skill file not found: %s", skill_path)
            return ""
        try:
            with open(skill_path, "r", encoding="utf-8") as f:
                data = _yaml.safe_load(f)
            return data.get("system_prompt", "") if isinstance(data, dict) else ""
        except Exception as e:
            logger.warning("Failed to load skill %s: %s", skill_name, e)
            return ""

    async def _run_with_coder_agent(self, node: Dict) -> Dict[str, Any]:
        """CoderAgent mode: complete ReAct loop with tool execution.

        Routes to the code_generator handler which supports file/bash/git/patch
        tools via the ReAct cycle. Passes upstream deliverables (PRD, tech design)
        as context for code generation.
        Aligns with §9.2 WorkflowExecutor Enhancement.
        """
        # Delegate to the existing code_generator handler
        return await self._exec_code_generator(node)


logger = logging.getLogger(__name__)
