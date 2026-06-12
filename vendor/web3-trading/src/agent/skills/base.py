# -*- coding: utf-8 -*-
"""
Base Skill class for Agent Skills

All skills should inherit from this base class.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict
import logging

logger = logging.getLogger(__name__)


class BaseSkill(ABC):
    """
    Agent Skill Base Class
    
    Skills are atomic capability components that can be composed
    into different workflows using LangGraph.
    
    Each skill should:
    - Have a unique name
    - Implement the execute method
    - Accept a state dict and return an updated state dict
    """
    name: str = "base_skill"
    description: str = ""
    
    @abstractmethod
    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the skill.
        
        Args:
            state: Current workflow state
            
        Returns:
            Updated workflow state
        """
        pass
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name={self.name})>"
