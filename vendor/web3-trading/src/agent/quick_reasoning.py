import logging

from agent.plan.orchestrator_agent import OrchestratorAgent
from agent.schema import AgentType

logger = logging.getLogger(__name__)


class QuickReasoningAgent(OrchestratorAgent):
    """QUICK_REASONING — Plan mode, no deep-think panel, no delegation.

    Inherits the full Plan → DAG Execute → Response pipeline from
    OrchestratorAgent.  Policy overrides:
        - _DELEGATABLE_AGENTS = set()   → never delegates to another agent
        - _resolve_enable_think → False → deep-think panel always off
    """
    NAME = AgentType.QUICK_REASONING
    _DELEGATABLE_AGENTS = set()

    def _resolve_enable_think(self, route_agent_type: str) -> bool:
        return False
