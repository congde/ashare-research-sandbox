# -*- coding: utf-8 -*-
"""
Token Budget — estimation and budget management for context windows.

Uses a fast heuristic (no tiktoken dependency) that is good enough
for budget planning without adding heavy dependencies.
"""

import logging
from dataclasses import dataclass
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


def estimate_tokens(text: str) -> int:
    """
    Fast heuristic token estimation.

    CJK characters average ~1.5 chars/token; Latin text ~4 chars/token.
    Mixed text uses a weighted average.
    """
    if not text:
        return 0
    cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff'
              or '\u3040' <= c <= '\u309f'
              or '\u30a0' <= c <= '\u30ff'
              or '\uac00' <= c <= '\ud7af')
    other = len(text) - cjk
    return int(cjk / 1.5 + other / 4)


def estimate_messages_tokens(messages: List[Dict[str, str]]) -> int:
    """Estimate total tokens for a list of chat messages."""
    total = 0
    for msg in messages:
        total += 4  # role/separator overhead per message
        total += estimate_tokens(msg.get("content", ""))
    return total


@dataclass
class TokenBudget:
    """
    Manages token budget for a single LLM call.

    Given the model's context window and reservations, calculates
    how much budget remains for conversation history.
    """
    model_context_window: int = 32000
    reserved_for_output: int = 8000
    reserved_for_system: int = 4000

    @property
    def total_available(self) -> int:
        return self.model_context_window - self.reserved_for_output

    def history_budget(
        self,
        system_prompt_tokens: int = 0,
        tools_result_tokens: int = 0,
        current_query_tokens: int = 0,
    ) -> int:
        """
        Calculate remaining token budget for history/context.

        Subtracts system prompt, tools result, and current query
        from total available budget.
        """
        used = system_prompt_tokens + tools_result_tokens + current_query_tokens
        remaining = self.total_available - used
        return max(remaining, 0)

    def check(
        self,
        history_tokens: int,
        system_prompt_tokens: int = 0,
        tools_result_tokens: int = 0,
        current_query_tokens: int = 0,
    ) -> "BudgetCheckResult":
        """
        Pre-check whether the proposed context fits the budget.

        Returns a BudgetCheckResult with the verdict and details.
        """
        budget = self.history_budget(
            system_prompt_tokens, tools_result_tokens, current_query_tokens
        )
        over = history_tokens - budget
        return BudgetCheckResult(
            fits=over <= 0,
            budget=budget,
            requested=history_tokens,
            overflow=max(over, 0),
        )

    @classmethod
    def from_config(cls, config_obj) -> "TokenBudget":
        """Load from application config with safe defaults."""
        try:
            ctx = getattr(config_obj, "context", None)
            if ctx is None:
                return cls()
            return cls(
                model_context_window=int(getattr(ctx, "model_context_window", 32000)),
                reserved_for_output=int(getattr(ctx, "reserved_for_output", 8000)),
                reserved_for_system=int(getattr(ctx, "reserved_for_system", 4000)),
            )
        except Exception as e:
            logger.warning(f"TokenBudget config load failed, using defaults: {e}")
            return cls()


@dataclass
class BudgetCheckResult:
    fits: bool
    budget: int
    requested: int
    overflow: int

    def __str__(self):
        if self.fits:
            return f"OK: {self.requested}/{self.budget} tokens"
        return f"OVER: {self.requested}/{self.budget} tokens (overflow={self.overflow})"
