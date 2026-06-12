"""S2.1 PR2 · Multi-hook dispatcher for the three event types.

Iterates through configured :class:`HookSpecRoute` entries, fires
each matching hook in order, and merges their outputs.  PR3 will
plug this into ``AgentLoop._execute_single_tool`` at the three
fire points; PR2's job is the merge logic so the AgentLoop edit
stays a 3-call insertion.

Merge rules (per event):

  PreToolUse           — first ``permission_override="deny"``
                         short-circuits.  ``updated_input``
                         applied IN ORDER (later = closer to
                         tool = wins).  ``reason`` from the
                         denying hook surfaces as ``deny_reason``.
  PostToolUse          — ``additional_feedback`` lines concatenated
                         in order.
  PostToolUseFailure   — first ``retry=True`` wins.  Last
                         ``final_message`` wins (closer-to-tool
                         override semantics).

Fail-soft at every layer: hook subprocess raises (timeout / spawn
error / invalid JSON) → that one hook's output is dropped, the
dispatcher continues with the rest.  The merged result is always
returned even when every hook failed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence

from .config import HookSpecRoute
from .protocol import (
    EVENT_POST_TOOL_USE,
    EVENT_POST_TOOL_USE_FAILURE,
    EVENT_PRE_TOOL_USE,
    HookInput,
    HookOutput,
)
from .runner import HookTimeout, run_hook

logger = logging.getLogger(__name__)


# ── Merged result types ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class MergedPreToolUse:
    """Aggregated result from all PreToolUse hooks for this tool call."""

    updated_input: Optional[Dict[str, Any]] = None
    permission_override: Optional[str] = None  # allow / deny / ask
    deny_reason: Optional[str] = None


@dataclass(frozen=True)
class MergedPostToolUse:
    additional_feedback: Optional[str] = None


@dataclass(frozen=True)
class MergedPostToolUseFailure:
    retry: bool = False
    final_message: Optional[str] = None


# ── Internal: safely run one hook ──────────────────────────────────────────


async def _safe_run(
    route: HookSpecRoute,
    payload: HookInput,
    *,
    workspace_root: Optional[str],
) -> Optional[HookOutput]:
    """Run a single hook, swallowing any exception.

    Returns ``None`` when the hook failed (timeout / spawn error /
    invalid JSON); the caller treats that as "no opinion" and
    continues with the next hook.
    """
    try:
        return await run_hook(
            route.spec, payload, workspace_root=workspace_root,
        )
    except HookTimeout as exc:
        logger.warning("hook %s timed out: %s", route.spec.name, exc)
        return None
    except FileNotFoundError as exc:
        logger.warning(
            "hook %s missing executable: %s", route.spec.name, exc,
        )
        return None
    except ValueError as exc:
        # Invalid JSON / schema violation in stdout.
        logger.warning(
            "hook %s returned invalid output: %s", route.spec.name, exc,
        )
        return None
    except Exception as exc:  # noqa: BLE001 — fail-soft per design
        logger.warning(
            "hook %s raised unexpectedly: %s", route.spec.name, exc,
        )
        return None


# ── PreToolUse ─────────────────────────────────────────────────────────────


async def fire_pre_tool_use(
    *,
    routes: Sequence[HookSpecRoute],
    tool_name: str,
    tool_input: Dict[str, Any],
    workspace_root: Optional[str] = None,
) -> MergedPreToolUse:
    """Fire all PreToolUse hooks matching ``tool_name``; return merged result.

    Short-circuits on the first ``permission_override="deny"`` —
    downstream hooks do NOT run (decision is final).
    """
    current_input: Dict[str, Any] = dict(tool_input or {})
    for route in routes:
        if not route.matches(tool_name):
            continue
        # Each hook sees the LATEST rewritten input so chained
        # rewrites compose (lint hook adds linter args → secrets
        # hook can then strip credentials from those args).
        payload = HookInput(
            event=EVENT_PRE_TOOL_USE,
            tool_name=tool_name,
            input=current_input,
        )
        out = await _safe_run(route, payload, workspace_root=workspace_root)
        if out is None:
            continue
        if out.permission_override == "deny":
            return MergedPreToolUse(
                updated_input=(
                    current_input if current_input != tool_input else None
                ),
                permission_override="deny",
                deny_reason=out.reason,
            )
        if out.updated_input is not None:
            current_input = dict(out.updated_input)

    return MergedPreToolUse(
        updated_input=(
            current_input if current_input != tool_input else None
        ),
    )


# ── PostToolUse ────────────────────────────────────────────────────────────


async def fire_post_tool_use(
    *,
    routes: Sequence[HookSpecRoute],
    tool_name: str,
    tool_input: Dict[str, Any],
    tool_result: Dict[str, Any],
    workspace_root: Optional[str] = None,
) -> MergedPostToolUse:
    """Fire all PostToolUse hooks matching ``tool_name``; concatenate
    feedback in hook order."""
    feedback_parts: list[str] = []
    payload = HookInput(
        event=EVENT_POST_TOOL_USE,
        tool_name=tool_name,
        input=dict(tool_input or {}),
        result=dict(tool_result or {}),
    )
    for route in routes:
        if not route.matches(tool_name):
            continue
        out = await _safe_run(route, payload, workspace_root=workspace_root)
        if out is None:
            continue
        if out.additional_feedback:
            feedback_parts.append(out.additional_feedback)

    return MergedPostToolUse(
        additional_feedback="\n".join(feedback_parts) if feedback_parts else None,
    )


# ── PostToolUseFailure ─────────────────────────────────────────────────────


async def fire_post_tool_use_failure(
    *,
    routes: Sequence[HookSpecRoute],
    tool_name: str,
    tool_input: Dict[str, Any],
    error: str,
    workspace_root: Optional[str] = None,
) -> MergedPostToolUseFailure:
    """Fire all PostToolUseFailure hooks; first ``retry=True`` wins,
    last ``final_message`` wins."""
    payload = HookInput(
        event=EVENT_POST_TOOL_USE_FAILURE,
        tool_name=tool_name,
        input=dict(tool_input or {}),
        error=str(error or ""),
    )
    retry = False
    final_message: Optional[str] = None
    for route in routes:
        if not route.matches(tool_name):
            continue
        out = await _safe_run(route, payload, workspace_root=workspace_root)
        if out is None:
            continue
        if not retry and out.retry:
            retry = True
        if out.final_message is not None:
            final_message = out.final_message  # last-wins

    return MergedPostToolUseFailure(retry=retry, final_message=final_message)
