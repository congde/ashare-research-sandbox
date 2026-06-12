# -*- coding: utf-8 -*-
"""
Gateway — Management and command center for agent dispatch.

The Gateway is the single entry point that:
0. Pre-filters messages (FastFilter: dedup, rate-limit, greeting detect)
1. Routes messages to the appropriate Agent (via Router)
2. Loads / creates the Agent session (Session Store)
3. Injects available skills into the Agent (Skills Injector)
4. Builds and injects a scoped ToolRegistry (Tool Policy)
5. Returns a fully configured Agent ready to execute
"""

import logging
from typing import Any, Callable, Dict, Optional

from agent.plan.fast_filter import FastFilter, FilterResult
from agent.plan.router import Router, RouteResult
from agent.plan.tool_policy import ToolPolicy
from agent.skills.registry import SkillRegistry
from agent.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class Gateway:
    """
    Command center: filter, route, inject skills & tools, then dispatch to Agent.

    Usage:
        gateway = Gateway()
        fr = await gateway.pre_filter(query, session_id, user_id)
        if fr.action != "proceed":
            ...  # reject / dedup
        agent = await gateway.dispatch(fr.query, user_id, session_id, extra_body=extra,
                                       agent_type_hint="QUICK_REASONING")
        async for event in agent.run():
            ...
    """

    def __init__(
        self,
        llm=None,
        model_name: str = "",
        skill_registry: Optional[SkillRegistry] = None,
        tool_policy: Optional[ToolPolicy] = None,
        fast_filter: Optional[FastFilter] = None,
        router_extra_body: Optional[Dict] = None,
        router_timeout: float = 15.0,
    ):
        self._llm = llm
        self._model_name = model_name
        self._skill_registry = skill_registry or SkillRegistry()
        self._tool_policy = tool_policy or ToolPolicy()
        self._fast_filter = fast_filter or FastFilter()
        self._router: Optional[Router] = None
        self._router_extra_body = router_extra_body
        self._router_timeout = router_timeout

    @property
    def router(self) -> Router:
        if self._router is None:
            if not self._llm:
                from llm.base import create_llm
                self._llm, self._model_name = create_llm()
                logger.info("Gateway: lazily initialized LLM for Router")
            self._router = Router(
                llm=self._llm,
                model_name=self._model_name,
                extra_body=self._router_extra_body,
                timeout=self._router_timeout,
            )
        return self._router

    @property
    def skill_registry(self) -> SkillRegistry:
        return self._skill_registry

    @property
    def tool_policy(self) -> ToolPolicy:
        return self._tool_policy

    def configure_llm(self, llm, model_name: str, extra_body: Optional[Dict] = None) -> None:
        """Reconfigure the LLM used by the Router (e.g. after startup)."""
        self._llm = llm
        self._model_name = model_name
        self._router_extra_body = extra_body
        self._router = None

    # ----------------------------------------------------------
    # Main dispatch pipeline
    # ----------------------------------------------------------

    async def dispatch(
        self,
        query: str,
        user_id: str,
        session_id: str,
        extra_body=None,
        agent_type_hint: Optional[str] = None,
        metadata: Optional[Dict] = None,
        **kwargs,
    ):
        """
        Full Gateway dispatch pipeline.

        1. Route: classify intent -> AgentType (or use hint)
        2. Session: load/create session (delegated to the Agent for now)
        3. Skills: determine which skills this agent type needs
        4. Tools: determine which tools this agent type can use
        5. Instantiate and configure the Agent

        Args:
            query: User query text.
            user_id: User identifier.
            session_id: Session identifier.
            extra_body: ExtraBodyModel from the web layer.
            agent_type_hint: If provided, skip routing and use this type directly.
            metadata: Additional metadata (e.g. eventId).
            **kwargs: Forwarded to the Agent constructor.

        Returns:
            A fully configured BaseAgent instance (not yet executed).
        """
        from agent import ALL_AGENTS
        from agent.schema import AgentType

        # 1. Route
        if agent_type_hint:
            route_result = RouteResult(
                agent_type=agent_type_hint,
                needs_tools=True,
                confidence=1.0,
                reasoning="agent_type_hint provided",
            )
        else:
            history_messages = kwargs.get("history_messages")
            route_result = await self.router.route(
                query=query,
                history=history_messages,
                metadata=metadata,
            )

        agent_type_str = route_result.agent_type
        logger.info(
            f"Gateway.dispatch: agent_type={agent_type_str}, "
            f"needs_tools={route_result.needs_tools}, "
            f"confidence={route_result.confidence}"
        )

        # 2. Resolve Agent class
        try:
            agent_type_enum = AgentType(agent_type_str)
        except ValueError:
            agent_type_enum = AgentType.QUICK_REASONING

        AgentClass = ALL_AGENTS.get(agent_type_enum)
        if not AgentClass:
            logger.warning(f"No agent registered for {agent_type_str}, falling back to QUICK_REASONING")
            AgentClass = ALL_AGENTS.get(AgentType.QUICK_REASONING)

        # 3. Skills: get per-agent skills
        skills = self._skill_registry.get_skills_for(agent_type_str)

        # 4. Tools: build scoped registry
        tools_info = await self._fetch_tools_info()
        context_provider = kwargs.pop("context_provider", None)
        tool_registry = self._tool_policy.build_registry(
            agent_type=agent_type_str,
            tools_info=tools_info,
            context_provider=context_provider,
        )

        # 5. Instantiate Agent
        agent = AgentClass(
            query=query,
            extra_body=extra_body,
            user_id=user_id,
            session_id=session_id,
            **kwargs,
        )

        # 6. Inject tools & skills
        agent.inject_tools(tool_registry)
        agent.inject_skills(skills)

        # Store route result on agent for downstream use
        agent._gateway_route_result = route_result

        return agent

    # ----------------------------------------------------------
    # Pre-filter (step 0 — before dispatch)
    # ----------------------------------------------------------

    async def pre_filter(
        self,
        query: str,
        session_id: str,
        user_id: str,
    ) -> FilterResult:
        """Run FastFilter checks (normalise, dedup, rate-limit, greeting detect).

        Returns FilterResult.  Caller should only proceed to dispatch()
        when ``result.action == "proceed"``.
        """
        result = await self._fast_filter.check(query, session_id, user_id)
        if result.action != "proceed":
            logger.info(
                f"Gateway.pre_filter: blocked — action={result.action}, "
                f"reason={result.reason}, session={session_id}"
            )
        return result

    async def route_only(
        self,
        query: str,
        history: Optional[list] = None,
        metadata: Optional[Dict] = None,
    ) -> RouteResult:
        """Run only the routing step without full dispatch."""
        return await self.router.route(query=query, history=history, metadata=metadata)

    # ----------------------------------------------------------
    # Internal helpers
    # ----------------------------------------------------------

    @staticmethod
    async def _fetch_tools_info():
        from mcp.mcp_http_client import mcp_client
        try:
            return await mcp_client.get_tools_info()
        except Exception as e:
            logger.warning(f"Gateway: failed to fetch MCP tools: {e}")
            return None


__all__ = ["Gateway"]
