# -*- coding: utf-8 -*-
"""
CostTrackingHook — automatic LLM cost recording (§14.8).

Dual-purpose:
  1. PluginHook — auto-registered in ConversationRuntime; fires on every LLM call.
  2. Standalone  — `record_llm_cost()` can be called directly from node_executor,
       evaluation grader, or any other LLM call site.

Attribution fields (per §14.8):
  session_id, requested_model, model_name, is_fallback, fallback_attempt,
  token_input, token_output, cache_creation_tokens, cache_read_tokens
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ── Cost calculation: model → price per 1K tokens (CNY) ───────────────────────
# 可通过 conf/default.yaml model_pricing 覆盖
_DEFAULT_PRICING: Dict[str, Dict[str, float]] = {
    # input_per_1k, output_per_1k (CNY)
    "qwen3.5-27b-instruct":   {"input": 0.004, "output": 0.012},
    "qwen3-5-27b-instruct":   {"input": 0.004, "output": 0.012},
    "qwen3.5-14b-instruct":   {"input": 0.002, "output": 0.006},
    "qwen3-5-14b-instruct":   {"input": 0.002, "output": 0.006},
    "qwen3-235b-a22b":        {"input": 0.004, "output": 0.012},
    "qwen-max":               {"input": 0.02,  "output": 0.06},
    "qwen-plus":              {"input": 0.004, "output": 0.012},
    "qwen-turbo":             {"input": 0.002, "output": 0.006},
    "gpt-4o":                 {"input": 0.018, "output": 0.072},
    "gpt-4o-mini":            {"input": 0.001, "output": 0.004},
    "gpt-4-turbo":            {"input": 0.072, "output": 0.216},
    "claude-sonnet-4-20250514":  {"input": 0.022, "output": 0.108},
    "claude-3-5-sonnet":      {"input": 0.022, "output": 0.108},
    "claude-3-haiku":         {"input": 0.002, "output": 0.009},
    "deepseek-chat":          {"input": 0.001, "output": 0.002},
    "deepseek-reasoner":      {"input": 0.004, "output": 0.016},
    # Zhipu GLM-5.1 (approximate CNY / 1K tokens; override via model_pricing)
    "glm-5.1":                {"input": 0.005, "output": 0.015},
}

# cache 价格: 创建 token 按 input 1.25x, 读取 token 按 input 0.1x (Anthropic 标准)
_CACHE_CREATE_MULTIPLIER = 1.25
_CACHE_READ_MULTIPLIER = 0.1


@dataclass
class LLMUsage:
    """Structured token usage extracted from an LLM response."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @classmethod
    def from_openai_usage(cls, usage) -> "LLMUsage":
        """Extract from OpenAI ChatCompletion.usage or dict."""
        if usage is None:
            return cls()
        if isinstance(usage, dict):
            return cls(
                prompt_tokens=usage.get("prompt_tokens", 0) or 0,
                completion_tokens=usage.get("completion_tokens", 0) or 0,
                total_tokens=usage.get("total_tokens", 0) or 0,
                cache_creation_input_tokens=usage.get("cache_creation_input_tokens", 0) or 0,
                cache_read_input_tokens=usage.get("cache_read_input_tokens", 0) or 0,
            )
        # OpenAI Usage object
        return cls(
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            total_tokens=getattr(usage, "total_tokens", 0) or 0,
            cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        )


@dataclass
class CostAttribution:
    """All attribution fields needed for a cost record.

    ``avatar_id`` and ``issue_id`` are introduced by S4 / Gap 5 —
    "归属到分身/员工/Issue" — and flow through HookContext.metadata to
    avoid widening the PluginHook protocol.
    """
    workspace_id: Optional[str] = None
    session_id: Optional[str] = None
    agent_id: Optional[str] = None
    avatar_id: Optional[str] = None  # Gap 5 — 分身级归属
    issue_id: Optional[str] = None   # Gap 5 — Issue 级归属
    agent_type: Optional[str] = None      # DEEP_THINK / QUICK_REASONING / AUTO / ...
    parent_agent_id: Optional[str] = None  # parent Agent for sub-agent attribution
    user_id: Optional[str] = None
    request_id: Optional[str] = None
    requested_model: Optional[str] = None
    model_name: Optional[str] = None
    is_fallback: bool = False
    fallback_attempt: int = 0
    turn_number: int = 0


def _get_model_pricing() -> Dict[str, Dict[str, float]]:
    """Load pricing from config, fallback to defaults."""
    try:
        from web.config import config
        custom = getattr(config, "model_pricing", None)
        if isinstance(custom, dict) and custom:
            merged = dict(_DEFAULT_PRICING)
            merged.update(custom)
            return merged
    except Exception:
        pass
    return _DEFAULT_PRICING


