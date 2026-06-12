"""
ConversationRuntime — 核心 ReAct 循环 (§5.1)

Drives a single conversation turn: user message → [ReAct loop] → final response.
Composes all Phase 1 reliability capabilities:

  §5.2  Interruptible API calls + stale-stream detection
  §5.1  Preflight compression trigger
  §5.7  Turn-scoped fallback restore
  §5.1  Tool call self-repair + dedup
  §5.1  Budget warning stripping
  §5.8  4-tier budget pressure injection
  §5.4  Session FSM state management
  §5.11 Activity tracking
  §5.13 Plugin hooks (pre/post LLM call)
  §3.4  Module toggles (per-feature enable/disable)

This class is the integration point between the existing agent/ codebase
and the new runtime/ reliability layer.  It wraps AgentLoop and adds the
reliability guardrails defined in the technical spec.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import AsyncGenerator, List, Optional

from vendor_runtime_sdk.runtime.activity import ActivityTracker
from vendor_runtime_sdk.runtime.budget.pressure import BudgetPressure, inject_into_last_tool_result
from vendor_runtime_sdk.runtime.budget.warning import strip_budget_warnings
from vendor_runtime_sdk.runtime.config.toggles import ModuleToggles
from vendor_runtime_sdk.runtime.fallback.manager import (
    FallbackManager,
)
from vendor_runtime_sdk.runtime.hooks.base import HookContext, HookDispatcher
from vendor_runtime_sdk.runtime.session.fsm import IllegalTransitionError, SessionFSM, SessionState
from vendor_runtime_sdk.runtime.tools.dedup import deduplicate_tool_calls
from vendor_runtime_sdk.runtime.tools.repair import repair_tool_calls

logger = logging.getLogger(__name__)

# Stale-stream timeout: if no activity for this many seconds during an LLM call,
# attempt reconnect (§5.2 stale-stream detection)
STALE_STREAM_TIMEOUT: float = 60.0

# Maximum times to retry a single LLM call before escalating to fallback
MAX_LLM_RETRIES: int = 2

def _is_llm_availability_error(exc: BaseException) -> bool:
    """T4-1: classify an exception as a retryable LLM-availability error.

    Triggers FallbackManager chain advance when the *primary* model is:
      * rejecting auth (401) — bad / expired key
      * rate-limited (429)
      * hitting 5xx / internal errors
      * unreachable (connection / timeout)

    Non-matching exceptions (e.g. 400 bad request, value errors, tool
    errors) propagate unchanged — falling back to another *model* won't
    fix them.

    Fail-soft: matches by openai exception class names and HTTP status
    codes so we don't hard-depend on a specific SDK version.
    """
    if exc is None:
        return False
    cls_name = type(exc).__name__
    _RETRYABLE_CLS = {
        "AuthenticationError",
        "PermissionDeniedError",
        "RateLimitError",
        "APIConnectionError",
        "APITimeoutError",
        "InternalServerError",
        "APIError",
    }
    if cls_name in _RETRYABLE_CLS:
        return True
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and (status == 401 or status == 429 or status >= 500):
        return True
    # openai.APIStatusError exposes .response.status_code
    resp = getattr(exc, "response", None)
    status = getattr(resp, "status_code", None)
    if isinstance(status, int) and (status == 401 or status == 429 or status >= 500):
        return True
    return False


# Markers that appear in FAILED StreamResponse.log when the root cause
# is the primary LLM being unavailable. agent.base.run() catches LLM
# exceptions internally and yields a FAILED event instead of raising —
# so wrap_agent_stream sniffs these markers to know when to fall back.
_LLM_FAILURE_MARKERS: tuple[str, ...] = (
    "authenticationerror",
    "authentication error",
    "unauthorized",
    "invalid api key",
    "invalid proxy server token",
    "token_not_found_in_db",
    "ratelimiterror",
    "rate limit",
    "apiconnectionerror",
    "apitimeouterror",
    "internalservererror",
    "error code: 401",
    "error code: 429",
    "error code: 500",
    "error code: 502",
    "error code: 503",
    "error code: 504",
)


def _failed_event_is_llm_availability(parsed: Optional[dict]) -> bool:
    """Return True iff a FAILED StreamResponse comes from LLM unavailability."""
    if not parsed:
        return False
    log_text = str(parsed.get("log", "") or "").lower()
    if not log_text:
        return False
    return any(marker in log_text for marker in _LLM_FAILURE_MARKERS)


# Live runtime registry — allows external endpoints (e.g. /runtime/snapshot)
# to look up an in-flight ConversationRuntime by session_id.
# Cleaned up automatically when wrap_agent_stream / run_turn completes.
_RUNTIME_REGISTRY: dict[str, "ConversationRuntime"] = {}
# Keep the most recent runtime for nudge after unregister
_LAST_RUNTIME: Optional["ConversationRuntime"] = None

# Fire-and-forget background tasks (Redis snapshot deletes on unregister).
# Holding a strong reference here prevents the event loop from garbage-
# collecting the task before it runs (see CPython asyncio.create_task docs —
# "the event loop only keeps weak references to tasks"). Tasks self-discard
# via done_callback.
_BACKGROUND_TASKS: set[asyncio.Task] = set()


@dataclass
class TurnResult:
    """
    Summary of a completed conversation turn.

    Attributes
    ----------
    text : str
        The final assistant response text.
    stop_reason : str
        Why the turn ended (end_turn / budget_exceeded / error / cancelled).
    iterations : int
        Number of ReAct iterations consumed.
    tool_calls_count : int
        Total tool invocations across all iterations.
    elapsed_ms : int
        Wall-clock time for the entire turn.
    is_fallback : bool
        True if a fallback model was used for any part of this turn.
    fallback_attempt : int
        0 = primary model, N = Nth fallback.
    """

    text: str
    stop_reason: str = "end_turn"
    iterations: int = 0
    tool_calls_count: int = 0
    elapsed_ms: int = 0
    is_fallback: bool = False
    fallback_attempt: int = 0


def _done_dict(stop_reason: str, session_id: str = "", summary: str = "") -> dict:
    data: dict = {}
    if summary:
        data["summary"] = summary
    return {
        "event_type": "done",
        "data": data,
        "stop_reason": stop_reason,
        "session_id": session_id,
    }


def _error_dict(message: str, session_id: str = "") -> dict:
    return {
        "event_type": "error",
        "data": {"message": message},
        "session_id": session_id,
    }
