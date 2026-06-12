import logging

from agent.plan.orchestrator_agent import OrchestratorAgent
from agent.schema import AgentType

logger = logging.getLogger(__name__)


class EventDeliveryAgent(OrchestratorAgent):
    """EVENT_DELIVERY — Plan mode, no deep-think panel, no delegation.

    Identical policy to QuickReasoningAgent; separated as a distinct
    AgentType so the routing layer can track event-triggered conversations.
    """
    NAME = AgentType.EVENT_DELIVERY
    _DELEGATABLE_AGENTS = set()

    def _resolve_enable_think(self, route_agent_type: str) -> bool:
        return False
