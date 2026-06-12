"""
4-tier Budget Pressure Injection (§5.8)

Injects budget-awareness messages into the conversation based on
iteration progress relative to max_iterations.

Injection strategy:
  • Pressure warning is embedded into the LAST tool result's JSON content
    (not as a standalone message) so it does not break message structure
    or disrupt Anthropic prompt cache.
  • Old budget warnings are stripped at turn start by warning.py.

Thresholds (fraction of max_iterations consumed):
  low      50% — informational nudge
  medium   70% — suggest converging
  high     90% — urgent, finish soon
  critical 95% — must respond immediately
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Marker embedded in tool result content so warning.py can strip it later
BUDGET_MARKER_KEY = "__budget_pressure__"


@dataclass(frozen=True)
class PressureLevel:
    name: str
    threshold: float  # fraction of max_iterations


_LEVELS: tuple[PressureLevel, ...] = (
    PressureLevel("critical", 0.95),
    PressureLevel("high", 0.90),
    PressureLevel("medium", 0.70),
    PressureLevel("low", 0.50),
)

_MESSAGES: dict[str, str] = {
    "low": (
        "<budget_warning level='low'>"
        "You have used about half of your available steps. "
        "Consider whether you can start wrapping up."
        "</budget_warning>"
    ),
    "medium": (
        "<budget_warning level='medium'>"
        "You are using 70% of your available steps. "
        "Start converging toward a final answer now."
        "</budget_warning>"
    ),
    "high": (
        "<budget_warning level='high'>"
        "URGENT: 90% of steps consumed. "
        "Complete your final answer in the next 1–2 steps."
        "</budget_warning>"
    ),
    "critical": (
        "<budget_warning level='critical'>"
        "CRITICAL: Steps nearly exhausted. "
        "Respond with your best answer immediately — no more tool calls."
        "</budget_warning>"
    ),
}


class BudgetPressure:
    """
    Tracks iteration progress and determines whether a pressure warning
    should be injected this step.

    Usage::

        pressure = BudgetPressure(max_iterations=10)

        # In the ReAct loop, after executing tools:
        warning_text = pressure.get_pressure(current_iteration=7)
        if warning_text:
            inject_into_last_tool_result(messages, warning_text)
    """

    def __init__(self, max_iterations: int):
        if max_iterations <= 0:
            raise ValueError(f"max_iterations must be > 0, got {max_iterations}")
        self._max = max_iterations
        self._last_injected_level: Optional[str] = None

    def get_pressure(self, current_iteration: int) -> Optional[str]:
        """
        Return the pressure warning text for *current_iteration*, or None.

        Each level is emitted at most once per turn (monotone — once we've
        emitted "high", we won't re-emit "medium").

        Parameters
        ----------
        current_iteration : int
            1-based iteration counter (1 = first LLM call this turn).
        """
        progress = current_iteration / self._max

        for level in _LEVELS:
            if progress >= level.threshold:
                # Skip if we already emitted this severity or higher
                current_idx = self._level_index(level.name)
                if self._last_injected_level is not None:
                    last_idx = self._level_index(self._last_injected_level)
                    if current_idx <= last_idx:
                        return None
                self._last_injected_level = level.name
                return _MESSAGES[level.name]

        return None

    def reset(self) -> None:
        """Reset injection state at the start of a new turn."""
        self._last_injected_level = None

    @staticmethod
    def _level_index(name: str) -> int:
        """Higher index = higher severity."""
        order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        return order.get(name, -1)

    @property
    def max_iterations(self) -> int:
        return self._max


def inject_into_last_tool_result(
    messages: list[dict],
    warning_text: str,
) -> bool:
    """
    Embed *warning_text* into the last tool-role message in *messages*.

    The warning is appended to the ``content`` field with a sentinel key so
    ``strip_budget_warnings`` can find and remove it later.

    Strategy:
      • If content is a JSON string with a dict at the top level → merge key
      • Otherwise → append the warning text as a string suffix

    Returns
    -------
    bool
        True if injection succeeded, False if no tool result was found.
    """
    # Find the last tool message (role == "tool")
    last_tool_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "tool":
            last_tool_idx = i
            break

    if last_tool_idx == -1:
        logger.debug("inject_into_last_tool_result: no tool message found")
        return False

    msg = messages[last_tool_idx]
    original_content = msg.get("content", "")

    # Try to merge into JSON dict
    try:
        parsed = json.loads(original_content) if isinstance(original_content, str) else original_content
        if isinstance(parsed, dict):
            parsed[BUDGET_MARKER_KEY] = warning_text
            messages[last_tool_idx] = dict(msg, content=json.dumps(parsed, ensure_ascii=False))
            return True
    except (json.JSONDecodeError, TypeError):
        pass

    # Fallback: string append with sentinel wrapper
    injected = str(original_content) + f"\n\n{BUDGET_MARKER_KEY}:{warning_text}"
    messages[last_tool_idx] = dict(msg, content=injected)
    return True
