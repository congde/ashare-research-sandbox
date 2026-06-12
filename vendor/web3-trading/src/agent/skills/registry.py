# -*- coding: utf-8 -*-
"""
Skill Registry — central registry for agent skills with per-agent-type awareness.

Skills are callable async functions: (args: dict) -> str | dict.
The registry supports both global skills (available to all agents) and
per-agent-type skill mappings managed by the Gateway.
"""

import logging
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class SkillRegistry:
    """
    Registry for skill packages with agent-type scoping.

    Two layers:
    - Global skills: available to all agent types via register() / get() / execute()
    - Agent-scoped skills: per-agent-type mappings via register_for_agent() / get_skills_for()
    """

    def __init__(self):
        self._skills: Dict[str, Callable] = {}
        self._agent_skills: Dict[str, Dict[str, Callable]] = {}

    # ----------------------------------------------------------
    # Global skill operations
    # ----------------------------------------------------------

    def register(self, name: str, skill: Callable) -> None:
        """Register a global skill by name."""
        self._skills[name] = skill
        logger.debug(f"Registered global skill: {name}")

    def get(self, name: str) -> Optional[Callable]:
        """Get a global skill by name."""
        return self._skills.get(name)

    def has(self, name: str) -> bool:
        """Check if a global skill is registered."""
        return name in self._skills

    async def execute(self, name: str, arguments: Dict[str, Any]) -> Any:
        """
        Execute a global skill by name.

        Raises:
            ValueError: If skill not found
        """
        skill = self._skills.get(name)
        if not skill:
            raise ValueError(f"Skill '{name}' not found. Available: {list(self._skills.keys())}")
        return await skill(arguments)

    @property
    def skill_names(self) -> list:
        """Get all global skill names."""
        return list(self._skills.keys())

    # ----------------------------------------------------------
    # Agent-scoped skill operations
    # ----------------------------------------------------------

    def register_for_agent(self, agent_type: str, skill_name: str, skill: Callable) -> None:
        """
        Register a skill for a specific agent type.

        Args:
            agent_type: AgentType string (e.g. "QUICK_REASONING")
            skill_name: Unique skill name within the agent scope
            skill: Async callable implementing the skill
        """
        if agent_type not in self._agent_skills:
            self._agent_skills[agent_type] = {}
        self._agent_skills[agent_type][skill_name] = skill
        logger.debug(f"Registered skill '{skill_name}' for agent type '{agent_type}'")

    def get_skills_for(self, agent_type: str) -> Dict[str, Callable]:
        """
        Return all skills available for a given agent type.

        Merges global skills with agent-specific skills.
        Agent-specific skills override globals of the same name.
        """
        merged = dict(self._skills)
        agent_specific = self._agent_skills.get(agent_type, {})
        merged.update(agent_specific)
        return merged

    def get_agent_skill_names(self, agent_type: str) -> List[str]:
        """Get skill names registered specifically for an agent type."""
        return list(self._agent_skills.get(agent_type, {}).keys())

    @property
    def registered_agent_types(self) -> List[str]:
        """Get all agent types that have specific skill registrations."""
        return list(self._agent_skills.keys())