def calculate_cost(
    model_name: str,
    usage: LLMUsage,
    currency: str = "CNY",
) -> Decimal:
    """
    Calculate cost for a single LLM call.

    Falls back to zero if model pricing is unknown — cost records are still
    valuable for token usage tracking even without dollar amounts.
    """
    pricing = _get_model_pricing()
    # 尝试精确匹配，然后前缀匹配
    model_lower = (model_name or "").lower().strip()
    if not model_lower:
        return Decimal("0")
    price = pricing.get(model_lower)
    if price is None:
        for key in pricing:
            if model_lower.startswith(key) or key.startswith(model_lower):
                price = pricing[key]
                break
    if price is None:
        return Decimal("0")

    input_cost = Decimal(str(usage.prompt_tokens)) * Decimal(str(price["input"])) / Decimal("1000")
    output_cost = Decimal(str(usage.completion_tokens)) * Decimal(str(price["output"])) / Decimal("1000")

    # Cache tokens
    cache_create_cost = (
        Decimal(str(usage.cache_creation_input_tokens))
        * Decimal(str(price["input"]))
        * Decimal(str(_CACHE_CREATE_MULTIPLIER))
        / Decimal("1000")
    )
    cache_read_cost = (
        Decimal(str(usage.cache_read_input_tokens))
        * Decimal(str(price["input"]))
        * Decimal(str(_CACHE_READ_MULTIPLIER))
        / Decimal("1000")
    )

    return input_cost + output_cost + cache_create_cost + cache_read_cost


# ── Standalone recording function ─────────────────────────────────────────────


async def record_llm_cost(
    usage: LLMUsage,
    attribution: CostAttribution,
    cost_type: str = "llm_token",
    currency: str = "CNY",
) -> Optional[str]:
    """
    Persist a single LLM cost record (fire-and-forget safe).

    Returns the cost record ID, or None on failure.
    """
    try:
        # PR-E4 (SDK extraction §5 PR-E4): CostRecordDao is now accessed via the
        # CostRecordRepository Protocol.  The legacy dao.mysql.cost_record is still
        # used via the _LegacyCostRecordRepository fallback so runtime behaviour
        # is unchanged in Phase 0.  Phase 2 removes the fallback when dao/ leaves
        # the engine import surface.
        from vendor_runtime_sdk.runtime.protocols.cost_record_repository import (
            CostRecordRow,
            get_cost_record_repository,
        )

        cost_amount = calculate_cost(attribution.model_name or "", usage, currency)

        # Compute cache hit ratio
        total_input = usage.prompt_tokens + usage.cache_read_input_tokens
        cache_hit_ratio = (
            usage.cache_read_input_tokens / total_input
            if total_input > 0
            else 0.0
        )

        rec = CostRecordRow(
            id=str(uuid.uuid4()),
            cost_type=cost_type,
            cost_amount=cost_amount,
            currency=currency,
            workspace_id=attribution.workspace_id,
            session_id=attribution.session_id,
            agent_id=attribution.agent_id,
            avatar_id=attribution.avatar_id,
            issue_id=attribution.issue_id,
            agent_type=attribution.agent_type,
            parent_agent_id=attribution.parent_agent_id,
            tool_id=None,
            model_name=attribution.model_name,
            requested_model=attribution.requested_model,
            is_fallback=attribution.is_fallback,
            fallback_attempt=attribution.fallback_attempt,
            turn_number=attribution.turn_number,
            token_input=usage.prompt_tokens,
            token_output=usage.completion_tokens,
            cache_creation_tokens=usage.cache_creation_input_tokens,
            cache_read_tokens=usage.cache_read_input_tokens,
            cache_hit_ratio=round(cache_hit_ratio, 4),
            request_id=attribution.request_id,
            user_id=attribution.user_id,
        )
        repo = get_cost_record_repository()
        result = await repo.create(rec)

        # ── Prometheus metrics for token billing ──
        try:
            from vendor_runtime_sdk.libs.agent_metrics import (
                record_llm_call_cost,
                record_token_cache_hit_ratio,
                record_token_cache_read,
                record_token_cache_creation,
            )
            model = attribution.model_name or "unknown"
            agent_type = attribution.agent_type or "unknown"
            is_fallback = attribution.is_fallback

            record_llm_call_cost(model, agent_type, is_fallback, float(cost_amount))
            record_token_cache_hit_ratio(model, cache_hit_ratio)
            if usage.cache_read_input_tokens > 0:
                record_token_cache_read(model, usage.cache_read_input_tokens)
            if usage.cache_creation_input_tokens > 0:
                record_token_cache_creation(model, usage.cache_creation_input_tokens)
        except Exception:
            pass  # Prometheus is best-effort

        return result
    except Exception as exc:
        logger.warning("record_llm_cost failed: %s", exc)
        return None


