# -*- coding: utf-8 -*-
"""
ContextProbe — context-length probing for the ConversationRuntime (§5.3 / §5.12).

Two complementary modes:

1. **Proactive probe** (§5.3): ``probe_context(messages, model_name)``
   Called before every LLM call. Estimates token usage from a static table and
   a safety factor. Aborts the turn with *context_overflow* if over limit.

2. **Reactive probe** (§5.12): error-driven dynamic discovery
   When the LLM API returns a context-length error, ``parse_context_limit_from_error``
   extracts the real limit, ``save_confirmed_limit`` caches it in-process, and
   ``get_next_probe_tier`` provides the next smaller tier for the compressor to
   target before retrying.

Tier ladder (§5.12): 200K → 128K → 64K → 32K → 16K
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Token estimation (local copy — avoids importing the agent package which
# pulls langgraph and other heavy deps unavailable in test environments)
# ---------------------------------------------------------------------------

def _estimate_messages_tokens(messages: List[Dict]) -> int:
    """
    Fast heuristic token estimation for a list of chat messages.

    Mirrors ``agent.context.token_budget.estimate_messages_tokens`` but kept
    local so this module remains import-free of the agent package.
    """

    def _text_tokens(text: str) -> int:
        if not text:
            return 0
        cjk = sum(
            1
            for c in text
            if "\u4e00" <= c <= "\u9fff"
            or "\u3040" <= c <= "\u309f"
            or "\u30a0" <= c <= "\u30ff"
            or "\uac00" <= c <= "\ud7af"
        )
        other = len(text) - cjk
        return int(cjk / 1.5 + other / 4)

    total = 0
    for msg in messages:
        total += 4  # role / separator overhead
        content = msg.get("content", "")
        if isinstance(content, str):
            total += _text_tokens(content)
        elif isinstance(content, list):  # multi-part content blocks
            for block in content:
                if isinstance(block, dict):
                    total += _text_tokens(block.get("text", ""))
    return total


# ---------------------------------------------------------------------------
# §5.12 Tier ladder — logically ordered largest → smallest
# ---------------------------------------------------------------------------

_PROBE_TIERS: List[int] = [200_000, 128_000, 64_000, 32_000, 16_000]

# In-process cache: "{model}:{base_url}" → confirmed context window (tokens).
# Populated from actual API error messages; survives for the lifetime of the
# process.  Reset on redeploy, which is correct because model deployments may
# change.
_confirmed_limits: Dict[str, int] = {}


def get_confirmed_limit(model: str, base_url: str = "") -> Optional[int]:
    """Return the runtime-confirmed context limit for *model*, or None."""
    return _confirmed_limits.get(f"{model}:{base_url}")


def save_confirmed_limit(model: str, base_url: str, limit: int) -> None:
    """Cache a confirmed context limit discovered from an API error response."""
    key = f"{model}:{base_url}"
    _confirmed_limits[key] = limit
    logger.info(
        "ContextProbe: confirmed limit %d for model=%s base_url=%s (cached for process lifetime)",
        limit, model or "unknown", base_url or "default",
    )


def get_next_probe_tier(current_limit: int) -> int:
    """
    Return the next smaller tier below *current_limit*.

    Used when the runtime detects a context-length error but cannot parse an
    exact limit from the error message — it falls back to the next lower tier.

    Example: current_limit=128_000 → returns 64_000.
    """
    for tier in _PROBE_TIERS:
        if tier < current_limit:
            return tier
    return _PROBE_TIERS[-1]  # already at minimum — return 16K


# ---------------------------------------------------------------------------
# §5.12 Reactive probe — error-driven detection
# ---------------------------------------------------------------------------

# Patterns used to extract the confirmed context window from API error text.
_LIMIT_PATTERNS = [
    r"maximum context length is (\d+)",
    r"context length.*?(\d{4,7})\s*token",
    r"limit is (\d{4,7})",
    r"max.*?token.*?(\d{4,7})",
    r"(\d{4,7})\s*token.*?limit",
    r"exceeds.*?limit.*?(\d{4,7})",
]

# Keywords that identify a context-length error (case-insensitive).
_CONTEXT_LENGTH_KEYWORDS = (
    "context_length_exceeded",
    "context length exceeded",
    "maximum context length",
    "too many tokens",
    "input is too long",
    "prompt is too long",
    "reduce the length",
    "tokens_exceeded",
)


def parse_context_limit_from_error(error_str: str) -> Optional[int]:
    """
    Extract the true context-window size from an API error message.

    Returns
    -------
    int or None
        The parsed token limit, or None if no numeric limit could be found.
    """
    for pattern in _LIMIT_PATTERNS:
        m = re.search(pattern, error_str, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                continue
    return None


def is_context_length_error(error: "Exception | str") -> bool:
    """Return True if *error* represents a context-window exceeded condition."""
    msg = str(error).lower()
    return any(kw in msg for kw in _CONTEXT_LENGTH_KEYWORDS)


# ---------------------------------------------------------------------------
# §5.3 Proactive probe — static table + confirmed-limit override
# ---------------------------------------------------------------------------

_MODEL_CONTEXT_WINDOWS: Dict[str, int] = {
    # Qwen family (KuCoin default LLM)
    "qwen3.5-27b": 32_768,
    "qwen2.5-72b": 131_072,
    "qwen2.5-32b": 131_072,
    "qwq-32b": 131_072,
    "qwen-turbo": 8_192,
    "qwen-plus": 131_072,
    "qwen-max": 32_768,
    # Anthropic Claude
    "claude-3-5-sonnet": 200_000,
    "claude-3-7-sonnet": 200_000,
    "claude-opus-4": 200_000,
    "claude-haiku": 200_000,
    # OpenAI
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "o1": 128_000,
    "o3-mini": 128_000,
    # DeepSeek
    "deepseek-chat": 65_536,
    "deepseek-r1": 65_536,
    # Zhipu GLM
    "glm-5.1": 128_000,
}

# Apply safety margin so the system prompt + output tokens always fit.
_SAFETY_FACTOR: float = 0.9

# Fallback when model is unknown and no confirmed limit has been cached.
_DEFAULT_CONTEXT_WINDOW: int = 32_000


def _lookup_context_window(model_name: str) -> int:
    """
    Return the context window for *model_name*.

    Priority: confirmed runtime limit > static table > default.
    """
    # 1. Prefer a limit confirmed from a real API error (§5.12)
    confirmed = get_confirmed_limit(model_name)
    if confirmed:
        return confirmed

    # 2. Static table — case-insensitive substring match
    key = (model_name or "").lower()
    for pattern, window in _MODEL_CONTEXT_WINDOWS.items():
        if pattern in key:
            return window

    return _DEFAULT_CONTEXT_WINDOW


@dataclass
class ProbeResult:
    """Outcome of a single context-length probe."""

    estimated_tokens: int
    context_window: int
    safe_limit: int  # = context_window * _SAFETY_FACTOR
    over_limit: bool
    utilization: float  # fraction of safe_limit consumed (0.0 – ∞)


def probe_context(
    messages: List[Dict],
    model_name: str = "",
    extra_tokens: int = 0,
) -> ProbeResult:
    """
    Estimate token usage and check against the model's context window.

    Parameters
    ----------
    messages : list[dict]
        Chat messages in OpenAI ``{role, content}`` format.
    model_name : str
        LLM model identifier.  Used for context-window lookup.
    extra_tokens : int
        Additional tokens to add to the estimate — pass the pre-calculated
        token count for the system prompt and tool schemas so the check
        accounts for the full request payload (§5.6).

    Returns
    -------
    ProbeResult
        Contains ``over_limit`` flag, token estimates, and utilization ratio.
    """
    estimated = _estimate_messages_tokens(messages) + extra_tokens
    window = _lookup_context_window(model_name)
    safe_limit = int(window * _SAFETY_FACTOR)
    over = estimated > safe_limit
    utilization = estimated / safe_limit if safe_limit > 0 else 0.0

    if over:
        logger.warning(
            "ContextProbe[%s]: %d tokens > safe limit %d (window=%d, %.1f%% used) — "
            "compaction or truncation recommended",
            model_name or "unknown",
            estimated,
            safe_limit,
            window,
            utilization * 100,
        )
    else:
        logger.debug(
            "ContextProbe[%s]: %d / %d tokens (%.1f%%)",
            model_name or "unknown",
            estimated,
            safe_limit,
            utilization * 100,
        )

    return ProbeResult(
        estimated_tokens=estimated,
        context_window=window,
        safe_limit=safe_limit,
        over_limit=over,
        utilization=utilization,
    )
