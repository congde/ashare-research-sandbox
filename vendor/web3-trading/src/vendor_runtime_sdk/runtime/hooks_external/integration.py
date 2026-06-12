"""S2.1 PR3 · AgentLoop integration shim for the external-hook dispatcher.

Plan ~/.claude/plans/tui-smooth-stroustrup.md §4.2.1.

This module is the small adapter that ``AgentLoop._execute_single_tool``
calls at the three documented fire points:

  PreToolUse           — after PermissionResolver, BEFORE the tool runs
  PostToolUse          — after a successful tool result, BEFORE
                         ``_record_tool_invocation``
  PostToolUseFailure   — when ``self.tool_registry.execute`` raises
                         (or the tool returns a failed ``ToolResult``)

Why a separate module:
- Keeps ``AgentLoop._execute_single_tool`` edits to 3 small inline
  blocks (toggle gate + helper call + apply).
- Toggle gate lives here so the AgentLoop hot path doesn't pull
  ``runtime.config.toggles`` on every tool call.
- Lets the integration be unit-tested without spinning up a full
  AgentLoop.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .config import HookConfig
from .dispatcher import (
    MergedPostToolUse,
    MergedPostToolUseFailure,
    MergedPreToolUse,
    fire_post_tool_use as dispatcher_fire_post,
    fire_post_tool_use_failure as dispatcher_fire_failure,
    fire_pre_tool_use as dispatcher_fire_pre,
)

logger = logging.getLogger(__name__)


def _toggle_enabled() -> bool:
    """Check the ``external_process_hooks`` toggle.  Fail-closed:
    any error reading the toggle treats it as OFF so a runtime
    config bug never accidentally exposes hook execution."""
    try:
        from vendor_runtime_sdk.runtime.config.toggles import get_toggles

        return bool(
            get_toggles().is_enabled("external_process_hooks")
        )
    except Exception:
        return False


def _routes_or_none(routes: Optional[HookConfig]) -> Optional[HookConfig]:
    """Return ``routes`` only when it's a HookConfig with at least
    one event populated.  Empty config = no-op."""
    if routes is None or not isinstance(routes, HookConfig):
        return None
    if (
        not routes.pre_tool_use
        and not routes.post_tool_use
        and not routes.post_tool_use_failure
    ):
        return None
    return routes


# ── PreToolUse ─────────────────────────────────────────────────────────────


async def fire_external_hooks_pre_tool_use(
    *,
    routes: Optional[HookConfig],
    tool_name: str,
    tool_input: Dict[str, Any],
    workspace_root: Optional[str] = None,
) -> Optional[MergedPreToolUse]:
    """Fire all matching PreToolUse hooks; return merged result or
    ``None`` when the toggle is off / no routes / dispatcher errors.

    Caller should:
      * Check ``permission_override == "deny"`` → block the tool
        and surface ``deny_reason`` to the LLM.
      * Apply ``updated_input`` to ``call_info.arguments`` so
        downstream tool execution sees the rewritten input.
    """
    if not _toggle_enabled():
        return None
    cfg = _routes_or_none(routes)
    if cfg is None or not cfg.pre_tool_use:
        return None
    try:
        return await dispatcher_fire_pre(
            routes=cfg.pre_tool_use,
            tool_name=tool_name,
            tool_input=tool_input,
            workspace_root=workspace_root,
        )
    except Exception:  # noqa: BLE001 — fail-soft per design
        logger.exception(
            "external_process_hooks: pre dispatcher raised "
            "(tool=%s); skipping hooks", tool_name,
        )
        return None


# ── PostToolUse + apply ────────────────────────────────────────────────────


async def fire_external_hooks_post_tool_use(
    *,
    routes: Optional[HookConfig],
    tool_name: str,
    tool_input: Dict[str, Any],
    tool_result: Dict[str, Any],
    workspace_root: Optional[str] = None,
) -> Optional[MergedPostToolUse]:
    if not _toggle_enabled():
        return None
    cfg = _routes_or_none(routes)
    if cfg is None or not cfg.post_tool_use:
        return None
    try:
        return await dispatcher_fire_post(
            routes=cfg.post_tool_use,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_result=tool_result,
            workspace_root=workspace_root,
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "external_process_hooks: post dispatcher raised "
            "(tool=%s); skipping hooks", tool_name,
        )
        return None


def apply_post_tool_use(
    result: Any, merged: Optional[MergedPostToolUse],
) -> Any:
    """Append ``additional_feedback`` to a ToolResult's ``content``.

    Returns the original ``result`` unchanged when ``merged`` is
    ``None`` or has no feedback (zero-cost fast path).  Otherwise
    returns a NEW ToolResult so the caller's reference to the
    original is preserved (callers may have already enqueued it
    for telemetry).
    """
    if merged is None or not merged.additional_feedback:
        return result
    try:
        from vendor_runtime_sdk.agent.tools.base import ToolResult
    except Exception:
        return result
    new_content = (result.content or "") + (
        f"\n\n[hook] {merged.additional_feedback}"
    )
    # Construct with the minimum kwargs every ToolResult variant
    # accepts (the stubbed test variant only takes
    # ``content / success / error``).  Optional ``data`` /
    # ``metadata`` go via setattr so they survive on the production
    # dataclass without breaking on the stub.
    try:
        new_result = ToolResult(
            success=getattr(result, "success", True),
            content=new_content,
            error=getattr(result, "error", None),
        )
    except TypeError:
        # Defensive: a different ToolResult shape (positional only)
        # — leave the original unchanged rather than crash the loop.
        return result
    for attr in ("data", "metadata"):
        if hasattr(result, attr):
            try:
                value = getattr(result, attr)
                if attr == "metadata":
                    value = dict(value or {})
                setattr(new_result, attr, value)
            except Exception:
                pass
    return new_result


# ── PostToolUseFailure ─────────────────────────────────────────────────────


async def fire_external_hooks_post_tool_use_failure(
    *,
    routes: Optional[HookConfig],
    tool_name: str,
    tool_input: Dict[str, Any],
    error: str,
    workspace_root: Optional[str] = None,
) -> Optional[MergedPostToolUseFailure]:
    if not _toggle_enabled():
        return None
    cfg = _routes_or_none(routes)
    if cfg is None or not cfg.post_tool_use_failure:
        return None
    try:
        return await dispatcher_fire_failure(
            routes=cfg.post_tool_use_failure,
            tool_name=tool_name,
            tool_input=tool_input,
            error=error,
            workspace_root=workspace_root,
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "external_process_hooks: failure dispatcher raised "
            "(tool=%s); skipping hooks", tool_name,
        )
        return None