async def record_tool_cost(
    tool_id: str,
    attribution: CostAttribution,
    cost_type: str = "tool_api",
    cost_amount: Decimal = Decimal("0"),
    currency: str = "CNY",
) -> Optional[str]:
    """Persist tool call cost record."""
    try:
        # PR-E4 (SDK extraction §5 PR-E4): CostRecordDao is now accessed via the
        # CostRecordRepository Protocol.  The legacy dao.mysql.cost_record is still
        # used via the _LegacyCostRecordRepository fallback so runtime behaviour
        # is unchanged in Phase 0.  Phase 2 removes the fallback when dao/ leaves
        # the engine import surface.
        from vendor_runtime_sdk.runtime.protocols.cost_record_repository import (
            CostRecordRow,
            get_cost_record_repository,
        )

        rec = CostRecordRow(
            id=str(uuid.uuid4()),
            cost_type=cost_type,
            cost_amount=cost_amount,
            currency=currency,
            workspace_id=attribution.workspace_id,
            session_id=attribution.session_id,
            agent_id=attribution.agent_id,
            avatar_id=attribution.avatar_id,
            issue_id=attribution.issue_id,
            agent_type=attribution.agent_type,
            parent_agent_id=attribution.parent_agent_id,
            tool_id=tool_id,
            model_name=None,
            requested_model=None,
            is_fallback=False,
            fallback_attempt=0,
            turn_number=attribution.turn_number,
            token_input=0,
            token_output=0,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            cache_hit_ratio=0.0,
            request_id=attribution.request_id,
            user_id=attribution.user_id,
        )
        repo = get_cost_record_repository()
        return await repo.create(rec)
    except Exception as exc:
        logger.warning("record_tool_cost failed: %s", exc)
        return None


# ── PluginHook implementation ─────────────────────────────────────────────────


class CostTrackingHook:
    """
    PluginHook that records LLM cost on every on_post_llm_call.

    Usage in HookContext.metadata:
      - "usage": OpenAI Usage object or dict (prompt_tokens, completion_tokens, ...)
      - "requested_model": str (from FallbackManager, optional)
      - "fallback_attempt": int (optional)

    The hook is synchronous per PluginHook protocol. It schedules the async
    DB write via asyncio.create_task() so it never blocks the agent loop.
    """

    def on_post_llm_call(self, context, response_text: str) -> None:
        """Fire-and-forget cost recording on every LLM response."""
        usage_raw = context.metadata.get("usage") if hasattr(context, "metadata") else None
        if usage_raw is None:
            return  # 无 usage 数据则不记录

        usage = LLMUsage.from_openai_usage(usage_raw)
        if usage.total_tokens == 0 and usage.prompt_tokens == 0:
            return  # 空调用不记录

        meta = context.metadata if hasattr(context, "metadata") else {}
        attr = CostAttribution(
            workspace_id=getattr(context, "workspace_id", None),
            session_id=getattr(context, "session_id", None),
            agent_id=meta.get("agent_id"),
            avatar_id=meta.get("avatar_id"),
            issue_id=meta.get("issue_id"),
            user_id=meta.get("user_id"),
            request_id=meta.get("request_id"),
            requested_model=meta.get("requested_model") or getattr(context, "model", None),
            model_name=getattr(context, "model", None),
            is_fallback=getattr(context, "is_fallback", False),
            fallback_attempt=meta.get("fallback_attempt", 0) or 0,
            agent_type=meta.get("agent_type"),
            parent_agent_id=meta.get("parent_agent_id"),
            turn_number=meta.get("turn_number", 0) or 0,
        )

        # 异步写入, 不阻塞 agent loop
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(record_llm_cost(usage, attr))
            # §T14-3 AlertPolicy evaluation — throttled per-workspace,
            # fire-and-forget. Must never block or raise into the agent loop.
            try:
                from vendor_runtime_sdk.runtime.alert.service import schedule_evaluation
                schedule_evaluation(attr.workspace_id)
            except Exception as exc:
                logger.debug("CostTrackingHook: alert evaluation skipped: %s", exc)
        except RuntimeError:
            # 没有 event loop (不应在正常运行时发生)
            logger.warning("CostTrackingHook: no running event loop, cost record dropped")

    def on_pre_llm_call(self, context) -> None:
        return None

    def on_session_start(self, session_id: str, workspace_id: str) -> None:
        pass

    def on_session_end(self, session_id: str, workspace_id: str, stop_reason: str) -> None:
        pass

    def on_tool_use_failure(self, context) -> None:
        return None
