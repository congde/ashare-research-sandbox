# -*- coding: utf-8 -*-
"""
Router — Lightweight LLM-based intent classifier.

Determines which AgentType should handle a user query and whether
external tool calls are needed. This is the first step in the Gateway
dispatch pipeline.
"""

import json
import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


ROUTE_SYSTEM_PROMPT = """\
You are an intent classifier for an AI crypto assistant.
Given a user query, decide which agent type should handle it.

Available agent types:
- QUICK_REASONING: General questions, greetings, simple factual queries, chitchat, \
market price checks, basic calculations, how-to questions. This is the default.
- DEEP_THINK: Complex analytical questions requiring deep reasoning with tool usage. \
Questions that need multi-step analysis, comparison of multiple data sources, \
or nuanced financial/technical analysis.
- DEEP_RESEARCH: Requests for comprehensive research reports, in-depth investigation \
of a topic, extensive multi-source analysis. Typically the user explicitly asks for \
"deep research", "detailed report", "comprehensive analysis" etc.
- EVENT_DELIVERY: System-initiated event notifications pushed to users. Only used \
when the query originates from an event trigger (eventId present in metadata).

Also determine whether the query requires external tool calls:
- needs_tools=true: query needs real-time data, search, lookups, or any external information
- needs_tools=false: query can be answered from general knowledge alone (greetings, \
chitchat, basic factual knowledge, explanations, how-to)

Rules:
1. If the query is a simple greeting, chitchat, or factual question → QUICK_REASONING, needs_tools=false
2. If the query asks for real-time prices, market data, search → needs_tools=true
3. If the query needs tool calls + analytical thinking → DEEP_THINK, needs_tools=true
4. If the query explicitly requests a report / deep research → DEEP_RESEARCH, needs_tools=true
5. Default to QUICK_REASONING when uncertain.
6. Respond with ONLY a JSON object, no extra text.

Output format (strict JSON):
{"agent_type": "<QUICK_REASONING|DEEP_THINK|DEEP_RESEARCH>", "needs_tools": <true|false>, "confidence": <0.0-1.0>, "reasoning": "<brief>"}
"""


@dataclass
class RouteResult:
    """Result of intent classification."""
    agent_type: str = "QUICK_REASONING"
    needs_tools: bool = True
    confidence: float = 0.5
    reasoning: str = ""
    elapsed_ms: int = 0


class Router:
    """
    Lightweight intent classifier: query -> RouteResult.

    Used by the Gateway to determine which Agent should handle a request
    before any tool catalogues are loaded (cheap LLM call).
    """

    def __init__(self, llm, model_name: str, extra_body: Optional[Dict] = None, timeout: float = 15.0):
        self.llm = llm
        self.model_name = model_name
        self.extra_body = extra_body
        self.timeout = timeout

    async def route(
        self,
        query: str,
        history: Optional[List[Dict]] = None,
        metadata: Optional[Dict] = None,
    ) -> RouteResult:
        """
        Classify the user query into an AgentType.

        Args:
            query: User query text.
            history: Optional conversation history (list of {role, content} dicts).
            metadata: Optional metadata (e.g. eventId for EVENT_DELIVERY).

        Returns:
            RouteResult with agent_type, needs_tools, confidence, reasoning.
        """
        metadata = metadata or {}

        if metadata.get("eventId"):
            return RouteResult(
                agent_type="EVENT_DELIVERY",
                needs_tools=True,
                confidence=1.0,
                reasoning="eventId present in metadata",
                elapsed_ms=0,
            )

        start = time.time()
        messages = [
            {"role": "system", "content": ROUTE_SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ]

        try:
            response = await self.llm.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=0.1,
                max_tokens=200,
                timeout=self.timeout,
                **({"extra_body": self.extra_body} if self.extra_body else {}),
            )
            content = response.choices[0].message.content or ""
            result = self._parse_json(content)
            agent_type = result.get("agent_type", "QUICK_REASONING")
            needs_tools = result.get("needs_tools", True)
            confidence = result.get("confidence", 0.5)
            reasoning = result.get("reasoning", "")
        except Exception as e:
            logger.warning(f"Router LLM call failed: {e}, defaulting to QUICK_REASONING")
            agent_type = "QUICK_REASONING"
            needs_tools = True
            confidence = 0.0
            reasoning = f"fallback due to error: {e}"

        elapsed = int((time.time() - start) * 1000)
        logger.info(
            f"Router.route: agent_type={agent_type}, needs_tools={needs_tools}, "
            f"confidence={confidence}, elapsed={elapsed}ms, reasoning={reasoning}"
        )

        return RouteResult(
            agent_type=agent_type,
            needs_tools=needs_tools,
            confidence=confidence,
            reasoning=reasoning,
            elapsed_ms=elapsed,
        )

    @staticmethod
    def _parse_json(text: str) -> Dict:
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end])
                except json.JSONDecodeError:
                    pass
        logger.warning(f"Failed to parse router JSON: {text[:200]}")
        return {}


__all__ = ["Router", "RouteResult", "ROUTE_SYSTEM_PROMPT"]
